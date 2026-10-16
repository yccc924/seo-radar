"""scripts/admin_explore.py 的測試。

全部使用假瀏覽器、假分頁與假 get_cookies：不連網、不呼叫真的 elevated_cookies、
不啟動真實瀏覽器。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("admin_explore", ROOT / "scripts" / "admin_explore.py")
assert _spec and _spec.loader
ae = importlib.util.module_from_spec(_spec)
sys.modules["admin_explore"] = ae
_spec.loader.exec_module(ae)

ADMIN = f"https://{ae.ADMIN_HOST}"
SECRET = "SECRET_COOKIE_VALUE_12345"

MENU_HTML = f"""<html><body>
<header><nav class="top-nav"><a href="/admin/profile">個人設定</a></nav></header>
<aside class="sidebar"><ul>
  <li><a href="/admin/products">商品</a></li>
  <li><a href="/admin/orders">訂單</a></li>
  <li><a href="{ADMIN}/admin/customers"> 會員
      管理 </a></li>
  <li><a href="/admin/blogs#top"><span>部落格</span></a></li>
  <li><a href="#">展開</a></li>
  <li><a href="javascript:void(0)">x</a></li>
  <li><a href="/admin/pages" title="自訂頁面"><i class="icon"></i></a></li>
  <li><a href="/admin/products">商品（重複）</a></li>
</ul></aside>
<main><a href="/admin/should-not-be-in-menu">內文連結</a></main>
</body></html>"""


# ---------------------------------------------------------------------------
# 假的 Playwright 物件
# ---------------------------------------------------------------------------


class FakeResponse:
    """模擬 Playwright Response。"""

    def __init__(self, status: int, url: str):
        """建立假回應。"""
        self.status = status
        self.url = url


class FakePage:
    """模擬 Playwright Page：依網址回傳 (狀態碼, HTML, 最終網址)。"""

    def __init__(self, pages: dict[str, tuple[int, str, str] | Exception] | None = None, default_html: str = "<html></html>"):
        """pages：網址 → (狀態碼, HTML, 最終網址) 或要丟出的例外；沒設定的網址回 200。"""
        self.pages = pages or {}
        self.default_html = default_html
        self.url = "about:blank"
        self._html = ""
        self.goto_calls: list[str] = []
        self.routes: list[tuple[str, Any]] = []

    def route(self, pattern: str, handler: Any) -> None:
        """記錄攔截器。"""
        self.routes.append((pattern, handler))

    def goto(self, url: str, **kwargs: Any) -> FakeResponse:
        """模擬導覽。"""
        self.goto_calls.append(url)
        result = self.pages.get(url, (200, self.default_html, url))
        if isinstance(result, Exception):
            raise result
        status, html, final_url = result
        self.url = final_url
        self._html = html
        return FakeResponse(status, final_url)

    def content(self) -> str:
        """回傳目前頁面 HTML。"""
        return self._html


class FakeContext:
    """模擬 BrowserContext。"""

    def __init__(self, page: FakePage, add_error: Exception | None = None):
        """建立假 context。"""
        self.page = page
        self.add_error = add_error
        self.cookies: list[dict[str, Any]] = []
        self.pages_opened = 0
        self.closed = False

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """記錄注入的 cookie（複製一份）。"""
        if self.add_error:
            raise self.add_error
        self.cookies = [dict(c) for c in cookies]

    def new_page(self) -> FakePage:
        """開新分頁。"""
        self.pages_opened += 1
        return self.page

    def close(self) -> None:
        """關閉 context。"""
        self.closed = True


class FakeBrowser:
    """模擬 Browser。"""

    def __init__(self, context: FakeContext):
        """建立假瀏覽器。"""
        self.context = context
        self.contexts_created = 0

    def new_context(self, **kwargs: Any) -> FakeContext:
        """建立 context。"""
        self.contexts_created += 1
        return self.context


class FakeRequest:
    """模擬 Playwright Request。"""

    def __init__(self, method: str, url: str):
        """建立假請求；headers 含 cookie，用來確認不會被記錄。"""
        self.method = method
        self.url = url
        self.headers = {"cookie": f"_admin_session={SECRET}"}


class FakeRoute:
    """模擬 Playwright Route。"""

    def __init__(self, method: str, url: str):
        """建立假 route。"""
        self.request = FakeRequest(method, url)
        self.action = ""

    def continue_(self) -> None:
        """放行。"""
        self.action = "continue"

    def abort(self) -> None:
        """擋下。"""
        self.action = "abort"


def fake_get_cookies(domains: list[str]) -> list[dict[str, Any]]:
    """假的 get_cookies：回傳含秘密字串的 cookie。"""
    assert domains == [".cyberbiz.co", "sinchih.cyberbiz.co"]
    return [
        {"name": "_admin_session", "value": SECRET, "domain": ".cyberbiz.co", "path": "/", "expires": 9999999999},
        {"name": "other_site", "value": SECRET, "domain": ".example.com", "path": "/"},
    ]


def no_sleep(_: float) -> None:
    """測試用：不真的等待。"""


def admin_urls(count: int) -> list[str]:
    """產生 count 個假後台網址。"""
    return [f"{ADMIN}/admin/p{i}" for i in range(count)]


def run_crawl(tmp_path: Path, page: FakePage, urls: list[str], **kwargs: Any) -> Any:
    """以假分頁執行 crawl，回傳結果。"""
    progress_path = tmp_path / "progress.json"
    progress = ae.Progress.load(progress_path)
    return ae.crawl(page, urls, progress, progress_path, on_page=lambda *a: None, sleep=no_sleep, **kwargs)


@pytest.fixture(autouse=True)
def no_real_browser_or_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """保險：測試中若意外匯入真的 elevated_cookies 或 playwright 就直接失敗。"""

    def blocked(*args: Any, **kwargs: Any) -> None:
        """攔截。"""
        raise AssertionError("測試不可呼叫真的 elevated_cookies 或啟動真實瀏覽器")

    monkeypatch.setattr(ae, "load_get_cookies", blocked)
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)


# ---------------------------------------------------------------------------
# 只放行 GET
# ---------------------------------------------------------------------------


class TestRequestGuard:
    """請求攔截。"""

    def test_get_allowed(self) -> None:
        """GET（不分大小寫）放行。"""
        guard = ae.RequestGuard()
        for method in ("GET", "get"):
            route = FakeRoute(method, f"{ADMIN}/admin")
            guard.handle(route)
            assert route.action == "continue"
        assert guard.blocked == []

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "post", "HEAD", "OPTIONS"])
    def test_non_get_blocked(self, method: str, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
        """非 GET 一律 abort，並記錄方法與網址，但不記錄 headers 或 cookie。"""
        caplog.set_level(logging.INFO, logger="admin_explore")
        guard = ae.RequestGuard()
        url = f"{ADMIN}/admin/api/save"
        route = FakeRoute(method, url)
        guard.handle(route)
        assert route.action == "abort"
        assert guard.blocked == [(method.upper(), url)]
        out = capsys.readouterr().out
        assert url in out and method.upper() in out
        assert url in caplog.text
        assert SECRET not in out + caplog.text

    def test_route_registered_for_all_requests(self, tmp_path: Path) -> None:
        """explore_admin 以 page.route('**/*', ...) 攔截所有請求。"""
        page = FakePage({ae.ADMIN_HOME: (200, MENU_HTML, ae.ADMIN_HOME)})
        ae.explore_admin(FakeBrowser(FakeContext(page)), fake_get_cookies, tmp_path, sleep=no_sleep)
        assert [pattern for pattern, _ in page.routes] == ["**/*"]
        _, handler = page.routes[0]
        post = FakeRoute("POST", f"{ADMIN}/admin/x")
        handler(post)
        assert post.action == "abort"


# ---------------------------------------------------------------------------
# 等待時間
# ---------------------------------------------------------------------------


class TestDelay:
    """每頁之間隨機等待 2～5 秒。"""

    def test_random_delay_range(self) -> None:
        """隨機秒數一定在 2～5 秒之間。"""
        delays = [ae.random_page_delay() for _ in range(500)]
        assert all(2.0 <= d <= 5.0 for d in delays)
        assert len(set(delays)) > 1

    def test_sleep_between_pages(self, tmp_path: Path) -> None:
        """每兩頁之間等待一次，第一頁前不等，秒數都在 2～5 秒之間。"""
        sleeps: list[float] = []
        progress_path = tmp_path / "progress.json"
        ae.crawl(FakePage(), admin_urls(5), ae.Progress(), progress_path, on_page=lambda *a: None, sleep=sleeps.append)
        assert len(sleeps) == 4
        assert all(2.0 <= s <= 5.0 for s in sleeps)


# ---------------------------------------------------------------------------
# cookie 絕不外洩
# ---------------------------------------------------------------------------


class TestCookieSecrecy:
    """cookie 不會出現在任何輸出。"""

    def _all_outputs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
        """收集終端機輸出、log 與 tmp_path 底下所有檔案內容。"""
        captured = capsys.readouterr()
        files = "".join(p.read_text(encoding="utf-8-sig") for p in tmp_path.rglob("*") if p.is_file())
        return captured.out + captured.err + caplog.text + files

    def test_full_run_never_outputs_cookie(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """完整跑一次：cookie 有注入瀏覽器，但不出現在終端機、log、progress.json、menu.csv。"""
        caplog.set_level(logging.INFO, logger="admin_explore")
        log_file = tmp_path / "explore.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        ae.logger.addHandler(handler)
        try:
            page = FakePage({ae.ADMIN_HOME: (200, MENU_HTML, ae.ADMIN_HOME)})
            context = FakeContext(page)
            browser = FakeBrowser(context)
            result = ae.explore_admin(browser, fake_get_cookies, tmp_path, sleep=no_sleep)
            page.routes[0][1](FakeRoute("POST", f"{ADMIN}/admin/api"))
        finally:
            ae.logger.removeHandler(handler)
            handler.close()

        assert result.finished
        assert context.cookies and context.cookies[0]["value"] == SECRET
        assert all(c["domain"].endswith("cyberbiz.co") for c in context.cookies)
        assert (tmp_path / "progress.json").is_file()
        assert (tmp_path / "menu.csv").is_file()
        assert log_file.read_text(encoding="utf-8")
        assert SECRET not in self._all_outputs(tmp_path, capsys, caplog)
        assert SECRET not in repr(result)

    def test_get_cookies_error_hides_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """get_cookies 丟出含 cookie 的例外時，只顯示例外類型。"""
        caplog.set_level(logging.INFO, logger="admin_explore")

        def broken(domains: list[str]) -> Any:
            """丟出夾帶秘密的例外。"""
            raise RuntimeError(f"bad cookie {SECRET}")

        page = FakePage()
        result = ae.explore_admin(FakeBrowser(FakeContext(page)), broken, tmp_path, sleep=no_sleep)
        assert "RuntimeError" in result.reason
        assert page.goto_calls == []
        assert SECRET not in self._all_outputs(tmp_path, capsys, caplog)

    def test_add_cookies_error_hides_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """add_cookies 丟出含 cookie 的例外時，只顯示例外類型，且不開啟任何頁面。"""
        caplog.set_level(logging.INFO, logger="admin_explore")
        page = FakePage()
        context = FakeContext(page, add_error=ValueError(f"invalid cookie value={SECRET}"))
        result = ae.explore_admin(FakeBrowser(context), fake_get_cookies, tmp_path, sleep=no_sleep)
        assert "ValueError" in result.reason
        assert page.goto_calls == []
        assert context.closed
        assert SECRET not in self._all_outputs(tmp_path, capsys, caplog)

    def test_no_cookies_stops(self, tmp_path: Path) -> None:
        """取不到 cookie 就不開頁面。"""
        page = FakePage()
        result = ae.explore_admin(FakeBrowser(FakeContext(page)), lambda d: [], tmp_path, sleep=no_sleep)
        assert "cookie" in result.reason
        assert page.goto_calls == []

    def test_to_playwright_cookies_formats(self) -> None:
        """支援 dict 與 list 形式；只留 cyberbiz.co 網域；不帶 expires。"""
        from_dict = ae.to_playwright_cookies({"a": "1"})
        assert from_dict == [{"name": "a", "value": "1", "domain": ae.ADMIN_HOST, "path": "/"}]
        from_list = ae.to_playwright_cookies(fake_get_cookies(list(ae.COOKIE_DOMAINS)))
        assert len(from_list) == 1
        assert from_list[0]["domain"] == ".cyberbiz.co"
        assert "expires" not in from_list[0]
        assert ae.to_playwright_cookies(None) == []


# ---------------------------------------------------------------------------
# 停止條件
# ---------------------------------------------------------------------------


class TestStopConditions:
    """遇到停止條件立即停止，不重試。"""

    @pytest.mark.parametrize("status", [429, 403, 500, 502, 503, 599])
    def test_stop_on_status(self, status: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """第 2 頁回 429/403/5xx：立即停止、不重試、印出原因與第 2 頁。"""
        urls = admin_urls(4)
        page = FakePage({urls[1]: (status, "", urls[1])})
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[:2]
        assert result.reason == f"HTTP {status}"
        assert result.stop_page == 2
        assert not result.finished
        out = capsys.readouterr().out
        assert f"HTTP {status}" in out
        assert "停在第 2 頁" in out
        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["last_stop_reason"] == f"HTTP {status}"
        assert saved["last_stop_page"] == 2
        assert urls[1] not in saved["visited_urls"]

    @pytest.mark.parametrize("login_path", ["/admins/sign_in", "/login", "/users/sign_in?return=/admin"])
    def test_stop_on_login_redirect(self, login_path: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """被導回登入頁立即停止。"""
        urls = admin_urls(3)
        page = FakePage({urls[0]: (200, "<form>登入</form>", f"{ADMIN}{login_path}")})
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[:1]
        assert "登入頁" in result.reason
        out = capsys.readouterr().out
        assert "登入頁" in out and "停在第 1 頁" in out

    @pytest.mark.parametrize(
        "html",
        [
            '<div class="g-recaptcha"></div>',
            '<script src="https://www.google.com/recaptcha/api.js"></script>',
            '<div class="cf-turnstile"></div>',
            "<p>請輸入驗證碼</p>",
            "<p>CAPTCHA required</p>",
        ],
    )
    def test_stop_on_captcha(self, html: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """頁面出現驗證碼立即停止。"""
        urls = admin_urls(3)
        page = FakePage({urls[1]: (200, html, urls[1])})
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[:2]
        assert result.reason == "頁面出現驗證碼"
        out = capsys.readouterr().out
        assert "驗證碼" in out and "停在第 2 頁" in out

    def test_stop_on_three_consecutive_404(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """連續 3 頁 404 立即停止。"""
        urls = admin_urls(5)
        page = FakePage({u: (404, "", u) for u in urls[1:4]})
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[:4]
        assert "連續 3 頁" in result.reason
        assert result.stop_page == 4
        assert "停在第 4 頁" in capsys.readouterr().out
        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["not_found_urls"] == urls[1:4]

    def test_single_404_skipped_and_counter_resets(self, tmp_path: Path) -> None:
        """單頁 404 記錄後跳過、不重試；中間有 200 時連續計數歸零。"""
        urls = admin_urls(6)
        page = FakePage({urls[0]: (404, "", urls[0]), urls[1]: (404, "", urls[1]), urls[3]: (404, "", urls[3]), urls[4]: (404, "", urls[4])})
        result = run_crawl(tmp_path, page, urls)
        assert result.finished
        assert page.goto_calls == urls
        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["not_found_urls"] == [urls[0], urls[1], urls[3], urls[4]]
        assert saved["visited_urls"] == [urls[2], urls[5]]

    def test_navigation_error_stops_without_retry(self, tmp_path: Path) -> None:
        """載入失敗（例如逾時）立即停止，不重試。"""
        urls = admin_urls(3)
        page = FakePage({urls[0]: TimeoutError("slow")})
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[:1]
        assert "TimeoutError" in result.reason


# ---------------------------------------------------------------------------
# 續傳與上限
# ---------------------------------------------------------------------------


class TestProgressAndLimit:
    """progress.json 續傳與每次 100 頁上限。"""

    def test_resume_skips_done_pages(self, tmp_path: Path) -> None:
        """已讀過與已記錄 404 的頁面下次執行會跳過。"""
        urls = admin_urls(5)
        (tmp_path / "progress.json").write_text(
            json.dumps({"visited_urls": urls[:2], "not_found_urls": [urls[2]]}), encoding="utf-8"
        )
        page = FakePage()
        result = run_crawl(tmp_path, page, urls)
        assert page.goto_calls == urls[3:]
        assert result.pages_read == 2
        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["visited_urls"] == [urls[0], urls[1], urls[3], urls[4]]

    def test_progress_saved_after_each_page(self, tmp_path: Path) -> None:
        """每讀完一頁就寫入 progress.json（中途停止也保留已讀頁面）。"""
        urls = admin_urls(4)
        page = FakePage({urls[2]: (500, "", urls[2])})
        run_crawl(tmp_path, page, urls)
        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["visited_urls"] == urls[:2]
        assert set(saved) == {"visited_urls", "not_found_urls", "last_stop_reason", "last_stop_page", "updated_at"}

    def test_max_pages_and_resume(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """一次最多讀 100 頁；下次執行從第 101 頁繼續。"""
        assert ae.MAX_PAGES == 100
        urls = admin_urls(105)
        page = FakePage()
        result = run_crawl(tmp_path, page, urls)
        assert len(page.goto_calls) == 100
        assert result.stop_page == 100
        assert "100" in result.reason
        assert not result.finished
        assert "停在第 100 頁" in capsys.readouterr().out

        page2 = FakePage()
        result2 = run_crawl(tmp_path, page2, urls)
        assert page2.goto_calls == urls[100:]
        assert result2.finished

    def test_menu_step_already_done(self, tmp_path: Path) -> None:
        """首頁已讀過時不再開啟，直接回報沒有待讀頁面。"""
        (tmp_path / "progress.json").write_text(json.dumps({"visited_urls": [ae.ADMIN_HOME]}), encoding="utf-8")
        page = FakePage()
        result = ae.explore_admin(FakeBrowser(FakeContext(page)), fake_get_cookies, tmp_path, sleep=no_sleep)
        assert page.goto_calls == []
        assert "沒有待讀頁面" in result.reason


# ---------------------------------------------------------------------------
# 選單解析與敏感頁面
# ---------------------------------------------------------------------------


class TestMenu:
    """左側選單解析、menu.csv 與敏感路徑過濾。"""

    def test_extract_menu_links(self) -> None:
        """只取左側選單；轉絕對網址、去 #、去重複；空文字改用 title。"""
        links = ae.extract_menu_links(MENU_HTML, ae.ADMIN_HOME)
        assert [(l.text, l.url) for l in links] == [
            ("商品", f"{ADMIN}/admin/products"),
            ("訂單", f"{ADMIN}/admin/orders"),
            ("會員 管理", f"{ADMIN}/admin/customers"),
            ("部落格", f"{ADMIN}/admin/blogs"),
            ("自訂頁面", f"{ADMIN}/admin/pages"),
        ]

    def test_fallback_to_whole_page(self) -> None:
        """找不到選單容器時改用整頁連結。"""
        links = ae.extract_menu_links('<div><a href="/admin/a">A</a></div>', ae.ADMIN_HOME)
        assert [l.url for l in links] == [f"{ADMIN}/admin/a"]

    def test_menu_csv_written(self, tmp_path: Path) -> None:
        """完整第一步：只開首頁一次、單一 context 與分頁，輸出 UTF-8 BOM 的 menu.csv。"""
        page = FakePage({ae.ADMIN_HOME: (200, MENU_HTML, ae.ADMIN_HOME)})
        context = FakeContext(page)
        browser = FakeBrowser(context)
        result = ae.explore_admin(browser, fake_get_cookies, tmp_path, sleep=no_sleep)
        assert result.finished
        assert page.goto_calls == [ae.ADMIN_HOME]
        assert browser.contexts_created == 1
        assert context.pages_opened == 1
        assert context.closed

        raw = (tmp_path / "menu.csv").read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        with (tmp_path / "menu.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0].keys()) == ["text", "url"]
        assert rows[0] == {"text": "商品", "url": f"{ADMIN}/admin/products"}
        assert len(rows) == 5

    @pytest.mark.parametrize(
        "url, text",
        [
            (f"{ADMIN}/admin/orders", ""),
            (f"{ADMIN}/admin/orders/123", ""),
            (f"{ADMIN}/admin/customers", ""),
            (f"{ADMIN}/admin/payments", ""),
            (f"{ADMIN}/admin/cashflow", ""),
            (f"{ADMIN}/admin/logout", ""),
            (f"{ADMIN}/admin/admins/sign_out", ""),
            (f"{ADMIN}/admin/report", "訂單報表"),
            (f"{ADMIN}/admin/list", "會員列表"),
            (f"{ADMIN}/admin/setting", "金流設定"),
            (f"{ADMIN}/admin/%E8%A8%82%E5%96%AE", ""),
        ],
    )
    def test_sensitive(self, url: str, text: str) -> None:
        """訂單、會員、金流、登出相關網址或文字判定為敏感。"""
        assert ae.is_sensitive(url, text)

    @pytest.mark.parametrize("url", [ae.ADMIN_HOME, f"{ADMIN}/admin/products", f"{ADMIN}/admin/blogs"])
    def test_not_sensitive(self, url: str) -> None:
        """一般頁面不判定為敏感。"""
        assert not ae.is_sensitive(url, "商品")

    def test_safe_queue(self) -> None:
        """佇列排除敏感頁面與外站網址。"""
        links = ae.extract_menu_links(MENU_HTML, ae.ADMIN_HOME) + [ae.MenuLink("外站", "https://other.com/admin")]
        assert ae.safe_queue(links) == [f"{ADMIN}/admin/products", f"{ADMIN}/admin/blogs", f"{ADMIN}/admin/pages"]

    def test_crawl_skips_sensitive_and_foreign(self, tmp_path: Path) -> None:
        """crawl 本身也不會造訪敏感頁面或外站。"""
        urls = [f"{ADMIN}/admin/orders", "https://other.com/admin", f"{ADMIN}/admin/products"]
        page = FakePage()
        run_crawl(tmp_path, page, urls)
        assert page.goto_calls == [f"{ADMIN}/admin/products"]


# ---------------------------------------------------------------------------
# 列表頁模式（--lists）
# ---------------------------------------------------------------------------


LIST_HTML = f"""<html><body>
<nav class="navbar"><a href="/admin/profile">頂部個人設定</a><span>頂部導覽</span></nav>
<div id="wrapper">
<aside class="sidebar"><ul><li><a href="/admin/products">側欄商品</a></li></ul></aside>
<div class="content-wrapper">
  <h2>谷歌 Google 設定</h2>
  <p>聯絡 Boss.Lin@sinchih.com.tw 或 0912-345-678，市話 (02)2345-6789</p>
  <form>
    <input type="hidden" name="authenticity_token" value="{SECRET}">
    <div class="form-group"><label for="ga">GA4 衡量 ID</label><input id="ga" name="shop[ga4_id]" value="G-ABC123XYZ9"></div>
    <label>GTM 容器 <input name="shop[gtm_id]" value="GTM-ABCD123"></label>
    <div class="form-group"><label>API 金鑰</label><input name="shop[api_key]" value="plainkey"></div>
    <input type="password" name="pw" value="{SECRET}">
    <select name="shop[mode]"><option value="a">關閉</option><option value="b" selected>開啟</option></select>
    <input type="checkbox" name="shop[enabled]" checked>
    <textarea name="shop[note]" placeholder="備註">店長電話 02-2345-6789</textarea>
    <button type="submit">儲存</button>
  </form>
  <table>
    <thead><tr><th>原網址</th><th>新網址</th><th>操作</th></tr></thead>
    <tbody>
      <tr><td>/old-a</td><td><a href="/pages/new-a">新 A</a></td><td><a href="/admin/redirections/12/edit">編輯</a></td></tr>
      <tr><td>a|b</td><td><a href="https://www.sinchih.com.tw/blogs/news?token=abcdef">文章</a></td><td></td></tr>
    </tbody>
  </table>
  <ul><li>第一項<ul><li>子項</li></ul></li><li><a href="/admin/menus">主選單</a></li></ul>
  <ul class="pagination"><li><a href="?page=2">2</a></li></ul>
</div></div>
<script>var token="{SECRET}";</script>
</body></html>"""

BLOGS = f"{ADMIN}/admin/blogs"
PRODUCT_TAGS = f"{ADMIN}/admin/product_tags"


def simple_list_html(extra: str = "") -> str:
    """有左側選單與 <main> 的簡單列表頁。"""
    return (
        '<html><body><aside class="sidebar"><a href="/admin/orders">訂單</a></aside>'
        f"<main><h2>列表</h2><table><tr><th>名稱</th></tr><tr><td>項目</td></tr></table>{extra}</main></body></html>"
    )


BLOGS_PAGE_1 = simple_list_html(
    '<a href="?page=2">2</a><a href="/admin/blogs?page=3">3</a>'
    '<a href="/admin/blogs/12/edit">編輯</a><a href="/admin/blogs/new">新增</a>'
    '<a href="/admin/blogs?page=2&sort=asc">排序</a><a href="/admin/blogs/12/articles?page=2">文章</a>'
    '<a href="/admin/orders?page=2">訂單</a><a href="https://other.com/admin/blogs?page=2">外站</a>'
)
BLOGS_PAGE_2 = simple_list_html('<a href="/admin/blogs">1</a><a href="?page=3">3</a>')


def collect_outputs(tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    """收集終端機輸出、log 與 tmp_path 底下所有檔案內容。"""
    captured = capsys.readouterr()
    files = "".join(p.read_text(encoding="utf-8-sig") for p in tmp_path.rglob("*") if p.is_file())
    return captured.out + captured.err + caplog.text + files


def run_lists(tmp_path: Path, page: FakePage, **kwargs: Any) -> Any:
    """以假瀏覽器執行列表頁模式。"""
    return ae.explore_lists(FakeBrowser(FakeContext(page)), fake_get_cookies, tmp_path, sleep=no_sleep, **kwargs)


class TestMaskSensitive:
    """email、電話、金鑰、token 遮蔽；追蹤 ID 與站內路徑保留。"""

    @pytest.mark.parametrize(
        "text, secret",
        [
            ("聯絡 Boss.Lin@sinchih.com.tw 謝謝", "Boss.Lin@sinchih.com.tw"),
            ("手機 0912-345-678", "0912-345-678"),
            ("手機 0912 345 678", "0912 345 678"),
            ("電話0912345678", "0912345678"),
            ("國際 +886-912-345-678", "+886-912-345-678"),
            ("市話 02-2345-6789", "02-2345-6789"),
            ("市話 (02)2345-6789。", "(02)2345-6789"),
            ("市話 +886-2-2345-6789", "+886-2-2345-6789"),
            ("高雄 07-123-4567", "07-123-4567"),
            ("API Key: abcd1234", "abcd1234"),
            ("token=xyz987", "xyz987"),
            ("client_secret：s3cr3t", "s3cr3t"),
            ("金鑰：mykey", "mykey"),
            ("key AIzaSyA1234567890abcdefghijklmnopq", "AIzaSyA1234567890abcdefghijklmnopq"),
            ("長字串 " + "a1" * 20, "a1" * 20),
            ("sk_live_abcdef123456", "sk_live_abcdef123456"),
            (f"{ADMIN}/admin/x?token=abc123&page=2", "abc123"),
            ("/admin/x?email=a%40b.com", "a%40b.com"),
            ("mailto:boss@example.com", "boss@example.com"),
        ],
    )
    def test_masked(self, text: str, secret: str) -> None:
        """敏感資料被換成 ***。"""
        masked = ae.mask_sensitive(text)
        assert secret not in masked
        assert "***" in masked

    @pytest.mark.parametrize(
        "text",
        [
            "GA4 衡量 ID：G-ABC123XYZ9",
            "GTM 容器 GTM-ABCD123",
            "舊版 UA-12345678-1",
            "Google Ads AW-123456789",
            f"{ADMIN}/admin/platforms/google",
            f"{ADMIN}/admin/blogs?page=2",
            "/admin/products/0912345678",
            "https://www.sinchih.com.tw/pages/%E4%BE%86%E8%A8%AA",
            "價格 NT$12,000，共 3 筆",
            "更新於 2026-10-16T12:00:00",
            "[新 A](https://sinchih.cyberbiz.co/pages/new-a)",
        ],
    )
    def test_preserved(self, text: str) -> None:
        """追蹤 ID、站內網址路徑、價格與日期不會被誤遮。"""
        assert ae.mask_sensitive(text) == text

    def test_field_value_masked_by_name_or_label(self) -> None:
        """欄位名稱或標籤像金鑰、secret、token 時整個值遮蔽，但追蹤 ID 保留。"""
        assert ae.mask_field_value("shop[api_key]", "", "plain") == "***"
        assert ae.mask_field_value("x", "Access Token", "plain") == "***"
        assert ae.mask_field_value("x", "API 金鑰", "plain") == "***"
        assert ae.mask_field_value("shop[gtm_token]", "", "GTM-ABCD123") == "GTM-ABCD123"
        assert ae.mask_field_value("shop[name]", "店名", "炘馳通訊") == "炘馳通訊"
        assert ae.mask_field_value("shop[phone]", "電話", "02-2345-6789") == "***"
        assert ae.mask_field_value("shop[secret]", "", "") == ""


class TestListTargets:
    """列表頁網址清單與 menu.csv 的「標籤管理」。"""

    def test_default_targets(self) -> None:
        """固定 9 個列表頁，都是後台網域、非敏感、非單一項目。"""
        targets = ae.list_targets(None)
        assert len(targets) == 9
        assert targets[0] == f"{ADMIN}/admin/platforms/google"
        assert targets[-1] == PRODUCT_TAGS
        assert f"{ADMIN}/admin/custom_pages_index" in targets
        for url in targets:
            assert ae.is_admin_url(url)
            assert not ae.is_sensitive(url)
            assert not ae.looks_like_single_item(url)
            assert ae.list_page_number(url) == 1

    def _write_menu(self, path: Path, rows: list[tuple[str, str]]) -> Path:
        """寫一個 menu.csv。"""
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["text", "url"])
            writer.writerows(rows)
        return path

    def test_tag_url_from_menu(self, tmp_path: Path) -> None:
        """menu.csv 有「標籤管理」的網址時取代預設的商品標籤管理。"""
        menu = self._write_menu(tmp_path / "menu.csv", [("商品", f"{ADMIN}/admin/products"), ("商品標籤管理", f"{ADMIN}/admin/tags_v2")])
        targets = ae.list_targets(menu)
        assert targets[-1] == f"{ADMIN}/admin/tags_v2"
        assert PRODUCT_TAGS not in targets
        assert len(targets) == 9

    def test_menu_same_as_default(self, tmp_path: Path) -> None:
        """menu.csv 的網址與預設相同時清單不變。"""
        menu = self._write_menu(tmp_path / "menu.csv", [("商品標籤管理", PRODUCT_TAGS)])
        assert ae.list_targets(menu) == list(ae.LIST_PAGE_URLS)

    @pytest.mark.parametrize(
        "url",
        [f"{ADMIN}/admin/product_tags/5/edit", f"{ADMIN}/admin/product_tags/new", "https://other.com/admin/tags", f"{ADMIN}/admin/orders/tags"],
    )
    def test_invalid_menu_url_ignored(self, url: str, tmp_path: Path) -> None:
        """menu.csv 裡的網址若是單一項目、外站或敏感頁面就不採用。"""
        menu = self._write_menu(tmp_path / "menu.csv", [("商品標籤管理", url)])
        assert ae.list_targets(menu) == list(ae.LIST_PAGE_URLS)

    def test_missing_menu(self, tmp_path: Path) -> None:
        """沒有 menu.csv 時用預設清單。"""
        assert ae.list_targets(tmp_path / "missing.csv") == list(ae.LIST_PAGE_URLS)


class TestPagination:
    """分頁判斷與主題檔名。"""

    @pytest.mark.parametrize(
        "url, expected",
        [
            (f"{BLOGS}?page=2", True),
            (f"{BLOGS}?page=10", True),
            (f"{BLOGS}?page=2#top", True),
            (BLOGS, False),
            (f"{BLOGS}?page=1", False),
            (f"{BLOGS}?page=0", False),
            (f"{BLOGS}?page=x", False),
            (f"{BLOGS}?page=2&sort=asc", False),
            (f"{BLOGS}?sort=asc", False),
            (f"{BLOGS}/12?page=2", False),
            (f"{BLOGS}/12/edit", False),
            (f"{ADMIN}/admin/blogs_v2?page=2", False),
            ("https://other.com/admin/blogs?page=2", False),
            (f"http://{ae.ADMIN_HOST}/admin/blogs?page=2", False),
        ],
    )
    def test_is_pagination_url(self, url: str, expected: bool) -> None:
        """只有同一路徑、query 只有 page=N（N≥2）才算分頁。"""
        assert ae.is_pagination_url(url, BLOGS) is expected

    def test_page_number(self) -> None:
        """沒有 query 是第 1 頁；page=N 是第 N 頁；其他 None。"""
        assert ae.list_page_number(BLOGS) == 1
        assert ae.list_page_number(f"{BLOGS}?page=3") == 3
        assert ae.list_page_number(f"{BLOGS}?q=a") is None

    def test_pagination_links(self) -> None:
        """只收分頁連結；單一項目、新增、其他 query、子路徑、敏感頁、外站都不收。"""
        assert ae.pagination_links(BLOGS_PAGE_1, BLOGS, BLOGS) == [f"{BLOGS}?page=2", f"{BLOGS}?page=3"]

    @pytest.mark.parametrize(
        "url, topic",
        [
            (f"{ADMIN}/admin/platforms/google", "platforms_google"),
            (f"{ADMIN}/admin/custom_pages_index", "custom_pages_index"),
            (f"{ADMIN}/admin/shop_add_ons", "shop_add_ons"),
            (f"{BLOGS}?page=2", "blogs"),
        ],
    )
    def test_topic_name(self, url: str, topic: str) -> None:
        """主題檔名由路徑轉成。"""
        assert ae.list_topic_name(url) == topic

    @pytest.mark.parametrize(
        "url, expected",
        [(f"{BLOGS}/12/edit", True), (f"{BLOGS}/new", True), (f"{BLOGS}/12", True), (BLOGS, False), (f"{ADMIN}/admin/platforms/google", False)],
    )
    def test_single_item(self, url: str, expected: bool) -> None:
        """/edit、/new、數字編號判定為單一項目。"""
        assert ae.looks_like_single_item(url) is expected


class TestListContent:
    """主內容區整理成 Markdown。"""

    def _render(self) -> str:
        """整理 LIST_HTML 第 1 頁。"""
        url = f"{ADMIN}/admin/platforms/google"
        return ae.render_list_page(LIST_HTML, url, url, 1)

    def test_excludes_sidebar_topnav_and_scripts(self) -> None:
        """左側選單、頂部導覽列、script、隱藏欄位與密碼都不出現。"""
        md = self._render()
        assert "側欄商品" not in md
        assert "頂部導覽" not in md and "頂部個人設定" not in md
        assert SECRET not in md
        assert "authenticity_token" not in md
        assert "| pw |" not in md
        assert "儲存" not in md

    def test_headings_and_paragraphs(self) -> None:
        """區塊標題與段落保留，段落中的 email 與電話被遮蔽。"""
        md = self._render()
        assert md.startswith("## 第 1 頁")
        assert "#### 谷歌 Google 設定" in md
        assert "聯絡 *** 或 ***，市話 ***" in md
        assert "Boss.Lin" not in md and "0912-345-678" not in md and "2345-6789" not in md

    def test_form_fields(self) -> None:
        """表單欄位輸出標籤、name、類型與目前的值；GA4/GTM ID 保留、金鑰遮蔽。"""
        md = self._render()
        assert "| 標籤 | name | 類型 | 目前的值 |" in md
        assert "| GA4 衡量 ID | shop[ga4_id] | text | G-ABC123XYZ9 |" in md
        assert "| GTM 容器 | shop[gtm_id] | text | GTM-ABCD123 |" in md
        assert "| API 金鑰 | shop[api_key] | text | *** |" in md
        assert "plainkey" not in md
        assert "| shop[mode] | select | 開啟 |" in md
        assert "| shop[enabled] | checkbox | 已勾選 |" in md
        assert "| 備註 | shop[note] | textarea | 店長電話 *** |" in md

    def test_table(self) -> None:
        """表格轉成 Markdown，保留文字與連結 href，| 被跳脫，網址中的 token 被遮蔽。"""
        md = self._render()
        assert "| 原網址 | 新網址 | 操作 |" in md
        assert "| --- | --- | --- |" in md
        assert (
            f"| /old-a | [新 A]({ADMIN}/pages/new-a) | [編輯]({ADMIN}/admin/redirections/12/edit) |" in md
        )
        assert "| a\\|b | [文章](https://www.sinchih.com.tw/blogs/news?token=***) |  |" in md
        assert "abcdef" not in md

    def test_lists(self) -> None:
        """清單（含巢狀）轉成 Markdown；分頁清單不列出。"""
        md = self._render()
        assert "- 第一項" in md
        assert "  - 子項" in md
        assert f"- [主選單]({ADMIN}/admin/menus)" in md
        assert "- [2](" not in md

    def test_table_without_header(self) -> None:
        """沒有標題列的表格用「欄1、欄2」。"""
        soup = ae.BeautifulSoup("<table><tr><td>a</td><td>b</td></tr></table>", "html.parser")
        lines = ae.table_to_markdown(soup.find("table"), ae.ADMIN_HOME)
        assert lines == ["| 欄1 | 欄2 |", "| --- | --- |", "| a | b |"]

    def test_empty_page(self) -> None:
        """主內容區沒東西時寫一行說明。"""
        md = ae.render_list_page("<html></html>", BLOGS, BLOGS, 1)
        assert "沒有可整理" in md

    def test_redirected_page_notes_final_url(self) -> None:
        """實際網址不同時記下來。"""
        md = ae.render_list_page(simple_list_html(), BLOGS, f"{BLOGS}/1/articles", 1)
        assert f"- 實際網址：{BLOGS}/1/articles" in md

    def test_write_list_page(self, tmp_path: Path) -> None:
        """第 1 頁重寫整個主題檔，之後的分頁接在同一檔案後面。"""
        path = tmp_path / "blogs.md"
        path.write_text("舊內容", encoding="utf-8")
        assert ae.write_list_page(tmp_path, BLOGS, 1, "## 第 1 頁\n") == path
        ae.write_list_page(tmp_path, BLOGS, 2, "## 第 2 頁\n")
        text = path.read_text(encoding="utf-8")
        assert "舊內容" not in text
        assert text.startswith("# 後台列表：blogs")
        assert text.index("## 第 1 頁") < text.index("## 第 2 頁")


class TestExploreLists:
    """列表頁模式完整流程。"""

    def test_reads_targets_and_pagination_only(self, tmp_path: Path) -> None:
        """依序讀 9 個列表頁，再讀分頁；不點進 /edit、/new 或其他網址；分頁合併在同一檔。"""
        targets = list(ae.LIST_PAGE_URLS)
        page = FakePage(
            {
                BLOGS: (200, BLOGS_PAGE_1, BLOGS),
                f"{BLOGS}?page=2": (200, BLOGS_PAGE_2, f"{BLOGS}?page=2"),
            },
            default_html=simple_list_html(),
        )
        sleeps: list[float] = []
        result = ae.explore_lists(FakeBrowser(FakeContext(page)), fake_get_cookies, tmp_path, sleep=sleeps.append)
        assert result.finished
        assert page.goto_calls == targets + [f"{BLOGS}?page=2", f"{BLOGS}?page=3"]
        assert not any("/edit" in u or "/new" in u or "orders" in u for u in page.goto_calls)
        assert len(sleeps) == len(page.goto_calls) - 1
        assert all(2.0 <= s <= 5.0 for s in sleeps)

        for url in targets:
            assert (tmp_path / f"{ae.list_topic_name(url)}.md").is_file()
        assert (tmp_path / "platforms_google.md").is_file()
        assert (tmp_path / "custom_pages_index.md").is_file()
        blogs = (tmp_path / "blogs.md").read_text(encoding="utf-8")
        assert blogs.index("## 第 1 頁") < blogs.index("## 第 2 頁") < blogs.index("## 第 3 頁")
        assert "| 名稱 |" in blogs

        saved = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert saved["visited_urls"] == page.goto_calls

    def test_max_list_pages(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """分頁再多，本次最多讀 50 頁（傳更大的上限也一樣）。"""
        assert ae.MAX_LIST_PAGES == 50
        pages: dict[str, tuple[int, str, str]] = {PRODUCT_TAGS: (200, simple_list_html('<a href="?page=2">2</a>'), PRODUCT_TAGS)}
        for n in range(2, 101):
            url = f"{PRODUCT_TAGS}?page={n}"
            pages[url] = (200, simple_list_html(f'<a href="?page={n + 1}">下一頁</a>'), url)
        page = FakePage(pages, default_html=simple_list_html())
        result = run_lists(tmp_path, page, max_pages=100)
        assert len(page.goto_calls) == 50
        assert result.stop_page == 50
        assert "50" in result.reason
        assert not result.finished
        assert "停在第 50 頁" in capsys.readouterr().out
        assert "## 第 41 頁" in (tmp_path / "product_tags.md").read_text(encoding="utf-8")

    def test_resume_skips_read_pages(self, tmp_path: Path) -> None:
        """已讀過的列表頁下次執行不再開啟。"""
        run_lists(tmp_path, FakePage(default_html=simple_list_html()))
        page = FakePage()
        result = run_lists(tmp_path, page)
        assert page.goto_calls == []
        assert "沒有待讀頁面" in result.reason

    @pytest.mark.parametrize("status", [429, 403, 500, 503])
    def test_stop_on_status(self, status: int, tmp_path: Path) -> None:
        """第 4 頁回 429/403/5xx 立即停止，不重試。"""
        targets = list(ae.LIST_PAGE_URLS)
        page = FakePage({targets[3]: (status, "", targets[3])}, default_html=simple_list_html())
        result = run_lists(tmp_path, page)
        assert page.goto_calls == targets[:4]
        assert result.reason == f"HTTP {status}"
        assert not (tmp_path / f"{ae.list_topic_name(targets[3])}.md").exists()

    def test_stop_on_login_and_captcha(self, tmp_path: Path) -> None:
        """被導回登入頁或出現驗證碼立即停止。"""
        targets = list(ae.LIST_PAGE_URLS)
        page = FakePage({targets[0]: (200, "<form></form>", f"{ADMIN}/admins/sign_in")})
        assert "登入頁" in run_lists(tmp_path / "a", page).reason
        assert page.goto_calls == targets[:1]
        page2 = FakePage({targets[1]: (200, '<div class="g-recaptcha"></div>', targets[1])}, default_html=simple_list_html())
        assert run_lists(tmp_path / "b", page2).reason == "頁面出現驗證碼"
        assert page2.goto_calls == targets[:2]

    def test_stop_on_three_404(self, tmp_path: Path) -> None:
        """連續 3 頁 404 立即停止。"""
        targets = list(ae.LIST_PAGE_URLS)
        page = FakePage({u: (404, "", u) for u in targets[:3]})
        result = run_lists(tmp_path, page)
        assert page.goto_calls == targets[:3]
        assert "連續 3 頁" in result.reason

    def test_tag_url_from_menu_csv(self, tmp_path: Path) -> None:
        """自動讀 output_dir/menu.csv 裡含「標籤管理」的網址。"""
        tags = f"{ADMIN}/admin/tags_v2"
        ae.write_menu_csv([ae.MenuLink("商品標籤管理", tags)], tmp_path / "menu.csv")
        page = FakePage(default_html=simple_list_html())
        run_lists(tmp_path, page)
        assert page.goto_calls[-1] == tags
        assert PRODUCT_TAGS not in page.goto_calls
        assert (tmp_path / "tags_v2.md").is_file()

    def test_get_only_guard_and_cookie_secrecy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """列表頁模式同樣只放行 GET，cookie 與 CSRF token 不出現在任何輸出。"""
        caplog.set_level(logging.INFO, logger="admin_explore")
        page = FakePage({ae.LIST_PAGE_URLS[0]: (200, LIST_HTML, ae.LIST_PAGE_URLS[0])}, default_html=simple_list_html())
        context = FakeContext(page)
        result = ae.explore_lists(FakeBrowser(context), fake_get_cookies, tmp_path, sleep=no_sleep)
        assert result.finished
        assert page.goto_calls[-1] == f"{ae.LIST_PAGE_URLS[0]}?page=2"
        assert [pattern for pattern, _ in page.routes] == ["**/*"]
        post = FakeRoute("POST", f"{ADMIN}/admin/platforms/google")
        page.routes[0][1](post)
        assert post.action == "abort"
        assert context.cookies and context.cookies[0]["value"] == SECRET
        assert context.closed
        outputs = collect_outputs(tmp_path, capsys, caplog)
        assert SECRET not in outputs
        assert "Boss.Lin@sinchih.com.tw" not in outputs
        assert "G-ABC123XYZ9" in outputs

    def test_no_cookies_stops(self, tmp_path: Path) -> None:
        """取不到 cookie 就不開頁面。"""
        page = FakePage()
        result = ae.explore_lists(FakeBrowser(FakeContext(page)), lambda d: [], tmp_path, sleep=no_sleep)
        assert "cookie" in result.reason
        assert page.goto_calls == []

    def test_form_values_synced_before_reading(self, tmp_path: Path) -> None:
        """每頁讀 HTML 前先同步表單欄位值；同步失敗不影響讀取。"""

        class EvalPage(FakePage):
            """有 evaluate 的假分頁。"""

            def __init__(self, fail: bool = False, **kwargs: Any):
                """fail=True 時 evaluate 丟出例外。"""
                super().__init__(**kwargs)
                self.fail = fail
                self.scripts: list[str] = []

            def evaluate(self, script: str) -> None:
                """記錄執行的腳本。"""
                self.scripts.append(script)
                if self.fail:
                    raise RuntimeError(f"boom {SECRET}")

        page = EvalPage(default_html=simple_list_html())
        run_lists(tmp_path / "a", page)
        assert page.scripts == [ae.SYNC_FORM_VALUES_JS] * 9

        failing = EvalPage(fail=True, default_html=simple_list_html())
        result = run_lists(tmp_path / "b", failing)
        assert result.finished
        assert len(failing.goto_calls) == 9

    def test_sync_without_evaluate(self) -> None:
        """分頁物件沒有 evaluate 時直接略過。"""
        ae.sync_form_values(object())


class TestCommandLine:
    """命令列參數與模式切換。"""

    @pytest.mark.parametrize(
        "argv, mode",
        [([], "menu"), (["--lists"], "lists"), (["--mode", "lists"], "lists"), (["--mode", "menu"], "menu")],
    )
    def test_parse_args(self, argv: list[str], mode: str) -> None:
        """預設讀左側選單；--lists 或 --mode lists 讀列表頁。"""
        assert ae.parse_args(argv) == mode

    def test_invalid_mode(self) -> None:
        """不認得的模式直接報錯。"""
        with pytest.raises(SystemExit):
            ae.parse_args(["--mode", "all"])

    def test_run_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """menu 呼叫 explore_admin，lists 呼叫 explore_lists。"""
        calls: list[str] = []
        monkeypatch.setattr(ae, "explore_admin", lambda *a, **k: calls.append("menu"))
        monkeypatch.setattr(ae, "explore_lists", lambda *a, **k: calls.append("lists"))
        ae.run_mode("menu", object(), fake_get_cookies, tmp_path)
        ae.run_mode("lists", object(), fake_get_cookies, tmp_path)
        assert calls == ["menu", "lists"]


# ---------------------------------------------------------------------------
# 其他
# ---------------------------------------------------------------------------


class TestMisc:
    """瀏覽器啟動方式與設定讀取。"""

    def test_launch_browser_headed(self) -> None:
        """瀏覽器以 headless=False 啟動。"""
        calls: list[dict[str, Any]] = []

        class FakeChromium:
            """假 chromium。"""

            def launch(self, **kwargs: Any) -> str:
                """記錄參數。"""
                calls.append(kwargs)
                return "browser"

        class FakePlaywright:
            """假 playwright。"""

            chromium = FakeChromium()

        assert ae.launch_browser(FakePlaywright()) == "browser"
        assert calls == [{"headless": False}]

    def test_xinchi_tools_path(self, tmp_path: Path) -> None:
        """XINCHI_TOOLS_PATH 從 .env 讀取，沒設定時用預設路徑。"""
        assert ae.xinchi_tools_path_from_env(tmp_path / "missing.env") == ae.DEFAULT_XINCHI_TOOLS_PATH
        env_file = tmp_path / ".env"
        env_file.write_text("XINCHI_TOOLS_PATH=D:\\xinchi\n", encoding="utf-8")
        assert ae.xinchi_tools_path_from_env(env_file) == Path("D:\\xinchi")
