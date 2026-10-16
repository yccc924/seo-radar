"""炘馳通訊快速健檢腳本（只讀）。

從 sitemap 取出首頁、部落格文章（/blogs/）、自訂頁（/pages/），
逐頁抓取並記錄 title、meta description、H1、JSON-LD、GA4 與 CSS 污染，
另外計算「沒有被任何受檢頁面連到」的孤兒頁。

安全規則：
- 只發 GET 請求、不登入、不送表單、不帶 cookie 以外的任何身分資訊。
- 嚴格遵守 robots.txt；robots.txt 讀不到（5xx 或連線失敗）時一律不爬。
- 每個請求之間隨機等待 2～5 秒；robots.txt 有 Crawl-delay 且更長時以它為準。
- 只抓與網站同網域的網址，不跟隨轉址（轉址只記錄狀態碼）。

用法：
    python scripts/quick_audit.py              # 全部
    python scripts/quick_audit.py --limit 5    # 只抓前 5 頁試跑
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

DEFAULT_SITE = "https://www.sinchih.com.tw"
USER_AGENT = "seo-radar-quick-audit/0.1 (read-only SEO audit)"
MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 5.0
REQUEST_TIMEOUT_SEC = 20
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "research" / "audit"

GA4_PATTERN = re.compile(r"\bG-[A-Z0-9]{6,12}\b")
CSS_MARKERS = (
    "font-family",
    ".article-content",
    "<style",
    "</style",
    "!important",
    "@media",
    "/*",
    "*/",
    ".editor-content",
    ":root",
    "scroll-behavior",
)
LIST_SEPARATOR = "|"


class HttpResponse(Protocol):
    """測試與 requests.Response 共用的最小回應介面。"""

    status_code: int
    content: bytes
    text: str
    headers: Any


class HttpSession(Protocol):
    """測試與 requests.Session 共用的最小 session 介面（只需要 get）。"""

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """發出 GET 請求。"""
        ...


# ---------------------------------------------------------------------------
# 網址處理
# ---------------------------------------------------------------------------


def _bare_host(host: str) -> str:
    """把主機名稱轉小寫並去掉開頭的 www.，讓 www 與非 www 視為同一站。"""
    host = host.lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, site_url: str) -> bool:
    """判斷網址是否屬於受檢網站（http/https 且主機相同，忽略 www.）。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    return _bare_host(parts.netloc) == _bare_host(urlsplit(site_url).netloc)


def normalize_url(url: str) -> str:
    """把網址正規化成比對用的鍵值。

    規則：統一用 https、主機轉小寫並去掉 www.、路徑先 unquote 解碼、
    去掉 query 與 fragment(#)、去掉結尾斜線（首頁路徑為空字串）。
    這樣編碼過與未編碼的中文網址、有無結尾斜線、有無 # 都會視為同一頁。
    """
    parts = urlsplit(url.strip())
    path = unquote(parts.path).rstrip("/")
    return f"https://{_bare_host(parts.netloc)}{path}"


def classify_url(url: str, site_url: str) -> str | None:
    """依網址路徑判斷頁面類型。

    回傳 "home"（首頁）、"blog"（/blogs/ 開頭）、"page"（/pages/ 開頭），
    其他（商品頁、分類集合頁、外站等）回傳 None 表示這次不檢查。
    """
    if not is_same_site(url, site_url):
        return None
    path = unquote(urlsplit(url).path)
    if path in ("", "/"):
        return "home"
    if path.startswith("/blogs/"):
        return "blog"
    if path.startswith("/pages/"):
        return "page"
    return None


# ---------------------------------------------------------------------------
# robots.txt 與 sitemap
# ---------------------------------------------------------------------------


def build_robot_parser(status_code: int | None, text: str) -> RobotFileParser:
    """依 robots.txt 的抓取結果建立 RobotFileParser。

    - 200：照內容解析。
    - 401、403：視為全站禁止。
    - 其他 4xx（例如 404 沒有 robots.txt）：視為全站允許。
    - 5xx 或連線失敗（status_code 為 None）：為求保守，視為全站禁止。
    """
    parser = RobotFileParser()
    if status_code == 200:
        parser.parse(text.splitlines())
    elif status_code in (401, 403):
        parser.disallow_all = True
    elif status_code is not None and 400 <= status_code < 500:
        parser.allow_all = True
    else:
        parser.disallow_all = True
    return parser


def is_allowed(parser: RobotFileParser, url: str, user_agent: str = USER_AGENT) -> bool:
    """回傳 robots.txt 是否允許這個 User-Agent 抓取該網址。"""
    return parser.can_fetch(user_agent, url)


def crawl_delay_for(parser: RobotFileParser, user_agent: str = USER_AGENT) -> float:
    """取得 robots.txt 宣告的 Crawl-delay 秒數，沒有宣告時回傳 0。"""
    declared = parser.crawl_delay(user_agent)
    return float(declared or 0)


def random_page_delay() -> float:
    """每頁之間的隨機等待秒數（2～5 秒）。"""
    return random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)


def _local_name(tag: str) -> str:
    """去掉 XML 標籤的命名空間，例如 {ns}loc → loc。"""
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """解析 sitemap XML。

    回傳 (頁面網址清單, 子 sitemap 網址清單)。
    一般 urlset 只會有前者；sitemapindex 只會有後者。保留原本順序並去除重複。
    """
    root = ET.fromstring(xml_bytes)
    is_index = _local_name(root.tag) == "sitemapindex"
    locs: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) == "loc" and element.text and element.text.strip():
            locs.append(element.text.strip())
    unique = list(dict.fromkeys(locs))
    return ([], unique) if is_index else (unique, [])


# ---------------------------------------------------------------------------
# 頁面解析
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """把連續空白與換行壓成一個空格，方便寫進 CSV。"""
    return " ".join(text.split())


def extract_title(soup: BeautifulSoup) -> str:
    """取得第一個 <title> 的文字，沒有則回傳空字串。"""
    tag = soup.find("title")
    return _clean_text(tag.get_text()) if tag else ""


def extract_meta_description(soup: BeautifulSoup) -> str:
    """取得 <meta name="description"> 的 content（name 不分大小寫），沒有則回傳空字串。"""
    for tag in soup.find_all("meta"):
        name = tag.get("name")
        if isinstance(name, str) and name.strip().lower() == "description":
            content = tag.get("content")
            return _clean_text(content) if isinstance(content, str) else ""
    return ""


def extract_h1_texts(soup: BeautifulSoup) -> list[str]:
    """取得所有 <h1> 的文字（含空的 H1，以空字串表示）。"""
    return [_clean_text(tag.get_text(" ")) for tag in soup.find_all("h1")]


def _walk_json_ld(node: Any, types: list[str], descriptions: list[str]) -> None:
    """遞迴走訪 JSON-LD 物件，收集所有 @type 與 description（含 @graph 內層）。"""
    if isinstance(node, dict):
        node_type = node.get("@type")
        if isinstance(node_type, str):
            types.append(node_type)
        elif isinstance(node_type, list):
            types.extend(str(t) for t in node_type)
        description = node.get("description")
        if isinstance(description, str):
            descriptions.append(_clean_text(description))
        for value in node.values():
            _walk_json_ld(value, types, descriptions)
    elif isinstance(node, list):
        for item in node:
            _walk_json_ld(item, types, descriptions)


def extract_json_ld(soup: BeautifulSoup) -> tuple[list[str], list[str], int]:
    """解析頁面上所有 application/ld+json。

    回傳 (所有 @type, 所有 description, 無法解析的區塊數)。
    JSON 格式錯誤的區塊不會中斷整頁檢查，只計入錯誤數。
    """
    types: list[str] = []
    descriptions: list[str] = []
    errors = 0
    for script in soup.find_all("script"):
        script_type = script.get("type")
        if not isinstance(script_type, str) or script_type.strip().lower() != "application/ld+json":
            continue
        raw = script.string if script.string is not None else script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            errors += 1
            continue
        _walk_json_ld(data, types, descriptions)
    return types, descriptions, errors


def has_ga4(html: str) -> bool:
    """HTML 中是否出現 GA4 衡量 ID（G- 開頭，例如 G-ABC123XYZ）。"""
    return GA4_PATTERN.search(html) is not None


def looks_like_css(text: str) -> bool:
    """判斷文字是否混入 CSS 或程式碼。

    Cyberbiz 會截取文章開頭 50 字當描述，CSS 常被截在 { 之後、} 之前，
    或整段都是 /* 註解 */，所以條件放寬。

    條件（任一成立即為 True）：同時含 { 與 }；同時含 { 與半形冒號 :（被截斷的
    CSS 規則，如 ody { color:）；或含 font-family、.article-content、<style、
    </style、!important、@media、/*、*/、.editor-content、:root、scroll-behavior
    等特徵（不分大小寫）。
    """
    if not text:
        return False
    if "{" in text and ("}" in text or ":" in text):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in CSS_MARKERS)


def extract_internal_links(soup: BeautifulSoup, page_url: str, site_url: str) -> set[str]:
    """取得頁面上所有 <a href> 的站內連結，回傳正規化後的網址集合。

    相對路徑會以 page_url 為基準轉成絕對網址；mailto:、tel:、javascript:、
    純 # 錨點與外站連結都會略過。
    """
    links: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag.get("href")
        if not isinstance(href, str):
            continue
        href = href.strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(page_url, href)
        if is_same_site(absolute, site_url):
            links.add(normalize_url(absolute))
    return links


# ---------------------------------------------------------------------------
# 檢查結果
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """單一頁面的檢查結果，欄位順序即 CSV 欄位順序。"""

    url: str
    decoded_url: str
    page_type: str
    status_code: int | None = None
    title: str = ""
    meta_description: str = ""
    h1_count: int = 0
    h1_texts: str = ""
    json_ld_types: str = ""
    json_ld_descriptions: str = ""
    has_ga4: bool = False
    meta_desc_has_css: bool = False
    json_ld_desc_has_css: bool = False
    has_css_in_desc: bool = False
    error: str = ""
    links: set[str] = field(default_factory=set, repr=False)


CSV_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(PageResult) if f.name != "links")


def analyze_html(url: str, page_type: str, status_code: int, html: str, site_url: str) -> PageResult:
    """解析一頁 HTML，回傳完整的 PageResult（不發任何網路請求）。"""
    soup = BeautifulSoup(html, "html.parser")
    meta_description = extract_meta_description(soup)
    h1_texts = extract_h1_texts(soup)
    ld_types, ld_descriptions, ld_errors = extract_json_ld(soup)

    meta_css = looks_like_css(meta_description)
    ld_css = any(looks_like_css(d) for d in ld_descriptions)
    return PageResult(
        url=url,
        decoded_url=unquote(url),
        page_type=page_type,
        status_code=status_code,
        title=extract_title(soup),
        meta_description=meta_description,
        h1_count=len(h1_texts),
        h1_texts=LIST_SEPARATOR.join(h1_texts),
        json_ld_types=LIST_SEPARATOR.join(ld_types),
        json_ld_descriptions=LIST_SEPARATOR.join(ld_descriptions),
        has_ga4=has_ga4(html),
        meta_desc_has_css=meta_css,
        json_ld_desc_has_css=ld_css,
        has_css_in_desc=meta_css or ld_css,
        error=f"JSON-LD 解析失敗 {ld_errors} 個" if ld_errors else "",
        links=extract_internal_links(soup, url, site_url),
    )


def find_orphans(results: Iterable[PageResult], candidates: Iterable[str]) -> list[str]:
    """找出孤兒頁：在候選清單中、但沒有被任何受檢頁面連到的網址（首頁除外）。

    頁面連到自己不算數。回傳候選清單中的原始網址，保留原本順序。
    """
    results = list(results)
    linked_from_others: set[str] = set()
    for result in results:
        own = normalize_url(result.url)
        linked_from_others.update(link for link in result.links if link != own)

    orphans: list[str] = []
    for url in candidates:
        if urlsplit(url).path in ("", "/"):
            continue
        if normalize_url(url) not in linked_from_others:
            orphans.append(url)
    return orphans


def write_csv(results: Iterable[PageResult], path: Path) -> None:
    """把檢查結果寫成 UTF-8 with BOM 的 CSV（Excel 直接開不會亂碼）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            writer.writerow([getattr(result, column) for column in CSV_COLUMNS])


def write_orphans(orphans: Iterable[str], path: Path) -> None:
    """把孤兒頁寫成文字檔，每行一個解碼後的網址（中文可直接閱讀）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [unquote(url) for url in orphans]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 抓取流程
# ---------------------------------------------------------------------------


class RobotsBlockedError(Exception):
    """robots.txt 不允許抓取這個網址。"""


class PoliteFetcher:
    """有禮貌的抓取器：只發 GET、遵守 robots.txt、每個請求之間隨機等待 2～5 秒。"""

    def __init__(
        self,
        session: HttpSession,
        site_url: str,
        sleep: Callable[[float], None] = time.sleep,
        random_delay: Callable[[], float] = random_page_delay,
    ) -> None:
        """建立抓取器；random_delay 產生每次的隨機等待秒數（測試可替換）。"""
        self.session = session
        self.site_url = site_url.rstrip("/")
        self.sleep = sleep
        self.random_delay = random_delay
        self.crawl_delay = 0.0
        self.robots: RobotFileParser | None = None
        self._has_requested = False

    def next_delay(self) -> float:
        """下一次請求前要等待的秒數：隨機 2～5 秒，Crawl-delay 更長時以它為準。"""
        return max(self.random_delay(), self.crawl_delay)

    def _get(self, url: str) -> HttpResponse:
        """實際發出 GET；第二個請求起先等待 next_delay() 秒，且不跟隨轉址。"""
        if self._has_requested:
            self.sleep(self.next_delay())
        self._has_requested = True
        return self.session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SEC,
            allow_redirects=False,
        )

    def load_robots(self) -> RobotFileParser:
        """抓取並解析 robots.txt，同時記下 Crawl-delay。"""
        robots_url = f"{self.site_url}/robots.txt"
        try:
            response = self._get(robots_url)
            parser = build_robot_parser(response.status_code, response.text)
        except requests.RequestException:
            parser = build_robot_parser(None, "")
        self.robots = parser
        self.crawl_delay = crawl_delay_for(parser)
        return parser

    def fetch(self, url: str) -> HttpResponse:
        """抓取站內網址；外站或 robots.txt 不允許時丟出例外，不發請求。"""
        if self.robots is None:
            self.load_robots()
        assert self.robots is not None
        if not is_same_site(url, self.site_url):
            raise RobotsBlockedError(f"不是受檢網站的網址：{url}")
        if not is_allowed(self.robots, url):
            raise RobotsBlockedError(f"robots.txt 不允許：{url}")
        return self._get(url)


def collect_sitemap_urls(fetcher: PoliteFetcher, sitemap_url: str, max_depth: int = 2) -> list[str]:
    """從 sitemap（含 sitemapindex 的子 sitemap）收集所有頁面網址。"""
    response = fetcher.fetch(sitemap_url)
    if response.status_code != 200:
        raise RuntimeError(f"sitemap 讀取失敗（HTTP {response.status_code}）：{sitemap_url}")
    pages, children = parse_sitemap(response.content)
    if max_depth > 0:
        for child in children:
            pages.extend(collect_sitemap_urls(fetcher, child, max_depth - 1))
    return list(dict.fromkeys(pages))


def select_targets(urls: Iterable[str], site_url: str) -> list[tuple[str, str]]:
    """從 sitemap 網址中挑出這次要檢查的頁面，回傳 (網址, 頁面類型) 清單。"""
    targets: list[tuple[str, str]] = []
    for url in urls:
        page_type = classify_url(url, site_url)
        if page_type is not None:
            targets.append((url, page_type))
    return targets


def audit_page(fetcher: PoliteFetcher, url: str, page_type: str) -> PageResult:
    """抓取並檢查單一頁面；被 robots 擋下、連線失敗、非 200 或非 HTML 都記錄在 error 欄位。"""
    base = PageResult(url=url, decoded_url=unquote(url), page_type=page_type)
    try:
        response = fetcher.fetch(url)
    except RobotsBlockedError as exc:
        base.error = str(exc)
        return base
    except requests.RequestException as exc:
        base.error = f"連線失敗：{type(exc).__name__}"
        return base

    base.status_code = response.status_code
    if response.status_code != 200:
        location = response.headers.get("Location", "") if response.headers else ""
        base.error = f"HTTP {response.status_code}" + (f" → {location}" if location else "")
        return base
    content_type = (response.headers.get("Content-Type", "") if response.headers else "").lower()
    if content_type and "html" not in content_type:
        base.error = f"不是 HTML：{content_type}"
        return base
    return analyze_html(url, page_type, response.status_code, response.text, fetcher.site_url)


def run_audit(
    session: HttpSession,
    site_url: str = DEFAULT_SITE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
    random_delay: Callable[[], float] = random_page_delay,
) -> tuple[list[PageResult], list[str]]:
    """執行完整快速健檢並寫出 CSV 與孤兒頁清單，回傳 (檢查結果, 孤兒頁)。"""
    site_url = site_url.rstrip("/")
    fetcher = PoliteFetcher(session, site_url, sleep=sleep, random_delay=random_delay)
    fetcher.load_robots()
    message = f"robots.txt 已讀取，每頁隨機間隔 {MIN_DELAY_SEC:g}～{MAX_DELAY_SEC:g} 秒"
    if fetcher.crawl_delay > MIN_DELAY_SEC:
        message += f"（Crawl-delay {fetcher.crawl_delay:g} 秒，較長時以它為準）"
    log(message)

    sitemap_urls = collect_sitemap_urls(fetcher, f"{site_url}/sitemap.xml")
    targets = select_targets(sitemap_urls, site_url)
    if limit is not None:
        targets = targets[:limit]
    log(f"sitemap 共 {len(sitemap_urls)} 個網址，這次檢查 {len(targets)} 頁")

    results: list[PageResult] = []
    for index, (url, page_type) in enumerate(targets, start=1):
        result = audit_page(fetcher, url, page_type)
        results.append(result)
        status = result.error or f"HTTP {result.status_code}"
        log(f"[{index}/{len(targets)}] {result.decoded_url} {status}")

    orphans = find_orphans(results, [url for url, _ in targets])
    write_csv(results, output_dir / "quick_audit.csv")
    write_orphans(orphans, output_dir / "orphans.txt")
    log(f"完成：{len(results)} 頁，孤兒頁 {len(orphans)} 個，輸出到 {output_dir}")
    return results, orphans


def main(argv: list[str] | None = None) -> int:
    """命令列進入點。"""
    parser = argparse.ArgumentParser(description="炘馳通訊快速健檢（只讀）")
    parser.add_argument("--site", default=DEFAULT_SITE, help="網站網址")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="輸出資料夾")
    parser.add_argument("--limit", type=int, default=None, help="只檢查前 N 頁（試跑用）")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with requests.Session() as session:
        run_audit(session, args.site, args.output_dir, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
