"""scripts/safety_gate.py 的測試：全部用假的 hook 輸入，不執行任何指令。"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("safety_gate", ROOT / "scripts" / "safety_gate.py")
assert _spec and _spec.loader
sg = importlib.util.module_from_spec(_spec)
sys.modules["safety_gate"] = sg
_spec.loader.exec_module(sg)


def run(command: str) -> str:
    """送一個 run_command 給閘門，回傳 decision。"""
    return sg.evaluate(json.dumps({"tool_name": "run_command", "tool_input": {"CommandLine": command}}))["decision"]


def file_tool(tool: str, path: str, key: str = "TargetFile") -> str:
    """送一個檔案工具給閘門，回傳 decision。"""
    return sg.evaluate(json.dumps({"tool_name": tool, "tool_input": {key: path}}))["decision"]


# ---------------------------------------------------------------------------
# run_command：白名單 allow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        r".venv\Scripts\python -m pytest",
        r".venv\Scripts\python -m pytest tests/test_safety_gate.py -q",
        r".venv\Scripts\python -m pytest tests/test_admin_edit.py",
        r".venv\Scripts\python.exe -m pytest -q 2>&1",
        r"C:\Users\ycc\Desktop\SEO\seo-radar\.venv\Scripts\python.exe -m pytest",
        r".venv\Scripts\python scripts\quick_audit.py",
        r".venv\Scripts\python scripts\admin_explore.py --page 1",
        r".venv\Scripts\python scripts\plan_fixes.py",
        r".venv\Scripts\python scripts\build_buyback_hub.py",
        r".venv\Scripts\python -m pip install -r requirements.txt",
        "python -m pytest",
        "pytest -q",
        "pip install pyyaml",
        "git status",
        "git diff --stat",
        "git log --oneline -5",
        "git add scripts/plan_fixes.py",
        'git commit -m "C3: 串接 Search Console"',
        "git push",
        "git push origin main",
        "git push -u origin main",
        'claude -p "幫我看測試"',
        "git status && git diff",
    ],
)
def test_whitelist_allows(command: str) -> None:
    assert run(command) == "allow"


# ---------------------------------------------------------------------------
# run_command：黑名單 deny
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        r".venv\Scripts\python scripts\admin_edit.py",
        r".venv\Scripts\python scripts\admin_edit.py --file changes/2026-10-17-s12.yaml --apply",
        r"C:\x\.venv\Scripts\python.exe C:\x\scripts\ADMIN_EDIT.PY --apply",
        "python scripts/admin_edit.py --apply --confirm=batch",
        'python "scripts/admin_edit.py"',
        "echo y | python scripts/admin_edit.py --apply",
        "git status; python scripts/admin_edit.py --apply",
        "git push --force",
        "git push origin main --force",
        "git push -f origin main",
        "git push --force-with-lease",
        "git push origin +main",
        "git reset --hard",
        "git reset --hard HEAD~1",
        r"type C:\Users\ycc\Desktop\xinchi-tools-main\sogi_accounts.json",
        "cat cookies.txt",
        "Get-Content cookie.json",
        "git status && git push --force",
    ],
)
def test_blacklist_denies(command: str) -> None:
    assert run(command) == "deny"


# ---------------------------------------------------------------------------
# run_command：刪除、保護檔案、未知指令 force_ask
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "del report.html",
        "rmdir /s /q backups",
        "Remove-Item -Recurse -Force backups",
        "remove-item x.txt",
        "git rm scripts/old.py",
        "git clean -fdx",
        "pytest && rm -rf data",
        "git status; Remove-Item x",
    ],
)
def test_delete_commands_ask(command: str) -> None:
    assert run(command) == "force_ask"


@pytest.mark.parametrize(
    "command",
    [
        "notepad .env",
        "type .env",
        "git add .env",
        "git add .gitignore",
        "git add AGENTS.md",
        "git commit -m x AGENTS.md",
        r"git add .agents\hooks.json",
        "git add scripts/safety_gate.py",
        "python scripts/safety_gate.py",
        "echo x >> .gitignore",
    ],
)
def test_protected_files_ask(command: str) -> None:
    assert run(command) == "force_ask"


@pytest.mark.parametrize(
    "command",
    [
        "curl https://example.com",
        "python -c \"print(1)\"",
        "python scripts/other.py",
        "Invoke-Expression $x",
        "git checkout main",
        "git -c core.x=y status",
        "git status; curl https://example.com",
        "pytest > out.txt",
        "git log $(whoami)",
        "git log `whoami`",
        "pytest | Out-File x.txt",
        "pytestx",
        "claude",
        "pip uninstall pyyaml",
    ],
)
def test_unknown_commands_ask(command: str) -> None:
    assert run(command) == "force_ask"


# ---------------------------------------------------------------------------
# 檔案工具
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["write_to_file", "replace_file_content"])
@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\ycc\Desktop\SEO\seo-radar\.agents\hooks.json",
        ".agents/hooks.json",
        r"C:\Users\ycc\Desktop\SEO\seo-radar\scripts\safety_gate.py",
        "AGENTS.md",
        "agents.md",
        "AGENTS.md.",
        "AGENTS.md::$DATA",
        r"scripts\..\AGENTS.md",
        ".env",
        r"C:\x\.env",
        ".gitignore",
    ],
)
def test_write_protected_files_ask(tool: str, path: str) -> None:
    assert file_tool(tool, path) == "force_ask"


@pytest.mark.parametrize("tool", ["write_to_file", "replace_file_content"])
@pytest.mark.parametrize("path", ["scripts/plan_fixes.py", "tests/test_safety_gate.py", "README.md", "hooks.json"])
def test_write_normal_files_allow(tool: str, path: str) -> None:
    assert file_tool(tool, path) == "allow"


@pytest.mark.parametrize(
    "path,expected",
    [
        (r"C:\Users\ycc\Desktop\xinchi-tools-main\sogi_accounts.json", "deny"),
        (r"C:\Users\ycc\Desktop\xinchi-tools-main\Cookies.txt", "deny"),
        ("data/cookie_store.json", "deny"),
        (".env", "force_ask"),
        (r"C:\Users\ycc\Desktop\SEO\seo-radar\.env", "force_ask"),
        ("SPEC.md", "allow"),
        ("scripts/admin_edit.py", "allow"),
    ],
)
def test_view_file(path: str, expected: str) -> None:
    assert file_tool("view_file", path, key="AbsolutePath") == expected


@pytest.mark.parametrize("tool", ["browser_open", "send_email", "run_command_v2", "", "unknown"])
def test_unknown_tools_ask(tool: str) -> None:
    result = sg.evaluate(json.dumps({"tool_name": tool, "tool_input": {"CommandLine": "git status"}}))
    assert result["decision"] == "force_ask"


def test_alternate_key_names() -> None:
    payload = {"toolName": "run_command", "toolInput": {"command": "git status"}}
    assert sg.evaluate(json.dumps(payload))["decision"] == "allow"
    payload = {"tool_name": "view_file", "tool_input": json.dumps({"AbsolutePath": "sogi_accounts.json"})}
    assert sg.evaluate(json.dumps(payload))["decision"] == "deny"


def test_conflicting_keys_use_strictest() -> None:
    """同時給兩個指令欄位時，不能用無害的那個偷渡。"""
    payload = {"tool_name": "run_command", "tool_input": {"command": "git status", "CommandLine": "rm -rf x"}}
    assert sg.evaluate(json.dumps(payload))["decision"] == "force_ask"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("pytest", "allow"),
        ("python scripts/admin_edit.py", "deny"),
        ("rm -rf build", "force_ask"),
    ],
)
@pytest.mark.parametrize("wrapper", ["toolCall", "tool_call"])
def test_antigravity_tool_call_wrapper(wrapper: str, command: str, expected: str) -> None:
    """Antigravity 官方格式 {"toolCall": {"name": ..., "args": {...}}} 要能解包。"""
    payload = {wrapper: {"name": "run_command", "args": {"CommandLine": command}}}
    assert sg.evaluate(json.dumps(payload))["decision"] == expected


def test_tool_call_wrapper_as_json_string() -> None:
    payload = {"toolCall": json.dumps({"name": "view_file", "args": {"AbsolutePath": "sogi_accounts.json"}})}
    assert sg.evaluate(json.dumps(payload))["decision"] == "deny"


def test_tool_call_wrapper_cannot_smuggle() -> None:
    """外層與 toolCall 內層都有工具時取最嚴格，不能用無害的一層偷渡。"""
    payload = {
        "tool_name": "run_command",
        "tool_input": {"CommandLine": "git status"},
        "toolCall": {"name": "run_command", "args": {"CommandLine": "python scripts/admin_edit.py"}},
    }
    assert sg.evaluate(json.dumps(payload))["decision"] == "deny"


@pytest.mark.parametrize(
    "payload",
    [
        {"toolCall": "not json"},
        {"toolCall": []},
        {"toolCall": {}},
        {"toolCall": {"name": "run_command"}},
        {"toolCall": {"name": "run_command", "args": {}}},
        {
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}},
            "tool_call": {"name": "run_command", "args": {"CommandLine": "git status"}},
        },
    ],
)
def test_malformed_tool_call_asks(payload: Any) -> None:
    assert sg.evaluate(json.dumps(payload)) == {"decision": "force_ask", "reason": sg.ERROR_REASON}


# ---------------------------------------------------------------------------
# 容錯：畸形 JSON、缺欄位、例外 → force_ask
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "{",
        "[]",
        "null",
        '"run_command"',
        "{}",
        '{"tool_name": "run_command"}',
        '{"tool_name": "run_command", "tool_input": {}}',
        '{"tool_name": "run_command", "tool_input": {"CommandLine": ""}}',
        '{"tool_name": "run_command", "tool_input": {"CommandLine": 123}}',
        '{"tool_name": "run_command", "tool_input": "not json"}',
        '{"tool_name": 5, "tool_input": {"CommandLine": "git status"}}',
        '{"tool_input": {"CommandLine": "git status"}}',
        '{"tool_name": "view_file", "tool_input": {}}',
        '{"tool_name": "write_to_file", "tool_input": {"TargetFile": null}}',
        b"\xff\xfe\x00garbage",
    ],
)
def test_malformed_input_asks(raw: Any) -> None:
    assert sg.evaluate(raw) == {"decision": "force_ask", "reason": sg.ERROR_REASON}


def test_unexpected_exception_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(payload: Any) -> Any:
        raise RuntimeError("意外錯誤")

    monkeypatch.setattr(sg, "decide", boom)
    assert sg.evaluate('{"tool_name": "run_command", "tool_input": {"CommandLine": "git status"}}')["decision"] == "force_ask"


def test_invalid_decision_from_decide_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sg, "decide", lambda payload: {"decision": "yes", "reason": ""})
    assert sg.evaluate("{}")["decision"] == "force_ask"


def test_utf8_bom_is_accepted() -> None:
    raw = "\ufeff" + json.dumps({"tool_name": "run_command", "tool_input": {"CommandLine": "git status"}})
    assert sg.evaluate(raw.encode("utf-8"))["decision"] == "allow"


# ---------------------------------------------------------------------------
# main：stdin → stdout
# ---------------------------------------------------------------------------


class FakeStdin:
    """有 buffer 屬性的假 stdin。"""

    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


def test_main_writes_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    data = json.dumps({"tool_name": "run_command", "tool_input": {"CommandLine": "git push --force"}}).encode()
    monkeypatch.setattr(sg.sys, "stdin", FakeStdin(data))
    assert sg.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "deny"
    assert set(output) == {"decision", "reason"}


def test_main_stdin_failure_asks(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class Broken:
        @property
        def buffer(self) -> Any:
            raise OSError("stdin 壞了")

    monkeypatch.setattr(sg.sys, "stdin", Broken())
    assert sg.main() == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "force_ask"
