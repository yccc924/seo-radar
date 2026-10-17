"""安全閘門：Antigravity PreToolUse Hook。

從 stdin 讀一個 JSON（工具名稱與參數），在 stdout 輸出
{"decision": "allow" | "deny" | "force_ask", "reason": "..."}。

判定規則（詳見 AGENTS.md「權限規則與安全閘門分類」）：
- run_command：
  - deny：提到 admin_edit.py、git push 帶 force、git reset --hard、sogi_accounts.json 或 cookie
  - force_ask：刪除指令、涉及保護檔案、任何不在白名單內的指令
  - allow：白名單指令（pytest、指定的 scripts、pip install、git status/diff/log/add/commit/push、claude -p）
  串接的指令（; && || | & 換行等）每一段分開判定，取最嚴格的結果。
- write_to_file / replace_file_content：目標是保護檔案 → force_ask，其他 → allow
- view_file：路徑含 sogi_accounts.json 或 cookie → deny；.env → force_ask；其他 → allow
- 其他工具 → force_ask

容錯：無效 JSON、缺欄位或任何例外，一律 force_ask，絕不回傳 allow。

用法（由 hooks.json 呼叫）：
    python scripts/safety_gate.py < hook_input.json
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from typing import Any

ALLOW = "allow"
DENY = "deny"
ASK = "force_ask"
_SEVERITY = {ALLOW: 0, ASK: 1, DENY: 2}

ERROR_REASON = "安全閘門解析錯誤或未知輸入，預設詢問"

WRAPPER_KEYS = ("toolcall", "tool_call")
TOOL_KEYS = ("tool_name", "toolname", "tool", "name")
ARGS_KEYS = ("tool_input", "toolinput", "arguments", "args", "input", "parameters", "params")
COMMAND_KEYS = ("commandline", "command", "cmd")
PATH_KEYS = ("targetfile", "absolutepath", "file_path", "filepath", "path", "target_file", "absolute_path", "file")

# --- run_command ---------------------------------------------------------

DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![\w])admin_edit\b"), "admin_edit.py 只能由使用者親自執行"),
    (
        re.compile(r"\bgit\b.*\bpush\b.*(?:--force\b|--force-with-lease\b|--force-if-includes\b|(?:^|\s)-[a-z]*f[a-z]*\b|(?:^|\s)\+\S)"),
        "禁止 git push --force",
    ),
    (re.compile(r"\bgit\b.*\breset\b.*--hard\b"), "禁止 git reset --hard"),
    (re.compile(r"sogi_accounts"), "禁止存取 sogi_accounts.json"),
    (re.compile(r"cookie"), "禁止存取 cookie"),
)

DELETE_PATTERN = re.compile(
    r"(?<![\w-])(?:rm|del|rmdir|rd|erase|unlink|shred|remove-item|ri|clear-content)(?![\w-])"
    r"|\bgit\s+(?:rm|clean)\b"
)

PROTECTED_IN_COMMAND = re.compile(
    r"\.agents/hooks\.json|hooks\.json|(?<![\w])safety_gate\.py|(?<![\w])agents\.md|\.env\b|\.gitignore"
)

_PYTHON = r"(?:\S*/)?(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?"
_VENV_OR_BARE = r"(?:\S*/\.venv/scripts/|\.venv/scripts/|\./\.venv/scripts/)?"
ALLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^{_PYTHON}\s+-m\s+pytest(?:\s|$)"),
    re.compile(rf"^{_PYTHON}\s+-m\s+pip\s+install(?:\s|$)"),
    re.compile(rf"^{_PYTHON}\s+(?:\./)?scripts/(?:quick_audit|admin_explore|plan_fixes|build_buyback_hub)\.py(?:\s|$)"),
    re.compile(rf"^{_VENV_OR_BARE}pytest(?:\.exe)?(?:\s|$)"),
    re.compile(rf"^{_VENV_OR_BARE}pip(?:3)?(?:\.exe)?\s+install(?:\s|$)"),
    re.compile(r"^git\s+(?:status|diff|log|add|commit|push)(?:\s|$)"),
    re.compile(r"^claude(?:\.exe|\.cmd)?\s+-p(?:\s|$)"),
)

# 指令串接、管線、子指令與重新導向
SPLIT_PATTERN = re.compile(r"\|\||&&|[;|&\n\r]")
SUBSHELL_PATTERN = re.compile(r"`|\$\(|<\(|>\(")
REDIRECT_PATTERN = re.compile(r"[<>]")
# 只合併或丟棄錯誤輸出的重新導向不算寫檔（例如 2>&1、2>$null）
SAFE_REDIRECT_PATTERN = re.compile(r"(?<!\S)[12*]?>&[12](?!\S)|(?<!\S)2>\s*(?:\$null|/dev/null)(?!\S)")

# --- 檔案工具 -------------------------------------------------------------

PROTECTED_BASENAMES = frozenset({"safety_gate.py", "agents.md", ".gitignore"})
WRITE_TOOLS = frozenset({"write_to_file", "replace_file_content"})


def result(decision: str, reason: str) -> dict[str, str]:
    """組成 hook 輸出。"""
    return {"decision": decision, "reason": reason}


def strictest(results: Iterable[dict[str, str]]) -> dict[str, str]:
    """取最嚴格的判定（deny > force_ask > allow）；沒有任何結果時視為 force_ask。"""
    chosen: dict[str, str] | None = None
    for item in results:
        if chosen is None or _SEVERITY[item["decision"]] > _SEVERITY[chosen["decision"]]:
            chosen = item
    return chosen or result(ASK, ERROR_REASON)


def normalize_command(command: str) -> str:
    """轉小寫、反斜線改斜線、去掉引號，方便比對。"""
    return command.lower().replace("\\", "/").replace('"', "").replace("'", "")


def check_segment(segment: str) -> dict[str, str]:
    """判定一段（不含串接符號）指令。"""
    text = segment.strip()
    if not text:
        return result(ALLOW, "空白")
    for pattern, reason in DENY_PATTERNS:
        if pattern.search(text):
            return result(DENY, reason)
    if DELETE_PATTERN.search(text):
        return result(ASK, "刪除指令需要使用者確認")
    if PROTECTED_IN_COMMAND.search(text):
        return result(ASK, "指令涉及保護檔案，需要使用者確認")
    if REDIRECT_PATTERN.search(text):
        return result(ASK, "指令含重新導向，需要使用者確認")
    if any(pattern.search(text) for pattern in ALLOW_PATTERNS):
        return result(ALLOW, "白名單指令")
    return result(ASK, "不在白名單內的指令，需要使用者確認")


def check_command(command: str) -> dict[str, str]:
    """判定 run_command 的指令；串接的每一段分開判定，取最嚴格的結果。"""
    if not command.strip():
        return result(ASK, ERROR_REASON)
    text = SAFE_REDIRECT_PATTERN.sub(" ", normalize_command(command))
    checks = [check_segment(part) for part in SPLIT_PATTERN.split(text)]
    if SUBSHELL_PATTERN.search(text):
        checks.append(result(ASK, "指令含子指令，需要使用者確認"))
    return strictest(checks)


def normalize_path(path: str) -> tuple[str, str]:
    """回傳（小寫斜線路徑, 檔名）；檔名去掉 Windows 會忽略的結尾點與空白，以及 :資料流。"""
    text = path.strip().strip('"').lower().replace("\\", "/")
    base = text.rstrip("/").rsplit("/", 1)[-1].split(":", 1)[0].rstrip(". ")
    return text, base


def is_protected_path(path: str) -> bool:
    """是否為保護檔案（.agents/hooks.json、safety_gate.py、AGENTS.md、.env、.gitignore）。"""
    text, base = normalize_path(path)
    if base in PROTECTED_BASENAMES or base.startswith(".env"):
        return True
    return base == "hooks.json" and (text.endswith(".agents/hooks.json") or "/.agents/" in text)


def check_write(path: str) -> dict[str, str]:
    """判定 write_to_file / replace_file_content 的目標檔案。"""
    if is_protected_path(path):
        return result(ASK, "修改保護檔案需要使用者確認")
    return result(ALLOW, "一般檔案")


def check_view(path: str) -> dict[str, str]:
    """判定 view_file 的路徑。"""
    text, base = normalize_path(path)
    if "sogi_accounts.json" in text or "cookie" in text:
        return result(DENY, "禁止讀取帳號或 cookie 檔案")
    if base.startswith(".env"):
        return result(ASK, "讀取 .env 需要使用者確認")
    return result(ALLOW, "一般檔案")


def _lower_keys(data: dict[str, Any]) -> dict[str, Any]:
    """把字典的鍵轉小寫。"""
    return {str(k).lower(): v for k, v in data.items()}


def _pick(data: dict[str, Any], keys: Iterable[str]) -> Any:
    """依序找第一個存在的鍵。"""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _strings(data: dict[str, Any], keys: Iterable[str]) -> list[str]:
    """取出所有候選鍵的字串值（有多個時全部判定，避免用另一個鍵偷渡）。"""
    values = [data[key] for key in keys if key in data and data[key] is not None]
    if not values or not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError("缺少或無效的參數")
    return values


def _unwrap(data: dict[str, Any]) -> dict[str, Any] | None:
    """取出 Antigravity 的 toolCall / tool_call 包裝（可能是物件或 JSON 字串）；沒有包裝時回傳 None。"""
    wrapped = [data[key] for key in WRAPPER_KEYS if key in data and data[key] is not None]
    if not wrapped:
        return None
    if len(wrapped) > 1:
        raise ValueError("同時有 toolCall 與 tool_call")
    inner = wrapped[0]
    if isinstance(inner, str):
        inner = json.loads(inner)
    if not isinstance(inner, dict):
        raise ValueError("toolCall 不是物件")
    return inner


def decide(payload: Any) -> dict[str, str]:
    """依 hook 輸入決定 allow / deny / force_ask。格式不對會丟例外（由 evaluate 轉成 force_ask）。

    支援 Antigravity 的 {"toolCall": {"name": ..., "args": {...}}} 包裝；
    若外層同時也有工具欄位，兩邊都判定並取最嚴格的結果，避免用另一層偷渡。
    """
    if not isinstance(payload, dict):
        raise ValueError("輸入不是物件")
    data = _lower_keys(payload)
    inner = _unwrap(data)
    if inner is not None:
        if _pick(data, TOOL_KEYS) is None:
            return decide(inner)
        outer = {k: v for k, v in payload.items() if str(k).lower() not in WRAPPER_KEYS}
        return strictest([decide(inner), decide(outer)])
    tool = _pick(data, TOOL_KEYS)
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError("缺少工具名稱")
    tool = re.split(r"[:.]", tool.strip().lower())[-1]
    args = _pick(data, ARGS_KEYS)
    if isinstance(args, str):
        args = json.loads(args)
    if not isinstance(args, dict):
        raise ValueError("缺少工具參數")
    args = _lower_keys(args)

    if tool == "run_command":
        return strictest(check_command(c) for c in _strings(args, COMMAND_KEYS))
    if tool in WRITE_TOOLS:
        return strictest(check_write(p) for p in _strings(args, PATH_KEYS))
    if tool == "view_file":
        return strictest(check_view(p) for p in _strings(args, PATH_KEYS))
    return result(ASK, f"未知工具 {tool}，需要使用者確認")


def evaluate(raw: str | bytes) -> dict[str, str]:
    """解析原始輸入並判定；任何錯誤一律 force_ask。"""
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw.lstrip("﻿")
        decision = decide(json.loads(text))
        if decision.get("decision") not in _SEVERITY:
            return result(ASK, ERROR_REASON)
        return decision
    except Exception:  # noqa: BLE001 - 容錯：任何例外都不可放行
        return result(ASK, ERROR_REASON)


def main() -> int:
    """命令列進入點：讀 stdin、輸出判定 JSON 到 stdout。"""
    try:
        raw: str | bytes = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
        output = evaluate(raw)
    except Exception:  # noqa: BLE001
        output = result(ASK, ERROR_REASON)
    sys.stdout.write(json.dumps(output) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
