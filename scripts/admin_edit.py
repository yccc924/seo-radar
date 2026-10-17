"""Cyberbiz 後台修改腳本：只執行修改單（changes/*.yaml）上的項目。

流程（每一筆）：
1. 開啟修改單上的後台網址，讀出欄位目前的值，和修改單的「改前（before）」比對。
   不符就跳過並在終端機警告。
2. 預設是預覽模式：只比對、不儲存。加上 --apply 才會真的修改。
3. --apply 時依授權確認等級詢問使用者：
   - --confirm=each（預設）：每筆修改前顯示「頁面、欄位、改前 → 改後」，輸入 y 才儲存，其他字跳過。
   - --confirm=batch：開瀏覽器前先顯示整份清單，輸入 y 一次執行全部。
   不提供全自動模式。
4. 確認後先把頁面原本的設定備份到 backups/YYYY-MM-DD/，再修改欄位、按下儲存。
5. 儲存後重新載入頁面，確認值已改成功；結果寫進 logs/admin_edit_YYYY-MM-DD.log。

修改單每筆的欄位：
- 必填：url（後台網址）、field、before、after、reason
- 選填：op（預設 set）、title、field_label、selector、absent、note
- op 的意義（「目前的值和修改單相符」的判斷方式）：
  - set：目前的值 = before，改成 after
  - replace：目前的值剛好含 1 次 before，把它換成 after（修錯字）
  - prepend／append：目前的值不含 absent（沒填則檢查不含 after），把 after 加在最前／最後
  - move_style_to_end：目前的值以 <style> 開頭，把開頭的 <style>…</style> 移到最後
- field 只接受 FIELDS 列出的欄位；網址只接受 ALLOWED_PATH_PREFIXES 開頭的後台頁面。

安全規則：
- 只能由真人在終端機執行：啟動時 sys.stdin 不是終端機就拒絕執行；
  確認 y 時在 Windows 用 msvcrt.getch() 直讀實體鍵盤，不接受管線輸入或重新導向。
- 瀏覽器有畫面（headless=False、slow_mo=800），開始操作前印出「瀏覽器即將開始操作，請觀看」。
- cookie 用 admin_explore.py 相同的 load_get_cookies 取得，只存在記憶體，
  絕不印出、寫入 log、備份或任何檔案。
- EditRequestGuard 用 page.route 攔截所有請求，預設擋下所有非 GET 請求。
  只有在使用者確認 y 之後，才臨時放行「該筆修改的那一次儲存請求」，儲存完立即恢復封鎖。
- 每次載入頁面之間隨機等待 2～5 秒；遇到登入頁、驗證碼、401／403／429／5xx 立即停止。

用法：
    python scripts/admin_edit.py --file changes/2026-10-17-s12.yaml              （預覽，不儲存）
    python scripts/admin_edit.py --file changes/2026-10-17-s12.yaml --apply      （每筆確認後儲存）
    python scripts/admin_edit.py --file changes/2026-10-17-s12.yaml --apply --confirm=batch
    （沒給 --file 時讀 changes/ 底下所有 .yaml）
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from admin_explore import (  # noqa: E402 - 需先把 scripts/ 加進 sys.path
    ADMIN_HOST,
    COOKIE_DOMAINS,
    NAVIGATION_TIMEOUT_MS,
    STOP_STATUSES,
    has_captcha,
    is_login_url,
    is_sensitive,
    load_get_cookies,
    random_page_delay,
    to_playwright_cookies,
    xinchi_tools_path_from_env,
)

ROOT = SCRIPTS_DIR.parent
CHANGES_DIR = ROOT / "changes"
BACKUP_DIR = ROOT / "backups"
LOG_DIR = ROOT / "logs"

SLOW_MO_MS = 800
SAVE_WAIT_MS = 15_000
MAX_SHOW_CHARS = 500
WATCH_MESSAGE = "瀏覽器即將開始操作，請觀看"

ALLOWED_PATH_PREFIXES = ("/admin/custom_pages/", "/admin/blogs/", "/admin/redirections/")
OPS = ("set", "replace", "prepend", "append", "move_style_to_end")
REQUIRED_KEYS = ("url", "field", "before", "after", "reason")

SAVE_SELECTORS = (
    'button:has-text("儲存")',
    'button:has-text("保存")',
    'input[type="submit"][value*="儲存"]',
    'input[type="submit"][value*="保存"]',
    'button:has-text("更新")',
    'button[type="submit"]',
    'input[type="submit"]',
)

STYLE_HEAD_RE = re.compile(r"^\s*(<style\b[^>]*>.*?</style>)\s*", re.IGNORECASE | re.DOTALL)
CSRF_META_RE = re.compile(r'(<meta[^>]+name="csrf-token"[^>]+content=")[^"]*(")', re.IGNORECASE)
CSRF_INPUT_RE = re.compile(r'(<input[^>]+name="authenticity_token"[^>]+value=")[^"]*(")', re.IGNORECASE)

logger = logging.getLogger("admin_edit")


def say(message: str) -> None:
    """在終端機顯示訊息並寫入 log（呼叫端保證訊息不含 cookie）。"""
    print(message, flush=True)
    logger.info(message)


# ---------------------------------------------------------------------------
# 欄位定義
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """一個表單欄位的找法：先 selector，再 name/id 關鍵字，最後標籤文字。"""

    label: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldDef:
    """修改單 field 對應的欄位；parts 不為空表示由多個子欄位組成（值為 dict）。"""

    label: str
    spec: FieldSpec | None = None
    parts: tuple[tuple[str, FieldSpec], ...] = ()
    creates: bool = False


FIELDS: dict[str, FieldDef] = {
    "status": FieldDef("頁面狀態", FieldSpec("狀態", ("[status]", "[published]", "[visible]"))),
    "body_html": FieldDef("頁面內容（HTML）", FieldSpec("內容", ("body_html",))),
    "seo_description": FieldDef(
        "SEO 描述（meta description）",
        FieldSpec("描述", ("seo_description", "seo-description", "meta_description", "[description]")),
    ),
    "redirect": FieldDef(
        "網站轉址",
        parts=(
            ("path", FieldSpec("舊網址", ("[path]", "[from]", "old_url"))),
            ("target", FieldSpec("新網址", ("[target]", "[to]", "new_url"))),
        ),
        creates=True,
    ),
}


# ---------------------------------------------------------------------------
# 修改單
# ---------------------------------------------------------------------------


@dataclass
class Change:
    """修改單上的一筆修改。"""

    url: str
    field: str
    before: Any
    after: Any
    reason: str
    op: str = "set"
    title: str = ""
    field_label: str = ""
    selector: Any = None
    absent: str = ""
    note: str = ""
    source: str = ""

    @property
    def field_def(self) -> FieldDef:
        """這筆修改的欄位定義。"""
        return FIELDS[self.field]

    @property
    def label(self) -> str:
        """顯示用的欄位名稱。"""
        return self.field_label or self.field_def.label

    @property
    def page_name(self) -> str:
        """顯示用的頁面名稱。"""
        return f"{self.title}（{self.url}）" if self.title else self.url


def _as_value(value: Any) -> Any:
    """把 YAML 的值轉成字串，dict 的每個子值也轉成字串；None 視為空字串。"""
    if isinstance(value, dict):
        return {str(k): "" if v is None else str(v) for k, v in value.items()}
    return "" if value is None else str(value)


def validate_change(raw: Any) -> tuple[Change | None, str]:
    """檢查一筆修改是否合法，回傳 (Change, "") 或 (None, 不合法原因)。"""
    if not isinstance(raw, dict):
        return None, "格式不是 key: value"
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        return None, f"缺少欄位 {', '.join(missing)}"
    url = str(raw["url"]).strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != ADMIN_HOST:
        return None, f"不是 Cyberbiz 後台網址（只接受 https://{ADMIN_HOST}）"
    if not any(parts.path.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        return None, "不在允許修改的後台頁面（自訂頁面、部落格、轉址）"
    if is_sensitive(url):
        return None, "屬於敏感頁面（訂單、會員、金流、刪除…），禁止修改"
    field_name = str(raw["field"]).strip()
    if field_name not in FIELDS:
        return None, f"不支援的欄位 {field_name}（只接受 {', '.join(FIELDS)}）"
    op = str(raw.get("op") or "set").strip()
    if op not in OPS:
        return None, f"不支援的修改方式 op={op}"
    field_def = FIELDS[field_name]
    before, after = _as_value(raw["before"]), _as_value(raw["after"])
    if field_def.parts:
        keys = {k for k, _ in field_def.parts}
        if op != "set" or not isinstance(before, dict) or not isinstance(after, dict):
            return None, f"{field_name} 的 before／after 必須是 {', '.join(sorted(keys))} 組成的對照，且 op 為 set"
        if set(before) != keys or set(after) != keys:
            return None, f"{field_name} 的 before／after 必須剛好有 {', '.join(sorted(keys))}"
    elif isinstance(before, dict) or isinstance(after, dict):
        return None, "before／after 必須是文字"
    if op == "replace" and not before:
        return None, "op=replace 的 before 不可為空"
    if op in ("prepend", "append") and not after:
        return None, f"op={op} 的 after 不可為空"
    return (
        Change(
            url=url,
            field=field_name,
            before=before,
            after=after,
            reason=str(raw["reason"]),
            op=op,
            title=str(raw.get("title") or ""),
            field_label=str(raw.get("field_label") or ""),
            selector=raw.get("selector"),
            absent=str(raw.get("absent") or ""),
            note=str(raw.get("note") or ""),
        ),
        "",
    )


def load_changes(paths: Sequence[Path]) -> list[Change]:
    """讀取修改單；不合法的項目跳過並警告。檔案可為 {changes: [...]} 或直接是清單。"""
    changes: list[Change] = []
    for path in paths:
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            say(f"⚠ 讀不到修改單 {path}（{type(exc).__name__}），略過整份")
            continue
        items = data.get("changes") if isinstance(data, dict) else data
        if not isinstance(items, list):
            say(f"⚠ 修改單 {path} 沒有 changes 清單，略過整份")
            continue
        for index, raw in enumerate(items, 1):
            change, problem = validate_change(raw)
            if change is None:
                say(f"⚠ {Path(path).name} 第 {index} 筆不合法，跳過：{problem}")
                continue
            change.source = Path(path).name
            changes.append(change)
    return changes


def change_files(file_arg: str | None, changes_dir: Path = CHANGES_DIR) -> list[Path]:
    """--file 指定時只用該檔；否則用 changes/ 底下所有 .yaml／.yml（依檔名排序）。"""
    if file_arg:
        return [Path(file_arg)]
    return sorted([*changes_dir.glob("*.yaml"), *changes_dir.glob("*.yml")])


# ---------------------------------------------------------------------------
# 比對與計算新值
# ---------------------------------------------------------------------------


def normalize(value: Any) -> Any:
    """比對用：把連續空白合併成一個並去掉頭尾空白；dict 逐項處理。"""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return " ".join(str(value or "").split())


def plan_value(change: Change, current: Any) -> tuple[Any | None, str]:
    """依 op 檢查目前的值是否和修改單相符，回傳 (新值, "") 或 (None, 不符原因)。"""
    op = change.op
    if op == "set":
        if normalize(current) != normalize(change.before):
            return None, "目前的值不等於修改單的改前值"
        return change.after, ""
    text = str(current or "")
    if op == "replace":
        count = text.count(change.before)
        if count != 1:
            return None, f"目前的值含有改前文字 {count} 次（必須剛好 1 次）"
        return text.replace(change.before, change.after), ""
    if op in ("prepend", "append"):
        marker = change.absent or change.after
        if marker.lower() in text.lower():
            return None, f"目前的值已經含有「{shorten(marker, 60)}」"
        if op == "prepend":
            return f"{change.after}\n{text.lstrip()}", ""
        return f"{text.rstrip()}\n{change.after}", ""
    match = STYLE_HEAD_RE.match(text)
    if not match:
        return None, "目前的內容開頭不是 <style>"
    rest = text[match.end() :].rstrip()
    return f"{rest}\n{match.group(1)}", ""


def values_match(expected: Any, actual: Any) -> bool:
    """儲存後驗證：忽略空白差異後是否相同。"""
    return normalize(expected) == normalize(actual)


def shorten(text: str, limit: int = MAX_SHOW_CHARS) -> str:
    """太長的文字只顯示前 limit 字並標出總字數。"""
    text = str(text)
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字）"


def show_value(value: Any) -> str:
    """把欄位值轉成適合在終端機顯示的文字。"""
    if isinstance(value, dict):
        return "；".join(f"{k}：{v or '（空白）'}" for k, v in value.items())
    return shorten(value) if value else "（空白）"


def describe_change(change: Change, index: int | None = None) -> str:
    """顯示「頁面、欄位、改前 → 改後」。"""
    prefix = f"[{index}] " if index is not None else ""
    op_note = {
        "set": "",
        "replace": "（把改前文字換成改後文字）",
        "prepend": "（把改後內容加在最前面）",
        "append": "（把改後內容加在最後面）",
        "move_style_to_end": "（把開頭的 <style> 移到文末）",
    }[change.op]
    lines = [
        f"{prefix}頁面：{change.page_name}",
        f"    欄位：{change.label}{op_note}",
        f"    改前：{show_value(change.before)}",
        f"    改後：{show_value(change.after)}",
        f"    原因：{change.reason}",
    ]
    if change.note:
        lines.append(f"    ⚠ 備註：{change.note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 讀寫表單欄位（只改瀏覽器裡的 DOM，不發任何請求）
# ---------------------------------------------------------------------------

_FIELD_HELPERS_JS = r"""
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
const CONTROL = 'select, textarea, input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset])';
const isControl = (el) => !!el && el.matches && el.matches(CONTROL);
const labelOf = (el) => {
  if (el.id) {
    const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    if (lab) return norm(lab.textContent);
  }
  const parent = el.closest('label');
  return parent ? norm(parent.textContent) : norm(el.value);
};
const wrap = (el) => {
  if (!isControl(el)) return null;
  if (el.matches('input[type=radio]')) {
    const scope = el.form || document;
    return {kind: 'radio', radios: Array.from(scope.querySelectorAll('input[type=radio]')).filter((r) => r.name === el.name)};
  }
  if (el.matches('select')) return {kind: 'select', el};
  if (el.matches('input[type=checkbox]')) return {kind: 'checkbox', el};
  return {kind: 'text', el};
};
const findField = (spec) => {
  if (spec.selector) return wrap(document.querySelector(spec.selector));
  const controls = Array.from(document.querySelectorAll(CONTROL));
  for (const name of spec.names || []) {
    const el = controls.find((c) => (c.name || '').includes(name) || (c.id || '').includes(name));
    if (el) return wrap(el);
  }
  for (const text of spec.labels || []) {
    if (!text) continue;
    for (const lab of document.querySelectorAll('label, legend, .control-label, th, dt')) {
      if (!norm(lab.textContent).includes(text)) continue;
      if (lab.htmlFor) {
        const el = wrap(document.getElementById(lab.htmlFor));
        if (el && el.kind !== 'radio') return el;
      }
      let box = lab.parentElement;
      for (let i = 0; i < 3 && box; i += 1, box = box.parentElement) {
        const el = box.querySelector(CONTROL);
        if (el) return wrap(el);
      }
    }
  }
  return null;
};
const editorOf = (el) => {
  const key = el.id || el.name;
  if (window.tinymce && el.id && window.tinymce.get(el.id)) {
    const ed = window.tinymce.get(el.id);
    return {get: () => ed.getContent(), set: (v) => ed.setContent(v)};
  }
  if (window.CKEDITOR && window.CKEDITOR.instances && window.CKEDITOR.instances[key]) {
    const ed = window.CKEDITOR.instances[key];
    return {get: () => ed.getData(), set: (v) => ed.setData(v)};
  }
  return null;
};
const getValue = (f) => {
  if (f.kind === 'select') {
    const opt = f.el.options[f.el.selectedIndex];
    return opt ? norm(opt.textContent) : '';
  }
  if (f.kind === 'radio') {
    const checked = f.radios.find((r) => r.checked);
    return checked ? labelOf(checked) : '';
  }
  if (f.kind === 'checkbox') return f.el.checked ? 'true' : 'false';
  const ed = editorOf(f.el);
  return ed ? ed.get() : f.el.value;
};
const fire = (el) => {
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
};
const setValue = (f, v) => {
  if (f.kind === 'select') {
    const opt = Array.from(f.el.options).find((o) => norm(o.textContent) === v || o.value === v);
    if (!opt) return false;
    f.el.value = opt.value;
    fire(f.el);
    return true;
  }
  if (f.kind === 'radio') {
    const radio = f.radios.find((r) => labelOf(r) === v || r.value === v);
    if (!radio) return false;
    radio.checked = true;
    fire(radio);
    return true;
  }
  if (f.kind === 'checkbox') {
    f.el.checked = v === 'true';
    fire(f.el);
    return true;
  }
  f.el.value = v;
  const ed = editorOf(f.el);
  if (ed) ed.set(v);
  fire(f.el);
  return true;
};
"""

READ_FIELD_JS = (
    "(spec) => {"
    + _FIELD_HELPERS_JS
    + "const f = findField(spec); if (!f) return {found: false, value: ''};"
    + " return {found: true, kind: f.kind, value: getValue(f)}; }"
)

WRITE_FIELD_JS = (
    "(arg) => {"
    + _FIELD_HELPERS_JS
    + "const f = findField(arg.spec); if (!f) return {ok: false};"
    + " return {ok: setValue(f, arg.value)}; }"
)


def field_specs(change: Change) -> list[tuple[str | None, dict[str, Any]]]:
    """把修改單的欄位轉成 JS 用的找法清單：[(子欄位名或 None, {selector, names, labels})]。"""
    field_def = change.field_def
    selector = change.selector
    if field_def.parts:
        result = []
        for key, spec in field_def.parts:
            sel = selector.get(key) if isinstance(selector, dict) else None
            result.append((key, {"selector": sel, "names": list(spec.names), "labels": [spec.label]}))
        return result
    assert field_def.spec is not None
    spec = field_def.spec
    labels = [change.field_label, spec.label] if change.field_label else [spec.label]
    sel = selector if isinstance(selector, str) else None
    return [(None, {"selector": sel, "names": list(spec.names), "labels": labels})]


def read_field(page: Any, change: Change) -> tuple[bool, Any]:
    """讀出欄位目前的值，回傳 (是否找到欄位, 值)；多欄位回傳 dict。"""
    values: dict[str, Any] = {}
    for key, spec in field_specs(change):
        result = page.evaluate(READ_FIELD_JS, spec) or {}
        if not result.get("found"):
            return False, None
        if key is None:
            return True, str(result.get("value") or "")
        values[key] = str(result.get("value") or "")
    return True, values


def write_field(page: Any, change: Change, value: Any) -> bool:
    """把新值填進欄位（只改瀏覽器裡的 DOM），全部填好回傳 True。"""
    for key, spec in field_specs(change):
        part_value = value[key] if key is not None else value
        result = page.evaluate(WRITE_FIELD_JS, {"spec": spec, "value": part_value}) or {}
        if not result.get("ok"):
            return False
    return True


# ---------------------------------------------------------------------------
# 只在確認後放行一次儲存請求的攔截器
# ---------------------------------------------------------------------------


def save_path(url: str) -> str:
    """儲存請求應該送到的路徑：編輯頁去掉 /edit，新增頁去掉 /new。"""
    path = urlsplit(url).path.rstrip("/")
    for suffix in ("/edit", "/new"):
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


class EditRequestGuard:
    """page.route 用的攔截器：GET 放行；非 GET 預設全部擋下。

    allow_once(路徑) 之後，只放行第一個「送到該路徑、非 GET」的請求一次，放行後自動恢復封鎖；
    revoke() 立即恢復封鎖。只記錄方法與網址，絕不記錄 headers、內容或 cookie。
    """

    def __init__(self) -> None:
        """建立攔截器。"""
        self.blocked: list[tuple[str, str]] = []
        self.allowed: list[tuple[str, str]] = []
        self._allow_path: str | None = None

    @property
    def is_open(self) -> bool:
        """目前是否有一次待用的放行額度。"""
        return self._allow_path is not None

    def allow_once(self, path: str) -> None:
        """臨時放行下一個送到 path 的非 GET 請求（只限一次）。"""
        self._allow_path = path.rstrip("/")

    def revoke(self) -> None:
        """立即恢復非 GET 全部封鎖。"""
        self._allow_path = None

    def _matches(self, url: str) -> bool:
        """請求是否送到被放行的路徑（同一後台網域，路徑相同或只多 .json）。"""
        if self._allow_path is None:
            return False
        parts = urlsplit(url)
        if parts.netloc != ADMIN_HOST:
            return False
        path = parts.path.rstrip("/")
        return path in (self._allow_path, f"{self._allow_path}.json")

    def handle(self, route: Any) -> None:
        """處理一個請求。"""
        request = route.request
        method = str(request.method or "").upper()
        url = str(request.url)
        if method == "GET":
            route.continue_()
            return
        if self._matches(url):
            self._allow_path = None
            self.allowed.append((method, url))
            say(f"已放行本筆儲存請求：{method} {urlsplit(url).path}（之後恢復封鎖）")
            route.continue_()
            return
        route.abort()
        self.blocked.append((method, url))
        say(f"已擋下非 GET 請求：{method} {url}")


# ---------------------------------------------------------------------------
# 開頁、備份、儲存
# ---------------------------------------------------------------------------


class StopRun(Exception):
    """遇到必須整個停止的狀況（登入失效、驗證碼、429…）。"""


class PageNotFound(Exception):
    """頁面 404，只跳過這一筆。"""


def open_page(page: Any, url: str) -> None:
    """開啟後台頁面並檢查停止條件。"""
    try:
        response = page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 - 只顯示例外類型，避免訊息夾帶敏感內容
        raise StopRun(f"頁面載入失敗（{type(exc).__name__}）") from None
    if response is None:
        raise StopRun("沒有收到 HTTP 回應")
    status = int(response.status)
    final_url = str(page.url or response.url or url)
    if status == 404:
        raise PageNotFound("HTTP 404")
    if status in STOP_STATUSES or 500 <= status <= 599:
        raise StopRun(f"HTTP {status}")
    if is_login_url(final_url):
        raise StopRun("被導回登入頁，cookie 可能已失效")
    if urlsplit(final_url).netloc != ADMIN_HOST:
        raise StopRun("被導到後台以外的網址")
    if status >= 400:
        raise StopRun(f"非預期的 HTTP {status}")
    try:
        page.wait_for_load_state("networkidle", timeout=SAVE_WAIT_MS)
    except Exception:  # noqa: BLE001 - 等不到網路閒置不影響，照常讀取
        pass
    if has_captcha(str(page.content())):
        raise StopRun("頁面出現驗證碼")


def _slug(url: str) -> str:
    """把後台網址路徑轉成檔名用的代號，例如 custom_pages_271201_edit。"""
    path = urlsplit(url).path.removeprefix("/admin/").strip("/")
    return re.sub(r"[^A-Za-z0-9_-]+", "_", path) or "admin"


def strip_csrf(html: str) -> str:
    """備份前把 CSRF token 清空（不是 cookie，但也不該留在檔案裡）。"""
    html = CSRF_META_RE.sub(r"\1\2", html)
    return CSRF_INPUT_RE.sub(r"\1\2", html)


def backup_page(page: Any, change: Change, current: Any, backup_root: Path, now: datetime) -> Path:
    """把頁面原本的 HTML 與欄位值備份到 backups/YYYY-MM-DD/，回傳 .json 的路徑。"""
    folder = backup_root / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{now.strftime('%H%M%S')}_{_slug(change.url)}_{change.field}"
    html_path = folder / f"{stem}.html"
    html_path.write_text(strip_csrf(str(page.content())), encoding="utf-8")
    record = {
        "backed_up_at": now.isoformat(timespec="seconds"),
        "source": change.source,
        "url": change.url,
        "field": change.field,
        "current_value": current,
        "change": {k: v for k, v in asdict(change).items() if k != "source"},
        "html_file": html_path.name,
    }
    json_path = folder / f"{stem}.json"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def click_save(page: Any) -> bool:
    """按下頁面上的儲存按鈕；找不到回傳 False。"""
    for selector in SAVE_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            locator.first.click()
            return True
    return False


def save_once(page: Any, guard: EditRequestGuard, change: Change) -> bool:
    """臨時放行這一筆的儲存請求、按下儲存，結束後一定恢復封鎖。回傳是否真的送出。"""
    guard.allow_once(save_path(change.url))
    try:
        if not click_save(page):
            say("⚠ 找不到儲存按鈕")
            return False
        try:
            page.wait_for_load_state("networkidle", timeout=SAVE_WAIT_MS)
        except Exception:  # noqa: BLE001
            pass
        return not guard.is_open
    finally:
        guard.revoke()


def verify_url(change: Change) -> str:
    """儲存後要重新載入確認的頁面：新增類（轉址）看列表頁，其他重新開同一頁。"""
    if change.field_def.creates:
        return f"https://{ADMIN_HOST}{save_path(change.url)}"
    return change.url


def verify_saved(page: Any, change: Change, expected: Any) -> tuple[bool, str]:
    """重新載入後確認值已修改。轉址檢查列表頁有沒有出現新舊網址。"""
    if change.field_def.creates:
        text = unquote(str(page.content()))
        missing = [v for v in expected.values() if unquote(v) not in text]
        return (not missing, "" if not missing else f"列表上找不到 {', '.join(missing)}")
    found, actual = read_field(page, change)
    if not found:
        return False, "重新載入後找不到欄位"
    if values_match(expected, actual):
        return True, ""
    return False, f"重新載入後的值是：{show_value(actual)}"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


@dataclass
class EditResult:
    """一筆修改的結果。"""

    change: Change
    status: str  # 預覽符合、成功、跳過、失敗
    message: str = ""


def is_interactive(stdin: Any = None) -> bool:
    """檢查標準輸入是否為真人終端機；管線、重新導向或檢查失敗都視為否。"""
    stream = sys.stdin if stdin is None else stdin
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def ask_keyboard(prompt: str, getch: Callable[[], bytes | str] | None = None) -> str:
    """顯示提示並讀取一個實體鍵盤按鍵。

    Windows 用 msvcrt.getch() 直接讀主控台鍵盤，不經過 stdin，
    所以管線或重新導向的內容不會被當成確認。讀取前先清掉鍵盤緩衝區，
    避免事先打好的字被當成回答。非 Windows 時必須是終端機才用 input()，否則一律視為取消。
    getch 可替換（測試用）。
    """
    print(prompt, end="", flush=True)
    if getch is None:
        if sys.platform == "win32":
            import msvcrt

            while msvcrt.kbhit():
                msvcrt.getch()
            getch = msvcrt.getch
        elif is_interactive():
            return input()
        else:
            print()
            return ""
    key = getch()
    text = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
    print(text if text.isprintable() else "")
    return text


@dataclass
class RunOptions:
    """執行選項與可替換的外部依賴（測試用）。"""

    apply: bool = False
    confirm: str = "each"
    ask: Callable[[str], str] = lambda prompt: ask_keyboard(prompt)
    sleep: Callable[[float], None] = time.sleep
    random_delay: Callable[[], float] = random_page_delay
    backup_root: Path = BACKUP_DIR
    now: Callable[[], datetime] = datetime.now
    results: list[EditResult] = field(default_factory=list)


def _record(options: RunOptions, change: Change, status: str, message: str = "") -> None:
    """記錄並顯示一筆結果。"""
    options.results.append(EditResult(change, status, message))
    say(f"結果：{status}｜{change.source}｜{change.url}｜{change.field}" + (f"｜{message}" if message else ""))


def confirm_batch(changes: Sequence[Change], ask: Callable[[str], str]) -> bool:
    """--confirm=batch：顯示整份清單，使用者輸入 y 才執行全部。"""
    say("=" * 50)
    say(f"即將修改以下 {len(changes)} 筆（每筆仍會先比對目前的值，不符就跳過）：")
    for index, change in enumerate(changes, 1):
        say(describe_change(change, index))
    say("=" * 50)
    return ask("全部執行請輸入 y，其他任何字取消：").strip().lower() == "y"


def process_change(page: Any, guard: EditRequestGuard, change: Change, options: RunOptions) -> None:
    """處理一筆：開頁 → 比對 → （確認 → 備份 → 填值 → 儲存 → 重新載入驗證）。"""
    say("-" * 50)
    say(describe_change(change))
    try:
        open_page(page, change.url)
    except PageNotFound as exc:
        _record(options, change, "跳過", str(exc))
        return
    found, current = read_field(page, change)
    if not found:
        say("⚠ 警告：頁面上找不到這個欄位，跳過")
        _record(options, change, "跳過", "找不到欄位")
        return
    new_value, problem = plan_value(change, current)
    if new_value is None:
        say(f"⚠ 警告：{problem}，跳過")
        say(f"    目前的值：{show_value(current)}")
        _record(options, change, "跳過", problem)
        return
    if not options.apply:
        _record(options, change, "預覽符合", "目前的值與修改單相符；加 --apply 才會修改")
        return
    if options.confirm == "each":
        answer = options.ask("要儲存這一筆嗎？輸入 y 儲存，其他任何字跳過：")
        if answer.strip().lower() != "y":
            _record(options, change, "跳過", "使用者未確認")
            return
    backup = backup_page(page, change, current, options.backup_root, options.now())
    say(f"已備份原本的設定：{backup}")
    if not write_field(page, change, new_value):
        _record(options, change, "失敗", "無法把新值填進欄位（例如下拉選單沒有這個選項），未儲存")
        return
    if not save_once(page, guard, change):
        _record(options, change, "失敗", "沒有送出儲存請求")
        return
    options.sleep(options.random_delay())
    open_page(page, verify_url(change))
    ok, message = verify_saved(page, change, new_value)
    _record(options, change, "成功" if ok else "失敗", "已重新載入確認" if ok else f"驗證失敗：{message}")


def run_changes(page: Any, guard: EditRequestGuard, changes: Sequence[Change], options: RunOptions) -> str:
    """依序處理所有修改；每次載入頁面之間隨機等待 2～5 秒。回傳停止原因。"""
    for index, change in enumerate(changes):
        if index > 0:
            options.sleep(options.random_delay())
        try:
            process_change(page, guard, change, options)
        except StopRun as exc:
            _record(options, change, "失敗", f"停止：{exc}")
            return f"停止：{exc}"
        finally:
            guard.revoke()
    return "全部處理完"


def run_with_browser(browser: Any, get_cookies: Callable[[list[str]], Any], changes: Sequence[Change], options: RunOptions) -> str:
    """取得並注入 cookie、開一個預設擋下非 GET 的分頁，依序處理修改。"""
    try:
        cookies = to_playwright_cookies(get_cookies(list(COOKIE_DOMAINS)))
    except Exception as exc:  # noqa: BLE001 - 只顯示例外類型，避免訊息夾帶 cookie
        return f"取得 cookie 失敗（{type(exc).__name__}）"
    if not cookies:
        return "沒有取得 Cyberbiz 後台的 cookie"
    say(f"已取得 {len(cookies)} 個 Cyberbiz cookie（內容不顯示）")

    context = browser.new_context()
    try:
        try:
            context.add_cookies(cookies)
        except Exception as exc:  # noqa: BLE001
            return f"注入 cookie 失敗（{type(exc).__name__}）"
        finally:
            cookies.clear()
        page = context.new_page()
        guard = EditRequestGuard()
        page.route("**/*", guard.handle)
        say(WATCH_MESSAGE)
        return run_changes(page, guard, changes, options)
    finally:
        context.close()


def summarize(options: RunOptions, reason: str) -> None:
    """在終端機與 log 顯示總結。"""
    counts: dict[str, int] = {}
    for result in options.results:
        counts[result.status] = counts.get(result.status, 0) + 1
    say("=" * 50)
    say(f"結束：{reason}")
    say("；".join(f"{k} {v} 筆" for k, v in counts.items()) or "沒有處理任何一筆")
    say("=" * 50)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(description="依修改單修改 Cyberbiz 後台（預設只預覽）")
    parser.add_argument("--file", help="修改單路徑（沒給時讀 changes/ 底下所有 .yaml）")
    parser.add_argument("--apply", action="store_true", help="真的儲存修改（沒加時只預覽）")
    parser.add_argument(
        "--confirm",
        choices=("each", "batch"),
        default="each",
        help="each：每筆確認（預設）；batch：看完整份清單後確認一次",
    )
    return parser.parse_args(argv)


def setup_file_log(log_dir: Path, today: datetime) -> Path:
    """把訊息同時寫到 logs/admin_edit_YYYY-MM-DD.log。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"admin_edit_{today.strftime('%Y-%m-%d')}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def launch_browser(playwright: Any) -> Any:
    """啟動有畫面的瀏覽器（headless=False、slow_mo=800）。"""
    return playwright.chromium.launch(headless=False, slow_mo=SLOW_MO_MS)


def main(argv: Sequence[str] | None = None) -> int:
    """命令列進入點。任何錯誤都只顯示例外類型，避免訊息夾帶 cookie。

    啟動時先檢查是否由真人在終端機執行；不是就拒絕執行（防止 AI 或腳本透過管線代為確認）。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if not is_interactive():
        print("拒絕執行：admin_edit.py 只能由使用者在終端機親自執行（偵測到非互動式輸入）", file=sys.stderr)
        return 2
    args = parse_args(argv)
    log_path = setup_file_log(LOG_DIR, datetime.now())
    say(f"模式：{'執行（會儲存）' if args.apply else '預覽（不儲存）'}；確認方式：{args.confirm}；紀錄：{log_path}")

    files = change_files(args.file)
    if not files:
        say("找不到任何修改單（changes/*.yaml）")
        return 1
    say("修改單：" + "、".join(str(p) for p in files))
    changes = load_changes(files)
    if not changes:
        say("沒有任何合法的修改項目")
        return 1

    options = RunOptions(apply=args.apply, confirm=args.confirm)
    if args.apply and args.confirm == "batch" and not confirm_batch(changes, options.ask):
        say("使用者取消，未開啟瀏覽器")
        return 1
    try:
        get_cookies = load_get_cookies(xinchi_tools_path_from_env())
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                reason = run_with_browser(browser, get_cookies, changes, options)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        say(f"程式中止：{type(exc).__name__}（為避免洩漏 cookie，不顯示詳細訊息）")
        return 1
    summarize(options, reason)
    return 0 if reason == "全部處理完" else 1


if __name__ == "__main__":
    raise SystemExit(main())
