"""Cyberbiz 後台唯讀探索腳本（第一步：只讀左側選單）。

開啟後台首頁 https://sinchih.cyberbiz.co/admin，解析左側選單所有連結的
文字與網址，輸出成 research/admin/menu.csv（UTF-8 with BOM，欄位 text,url）。

安全規則：
- cookie 由 xinchi-tools-main/共用/elevated_cookies.py 的 get_cookies 取得，
  只存在程式記憶體中；絕不印出、寫入 log、progress.json 或任何檔案。
  本腳本不讀取 xinchi-tools-main 裡的任何 cookie 或帳號檔案。
- 用 Playwright 開有畫面的瀏覽器，單一 context、單一分頁，一頁一頁依序讀。
- 攔截所有請求：只放行 GET，其他方法（POST、PUT、DELETE、PATCH…）一律擋下並記錄。
- 每頁之間隨機等待 2～5 秒；每次執行最多讀 100 頁。
- 只造訪從選單或列表頁實際取得的網址，不自己拼湊網址；敏感頁面（訂單、會員、金流…）不進入。
- 遇到 HTTP 429、403、5xx、被導回登入頁、出現驗證碼、連續 3 頁 404 立即停止，不重試。
- 每讀完一頁就寫 research/admin/progress.json，下次執行自動跳過已讀頁面。

用法：
    python scripts/admin_explore.py
    （要重新讀一次首頁，請先刪除 research/admin/progress.json）
"""

from __future__ import annotations

import csv
import importlib
import json
import logging
import os
import random
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "research" / "admin"
DEFAULT_XINCHI_TOOLS_PATH = Path(r"C:\Users\ycc\Desktop\xinchi-tools-main")

ADMIN_HOST = "sinchih.cyberbiz.co"
ADMIN_HOME = f"https://{ADMIN_HOST}/admin"
COOKIE_DOMAINS: tuple[str, ...] = (".cyberbiz.co", "sinchih.cyberbiz.co")

MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 5.0
MAX_PAGES = 100
MAX_CONSECUTIVE_404 = 3
NAVIGATION_TIMEOUT_MS = 60_000

STOP_STATUSES = frozenset({401, 403, 429})
LOGIN_MARKERS = ("/login", "/sign_in", "/signin", "/admins/sign_in", "/users/sign_in")
CAPTCHA_MARKERS = ("recaptcha", "g-recaptcha", "cf-turnstile", "hcaptcha", "captcha", "驗證碼")

# 敏感路徑過濾器：後續步驟建立佇列時，網址或連結文字含這些字就不造訪
SENSITIVE_PATH_KEYWORDS = (
    "order",
    "customer",
    "member",
    "payment",
    "cashflow",
    "cash_flow",
    "refund",
    "invoice",
    "transaction",
    "checkout",
    "billing",
    "logout",
    "sign_out",
    "signout",
    "delete",
    "destroy",
)
SENSITIVE_TEXT_KEYWORDS = (
    "訂單",
    "會員",
    "顧客",
    "客戶",
    "金流",
    "付款",
    "收款",
    "退款",
    "發票",
    "帳務",
    "對帳",
    "登出",
    "刪除",
)

# 左側選單容器的 id / class 線索
SIDEBAR_HINTS = (
    "sidebar",
    "side-bar",
    "side_bar",
    "sidemenu",
    "side-menu",
    "side_menu",
    "sidenav",
    "side-nav",
    "left-menu",
    "leftmenu",
    "left-nav",
    "admin-menu",
    "main-menu",
)

logger = logging.getLogger("admin_explore")


def say(message: str) -> None:
    """在終端機顯示訊息並寫入 log（呼叫端保證訊息不含 cookie）。"""
    print(message, flush=True)
    logger.info(message)


def random_page_delay() -> float:
    """每頁之間的隨機等待秒數（2～5 秒）。"""
    return random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)


# ---------------------------------------------------------------------------
# 網址判斷
# ---------------------------------------------------------------------------


def clean_url(url: str) -> str:
    """去掉網址前後空白與 # 錨點，作為已讀比對的鍵值。"""
    return urldefrag(url.strip())[0]


def is_admin_url(url: str) -> bool:
    """是否為 Cyberbiz 後台網域（https://sinchih.cyberbiz.co）的網址。"""
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc.lower() == ADMIN_HOST


def is_sensitive(url: str, text: str = "") -> bool:
    """判斷網址或連結文字是否屬於訂單、會員、金流、登出等敏感頁面。"""
    parts = urlsplit(url)
    target = unquote(f"{parts.path}?{parts.query}").lower()
    if any(keyword in target for keyword in SENSITIVE_PATH_KEYWORDS):
        return True
    if any(keyword in target for keyword in SENSITIVE_TEXT_KEYWORDS):
        return True
    return any(keyword in text for keyword in SENSITIVE_TEXT_KEYWORDS)


def is_login_url(url: str) -> bool:
    """網址是否為登入頁（被導回登入頁代表 cookie 失效）。"""
    path = urlsplit(url).path.lower()
    return any(marker in path for marker in LOGIN_MARKERS)


def has_captcha(html: str) -> bool:
    """HTML 或可見文字中是否出現驗證碼。"""
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


# ---------------------------------------------------------------------------
# 左側選單解析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuLink:
    """選單上的一個連結。"""

    text: str
    url: str


def _clean_text(text: str) -> str:
    """把連續空白與換行壓成一個空格。"""
    return " ".join(text.split())


def _container_score(tag: Tag) -> int:
    """估計一個元素像不像左側選單：id/class 有側欄線索最高，<aside> 次之，<nav> 再次之。"""
    classes = tag.get("class") or []
    attrs = " ".join([str(tag.get("id") or ""), *[str(c) for c in classes]]).lower()
    if any(hint in attrs for hint in SIDEBAR_HINTS):
        return 3
    if tag.name == "aside":
        return 2
    if tag.name == "nav":
        return 1
    return 0


def find_menu_container(soup: BeautifulSoup) -> Tag | None:
    """找出最像左側選單的容器；同分時取連結最多的。找不到回傳 None。"""
    best: tuple[int, int] = (0, 0)
    best_tag: Tag | None = None
    for tag in soup.find_all(True):
        score = _container_score(tag)
        if score == 0:
            continue
        link_count = len(tag.find_all("a", href=True))
        if link_count and (score, link_count) > best:
            best, best_tag = (score, link_count), tag
    return best_tag


def extract_menu_links(html: str, base_url: str) -> list[MenuLink]:
    """解析左側選單所有連結（文字與絕對網址），依出現順序、去除重複網址。

    文字是空的（例如只有圖示）時改用 title 或 aria-label。
    略過 #、javascript:、mailto:、tel: 連結。找不到選單容器時改用整頁連結。
    """
    soup = BeautifulSoup(html, "html.parser")
    container: Tag | BeautifulSoup | None = find_menu_container(soup)
    if container is None:
        say("找不到左側選單容器，改用整頁連結")
        container = soup

    links: dict[str, MenuLink] = {}
    for anchor in container.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        href = href.strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        url = clean_url(urljoin(base_url, href))
        text = _clean_text(anchor.get_text(" "))
        if not text:
            text = _clean_text(str(anchor.get("title") or anchor.get("aria-label") or ""))
        if url not in links:
            links[url] = MenuLink(text=text, url=url)
    return list(links.values())


def write_menu_csv(links: Iterable[MenuLink], path: Path) -> None:
    """把選單連結寫成 UTF-8 with BOM 的 CSV（欄位 text,url）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text", "url"])
        for link in links:
            writer.writerow([link.text, link.url])


def safe_queue(links: Iterable[MenuLink]) -> list[str]:
    """供後續步驟使用：只留後台網域、非敏感頁面的網址（去除重複、保留順序）。"""
    queue: dict[str, None] = {}
    for link in links:
        if is_admin_url(link.url) and not is_sensitive(link.url, link.text):
            queue[clean_url(link.url)] = None
    return list(queue)


# ---------------------------------------------------------------------------
# cookie（只在記憶體中）
# ---------------------------------------------------------------------------


_PLAYWRIGHT_COOKIE_KEYS = ("name", "value", "domain", "path", "httpOnly", "secure", "sameSite")
_SAME_SITE = {"strict": "Strict", "lax": "Lax", "none": "None"}


def _is_cyberbiz_domain(domain: str) -> bool:
    """cookie 網域是否屬於 cyberbiz.co。"""
    bare = domain.lower().lstrip(".")
    return bare == "cyberbiz.co" or bare.endswith(".cyberbiz.co")


def to_playwright_cookies(raw: Any) -> list[dict[str, Any]]:
    """把 get_cookies 的回傳值轉成 context.add_cookies 可用的格式。

    支援三種形式：{name: value} 字典、dict 清單、有 name/value 屬性的物件清單。
    只保留 cyberbiz.co 網域的 cookie；不帶 expires（瀏覽器關閉即失效）。
    本函式不印出、不記錄任何 cookie 內容。
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        items: list[dict[str, Any]] = [{"name": k, "value": v} for k, v in raw.items()]
    else:
        items = []
        for item in raw:
            if isinstance(item, dict):
                items.append(dict(item))
            else:
                items.append({key: getattr(item, key, None) for key in ("name", "value", "domain", "path", "secure")})

    cookies: list[dict[str, Any]] = []
    for item in items:
        name, value = item.get("name"), item.get("value")
        if not name or value is None:
            continue
        domain = str(item.get("domain") or ADMIN_HOST)
        if not _is_cyberbiz_domain(domain):
            continue
        cookie: dict[str, Any] = {key: item[key] for key in _PLAYWRIGHT_COOKIE_KEYS if item.get(key) is not None}
        cookie["name"], cookie["value"] = str(name), str(value)
        cookie["domain"] = domain
        cookie["path"] = str(item.get("path") or "/")
        same_site = _SAME_SITE.get(str(cookie.pop("sameSite", "")).lower())
        if same_site:
            cookie["sameSite"] = same_site
        cookies.append(cookie)
    return cookies


def load_get_cookies(xinchi_tools_path: Path) -> Callable[[list[str]], Any]:
    """把 xinchi-tools-main/共用 加進 sys.path，匯入 elevated_cookies.get_cookies。

    只匯入函式，不讀取該資料夾裡的任何 cookie 或帳號檔案。
    """
    shared = str(Path(xinchi_tools_path) / "共用")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    module = importlib.import_module("elevated_cookies")
    return module.get_cookies


# ---------------------------------------------------------------------------
# 只放行 GET 的請求攔截器
# ---------------------------------------------------------------------------


class RequestGuard:
    """page.route 用的攔截器：GET 放行，其他方法一律擋下並記錄方法與網址。"""

    def __init__(self) -> None:
        """建立攔截器；blocked 記錄被擋下的 (方法, 網址)。"""
        self.blocked: list[tuple[str, str]] = []

    def handle(self, route: Any) -> None:
        """處理一個請求。只記錄方法與網址，絕不記錄 headers 或 cookie。"""
        request = route.request
        method = str(request.method or "").upper()
        if method == "GET":
            route.continue_()
            return
        route.abort()
        self.blocked.append((method, request.url))
        say(f"已擋下非 GET 請求：{method} {request.url}")


# ---------------------------------------------------------------------------
# 進度存檔
# ---------------------------------------------------------------------------


@dataclass
class Progress:
    """進度存檔內容（不含任何 cookie）。"""

    visited_urls: list[str] = field(default_factory=list)
    not_found_urls: list[str] = field(default_factory=list)
    last_stop_reason: str = ""
    last_stop_page: int = 0
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path) -> Progress:
        """讀取 progress.json；不存在或格式錯誤時從頭開始。"""
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            say(f"進度檔讀取失敗，從頭開始：{path}")
            return cls()
        return cls(
            visited_urls=[str(u) for u in data.get("visited_urls", [])],
            not_found_urls=[str(u) for u in data.get("not_found_urls", [])],
            last_stop_reason=str(data.get("last_stop_reason", "")),
            last_stop_page=int(data.get("last_stop_page", 0)),
            updated_at=str(data.get("updated_at", "")),
        )

    def save(self, path: Path) -> None:
        """寫入 progress.json（先寫暫存檔再取代，避免中斷時檔案損壞）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def is_done(self, url: str) -> bool:
        """這個網址是否已讀過（含已記錄為 404 的頁面）。"""
        return url in self.visited_urls or url in self.not_found_urls


# ---------------------------------------------------------------------------
# 依序讀取頁面
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlResult:
    """一次執行的結果。"""

    reason: str
    stop_page: int
    pages_read: int
    finished: bool = False


def finish_run(result: CrawlResult, progress: Progress, progress_path: Path) -> CrawlResult:
    """記錄停止原因與頁數到 progress.json，並在終端機清楚顯示。"""
    progress.last_stop_reason = result.reason
    progress.last_stop_page = result.stop_page
    progress.save(progress_path)
    say("=" * 50)
    say(f"停止原因：{result.reason}")
    say(f"停在第 {result.stop_page} 頁（本次共讀取 {result.pages_read} 頁）")
    say(f"進度已存到：{progress_path}")
    say("=" * 50)
    return result


def crawl(
    page: Any,
    urls: Sequence[str],
    progress: Progress,
    progress_path: Path,
    on_page: Callable[[str, str, str], None],
    sleep: Callable[[float], None] = time.sleep,
    random_delay: Callable[[], float] = random_page_delay,
    max_pages: int = MAX_PAGES,
) -> CrawlResult:
    """用同一個分頁依序讀取 urls，每讀完一頁存一次進度。

    on_page(原網址, 最終網址, HTML) 在頁面正常讀取後呼叫。
    已讀過、非後台網域、敏感頁面會跳過；遇到停止條件立即結束，不重試。
    """
    pages_read = 0
    consecutive_404 = 0

    def stop(reason: str, finished: bool = False) -> CrawlResult:
        """結束本次執行。"""
        return finish_run(CrawlResult(reason, pages_read, pages_read, finished), progress, progress_path)

    for raw_url in urls:
        url = clean_url(raw_url)
        if progress.is_done(url):
            say(f"略過（之前已讀過）：{url}")
            continue
        if not is_admin_url(url):
            say(f"略過（不是後台網域）：{url}")
            continue
        if is_sensitive(url):
            say(f"略過（敏感頁面）：{url}")
            continue
        if pages_read >= max_pages:
            return stop(f"已達每次執行上限 {max_pages} 頁")

        if pages_read > 0:
            sleep(random_delay())
        pages_read += 1
        say(f"[第 {pages_read} 頁] 讀取 {url}")

        try:
            response = page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - 只顯示例外類型，避免訊息夾帶敏感內容
            return stop(f"頁面載入失敗（{type(exc).__name__}）")
        if response is None:
            return stop("沒有收到 HTTP 回應")

        status = int(response.status)
        final_url = str(page.url or response.url or url)

        if status == 404:
            consecutive_404 += 1
            progress.not_found_urls.append(url)
            progress.save(progress_path)
            say(f"HTTP 404，跳過不重試：{url}（連續第 {consecutive_404} 次）")
            if consecutive_404 >= MAX_CONSECUTIVE_404:
                return stop(f"連續 {MAX_CONSECUTIVE_404} 頁 HTTP 404")
            continue
        if status in STOP_STATUSES or 500 <= status <= 599:
            return stop(f"HTTP {status}")
        if is_login_url(final_url) or is_login_url(str(response.url or "")):
            return stop(f"被導回登入頁（{urlsplit(final_url).path}），cookie 可能已失效")
        if not is_admin_url(final_url):
            return stop(f"被導到後台以外的網址（{urlsplit(final_url).netloc}）")
        if status >= 400:
            return stop(f"非預期的 HTTP {status}")

        try:
            html = str(page.content())
        except Exception as exc:  # noqa: BLE001
            return stop(f"讀取頁面內容失敗（{type(exc).__name__}）")
        if has_captcha(html):
            return stop("頁面出現驗證碼")

        consecutive_404 = 0
        on_page(url, final_url, html)
        progress.visited_urls.append(url)
        progress.save(progress_path)

    if pages_read == 0:
        return stop("沒有待讀頁面（都已讀過）", finished=True)
    return stop("全部讀完", finished=True)


# ---------------------------------------------------------------------------
# 第一步：讀左側選單
# ---------------------------------------------------------------------------


def explore_admin(
    browser: Any,
    get_cookies: Callable[[list[str]], Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sleep: Callable[[float], None] = time.sleep,
    random_delay: Callable[[], float] = random_page_delay,
    max_pages: int = MAX_PAGES,
) -> CrawlResult:
    """注入 cookie、開啟後台首頁，解析左側選單並寫出 menu.csv。"""
    progress_path = output_dir / "progress.json"
    menu_path = output_dir / "menu.csv"
    progress = Progress.load(progress_path)

    try:
        cookies = to_playwright_cookies(get_cookies(list(COOKIE_DOMAINS)))
    except Exception as exc:  # noqa: BLE001 - 只顯示例外類型，避免訊息夾帶 cookie
        return finish_run(CrawlResult(f"取得 cookie 失敗（{type(exc).__name__}）", 0, 0), progress, progress_path)
    if not cookies:
        return finish_run(CrawlResult("沒有取得 Cyberbiz 後台的 cookie", 0, 0), progress, progress_path)
    say(f"已取得 {len(cookies)} 個 Cyberbiz cookie（內容不顯示）")

    context = browser.new_context()
    try:
        try:
            context.add_cookies(cookies)
        except Exception as exc:  # noqa: BLE001
            return finish_run(CrawlResult(f"注入 cookie 失敗（{type(exc).__name__}）", 0, 0), progress, progress_path)
        finally:
            cookies.clear()

        page = context.new_page()
        guard = RequestGuard()
        page.route("**/*", guard.handle)

        def save_menu(url: str, final_url: str, html: str) -> None:
            """解析左側選單並寫出 menu.csv。"""
            links = extract_menu_links(html, final_url)
            write_menu_csv(links, menu_path)
            say(
                f"左側選單共 {len(links)} 個連結，已寫入 {menu_path}"
                f"（排除敏感頁面後可供下一步讀取 {len(safe_queue(links))} 個）"
            )

        return crawl(
            page,
            [ADMIN_HOME],
            progress,
            progress_path,
            on_page=save_menu,
            sleep=sleep,
            random_delay=random_delay,
            max_pages=max_pages,
        )
    finally:
        context.close()


def launch_browser(playwright: Any) -> Any:
    """啟動有畫面的瀏覽器（headless=False）。"""
    return playwright.chromium.launch(headless=False)


def setup_file_log(path: Path) -> None:
    """把 log 同時寫到 research/admin/explore.log。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def xinchi_tools_path_from_env(env_file: Path = ROOT / ".env") -> Path:
    """從 .env 或環境變數讀 XINCHI_TOOLS_PATH，沒設定時用預設路徑。"""
    from dotenv import load_dotenv

    if env_file.is_file():
        load_dotenv(env_file, override=False)
    value = os.environ.get("XINCHI_TOOLS_PATH", "").strip()
    return Path(value) if value else DEFAULT_XINCHI_TOOLS_PATH


def main() -> int:
    """命令列進入點。任何錯誤都只顯示例外類型，避免訊息夾帶 cookie。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    setup_file_log(DEFAULT_OUTPUT_DIR / "explore.log")
    try:
        get_cookies = load_get_cookies(xinchi_tools_path_from_env())
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                result = explore_admin(browser, get_cookies)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        say(f"程式中止：{type(exc).__name__}（為避免洩漏 cookie，不顯示詳細訊息）")
        return 1
    return 0 if result.finished else 1


if __name__ == "__main__":
    raise SystemExit(main())
