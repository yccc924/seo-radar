"""scripts/admin_edit.py 的測試。

全部使用假瀏覽器、假分頁與假 get_cookies：不連網、不呼叫真的 elevated_cookies、
不啟動真實瀏覽器。假分頁會模擬「伺服器上的值」與 page.route 攔截：
只有攔截器放行的儲存請求才會真的改到伺服器上的值。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("admin_edit", ROOT / "scripts" / "admin_edit.py")
assert _spec and _spec.loader
ae = importlib.util.module_from_spec(_spec)
sys.modules["admin_edit"] = ae
_spec.loader.exec_module(ae)

ADMIN = f"https://{ae.ADMIN_HOST}"
PAGE_URL = f"{ADMIN}/admin/custom_pages/271201/edit"
PAGE_URL_2 = f"{ADMIN}/admin/custom_pages/271199/edit"
REDIRECT_NEW = f"{ADMIN}/admin/redirections/new"
REDIRECT_LIST = f"{ADMIN}/admin/redirections"
SECRET = "SECRET_COOKIE_VALUE_12345"
NOW = datetime(2026, 10, 17, 14, 30, 5)


# ---------------------------------------------------------------------------
# 假瀏覽器
# ---------------------------------------------------------------------------


class FakeResponse:
    """假的 HTTP 回應。"""

    def __init__(self, status: int, url: str) -> None:
        self.status = status
        self.url = url


class FakeRequest:
    """假的請求（只有方法與網址）。"""

    def __init__(self, method: str, url: str) -> None:
        self.method = method
        self.url = url


class FakeRoute:
    """假的 route：記錄被放行或擋下。"""

    def __init__(self, method: str, url: str) -> None:
        self.request = FakeRequest(method, url)
        self.continued = False
        self.aborted = False

    def continue_(self) -> None:
        self.continued = True

    def abort(self) -> None:
        self.aborted = True


class FakeServer:
    """假的 Cyberbiz：每個網址有一組欄位值；redirects 是已建立的轉址。"""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}
        self.status: dict[str, int] = {}
        self.final_url: dict[str, str] = {}
        self.redirects: list[tuple[str, str]] = []
        self.save_path_override: dict[str, str] = {}
        self.strip_on_save: bool = False


def _key(spec: dict[str, Any]) -> str:
    """假分頁用來找欄位的鍵：有 selector 用 selector，否則用第一個 name 關鍵字。"""
    return spec.get("selector") or spec["names"][0]


class FakeLocator:
    """假的 locator：只認得「儲存」按鈕。"""

    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def count(self) -> int:
        return 1 if self.page.has_save_button and self.selector == ae.SAVE_SELECTORS[0] else 0

    @property
    def first(self) -> FakeLocator:
        return self

    def click(self) -> None:
        self.page.clicks += 1
        self.page.submit()


class FakePage:
    """假分頁：goto 會從伺服器載入值；evaluate 讀寫 DOM；按儲存會送出 POST 經過攔截器。"""

    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self.url = ""
        self.dom: dict[str, str] = {}
        self.handler: Any = None
        self.routes: list[str] = []
        self.visited: list[str] = []
        self.clicks = 0
        self.has_save_button = True
        self.html = "<html><body>編輯頁</body></html>"

    def route(self, pattern: str, handler: Any) -> None:
        self.routes.append(pattern)
        self.handler = handler

    def _request(self, method: str, url: str) -> FakeRoute:
        route = FakeRoute(method, url)
        assert self.handler is not None, "必須先註冊 page.route 才能發請求"
        self.handler(route)
        return route

    def goto(self, url: str, wait_until: str = "load", timeout: int = 0) -> FakeResponse:
        route = self._request("GET", url)
        assert route.continued
        self.visited.append(url)
        self.url = self.server.final_url.get(url, url)
        self.dom = dict(self.server.values.get(url, {}))
        if url == REDIRECT_LIST:
            self.html = "<table>" + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in self.server.redirects) + "</table>"
        else:
            self.html = '<html><head><meta name="csrf-token" content="CSRF123"></head><body>編輯頁</body></html>'
        return FakeResponse(self.server.status.get(url, 200), self.url)

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        return None

    def content(self) -> str:
        return self.html

    def evaluate(self, script: str, arg: Any) -> dict[str, Any]:
        if script == ae.READ_FIELD_JS:
            key = _key(arg)
            if key not in self.dom:
                return {"found": False, "value": ""}
            return {"found": True, "kind": "text", "value": self.dom[key]}
        if script == ae.WRITE_FIELD_JS:
            key = _key(arg["spec"])
            if key not in self.dom:
                return {"ok": False}
            self.dom[key] = arg["value"]
            return {"ok": True}
        raise AssertionError("未預期的 evaluate")

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def submit(self) -> None:
        """模擬按下儲存：送出 POST，只有被放行才會改到伺服器。"""
        url = self.server.save_path_override.get(self.url) or f"{ADMIN}{ae.save_path(self.url)}"
        route = self._request("POST", url)
        if not route.continued:
            return
        if self.url == REDIRECT_NEW:
            self.server.redirects.append((self.dom["[path]"], self.dom["[target]"]))
            return
        saved = dict(self.dom)
        if self.server.strip_on_save:
            saved = {k: v.replace("<script", "") for k, v in saved.items()}
        self.server.values[self.url] = saved


class FakeContext:
    """假的 browser context。"""

    def __init__(self, page: FakePage, fail_cookies: bool = False) -> None:
        self.page = page
        self.cookies: list[dict[str, Any]] = []
        self.closed = False
        self.fail_cookies = fail_cookies

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        if self.fail_cookies:
            raise RuntimeError(SECRET)
        self.cookies.extend(dict(c) for c in cookies)

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    """假的瀏覽器。"""

    def __init__(self, page: FakePage, fail_cookies: bool = False) -> None:
        self.context = FakeContext(page, fail_cookies)

    def new_context(self) -> FakeContext:
        return self.context


# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_logger() -> Any:
    """每個測試後移除 log 檔 handler，避免互相影響。"""
    yield
    for handler in list(ae.logger.handlers):
        ae.logger.removeHandler(handler)
        handler.close()


def make_change(**overrides: Any) -> Any:
    """建立一筆合法的修改（預設：自訂頁面 status 發佈 → 隱藏）。"""
    raw: dict[str, Any] = {
        "url": PAGE_URL,
        "title": "iPhone 17 Pro Max 512GB 二手收購價",
        "field": "status",
        "field_label": "頁面狀態",
        "before": "發佈",
        "after": "隱藏",
        "reason": "S12 重複頁",
    }
    raw.update(overrides)
    change, problem = ae.validate_change(raw)
    assert change is not None, problem
    change.source = "test.yaml"
    return change


def make_options(tmp_path: Path, answers: list[str] | None = None, **kwargs: Any) -> Any:
    """建立測試用的執行選項：不真的等待，回答依序取自 answers。"""
    queue = list(answers or [])
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return queue.pop(0) if queue else ""

    options = ae.RunOptions(
        ask=ask,
        sleep=lambda s: None,
        random_delay=lambda: 3.0,
        backup_root=tmp_path / "backups",
        now=lambda: NOW,
        **kwargs,
    )
    options.asked = asked  # type: ignore[attr-defined]
    return options


def setup(values: dict[str, dict[str, str]] | None = None) -> tuple[FakeServer, FakePage, Any]:
    """建立假伺服器、假分頁並註冊攔截器。"""
    server = FakeServer()
    server.values = values if values is not None else {PAGE_URL: {"[status]": "發佈"}}
    page = FakePage(server)
    guard = ae.EditRequestGuard()
    page.route("**/*", guard.handle)
    return server, page, guard


# ---------------------------------------------------------------------------
# 修改單讀取與檢查
# ---------------------------------------------------------------------------


def test_real_s12_change_file_is_valid() -> None:
    changes = ae.load_changes([ROOT / "changes" / "2026-10-17-s12.yaml"])
    assert [c.field for c in changes] == ["status", "status"]
    assert changes[0].before == "發佈" and changes[0].after == "隱藏"
    assert changes[0].op == "set"
    assert changes[0].label == "頁面狀態"
    assert changes[0].source == "2026-10-17-s12.yaml"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": "https://evil.example.com/admin/custom_pages/1/edit"}, "不是 Cyberbiz 後台網址"),
        ({"url": f"http://{ae.ADMIN_HOST}/admin/custom_pages/1/edit"}, "不是 Cyberbiz 後台網址"),
        ({"url": f"{ADMIN}/admin/products/1/edit"}, "不在允許修改"),
        ({"url": f"{ADMIN}/admin/orders/1/edit"}, "不在允許修改"),
        ({"url": f"{ADMIN}/admin/custom_pages/1/delete"}, "敏感頁面"),
        ({"field": "price"}, "不支援的欄位"),
        ({"op": "delete"}, "不支援的修改方式"),
        ({"op": "replace", "before": ""}, "before 不可為空"),
        ({"op": "append", "after": ""}, "after 不可為空"),
        ({"before": {"a": "b"}}, "必須是文字"),
        ({"field": "redirect", "url": REDIRECT_NEW, "before": "", "after": "x"}, "對照"),
        (
            {"field": "redirect", "url": REDIRECT_NEW, "before": {"path": ""}, "after": {"path": "/a"}},
            "剛好有",
        ),
    ],
)
def test_validate_change_rejects(overrides: dict[str, Any], message: str) -> None:
    raw = {"url": PAGE_URL, "field": "status", "before": "發佈", "after": "隱藏", "reason": "r"}
    raw.update(overrides)
    change, problem = ae.validate_change(raw)
    assert change is None
    assert message in problem


def test_validate_change_requires_all_keys() -> None:
    change, problem = ae.validate_change({"url": PAGE_URL, "field": "status", "before": "發佈"})
    assert change is None
    assert "after" in problem and "reason" in problem


def test_validate_change_accepts_redirect() -> None:
    change, _ = ae.validate_change(
        {
            "url": REDIRECT_NEW,
            "field": "redirect",
            "before": {"path": None, "target": ""},
            "after": {"path": "/pages/old", "target": "/pages/new"},
            "reason": "r",
        }
    )
    assert change is not None
    assert change.before == {"path": "", "target": ""}


def test_load_changes_skips_invalid_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "changes": [
                    {"url": PAGE_URL, "field": "status", "before": "發佈", "after": "隱藏", "reason": "ok"},
                    {"url": f"{ADMIN}/admin/products/1/edit", "field": "status", "before": "a", "after": "b", "reason": "x"},
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    changes = ae.load_changes([path])
    assert len(changes) == 1
    assert "第 2 筆不合法" in capsys.readouterr().out


def test_load_changes_accepts_plain_list_and_bad_file(tmp_path: Path) -> None:
    good = tmp_path / "list.yaml"
    good.write_text(
        yaml.safe_dump([{"url": PAGE_URL, "field": "status", "before": "發佈", "after": "隱藏", "reason": "r"}]),
        encoding="utf-8",
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text("description: 沒有清單\n", encoding="utf-8")
    assert len(ae.load_changes([good, bad, tmp_path / "missing.yaml"])) == 1


def test_change_files(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "a.yml").write_text("[]", encoding="utf-8")
    (tmp_path / "note.txt").write_text("", encoding="utf-8")
    assert [p.name for p in ae.change_files(None, tmp_path)] == ["a.yml", "b.yaml"]
    assert ae.change_files("x.yaml", tmp_path) == [Path("x.yaml")]


# ---------------------------------------------------------------------------
# 比對與新值
# ---------------------------------------------------------------------------


def test_plan_value_set() -> None:
    change = make_change()
    assert ae.plan_value(change, " 發佈 ") == ("隱藏", "")
    value, problem = ae.plan_value(change, "隱藏")
    assert value is None and "不等於" in problem


def test_plan_value_replace() -> None:
    change = make_change(field="seo_description", op="replace", before="數化路", after="敦化路")
    assert ae.plan_value(change, "台中市北屯區數化路一段493號")[0] == "台中市北屯區敦化路一段493號"
    assert ae.plan_value(change, "敦化路")[0] is None
    assert "2 次" in ae.plan_value(change, "數化路 數化路")[1]


def test_plan_value_replace_can_delete_text() -> None:
    change = make_change(field="body_html", op="replace", before="<h1></h1>", after="")
    assert ae.plan_value(change, "<h1></h1><p>內文</p>")[0] == "<p>內文</p>"


def test_plan_value_prepend_and_append() -> None:
    prepend = make_change(field="body_html", op="prepend", before="", after="<h1>標題</h1>", absent="<h1")
    assert ae.plan_value(prepend, "  <p>內文</p>")[0] == "<h1>標題</h1>\n<p>內文</p>"
    assert ae.plan_value(prepend, "<H1 class='x'>已有</H1>")[0] is None
    append = make_change(field="body_html", op="append", before="", after="<script>{}</script>")
    assert ae.plan_value(append, "<p>內文</p>\n")[0] == "<p>內文</p>\n<script>{}</script>"
    assert ae.plan_value(append, "<p>內文</p><script>{}</script>")[0] is None


def test_plan_value_move_style_to_end() -> None:
    change = make_change(field="body_html", op="move_style_to_end", before="開頭 style", after="移到文末")
    html = "\n<style>\n.a { color: red; }\n</style>\n<p>內文</p>\n"
    assert ae.plan_value(change, html)[0] == "<p>內文</p>\n<style>\n.a { color: red; }\n</style>"
    value, problem = ae.plan_value(change, "<p>內文</p><style>.a{}</style>")
    assert value is None and "<style>" in problem


def test_describe_change_and_show_value() -> None:
    text = ae.describe_change(make_change(note="AI 撰寫，請確認內容"), 2)
    assert "[2] 頁面：iPhone 17 Pro Max 512GB" in text
    assert "欄位：頁面狀態" in text
    assert "改前：發佈" in text and "改後：隱藏" in text
    assert "AI 撰寫" in text
    assert ae.show_value("") == "（空白）"
    assert ae.show_value({"path": "/a", "target": ""}) == "path：/a；target：（空白）"
    assert "共 600 字" in ae.show_value("x" * 600)


def test_field_specs_use_label_and_selector() -> None:
    specs = ae.field_specs(make_change(selector="#page_status"))
    assert specs == [(None, {"selector": "#page_status", "names": ["[status]", "[published]", "[visible]"], "labels": ["頁面狀態", "狀態"]})]
    redirect = make_change(
        url=REDIRECT_NEW, field="redirect", field_label="", before={"path": "", "target": ""}, after={"path": "/a", "target": "/b"},
        selector={"path": "#old"},
    )
    parts = ae.field_specs(redirect)
    assert [k for k, _ in parts] == ["path", "target"]
    assert parts[0][1]["selector"] == "#old" and parts[1][1]["selector"] is None


def test_field_js_never_submits() -> None:
    for script in (ae.READ_FIELD_JS, ae.WRITE_FIELD_JS):
        for word in ("submit()", "fetch(", "XMLHttpRequest", "requestSubmit", "document.cookie"):
            assert word not in script


# ---------------------------------------------------------------------------
# 攔截器
# ---------------------------------------------------------------------------


def test_guard_blocks_non_get_by_default() -> None:
    guard = ae.EditRequestGuard()
    get = FakeRoute("GET", PAGE_URL)
    guard.handle(get)
    assert get.continued
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        route = FakeRoute(method, f"{ADMIN}/admin/custom_pages/271201")
        guard.handle(route)
        assert route.aborted and not route.continued
    assert len(guard.blocked) == 4


def test_guard_allows_only_one_matching_save() -> None:
    guard = ae.EditRequestGuard()
    guard.allow_once(ae.save_path(PAGE_URL))
    other = FakeRoute("POST", f"{ADMIN}/admin/custom_pages/999")
    guard.handle(other)
    assert other.aborted, "別頁的儲存不放行"
    foreign = FakeRoute("POST", "https://evil.example.com/admin/custom_pages/271201")
    guard.handle(foreign)
    assert foreign.aborted
    save = FakeRoute("PATCH", f"{ADMIN}/admin/custom_pages/271201.json")
    guard.handle(save)
    assert save.continued
    assert not guard.is_open
    again = FakeRoute("POST", f"{ADMIN}/admin/custom_pages/271201")
    guard.handle(again)
    assert again.aborted, "放行一次後立即恢復封鎖"
    assert guard.allowed == [("PATCH", f"{ADMIN}/admin/custom_pages/271201.json")]


def test_guard_revoke() -> None:
    guard = ae.EditRequestGuard()
    guard.allow_once("/admin/custom_pages/1")
    guard.revoke()
    route = FakeRoute("POST", f"{ADMIN}/admin/custom_pages/1")
    guard.handle(route)
    assert route.aborted


def test_save_path() -> None:
    assert ae.save_path(PAGE_URL) == "/admin/custom_pages/271201"
    assert ae.save_path(REDIRECT_NEW) == "/admin/redirections"
    assert ae.save_path(f"{ADMIN}/admin/blogs/1/articles/2/edit/") == "/admin/blogs/1/articles/2"


# ---------------------------------------------------------------------------
# 預覽模式
# ---------------------------------------------------------------------------


def test_preview_does_not_save(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL: {"[status]": "發佈"}, PAGE_URL_2: {"[status]": "隱藏"}})
    options = make_options(tmp_path, apply=False)
    changes = [make_change(), make_change(url=PAGE_URL_2)]
    assert ae.run_changes(page, guard, changes, options) == "全部處理完"
    assert [r.status for r in options.results] == ["預覽符合", "跳過"]
    assert "不等於" in options.results[1].message
    assert server.values[PAGE_URL] == {"[status]": "發佈"}
    assert page.clicks == 0
    assert options.asked == []
    assert not (tmp_path / "backups").exists()


def test_preview_waits_between_pages(tmp_path: Path) -> None:
    _, page, guard = setup({PAGE_URL: {"[status]": "發佈"}, PAGE_URL_2: {"[status]": "發佈"}})
    waits: list[float] = []
    options = make_options(tmp_path)
    options.sleep = waits.append
    ae.run_changes(page, guard, [make_change(), make_change(url=PAGE_URL_2)], options)
    assert waits == [3.0]
    for _ in range(50):
        assert 2.0 <= ae.random_page_delay() <= 5.0


def test_missing_field_is_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, page, guard = setup({PAGE_URL: {}})
    options = make_options(tmp_path, apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    assert options.results[0].status == "跳過"
    assert "找不到這個欄位" in capsys.readouterr().out


def test_mismatch_warns_and_skips_in_apply_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    server, page, guard = setup({PAGE_URL: {"[status]": "隱藏"}})
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    out = capsys.readouterr().out
    assert "⚠ 警告" in out and "目前的值：隱藏" in out
    assert options.asked == []
    assert page.clicks == 0
    assert server.values[PAGE_URL] == {"[status]": "隱藏"}


# ---------------------------------------------------------------------------
# 執行模式
# ---------------------------------------------------------------------------


def test_apply_each_yes_backs_up_saves_and_verifies(tmp_path: Path) -> None:
    server, page, guard = setup()
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    assert options.results[0].status == "成功"
    assert server.values[PAGE_URL] == {"[status]": "隱藏"}
    assert len(options.asked) == 1
    assert page.visited == [PAGE_URL, PAGE_URL], "儲存後重新載入同一頁確認"
    assert len(guard.allowed) == 1
    assert not guard.is_open

    folder = tmp_path / "backups" / "2026-10-17"
    record = json.loads((folder / "143005_custom_pages_271201_edit_status.json").read_text(encoding="utf-8"))
    assert record["current_value"] == "發佈"
    assert record["change"]["after"] == "隱藏"
    html = (folder / record["html_file"]).read_text(encoding="utf-8")
    assert "編輯頁" in html and "CSRF123" not in html


def test_apply_each_other_answer_skips(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL: {"[status]": "發佈"}, PAGE_URL_2: {"[status]": "發佈"}})
    options = make_options(tmp_path, ["n", "Y"], apply=True)
    ae.run_changes(page, guard, [make_change(), make_change(url=PAGE_URL_2)], options)
    assert [r.status for r in options.results] == ["跳過", "成功"]
    assert server.values[PAGE_URL] == {"[status]": "發佈"}
    assert server.values[PAGE_URL_2] == {"[status]": "隱藏"}
    assert not list((tmp_path / "backups" / "2026-10-17").glob("*271201*"))


def test_non_get_stays_blocked_after_skip(tmp_path: Path) -> None:
    server, page, guard = setup()
    options = make_options(tmp_path, ["n"], apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    page.submit()  # 使用者沒確認時，頁面自己送出的儲存也會被擋
    assert server.values[PAGE_URL] == {"[status]": "發佈"}
    assert guard.blocked and guard.blocked[-1][0] == "POST"


def test_save_to_other_path_is_blocked(tmp_path: Path) -> None:
    server, page, guard = setup()
    server.save_path_override[PAGE_URL] = f"{ADMIN}/admin/custom_pages/999"
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    assert options.results[0].status == "失敗"
    assert "沒有送出儲存請求" in options.results[0].message
    assert server.values[PAGE_URL] == {"[status]": "發佈"}
    assert not guard.is_open


def test_missing_save_button_fails(tmp_path: Path) -> None:
    server, page, guard = setup()
    page.has_save_button = False
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [make_change()], options)
    assert options.results[0].status == "失敗"
    assert not guard.is_open
    assert server.values[PAGE_URL] == {"[status]": "發佈"}


def test_verify_failure_is_reported(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL: {"body_html": "<p>內文</p>"}})
    server.strip_on_save = True
    change = make_change(field="body_html", field_label="", op="append", before="", after='<script type="application/ld+json">{}</script>')
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [change], options)
    assert options.results[0].status == "失敗"
    assert "驗證失敗" in options.results[0].message


def test_move_style_to_end_end_to_end(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL: {"body_html": "<style>.a{}</style><p>內文</p>"}})
    change = make_change(field="body_html", field_label="", op="move_style_to_end", before="開頭 style", after="移到文末")
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [change], options)
    assert options.results[0].status == "成功"
    assert server.values[PAGE_URL]["body_html"] == "<p>內文</p>\n<style>.a{}</style>"


def test_redirect_create_and_verify_on_list(tmp_path: Path) -> None:
    server, page, guard = setup({REDIRECT_NEW: {"[path]": "", "[target]": ""}})
    change = make_change(
        url=REDIRECT_NEW, field="redirect", field_label="", before={"path": "", "target": ""},
        after={"path": "/pages/iphone-17-pro-max-512gb-二手收購價", "target": "/pages/17-pro-max-512g"},
    )
    options = make_options(tmp_path, ["y"], apply=True)
    ae.run_changes(page, guard, [change], options)
    assert server.redirects == [("/pages/iphone-17-pro-max-512gb-二手收購價", "/pages/17-pro-max-512g")]
    assert page.visited == [REDIRECT_NEW, REDIRECT_LIST]
    assert options.results[0].status == "成功"
    assert guard.allowed == [("POST", REDIRECT_LIST)]


def test_batch_mode_does_not_ask_per_item(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL: {"[status]": "發佈"}, PAGE_URL_2: {"[status]": "發佈"}})
    options = make_options(tmp_path, apply=True, confirm="batch")
    ae.run_changes(page, guard, [make_change(), make_change(url=PAGE_URL_2)], options)
    assert options.asked == []
    assert [r.status for r in options.results] == ["成功", "成功"]
    assert len(guard.allowed) == 2


def test_confirm_batch_lists_all_and_needs_y(capsys: pytest.CaptureFixture[str]) -> None:
    changes = [make_change(), make_change(url=PAGE_URL_2, title="256GB")]
    assert ae.confirm_batch(changes, lambda prompt: "y")
    out = capsys.readouterr().out
    assert "即將修改以下 2 筆" in out and "[1] 頁面" in out and "[2] 頁面：256GB" in out
    assert not ae.confirm_batch(changes, lambda prompt: "yes")
    assert not ae.confirm_batch(changes, lambda prompt: "")


# ---------------------------------------------------------------------------
# 停止條件
# ---------------------------------------------------------------------------


def test_404_skips_only_that_item(tmp_path: Path) -> None:
    server, page, guard = setup({PAGE_URL_2: {"[status]": "發佈"}})
    server.status[PAGE_URL] = 404
    options = make_options(tmp_path)
    assert ae.run_changes(page, guard, [make_change(), make_change(url=PAGE_URL_2)], options) == "全部處理完"
    assert [r.status for r in options.results] == ["跳過", "預覽符合"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_stop_statuses(tmp_path: Path, status: int) -> None:
    server, page, guard = setup({PAGE_URL: {"[status]": "發佈"}, PAGE_URL_2: {"[status]": "發佈"}})
    server.status[PAGE_URL] = status
    options = make_options(tmp_path)
    reason = ae.run_changes(page, guard, [make_change(), make_change(url=PAGE_URL_2)], options)
    assert reason == f"停止：HTTP {status}"
    assert page.visited == [PAGE_URL]


def test_login_redirect_stops(tmp_path: Path) -> None:
    server, page, guard = setup()
    server.final_url[PAGE_URL] = f"{ADMIN}/admin/login"
    options = make_options(tmp_path)
    assert "登入頁" in ae.run_changes(page, guard, [make_change()], options)


def test_captcha_stops(tmp_path: Path) -> None:
    _, page, guard = setup()
    page.goto = _wrap_goto(page, "<div class='g-recaptcha'></div>")  # type: ignore[method-assign]
    options = make_options(tmp_path)
    assert "驗證碼" in ae.run_changes(page, guard, [make_change()], options)


def _wrap_goto(page: FakePage, html: str) -> Any:
    original = page.goto

    def goto(url: str, **kwargs: Any) -> FakeResponse:
        response = original(url, **kwargs)
        page.html = html
        return response

    return goto


# ---------------------------------------------------------------------------
# cookie 與瀏覽器
# ---------------------------------------------------------------------------


def test_run_with_browser_keeps_cookie_in_memory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_path = ae.setup_file_log(tmp_path / "logs", NOW)
    server, page, _ = setup()
    page.handler = None
    page.routes = []
    browser = FakeBrowser(page)
    returned: list[Any] = []

    def get_cookies(domains: list[str]) -> list[dict[str, Any]]:
        cookies = [{"name": "_session", "value": SECRET, "domain": ".cyberbiz.co"}]
        returned.append(cookies)
        return cookies

    options = make_options(tmp_path, ["y"], apply=True)
    reason = ae.run_with_browser(browser, get_cookies, [make_change()], options)
    assert reason == "全部處理完"
    assert server.values[PAGE_URL] == {"[status]": "隱藏"}
    assert page.routes == ["**/*"]
    assert browser.context.closed
    assert browser.context.cookies[0]["value"] == SECRET

    out = capsys.readouterr().out
    assert ae.WATCH_MESSAGE in out
    assert SECRET not in out
    log_text = log_path.read_text(encoding="utf-8")
    assert log_path.name == "admin_edit_2026-10-17.log"
    assert "結果：成功" in log_text
    assert SECRET not in log_text
    for path in (tmp_path / "backups").rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8")


def test_run_with_browser_cookie_errors_hide_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, page, _ = setup()

    def broken(domains: list[str]) -> Any:
        raise RuntimeError(SECRET)

    options = make_options(tmp_path)
    assert ae.run_with_browser(FakeBrowser(page), broken, [make_change()], options) == "取得 cookie 失敗（RuntimeError）"
    assert ae.run_with_browser(FakeBrowser(page), lambda d: [], [make_change()], options) == "沒有取得 Cyberbiz 後台的 cookie"
    failing = FakeBrowser(page, fail_cookies=True)
    reason = ae.run_with_browser(failing, lambda d: {"_session": SECRET}, [make_change()], options)
    assert reason == "注入 cookie 失敗（RuntimeError）"
    assert failing.context.closed
    assert SECRET not in capsys.readouterr().out


def test_launch_browser_shows_window_with_slow_mo() -> None:
    calls: dict[str, Any] = {}

    class Chromium:
        def launch(self, **kwargs: Any) -> str:
            calls.update(kwargs)
            return "browser"

    class Playwright:
        chromium = Chromium()

    assert ae.launch_browser(Playwright()) == "browser"
    assert calls == {"headless": False, "slow_mo": 800}


def test_uses_admin_explore_cookie_loader() -> None:
    for func, name in ((ae.load_get_cookies, "load_get_cookies"), (ae.to_playwright_cookies, "to_playwright_cookies")):
        assert func.__module__ == "admin_explore"
        assert func.__name__ == name


# ---------------------------------------------------------------------------
# 命令列
# ---------------------------------------------------------------------------


def test_parse_args_defaults() -> None:
    args = ae.parse_args([])
    assert args.apply is False
    assert args.confirm == "each"
    assert ae.parse_args(["--apply", "--confirm=batch", "--file", "x.yaml"]).confirm == "batch"
    with pytest.raises(SystemExit):
        ae.parse_args(["--confirm=auto"])


def test_main_batch_cancel_never_opens_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ae, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    def no_cookies(path: Any) -> Any:
        raise AssertionError("取消後不應取得 cookie")

    monkeypatch.setattr(ae, "load_get_cookies", no_cookies)
    file = ROOT / "changes" / "2026-10-17-s12.yaml"
    assert ae.main(["--file", str(file), "--apply", "--confirm=batch"]) == 1
    log_text = (tmp_path / "logs" / f"admin_edit_{datetime.now():%Y-%m-%d}.log").read_text(encoding="utf-8")
    assert "使用者取消" in log_text


def test_main_without_valid_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ae, "LOG_DIR", tmp_path / "logs")
    empty = tmp_path / "empty.yaml"
    empty.write_text("changes: []\n", encoding="utf-8")
    assert ae.main(["--file", str(empty)]) == 1


def test_logger_has_no_handlers_left() -> None:
    assert not any(isinstance(h, logging.FileHandler) for h in ae.logger.handlers)
