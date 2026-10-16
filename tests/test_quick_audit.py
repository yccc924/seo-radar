"""scripts/quick_audit.py 的測試。全部使用假 HTML 與假 session，不連任何網站。"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("quick_audit", ROOT / "scripts" / "quick_audit.py")
assert _spec and _spec.loader
qa = importlib.util.module_from_spec(_spec)
sys.modules["quick_audit"] = qa
_spec.loader.exec_module(qa)

SITE = "https://www.example.com"


def soup(html: str) -> BeautifulSoup:
    """把假 HTML 轉成 BeautifulSoup。"""
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# 假的 HTTP session
# ---------------------------------------------------------------------------


class FakeResponse:
    """模擬 requests.Response 的最小物件。"""

    def __init__(self, status_code: int = 200, text: str = "", headers: dict[str, str] | None = None):
        """建立假回應。"""
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    """依網址回傳預先設定的回應，並記錄所有請求。"""

    def __init__(self, pages: dict[str, FakeResponse | Exception]):
        """pages：網址 → 回應（或要丟出的例外）。"""
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """模擬 GET；沒設定的網址回 404。"""
        self.calls.append((url, kwargs))
        result = self.pages.get(url, FakeResponse(404, "not found"))
        if isinstance(result, Exception):
            raise result
        return result

    # 確保程式不會用到 GET 以外的方法
    def post(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        """呼叫到就代表違反只讀規則。"""
        raise AssertionError("不應該發出 POST")


def page_html(title: str, links: list[str], extra: str = "") -> str:
    """產生簡單的假頁面。"""
    anchors = "".join(f'<a href="{href}">x</a>' for href in links)
    return f"<html><head><title>{title}</title>{extra}</head><body><h1>{title}</h1>{anchors}</body></html>"


# ---------------------------------------------------------------------------
# 網址處理
# ---------------------------------------------------------------------------


class TestUrls:
    """網址正規化與分類。"""

    @pytest.mark.parametrize(
        "a, b",
        [
            (f"{SITE}/pages/abc/", f"{SITE}/pages/abc"),
            (f"{SITE}/pages/abc#top", f"{SITE}/pages/abc"),
            (f"{SITE}/pages/abc?utm=1", f"{SITE}/pages/abc"),
            ("http://WWW.example.com/pages/abc", f"{SITE}/pages/abc"),
            ("https://example.com/pages/abc", f"{SITE}/pages/abc"),
            (f"{SITE}/pages/%E6%94%B6%E8%B3%BC", f"{SITE}/pages/收購"),
            (f"{SITE}/", SITE),
        ],
    )
    def test_normalize_equivalent(self, a: str, b: str) -> None:
        """編碼、大小寫、www、結尾斜線、#、query 不同仍視為同一頁。"""
        assert qa.normalize_url(a) == qa.normalize_url(b)

    def test_normalize_different_pages(self) -> None:
        """不同路徑不會被誤判為同一頁。"""
        assert qa.normalize_url(f"{SITE}/pages/a") != qa.normalize_url(f"{SITE}/pages/b")

    @pytest.mark.parametrize(
        "url, expected",
        [
            (SITE, "home"),
            (f"{SITE}/", "home"),
            (f"{SITE}/blogs/news/iphone-17", "blog"),
            (f"{SITE}/pages/%E4%BE%86%E8%A8%AA%E6%88%91%E5%80%91", "page"),
            (f"{SITE}/products/iphone", None),
            (f"{SITE}/collections/apple", None),
            (f"{SITE}/categories/phone", None),
            ("https://other.com/pages/x", None),
        ],
    )
    def test_classify(self, url: str, expected: str | None) -> None:
        """首頁、部落格、自訂頁納入；商品與集合頁、外站跳過。"""
        assert qa.classify_url(url, SITE) == expected

    def test_is_same_site(self) -> None:
        """只接受同網域的 http/https 網址。"""
        assert qa.is_same_site("https://example.com/x", SITE)
        assert not qa.is_same_site("mailto:a@example.com", SITE)
        assert not qa.is_same_site("https://evil.example.com.tw/x", SITE)


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


ROBOTS = """User-agent: *
Disallow: /admin/
Disallow: /cart
Disallow: /pages/secret
Content-Signal: ai-train=no, search=yes, ai-input=yes
Sitemap: https://www.example.com/sitemap.xml
"""


class TestRobots:
    """robots.txt 遵守邏輯。"""

    def test_rules(self) -> None:
        """Disallow 的路徑不可抓，其他可抓。"""
        parser = qa.build_robot_parser(200, ROBOTS)
        assert qa.is_allowed(parser, f"{SITE}/pages/ok")
        assert qa.is_allowed(parser, f"{SITE}/blogs/news/a")
        assert not qa.is_allowed(parser, f"{SITE}/admin/login")
        assert not qa.is_allowed(parser, f"{SITE}/cart")
        assert not qa.is_allowed(parser, f"{SITE}/pages/secret")

    def test_chinese_path_rule(self) -> None:
        """中文路徑規則對編碼過的網址一樣有效。"""
        parser = qa.build_robot_parser(200, "User-agent: *\nDisallow: /pages/收購\n")
        assert not qa.is_allowed(parser, f"{SITE}/pages/%E6%94%B6%E8%B3%BC-apple")

    def test_specific_user_agent(self) -> None:
        """針對本工具 User-Agent 的規則會生效。"""
        parser = qa.build_robot_parser(200, "User-agent: seo-radar-quick-audit\nDisallow: /\n")
        assert not qa.is_allowed(parser, f"{SITE}/pages/ok")

    @pytest.mark.parametrize(
        "status, allowed", [(404, True), (410, True), (401, False), (403, False), (500, False), (None, False)]
    )
    def test_status_handling(self, status: int | None, allowed: bool) -> None:
        """404 視為全允許；401/403、5xx、連線失敗一律視為禁止。"""
        parser = qa.build_robot_parser(status, "")
        assert qa.is_allowed(parser, f"{SITE}/pages/ok") is allowed

    def test_crawl_delay(self) -> None:
        """讀出 robots.txt 宣告的 Crawl-delay，沒宣告時為 0。"""
        slow = qa.build_robot_parser(200, "User-agent: *\nCrawl-delay: 8\n")
        # 標準庫 RobotFileParser 只接受整數的 Crawl-delay，小數（如 0.2）會被忽略
        fast = qa.build_robot_parser(200, "User-agent: *\nCrawl-delay: 1\n")
        none = qa.build_robot_parser(200, "User-agent: *\nDisallow:\n")
        assert qa.crawl_delay_for(slow) == 8
        assert qa.crawl_delay_for(fast) == 1
        assert qa.crawl_delay_for(none) == 0

    def test_random_page_delay_range(self) -> None:
        """隨機等待時間一定落在 2～5 秒之間。"""
        delays = [qa.random_page_delay() for _ in range(500)]
        assert all(2.0 <= d <= 5.0 for d in delays)
        assert len(set(delays)) > 1

    def test_fetcher_blocks_disallowed_without_request(self) -> None:
        """robots 禁止的網址不會發出請求。"""
        session = FakeSession({f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {})})
        fetcher = qa.PoliteFetcher(session, SITE, sleep=lambda _: None)
        with pytest.raises(qa.RobotsBlockedError):
            fetcher.fetch(f"{SITE}/pages/secret")
        assert [url for url, _ in session.calls] == [f"{SITE}/robots.txt"]

    def test_fetcher_blocks_other_sites(self) -> None:
        """外站網址不會發出請求。"""
        session = FakeSession({f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {})})
        fetcher = qa.PoliteFetcher(session, SITE, sleep=lambda _: None)
        with pytest.raises(qa.RobotsBlockedError):
            fetcher.fetch("https://other.com/pages/ok")
        assert len(session.calls) == 1

    def test_robots_unreachable_blocks_everything(self) -> None:
        """robots.txt 連不到時什麼都不抓。"""
        session = FakeSession({f"{SITE}/robots.txt": requests.ConnectionError("down")})
        fetcher = qa.PoliteFetcher(session, SITE, sleep=lambda _: None)
        with pytest.raises(qa.RobotsBlockedError):
            fetcher.fetch(f"{SITE}/pages/ok")
        assert len(session.calls) == 1

    def test_fetcher_delay_and_get_only(self) -> None:
        """每個請求之間都隨機等待 2～5 秒，帶 User-Agent，不跟隨轉址。"""
        session = FakeSession(
            {
                f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {}),
                f"{SITE}/pages/a": FakeResponse(200, "<html></html>"),
                f"{SITE}/pages/b": FakeResponse(200, "<html></html>"),
            }
        )
        sleeps: list[float] = []
        fetcher = qa.PoliteFetcher(session, SITE, sleep=sleeps.append)
        fetcher.fetch(f"{SITE}/pages/a")
        fetcher.fetch(f"{SITE}/pages/b")
        assert len(sleeps) == 2
        assert all(2.0 <= s <= 5.0 for s in sleeps)
        for _, kwargs in session.calls:
            assert kwargs["allow_redirects"] is False
            assert kwargs["headers"]["User-Agent"] == qa.USER_AGENT

    def test_longer_crawl_delay_wins(self) -> None:
        """Crawl-delay 比隨機秒數長時以 Crawl-delay 為準；較短時仍用隨機 2～5 秒。"""
        for declared, expected in (("8", 8.0), ("1", 3.5)):
            session = FakeSession(
                {
                    f"{SITE}/robots.txt": FakeResponse(200, f"User-agent: *\nCrawl-delay: {declared}\n", {}),
                    f"{SITE}/pages/a": FakeResponse(200, "<html></html>"),
                }
            )
            sleeps: list[float] = []
            fetcher = qa.PoliteFetcher(session, SITE, sleep=sleeps.append, random_delay=lambda: 3.5)
            fetcher.fetch(f"{SITE}/pages/a")
            assert sleeps == [expected]


# ---------------------------------------------------------------------------
# sitemap
# ---------------------------------------------------------------------------


URLSET = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{SITE}/</loc></url>
  <url><loc>{SITE}/blogs/news/a</loc></url>
  <url><loc> {SITE}/pages/%E6%94%B6%E8%B3%BC-apple </loc></url>
  <url><loc>{SITE}/products/iphone</loc></url>
  <url><loc>{SITE}/collections/apple</loc></url>
  <url><loc>{SITE}/categories/phone</loc></url>
  <url><loc>{SITE}/blogs/news/a</loc></url>
</urlset>"""


class TestSitemap:
    """sitemap 解析與篩選。"""

    def test_parse_urlset(self) -> None:
        """取出所有 loc、去空白、去重複並保留順序。"""
        pages, children = qa.parse_sitemap(URLSET.encode())
        assert children == []
        assert pages[0] == f"{SITE}/"
        assert pages[2] == f"{SITE}/pages/%E6%94%B6%E8%B3%BC-apple"
        assert len(pages) == 6

    def test_parse_index(self) -> None:
        """sitemapindex 回傳子 sitemap 清單。"""
        xml = f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{SITE}/sitemap_1.xml</loc></sitemap></sitemapindex>"""
        pages, children = qa.parse_sitemap(xml.encode())
        assert pages == []
        assert children == [f"{SITE}/sitemap_1.xml"]

    def test_select_targets(self) -> None:
        """只挑首頁、部落格、自訂頁。"""
        pages, _ = qa.parse_sitemap(URLSET.encode())
        targets = qa.select_targets(pages, SITE)
        assert [t for _, t in targets] == ["home", "blog", "page"]

    def test_collect_follows_index(self) -> None:
        """sitemapindex 會再讀子 sitemap。"""
        index = f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{SITE}/sitemap_1.xml</loc></sitemap></sitemapindex>"""
        session = FakeSession(
            {
                f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {}),
                f"{SITE}/sitemap.xml": FakeResponse(200, index),
                f"{SITE}/sitemap_1.xml": FakeResponse(200, URLSET),
            }
        )
        fetcher = qa.PoliteFetcher(session, SITE, sleep=lambda _: None)
        assert len(qa.collect_sitemap_urls(fetcher, f"{SITE}/sitemap.xml")) == 6


# ---------------------------------------------------------------------------
# 頁面解析
# ---------------------------------------------------------------------------


class TestParsing:
    """title、description、H1、JSON-LD 解析。"""

    def test_title_and_meta(self) -> None:
        """抓到 title 與 meta description（name 不分大小寫、空白會整理）。"""
        s = soup('<title> 收購表 \n APPLE </title><meta name="Description" content=" 高價\n收購 ">')
        assert qa.extract_title(s) == "收購表 APPLE"
        assert qa.extract_meta_description(s) == "高價 收購"

    def test_missing_title_and_meta(self) -> None:
        """沒有 title 或 description 時回傳空字串。"""
        s = soup('<meta property="og:description" content="x">')
        assert qa.extract_title(s) == ""
        assert qa.extract_meta_description(s) == ""

    def test_h1(self) -> None:
        """多個 H1 全部取出，內層標籤文字也算。"""
        assert qa.extract_h1_texts(soup("<h1>A <span>B</span></h1><h1>C</h1>")) == ["A B", "C"]
        assert qa.extract_h1_texts(soup("<h2>x</h2>")) == []

    def test_json_ld(self) -> None:
        """收集所有區塊、@graph、巢狀物件、陣列型 @type 的 type 與 description。"""
        html = """
        <script type="application/ld+json">{"@type": "BlogPosting", "description": "文章摘要",
          "author": {"@type": "Organization", "name": "炘馳"}}</script>
        <script type="application/ld+json">{"@graph": [{"@type": ["WebPage", "FAQPage"]},
          {"@type": "BreadcrumbList", "description": "麵包屑"}]}</script>
        <script type="application/ld+json">[{"@type": "Product"}]</script>
        <script type="text/javascript">var x = {"@type": "Fake"};</script>
        """
        types, descriptions, errors = qa.extract_json_ld(soup(html))
        assert types == ["BlogPosting", "Organization", "WebPage", "FAQPage", "BreadcrumbList", "Product"]
        assert descriptions == ["文章摘要", "麵包屑"]
        assert errors == 0

    def test_json_ld_invalid_and_control_chars(self) -> None:
        """格式錯誤的區塊計入錯誤數；description 內的換行字元仍可解析。"""
        html = (
            '<script type="application/ld+json">{bad json</script>'
            '<script type="application/ld+json">{"@type": "Article", "description": "第一行\n第二行"}</script>'
        )
        types, descriptions, errors = qa.extract_json_ld(soup(html))
        assert types == ["Article"]
        assert descriptions == ["第一行 第二行"]
        assert errors == 1


class TestGa4:
    """GA4 衡量 ID 偵測。"""

    @pytest.mark.parametrize(
        "html, expected",
        [
            ("gtag('config', 'G-ABC123XYZ');", True),
            ('<script src="https://www.googletagmanager.com/gtag/js?id=G-1A2B3C4D5E"></script>', True),
            ("gtag('config', 'UA-12345-1');", False),
            ("<p>G-SHOCK 手錶</p>", False),
            ("G-abc123xyz", False),
            ("", False),
        ],
    )
    def test_has_ga4(self, html: str, expected: bool) -> None:
        """只有 G- 加 6～12 個大寫英數字才算。"""
        assert qa.has_ga4(html) is expected


class TestCssDetection:
    """CSS 污染判定。"""

    @pytest.mark.parametrize(
        "text",
        [
            "body { font-family: sans-serif; }",
            ".article-content{color:red}",
            "font-family: 'Noto Sans TC'",
            "<style>.x{}</style> 內文",
            "color: red !important",
            "@media (max-width: 600px)",
            ".ARTICLE-CONTENT p",
        ],
    )
    def test_css_detected(self, text: str) -> None:
        """含 CSS 特徵時判定為污染。"""
        assert qa.looks_like_css(text)

    @pytest.mark.parametrize(
        "text",
        [
            "html { scroll-behavior: smooth;",
            "ody { font-family: Arial, sans-serif; line-he",
            "ody { color: #333; line-height: 1.8; margin: 0 au",
            "/* 風格樣式 v4.2 ",
            "式 v4.2 */ 內文開始",
            ":root",
            ".editor-content",
            ".EDITOR-CONTENT h2",
        ],
    )
    def test_truncated_css_detected(self, text: str) -> None:
        """Cyberbiz 截取前 50 字時被截斷的 CSS（只有 {、只有註解）也要判定為污染。"""
        assert qa.looks_like_css(text)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "iPhone 17 Pro 高價收購，台中現金交易",
            "價格 {待更新",
            "格式：A } B",
            "價格 {待更新：下週公布",
            "營業時間 10:00-21:00，歡迎來店",
        ],
    )
    def test_clean_text(self, text: str) -> None:
        """一般文字（含單邊括號）不會誤判。"""
        assert not qa.looks_like_css(text)


class TestLinks:
    """站內連結擷取。"""

    def test_extract_internal_links(self) -> None:
        """相對、絕對、編碼、# 與結尾斜線都正規化；外站與特殊連結略過。"""
        html = """
        <a href="/pages/a/">a</a>
        <a href="b#section">b</a>
        <a href="https://example.com/pages/%E6%94%B6%E8%B3%BC">c</a>
        <a href="https://other.com/pages/x">x</a>
        <a href="mailto:a@example.com">m</a>
        <a href="tel:0412345678">t</a>
        <a href="javascript:void(0)">j</a>
        <a href="#top">top</a>
        <a>no href</a>
        """
        links = qa.extract_internal_links(soup(html), f"{SITE}/pages/current", SITE)
        assert links == {
            qa.normalize_url(f"{SITE}/pages/a"),
            qa.normalize_url(f"{SITE}/pages/b"),
            qa.normalize_url(f"{SITE}/pages/收購"),
        }


# ---------------------------------------------------------------------------
# 整頁分析與孤兒頁
# ---------------------------------------------------------------------------


POLLUTED_BLOG = """<html><head>
<title>iPhone 17 評測</title>
<meta name="description" content="body { font-family: 'Noto Sans TC'; } .article-content { color: #333; }">
<script type="application/ld+json">{"@type": "BlogPosting", "description": ".article-content { margin: 0 }"}</script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-TEST123456"></script>
</head><body><h1>iPhone 17 評測</h1><h1>第二個標題</h1><a href="/">首頁</a></body></html>"""


class TestAnalyzeHtml:
    """整頁分析。"""

    def test_polluted_blog(self) -> None:
        """CSS 污染、多個 H1、GA4、JSON-LD 都正確記錄。"""
        url = f"{SITE}/blogs/news/%E6%B8%AC%E8%A9%A6"
        result = qa.analyze_html(url, "blog", 200, POLLUTED_BLOG, SITE)
        assert result.decoded_url == f"{SITE}/blogs/news/測試"
        assert result.title == "iPhone 17 評測"
        assert result.h1_count == 2
        assert result.h1_texts == "iPhone 17 評測|第二個標題"
        assert result.json_ld_types == "BlogPosting"
        assert result.json_ld_descriptions == ".article-content { margin: 0 }"
        assert result.has_ga4
        assert result.meta_desc_has_css
        assert result.json_ld_desc_has_css
        assert result.has_css_in_desc
        assert result.links == {qa.normalize_url(SITE)}

    def test_only_json_ld_polluted(self) -> None:
        """只有 JSON-LD 被污染時，has_css_in_desc 仍為 True。"""
        html = (
            '<meta name="description" content="正常描述">'
            '<script type="application/ld+json">{"@type": "BlogPosting", "description": "<style>p{}</style>"}</script>'
        )
        result = qa.analyze_html(f"{SITE}/blogs/news/a", "blog", 200, html, SITE)
        assert not result.meta_desc_has_css
        assert result.json_ld_desc_has_css
        assert result.has_css_in_desc

    def test_clean_page(self) -> None:
        """乾淨頁面所有旗標為 False，沒有 H1 時數量為 0。"""
        html = '<title>收購表</title><meta name="description" content="高價收購">'
        result = qa.analyze_html(f"{SITE}/pages/a", "page", 200, html, SITE)
        assert result.h1_count == 0
        assert result.h1_texts == ""
        assert not result.has_ga4
        assert not result.has_css_in_desc


class TestOrphans:
    """孤兒頁計算。"""

    def _result(self, url: str, links: list[str]) -> Any:
        """建立只有連結資訊的檢查結果。"""
        return qa.PageResult(
            url=url, decoded_url=url, page_type="page", links={qa.normalize_url(link) for link in links}
        )

    def test_find_orphans(self) -> None:
        """沒被別頁連到的才是孤兒；首頁除外；自己連自己不算；編碼與斜線差異不影響。"""
        home = f"{SITE}/"
        a = f"{SITE}/pages/a"
        b = f"{SITE}/pages/%E6%94%B6%E8%B3%BC"
        c = f"{SITE}/blogs/news/c"
        results = [
            self._result(home, [f"{SITE}/pages/a/"]),
            self._result(a, [f"{SITE}/pages/收購#faq"]),
            self._result(c, [c]),
        ]
        assert qa.find_orphans(results, [home, a, b, c]) == [c]

    def test_home_never_orphan(self) -> None:
        """首頁就算沒被連到也不列入。"""
        assert qa.find_orphans([], [SITE, f"{SITE}/"]) == []


# ---------------------------------------------------------------------------
# 輸出與完整流程
# ---------------------------------------------------------------------------


class TestRunAudit:
    """完整流程（全部使用假 session）。"""

    def _session(self) -> FakeSession:
        """建立一個小型假網站。"""
        return FakeSession(
            {
                f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {"Content-Type": "text/plain"}),
                f"{SITE}/sitemap.xml": FakeResponse(
                    200,
                    f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>{SITE}/</loc></url>
                    <url><loc>{SITE}/blogs/news/a</loc></url>
                    <url><loc>{SITE}/pages/%E6%94%B6%E8%B3%BC</loc></url>
                    <url><loc>{SITE}/pages/orphan</loc></url>
                    <url><loc>{SITE}/pages/secret</loc></url>
                    <url><loc>{SITE}/pages/moved</loc></url>
                    <url><loc>{SITE}/products/skip-me</loc></url>
                    </urlset>""",
                    {"Content-Type": "application/xml"},
                ),
                f"{SITE}/": FakeResponse(200, page_html("首頁", ["/blogs/news/a/", "/pages/收購"])),
                f"{SITE}/blogs/news/a": FakeResponse(200, POLLUTED_BLOG),
                f"{SITE}/pages/%E6%94%B6%E8%B3%BC": FakeResponse(200, page_html("收購", ["/"])),
                f"{SITE}/pages/orphan": FakeResponse(200, page_html("孤兒", ["/pages/orphan"])),
                f"{SITE}/pages/moved": FakeResponse(301, "", {"Location": f"{SITE}/pages/new"}),
                f"{SITE}/products/skip-me": AssertionError("商品頁不該被抓"),
            }
        )

    def test_run_audit(self, tmp_path: Path) -> None:
        """產出 CSV 與孤兒頁清單；robots 禁止的頁不抓；每個請求都有間隔。"""
        session = self._session()
        sleeps: list[float] = []
        results, orphans = qa.run_audit(
            session, SITE, tmp_path, sleep=sleeps.append, log=lambda _: None
        )

        requested = [url for url, _ in session.calls]
        assert f"{SITE}/pages/secret" not in requested
        assert f"{SITE}/products/skip-me" not in requested
        assert len(sleeps) == len(requested) - 1
        assert all(2.0 <= s <= 5.0 for s in sleeps)

        by_url = {r.decoded_url: r for r in results}
        assert "robots.txt 不允許" in by_url[f"{SITE}/pages/secret"].error
        assert by_url[f"{SITE}/pages/secret"].status_code is None
        assert by_url[f"{SITE}/pages/moved"].status_code == 301
        assert "/pages/new" in by_url[f"{SITE}/pages/moved"].error
        assert by_url[f"{SITE}/blogs/news/a"].has_css_in_desc

        assert orphans == [f"{SITE}/pages/orphan", f"{SITE}/pages/secret", f"{SITE}/pages/moved"]

        raw = (tmp_path / "quick_audit.csv").read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        with (tmp_path / "quick_audit.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0].keys()) == list(qa.CSV_COLUMNS)
        assert [row["page_type"] for row in rows] == ["home", "blog", "page", "page", "page", "page"]
        assert rows[2]["decoded_url"] == f"{SITE}/pages/收購"
        assert rows[1]["has_ga4"] == "True"
        assert rows[1]["h1_count"] == "2"

        orphan_lines = (tmp_path / "orphans.txt").read_text(encoding="utf-8").splitlines()
        assert orphan_lines == [f"{SITE}/pages/orphan", f"{SITE}/pages/secret", f"{SITE}/pages/moved"]

    def test_limit(self, tmp_path: Path) -> None:
        """--limit 只檢查前 N 頁。"""
        results, _ = qa.run_audit(
            self._session(), SITE, tmp_path, limit=2, sleep=lambda _: None, log=lambda _: None
        )
        assert [r.page_type for r in results] == ["home", "blog"]

    def test_connection_error_recorded(self, tmp_path: Path) -> None:
        """單頁連線失敗只記錄錯誤，不中斷整體檢查。"""
        session = self._session()
        session.pages[f"{SITE}/blogs/news/a"] = requests.Timeout("slow")
        results, _ = qa.run_audit(session, SITE, tmp_path, sleep=lambda _: None, log=lambda _: None)
        blog = next(r for r in results if r.page_type == "blog")
        assert blog.error == "連線失敗：Timeout"
        assert len(results) == 6

    def test_non_html_skipped(self, tmp_path: Path) -> None:
        """非 HTML 回應不解析。"""
        session = self._session()
        session.pages[f"{SITE}/pages/orphan"] = FakeResponse(200, "%PDF", {"Content-Type": "application/pdf"})
        results, _ = qa.run_audit(session, SITE, tmp_path, sleep=lambda _: None, log=lambda _: None)
        pdf = next(r for r in results if r.url.endswith("/pages/orphan"))
        assert pdf.error.startswith("不是 HTML")
        assert pdf.title == ""

    def test_sitemap_failure_raises(self, tmp_path: Path) -> None:
        """sitemap 讀不到時直接中止，不寫出檔案。"""
        session = FakeSession({f"{SITE}/robots.txt": FakeResponse(200, ROBOTS, {})})
        with pytest.raises(RuntimeError):
            qa.run_audit(session, SITE, tmp_path, sleep=lambda _: None, log=lambda _: None)
        assert not (tmp_path / "quick_audit.csv").exists()


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """保險：任何測試若意外用到真的 requests 連線就直接失敗。"""

    def blocked(*args: Any, **kwargs: Any) -> None:
        """攔截真實網路請求。"""
        raise AssertionError("測試不可連真網")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(requests, "get", blocked)
