"""Cyberbiz 後台唯讀探索腳本。

兩種模式：
- 預設（--mode menu）：開啟後台首頁 https://sinchih.cyberbiz.co/admin，解析左側選單
  所有連結的文字與網址，輸出成 research/admin/menu.csv（UTF-8 with BOM，欄位 text,url）。
- 列表頁（--lists 或 --mode lists）：只讀 LIST_PAGE_URLS 這 9 個後台列表頁本身
  （「商品標籤管理」會優先用 menu.csv 裡含「標籤管理」的網址），把主內容區的區塊標題、
  表單欄位、表格與清單整理成 research/admin/<主題>.md。列表有分頁（同一路徑、
  query 只有 page=2、page=3…）時會接著讀，分頁合併在同一個主題檔；本模式每次最多
  讀 MAX_LIST_PAGES（50）頁。不點進任何單一項目（/edit、/new、單一項目子路徑）。
  輸出前一律遮蔽 email、電話、API 金鑰、secret、token（保留 GA4 的 G-、GTM- 等追蹤 ID
  與站內網址路徑）。
- 動態載入頁（--dynamic 或 --mode dynamic）：重新只讀 /admin/menus 與 /admin/custom_pages_index
  （會先把這兩頁與其分頁從 progress.json 的已讀紀錄移除）。這兩頁的內容由前端 JS 動態載入，
  讀 HTML 前會等待網路閒置、動態項目出現與渲染穩定；同時整合渲染後的 DOM、頁面內嵌 JSON
  （data-react-props 等 data-* 屬性與 script 內的 JSON）與被動監聽到的同網域 GET JSON 回應：
  menus 輸出選單樹（群組、層級、名稱、連結），custom_pages_index 輸出自訂頁面表
  （標題、網址、發佈／隱藏狀態），自訂頁面有分頁時接著讀（最多 50 頁）。

安全規則：
- cookie 由 xinchi-tools-main/共用/elevated_cookies.py 的 get_cookies 取得，
  只存在程式記憶體中；絕不印出、寫入 log、progress.json 或任何檔案。
  本腳本不讀取 xinchi-tools-main 裡的任何 cookie 或帳號檔案。
- 用 Playwright 開有畫面的瀏覽器，單一 context、單一分頁，一頁一頁依序讀。
- 攔截所有請求：只放行 GET，其他方法（POST、PUT、DELETE、PATCH…）一律擋下並記錄。
- 每頁之間隨機等待 2～5 秒；每次執行最多讀 100 頁（列表頁模式 50 頁）。
- 只造訪從選單或列表頁實際取得的網址，不自己拼湊網址；敏感頁面（訂單、會員、金流…）不進入。
- 遇到 HTTP 429、403、5xx、被導回登入頁、出現驗證碼、連續 3 頁 404 立即停止，不重試。
- 每讀完一頁就寫 research/admin/progress.json，下次執行自動跳過已讀頁面。

用法：
    python scripts/admin_explore.py            （第一步：讀左側選單）
    python scripts/admin_explore.py --lists    （讀 9 個列表頁）
    python scripts/admin_explore.py --dynamic  （重新讀 menus 與 custom_pages_index，等待 JS 動態載入）
    （要重新讀一次，請先刪除 research/admin/progress.json）
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import logging
import os
import random
import re
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "research" / "admin"
DEFAULT_XINCHI_TOOLS_PATH = Path(r"C:\Users\ycc\Desktop\xinchi-tools-main")

ADMIN_HOST = "sinchih.cyberbiz.co"
ADMIN_HOME = f"https://{ADMIN_HOST}/admin"
COOKIE_DOMAINS: tuple[str, ...] = (".cyberbiz.co", "sinchih.cyberbiz.co")

MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 5.0
MAX_PAGES = 100
MAX_LIST_PAGES = 50
MAX_CONSECUTIVE_404 = 3
NAVIGATION_TIMEOUT_MS = 60_000

STOP_STATUSES = frozenset({401, 403, 429})
LOGIN_MARKERS = ("/login", "/sign_in", "/signin", "/admins/sign_in", "/users/sign_in")
CAPTCHA_MARKERS = ("recaptcha", "g-recaptcha", "cf-turnstile", "hcaptcha", "captcha", "驗證碼")

# 列表頁模式只讀這些網址（商品標籤管理已從 menu.csv 確認）
PRODUCT_TAGS_URL = f"https://{ADMIN_HOST}/admin/product_tags"
LIST_PAGE_URLS: tuple[str, ...] = (
    f"https://{ADMIN_HOST}/admin/platforms/google",
    f"https://{ADMIN_HOST}/admin/shop_add_ons",
    f"https://{ADMIN_HOST}/admin/menus",
    f"https://{ADMIN_HOST}/admin/redirections",
    f"https://{ADMIN_HOST}/admin/blogs",
    f"https://{ADMIN_HOST}/admin/custom_pages_index",
    f"https://{ADMIN_HOST}/admin/smart_collections",
    f"https://{ADMIN_HOST}/admin/custom_collections",
    PRODUCT_TAGS_URL,
)
TAG_MENU_TEXT = "標籤管理"
SINGLE_ITEM_SEGMENTS = frozenset({"edit", "new"})

# --dynamic 模式只讀這兩頁（內容由前端 JS 動態載入）
MENUS_URL = f"https://{ADMIN_HOST}/admin/menus"
CUSTOM_PAGES_URL = f"https://{ADMIN_HOST}/admin/custom_pages_index"
CUSTOM_PAGES_ALT_URL = f"https://{ADMIN_HOST}/admin/custom_pages"
DYNAMIC_PAGE_URLS: tuple[str, ...] = (MENUS_URL, CUSTOM_PAGES_URL)
# 列表路徑 → 寫入哪個主題檔（/admin/custom_pages?page=N 的分頁也併入 custom_pages_index.md）
DYNAMIC_LIST_PATHS: dict[str, str] = {
    MENUS_URL: MENUS_URL,
    CUSTOM_PAGES_URL: CUSTOM_PAGES_URL,
    CUSTOM_PAGES_ALT_URL: CUSTOM_PAGES_URL,
}
NETWORK_IDLE_TIMEOUT_MS = 15_000
DYNAMIC_SELECTOR_TIMEOUT_MS = 10_000
RENDER_SETTLE_MS = 2_000
# 主內容區「動態項目已出現」的線索（任一個出現就算）
DYNAMIC_CONTENT_SELECTOR = ", ".join(
    (
        "table tbody tr",
        ".dd-item",
        ".tree-node",
        "[role='treeitem']",
        "[data-react-class] *",
        "a[href*='/pages/']",
        "main input:not([type='hidden'])",
        "[role='main'] input:not([type='hidden'])",
    )
)
MAX_JSON_RESPONSES_PER_PAGE = 50
MAX_JSON_BODY_BYTES = 5_000_000
MAX_EMBEDDED_JSON_CHARS = 2_000_000
MAX_SCRIPT_JSON_ATTEMPTS = 300
MAX_JSON_DEPTH = 40

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

# 頂部導覽列的 id / class（完全相同才算）
TOP_NAV_TOKENS = frozenset(
    {"navbar", "navbar-fixed-top", "navbar-static-top", "topbar", "top-bar", "top-nav", "topnav", "main-header", "site-header", "header-nav"}
)
# 主內容區的 id / class（完全相同才算）
MAIN_CONTENT_TOKENS = frozenset(
    {
        "main",
        "main-content",
        "main_content",
        "maincontent",
        "main-container",
        "main-panel",
        "content",
        "content-wrapper",
        "content-body",
        "page-content",
        "page-wrapper",
        "app-content",
    }
)
# 看起來像區塊標題的 class（完全相同才算）
TITLE_CLASS_TOKENS = frozenset(
    {"page-title", "panel-title", "card-title", "box-title", "section-title", "panel-heading", "card-header", "box-header"}
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "legend"})
MAX_TITLE_CHARS = 200
MAX_PARAGRAPH_CHARS = 500

# 表單欄位：這些類型不輸出（隱藏欄位、密碼、按鈕）
SKIP_INPUT_TYPES = frozenset({"hidden", "password", "submit", "button", "reset", "image", "file"})
SKIP_FIELD_NAMES = ("authenticity_token", "csrf", "_method", "utf8")

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


def strip_query(url: str) -> str:
    """去掉網址的 query 與 # 錨點，只留 scheme://host/path。"""
    parts = urlsplit(clean_url(url))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def looks_like_single_item(url: str) -> bool:
    """網址是否像單一項目頁（路徑含 edit、new 或純數字的項目編號）。"""
    segments = [s for s in urlsplit(url).path.lower().split("/") if s]
    return any(s in SINGLE_ITEM_SEGMENTS or s.isdigit() for s in segments)


def list_page_number(url: str) -> int | None:
    """列表頁的頁碼：沒有 query 是第 1 頁；query 只有 page=N（N≥2）是第 N 頁；其他回傳 None。"""
    query = urlsplit(clean_url(url)).query
    if not query:
        return 1
    pairs = parse_qsl(query, keep_blank_values=True)
    if len(pairs) != 1 or pairs[0][0] != "page" or not pairs[0][1].isdigit():
        return None
    number = int(pairs[0][1])
    return number if number >= 2 else None


def is_pagination_url(url: str, list_url: str) -> bool:
    """url 是否為 list_url 的分頁連結（同一網域與路徑，query 只有 page=2、page=3…）。"""
    url = clean_url(url)
    if not is_admin_url(url) or strip_query(url) != strip_query(list_url):
        return False
    number = list_page_number(url)
    return number is not None and number >= 2


def list_topic_name(url: str) -> str:
    """列表頁的主題檔名（不含副檔名），例如 /admin/platforms/google → platforms_google。"""
    path = urlsplit(url).path.strip("/")
    if path.startswith("admin/"):
        path = path[len("admin/") :]
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", path).strip("_")
    return slug or "admin"


# ---------------------------------------------------------------------------
# 敏感資料遮蔽
# ---------------------------------------------------------------------------


MASK = "***"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# 台灣手機（09xx-xxx-xxx、+886-9xx-xxx-xxx）與市話（02-2345-6789、(02)2345-6789、+886-2-2345-6789）
# 前後用 ASCII 字元判斷邊界（中文字緊接著電話也要遮）
MOBILE_RE = re.compile(r"(?<![A-Za-z0-9_.\-/+])(?:\+?886[\s-]?|0)9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![A-Za-z0-9_\-/])")
LANDLINE_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/+])(?:\+?886[\s-]?\(?|\(?0)\d{1,2}\)?[\s-]?\d{3,4}[\s-]?\d{4}"
    r"(?:\s*(?:#|分機|ext\.?)\s*\d{1,5})?(?![A-Za-z0-9_\-/])",
    re.IGNORECASE,
)
SECRET_WORDS = r"api[\s_-]?key|apikey|secret|token|password|passwd|private[\s_-]?key|access[\s_-]?key|金鑰|密鑰|密碼|權杖"
SECRET_NAME_RE = re.compile(SECRET_WORDS, re.IGNORECASE)
# 「API Key: xxx」「token=xxx」這類寫法：保留前面的名稱，只遮後面的值
KEYED_SECRET_RE = re.compile(rf"((?:{SECRET_WORDS})\s*[:=：]\s*)([^\s,;|，；]+)", re.IGNORECASE)
# 常見金鑰格式（Google API key、Stripe、GitHub、Facebook、Slack）
KNOWN_TOKEN_RE = re.compile(
    r"AIza[0-9A-Za-z_\-]{20,}|(?:sk|pk|rk)_(?:live|test)_[0-9A-Za-z]{8,}|gh[pousr]_[0-9A-Za-z]{20,}"
    r"|EAA[0-9A-Za-z]{20,}|xox[abpr]-[0-9A-Za-z-]{10,}"
)
# 32 字元以上、英數混合的長字串，視為金鑰或 token
LONG_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])"
)
# GA4 衡量 ID、GTM 容器 ID、UA、Google Ads 等追蹤 ID：保留不遮
TRACKING_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])(?:G|GTM|UA|AW|GT|DC)-[A-Z0-9]{4,}(?:-\d+)?(?![A-Za-z0-9_-])")
# 網址（絕對網址或 / 開頭的站內路徑）：路徑保留，只檢查 query
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#@!$&*+,;=%]+|(?<![\w/])/[A-Za-z_][A-Za-z0-9\-._~:/?#@!$&*+,;=%]*")
PROTECTED_RE = re.compile(f"{URL_RE.pattern}|{TRACKING_ID_RE.pattern}")
QUERY_PARAM_RE = re.compile(r"([?&])([^=&#]+)=([^&#]*)")
PII_PARAM_RE = re.compile(r"email|e-mail|mail|phone|mobile|tel", re.IGNORECASE)


def _mask_url(url: str) -> str:
    """遮蔽網址裡的 email，以及 query 中金鑰、token、email、電話類參數的值；路徑不動。"""
    if TRACKING_ID_RE.fullmatch(url):
        return url

    def replace_param(match: re.Match[str]) -> str:
        """處理一個 query 參數。"""
        prefix, key, value = match.groups()
        decoded = unquote(value)
        if value and (
            SECRET_NAME_RE.search(key)
            or PII_PARAM_RE.search(key)
            or EMAIL_RE.search(decoded)
            or LONG_TOKEN_RE.search(decoded)
            or KNOWN_TOKEN_RE.search(decoded)
        ):
            value = MASK
        return f"{prefix}{key}={value}"

    return EMAIL_RE.sub(MASK, QUERY_PARAM_RE.sub(replace_param, url))


def _mask_plain(text: str) -> str:
    """遮蔽一般文字裡的 email、金鑰、token、電話。"""
    text = EMAIL_RE.sub(MASK, text)
    text = KEYED_SECRET_RE.sub(lambda m: f"{m.group(1)}{MASK}", text)
    text = KNOWN_TOKEN_RE.sub(MASK, text)
    text = LONG_TOKEN_RE.sub(MASK, text)
    text = MOBILE_RE.sub(MASK, text)
    return LANDLINE_RE.sub(MASK, text)


def mask_sensitive(text: str) -> str:
    """把 email、電話（市話與手機）、API 金鑰、secret、token 換成 ***。

    GA4（G-）、GTM（GTM-）等追蹤 ID 與站內網址路徑不遮；網址只遮 query 中的敏感值。
    """
    pieces: list[str] = []
    last = 0
    for match in PROTECTED_RE.finditer(text):
        pieces.append(_mask_plain(text[last : match.start()]))
        pieces.append(_mask_url(match.group(0)))
        last = match.end()
    pieces.append(_mask_plain(text[last:]))
    return "".join(pieces)


def mask_field_value(name: str, label: str, value: str) -> str:
    """表單欄位值：欄位名稱或標籤像金鑰、secret、token、密碼時整個遮蔽（追蹤 ID 除外）。"""
    if not value:
        return value
    if (SECRET_NAME_RE.search(name) or SECRET_NAME_RE.search(label)) and not TRACKING_ID_RE.fullmatch(value.strip()):
        return MASK
    return mask_sensitive(value)


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
# 列表頁：要讀哪些網址
# ---------------------------------------------------------------------------


def tag_url_from_menu(menu_csv: Path) -> str | None:
    """從 menu.csv 找文字含「標籤管理」的後台列表網址；找不到或不合規回傳 None。"""
    if not menu_csv.is_file():
        return None
    try:
        with menu_csv.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error, UnicodeDecodeError):
        say(f"menu.csv 讀取失敗，改用預設的商品標籤管理網址：{menu_csv}")
        return None
    for row in rows:
        text = str(row.get("text") or "")
        url = clean_url(str(row.get("url") or ""))
        if TAG_MENU_TEXT not in text:
            continue
        if is_admin_url(url) and not is_sensitive(url, text) and not looks_like_single_item(url):
            return strip_query(url)
    return None


def list_targets(menu_csv: Path | None = None) -> list[str]:
    """列表頁模式要讀的網址：固定 9 頁；menu.csv 有「標籤管理」網址時用它取代預設的商品標籤管理。"""
    targets = list(LIST_PAGE_URLS)
    tag_url = tag_url_from_menu(menu_csv) if menu_csv is not None else None
    if tag_url and tag_url not in targets:
        targets[targets.index(PRODUCT_TAGS_URL)] = tag_url
    return targets


def pagination_links(html: str, page_url: str, list_url: str) -> list[str]:
    """找出頁面上屬於 list_url 的分頁連結（只收 query 為 page=N 的連結），去重複、保留順序。"""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, None] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.strip() or href.strip().startswith("#"):
            continue
        url = clean_url(urljoin(page_url, href.strip()))
        if is_pagination_url(url, list_url) and not is_sensitive(url):
            found[url] = None
    return list(found)


# ---------------------------------------------------------------------------
# 列表頁：主內容區整理
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormField:
    """主內容區的一個表單欄位（值已遮蔽）。"""

    label: str
    name: str
    kind: str
    value: str


def _tokens(tag: Tag) -> set[str]:
    """元素的 id 與 class（小寫）。"""
    return {str(tag.get("id") or "").lower(), *[str(c).lower() for c in tag.get("class") or []]} - {""}


def _is_inside(tag: Tag, ancestor: Tag | None) -> bool:
    """tag 是否在 ancestor 裡面（不含自己）。"""
    return ancestor is not None and any(parent is ancestor for parent in tag.parents)


def find_main_container(soup: BeautifulSoup) -> tuple[Tag | BeautifulSoup, bool]:
    """找主內容區：<main> 或 role=main，其次 id/class 像主內容的元素（取文字最多的）。

    回傳 (容器, 是否為退回整頁)。退回整頁時呼叫端要自行移除選單與導覽列。
    """
    for candidate in (soup.find("main"), soup.find(attrs={"role": "main"})):
        if isinstance(candidate, Tag):
            return candidate, False

    menu = find_menu_container(soup)
    sidebar = menu if menu is not None and _container_score(menu) >= 2 else None
    best: Tag | None = None
    best_len = -1
    for tag in soup.find_all(True):
        if not _tokens(tag) & MAIN_CONTENT_TOKENS:
            continue
        if sidebar is not None and (tag is sidebar or _is_inside(sidebar, tag) or _is_inside(tag, sidebar)):
            continue
        length = len(tag.get_text(" ", strip=True))
        if length > best_len:
            best, best_len = tag, length
    if best is not None:
        return best, False
    return (soup.body or soup), True


def _top_nav_elements(soup: BeautifulSoup) -> list[Tag]:
    """頂部導覽列：id/class 為 navbar、topbar 等（完全相同才算）、role=banner，
    以及直接放在 <body> 或 <header> 底下的 <header>／<nav>。

    主內容區裡的 <nav>（例如選單編輯元件）不算。
    """
    found: list[Tag] = []
    for tag in soup.find_all(True):
        if _tokens(tag) & TOP_NAV_TOKENS or str(tag.get("role") or "").lower() == "banner":
            found.append(tag)
        elif tag.name in ("header", "nav") and isinstance(tag.parent, Tag) and tag.parent.name in ("body", "html", "header"):
            found.append(tag)
    return found


def _main_content_soup(html: str) -> BeautifulSoup:
    """取出主內容區的副本，只移除判定為左側選單的那一個容器、頂部導覽列與 script、style 等。

    左側選單只移除 find_menu_container 找到的那一個；若它在主內容區裡面（且主內容區不是退回
    整頁），代表它其實是主內容區的元件（例如 class 含 main-menu 的選單編輯區），保留不刪。
    主內容區裡其他的 <nav>、<aside>、class 含 menu 的元素一律保留。
    """
    soup = BeautifulSoup(html, "html.parser")
    container, fallback = find_main_container(soup)
    targets: list[Tag] = []
    menu = find_menu_container(soup)
    if menu is not None and (fallback or not _is_inside(menu, container)):
        targets.append(menu)
    targets.extend(_top_nav_elements(soup))
    for tag in targets:
        if tag is container or _is_inside(container, tag) or getattr(tag, "decomposed", False):
            continue
        tag.decompose()

    content = BeautifulSoup(str(container), "html.parser")
    for tag in content.find_all(["script", "style", "noscript", "template", "svg"]):
        if not getattr(tag, "decomposed", False):
            tag.decompose()
    return content


def _absolute_href(href: Any, base_url: str) -> str:
    """把 href 轉成絕對網址；#、javascript: 回傳空字串，mailto:/tel: 保留原樣（之後會被遮蔽）。"""
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return ""
    if href.lower().startswith(("mailto:", "tel:")):
        return href
    return clean_url(urljoin(base_url, href))


def _field_kind(tag: Tag) -> str:
    """表單欄位類型：select、textarea 或 input 的 type。"""
    if tag.name == "input":
        return str(tag.get("type") or "text").lower()
    return str(tag.name)


def _is_skipped_field(tag: Tag) -> bool:
    """隱藏欄位、密碼、按鈕與 CSRF token 欄位不輸出。"""
    name = str(tag.get("name") or "").lower()
    if any(skip in name for skip in SKIP_FIELD_NAMES):
        return True
    return tag.name == "input" and _field_kind(tag) in SKIP_INPUT_TYPES


def _raw_field_value(tag: Tag) -> str:
    """欄位目前的值（未遮蔽）。勾選框顯示已勾選/未勾選，下拉選單顯示選中的選項文字。"""
    if tag.name == "select":
        options = tag.find_all("option")
        chosen = [o for o in options if o.has_attr("selected")]
        if not chosen and options and not tag.has_attr("multiple"):
            chosen = options[:1]
        return "、".join(_clean_text(o.get_text(" ")) for o in chosen)
    if tag.name == "textarea":
        return _clean_text(tag.get_text(" "))
    kind = _field_kind(tag)
    value = _clean_text(str(tag.get("value") or ""))
    if kind in ("checkbox", "radio"):
        state = "已勾選" if tag.has_attr("checked") else "未勾選"
        return f"{state}（{value}）" if value and value.lower() not in ("on", "1", "true") else state
    return value


def _label_text(label: Tag, field_tag: Tag) -> str:
    """label 的文字（不含欄位本身與下拉選項的文字）。"""
    parts: list[str] = []
    for string in label.find_all(string=True):
        if isinstance(string, Comment) or _is_inside(string, field_tag):  # type: ignore[arg-type]
            continue
        if string.find_parent(["select", "option", "textarea", "script", "style"]) is not None:
            continue
        parts.append(str(string))
    return _clean_text(" ".join(parts))


def _field_label(tag: Tag, content: BeautifulSoup) -> str:
    """找欄位的標籤：<label for>、包住欄位的 <label>、同一 form-group 的 <label>、aria-label、placeholder、title。"""
    field_id = tag.get("id")
    if isinstance(field_id, str) and field_id:
        label = content.find("label", attrs={"for": field_id})
        if isinstance(label, Tag):
            text = _label_text(label, tag)
            if text:
                return text
    parent_label = tag.find_parent("label")
    if isinstance(parent_label, Tag):
        text = _label_text(parent_label, tag)
        if text:
            return text
    group = tag.find_parent(lambda t: isinstance(t, Tag) and bool({"form-group", "field", "form-item"} & _tokens(t)))
    if isinstance(group, Tag):
        label = group.find("label")
        if isinstance(label, Tag):
            text = _label_text(label, tag)
            if text:
                return text
    for attr in ("aria-label", "placeholder", "title"):
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def extract_form_fields(content: BeautifulSoup) -> list[FormField]:
    """主內容區所有表單欄位的標籤、name、類型與目前的值（值已遮蔽）。"""
    fields: list[FormField] = []
    for tag in content.find_all(["input", "select", "textarea"]):
        if _is_skipped_field(tag):
            continue
        name = str(tag.get("name") or tag.get("id") or "")
        label = _field_label(tag, content)
        value = mask_field_value(name, label, _raw_field_value(tag))
        fields.append(FormField(label=label, name=name, kind=_field_kind(tag), value=value))
    return fields


def _inline_text(node: Any, base_url: str) -> str:
    """把元素轉成一行文字，連結寫成 [文字](網址)，表單欄位顯示目前的值。"""
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in ("script", "style", "template", "svg"):
        return ""
    if node.name == "br":
        return " "
    if node.name == "img":
        alt = _clean_text(str(node.get("alt") or ""))
        return f" [圖片：{alt}] " if alt else ""
    if node.name in ("input", "select", "textarea"):
        if _is_skipped_field(node):
            return ""
        name = str(node.get("name") or "")
        return f" {mask_field_value(name, '', _raw_field_value(node))} "
    if node.name == "a":
        text = _clean_text("".join(_inline_text(child, base_url) for child in node.children))
        if not text:
            text = _clean_text(str(node.get("title") or node.get("aria-label") or ""))
        href = _absolute_href(node.get("href"), base_url)
        if href:
            return f" [{text or href}]({href}) "
        return f" {text} "
    return "".join(_inline_text(child, base_url) for child in node.children)


def _cell_text(cell: Tag, base_url: str) -> str:
    """表格儲存格文字（跳脫 | 以免破壞 Markdown 表格）。"""
    return _clean_text(_inline_text(cell, base_url)).replace("|", "\\|")


def table_to_markdown(table: Tag, base_url: str) -> list[str]:
    """把 <table> 轉成 Markdown 表格（保留列內文字與連結 href）。沒有標題列時用「欄1、欄2…」。"""
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    matrix: list[list[str]] = []
    header_row = False
    for index, tr in enumerate(rows):
        cells = tr.find_all(["th", "td"], recursive=False)
        texts = [_cell_text(cell, base_url) for cell in cells]
        if not any(texts):
            continue
        if not matrix:
            header_row = tr.find_parent("thead") is not None or (bool(cells) and all(c.name == "th" for c in cells))
        matrix.append(texts)
    if not matrix:
        return []
    width = max(len(row) for row in matrix)
    matrix = [row + [""] * (width - len(row)) for row in matrix]
    if header_row:
        header, body = matrix[0], matrix[1:]
    else:
        header, body = [f"欄{i + 1}" for i in range(width)], matrix
    lines: list[str] = []
    caption = table.find("caption")
    if isinstance(caption, Tag) and caption.get_text(strip=True):
        lines.append(f"**{_clean_text(caption.get_text(' '))}**")
        lines.append("")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * width) + " |")
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return lines


def list_to_markdown(element: Tag, base_url: str, depth: int = 0) -> list[str]:
    """把 <ul>/<ol> 轉成 Markdown 清單（巢狀清單縮排）。"""
    lines: list[str] = []
    for item in element.find_all("li", recursive=False):
        nested = [child for child in item.children if isinstance(child, Tag) and child.name in ("ul", "ol")]
        text = _clean_text(
            "".join(_inline_text(child, base_url) for child in item.children if all(child is not sub for sub in nested))
        )
        if text:
            lines.append(f"{'  ' * depth}- {text}")
        for sub in nested:
            lines.extend(list_to_markdown(sub, base_url, depth + 1))
    return lines


def _is_title(tag: Tag) -> bool:
    """是否為區塊標題（h1～h6、legend 或常見的標題 class）。"""
    return tag.name in HEADING_TAGS or bool(_tokens(tag) & TITLE_CLASS_TOKENS)


def extract_main_blocks(content: BeautifulSoup, base_url: str) -> list[str]:
    """依出現順序整理主內容區的區塊標題、段落、表格與清單，回傳 Markdown 行。"""
    lines: list[str] = []
    taken: set[int] = set()
    for tag in content.find_all(True):
        if any(id(parent) in taken for parent in tag.parents):
            continue
        if tag.name == "table":
            taken.add(id(tag))
            table_lines = table_to_markdown(tag, base_url)
            if table_lines:
                lines.extend(["", *table_lines, ""])
        elif tag.name in ("ul", "ol"):
            taken.add(id(tag))
            if "pagination" in _tokens(tag):
                continue
            list_lines = list_to_markdown(tag, base_url)
            if list_lines:
                lines.extend(["", *list_lines, ""])
        elif _is_title(tag):
            taken.add(id(tag))
            text = _clean_text(tag.get_text(" "))
            if text and len(text) <= MAX_TITLE_CHARS:
                lines.extend(["", f"#### {text}", ""])
        elif tag.name == "p":
            taken.add(id(tag))
            text = _clean_text(_inline_text(tag, base_url))
            if text and len(text) <= MAX_PARAGRAPH_CHARS:
                lines.append(text)
    return lines


def fields_to_markdown(fields: Sequence[FormField]) -> list[str]:
    """把表單欄位整理成 Markdown 表格（標籤 | name | 類型 | 目前的值）。"""
    if not fields:
        return []

    def cell(text: str) -> str:
        """跳脫 |。"""
        return text.replace("|", "\\|")

    lines = ["| 標籤 | name | 類型 | 目前的值 |", "| --- | --- | --- | --- |"]
    lines.extend(f"| {cell(f.label)} | {cell(f.name)} | {cell(f.kind)} | {cell(f.value)} |" for f in fields)
    return lines


def _page_meta_lines(url: str, final_url: str, page_number: int) -> list[str]:
    """每頁段落開頭：頁碼、網址、實際網址（不同時）與讀取時間。"""
    lines = [f"## 第 {page_number} 頁", "", f"- 網址：{url}"]
    if clean_url(final_url) != clean_url(url):
        lines.append(f"- 實際網址：{final_url}")
    lines.append(f"- 讀取時間：{datetime.now().isoformat(timespec='seconds')}")
    return lines


def _finish_markdown(lines: Sequence[str]) -> str:
    """合併 Markdown 行、壓掉多餘空行，並遮蔽敏感資料。"""
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return mask_sensitive(text) + "\n"


def render_list_page(html: str, url: str, final_url: str, page_number: int) -> str:
    """把一個列表頁整理成 Markdown 段落（已遮蔽敏感資料）。"""
    content = _main_content_soup(html)
    blocks = extract_main_blocks(content, final_url)
    fields = extract_form_fields(content)

    lines = _page_meta_lines(url, final_url, page_number)
    lines.append("")
    if blocks:
        lines.extend(["### 區塊標題、表格與清單", *blocks, ""])
    if fields:
        lines.extend(["### 表單欄位設定", "", *fields_to_markdown(fields), ""])
    if not blocks and not fields:
        lines.extend(["（主內容區沒有可整理的標題、表格、清單或表單欄位）", ""])
    return _finish_markdown(lines)


def list_file_header(topic: str, list_url: str) -> str:
    """主題檔開頭說明。"""
    return (
        f"# 後台列表：{topic}\n\n"
        f"- 列表網址：{list_url}\n"
        "- 產生方式：scripts/admin_explore.py --lists（唯讀，只讀列表頁與分頁，不點進單一項目）\n"
        "- email、電話、API 金鑰、secret、token 已遮蔽為 ***\n\n"
    )


def write_list_page(output_dir: Path, list_url: str, page_number: int, section: str, header: str | None = None) -> Path:
    """寫入主題檔：第 1 頁重寫整個檔案（header 沒給時用 list_file_header），之後的分頁接在同一檔案後面。"""
    topic = list_topic_name(list_url)
    path = output_dir / f"{topic}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if page_number == 1 or not path.is_file():
        head = header if header is not None else list_file_header(topic, list_url)
        path.write_text(mask_sensitive(head) + section, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + section)
    return path


# 把表單欄位目前的值（JS 設定的 property）同步到 HTML 屬性，page.content() 才看得到。
# 只改瀏覽器裡的 DOM 屬性，不送出表單、不觸發事件、不發出任何請求；密碼與隱藏欄位不處理。
SYNC_FORM_VALUES_JS = """() => {
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (['password', 'hidden', 'file'].includes(type)) continue;
    if (el.tagName === 'SELECT') {
      for (const option of el.options) {
        if (option.selected) option.setAttribute('selected', 'selected'); else option.removeAttribute('selected');
      }
    } else if (el.tagName === 'TEXTAREA') {
      el.textContent = el.value;
    } else if (type === 'checkbox' || type === 'radio') {
      if (el.checked) el.setAttribute('checked', 'checked'); else el.removeAttribute('checked');
    } else {
      el.setAttribute('value', el.value);
    }
  }
}"""


def sync_form_values(page: Any) -> None:
    """讀 HTML 前，把表單欄位目前的值寫回屬性（分頁物件沒有 evaluate 時略過）。"""
    if hasattr(page, "evaluate"):
        page.evaluate(SYNC_FORM_VALUES_JS)


# ---------------------------------------------------------------------------
# --dynamic 模式：等待 JS 動態內容、內嵌 JSON、被動收集的 GET JSON
# ---------------------------------------------------------------------------


def wait_for_dynamic_content(page: Any) -> None:
    """讀 HTML 前等待前端 JS 動態內容載入完成，最後同步表單欄位值。

    依序：等待網路閒置（networkidle）→ 等待主內容區的動態項目出現 → 等待渲染穩定。
    每一步逾時或失敗都只顯示例外類型並繼續，不中斷讀取。只等待，不點擊、不發出請求。
    """
    steps: tuple[tuple[str, str, tuple[Any, ...], dict[str, Any]], ...] = (
        ("等待網路閒置", "wait_for_load_state", ("networkidle",), {"timeout": NETWORK_IDLE_TIMEOUT_MS}),
        (
            "等待動態項目出現",
            "wait_for_selector",
            (DYNAMIC_CONTENT_SELECTOR,),
            {"state": "attached", "timeout": DYNAMIC_SELECTOR_TIMEOUT_MS},
        ),
        ("等待渲染穩定", "wait_for_timeout", (RENDER_SETTLE_MS,), {}),
    )
    for label, method, args, kwargs in steps:
        action = getattr(page, method, None)
        if action is None:
            continue
        try:
            action(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 只顯示例外類型
            say(f"{label}逾時或失敗（{type(exc).__name__}），繼續讀取")
    sync_form_values(page)


@dataclass(frozen=True)
class CapturedJson:
    """被動監聽到的一筆同網域 GET JSON 回應（只在記憶體中，不存檔）。"""

    url: str
    data: Any


class JsonResponseRecorder:
    """page.on("response", ...) 用的被動監聽器：只收同網域、GET、2xx、JSON 的回應。

    只讀取瀏覽器已經收到的回應內容，不發出任何額外請求；不讀取、不記錄任何 cookie。
    事件處理時只做篩選，回應內容在 drain() 時才讀（離開事件處理函式後再讀，不阻塞瀏覽器）。
    """

    def __init__(self) -> None:
        """建立監聽器。"""
        self._pending: list[Any] = []

    def handle(self, response: Any) -> None:
        """篩選一個回應：符合條件就暫存，等 drain() 讀內容。"""
        try:
            method = str(getattr(response.request, "method", "") or "").upper()
            url = clean_url(str(response.url or ""))
            status = int(response.status)
            content_type = str((response.headers or {}).get("content-type", "")).lower()
        except Exception:  # noqa: BLE001
            return
        if method != "GET" or not 200 <= status < 300 or "json" not in content_type:
            return
        if not is_admin_url(url) or is_sensitive(url):
            return
        if len(self._pending) < MAX_JSON_RESPONSES_PER_PAGE:
            self._pending.append(response)

    def drain(self) -> list[CapturedJson]:
        """讀出暫存回應的 JSON 內容並清空暫存；讀不到或不是 JSON 的略過。"""
        pending, self._pending = self._pending, []
        captured: list[CapturedJson] = []
        for response in pending:
            try:
                body = response.body()
                if len(body) > MAX_JSON_BODY_BYTES:
                    continue
                text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
                data = json.loads(text)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(data, (dict, list)) and data:
                captured.append(CapturedJson(clean_url(str(response.url)), data))
        return captured


# script 內 JSON 的可能起點：= ( : , 後面接 { 或 [
SCRIPT_JSON_START_RE = re.compile(r"[=(:,]\s*(?=[\[{])")


def _json_in_script(text: str) -> list[Any]:
    """從一般 script 文字中找出合法的 JSON 物件或陣列（例如 window.__DATA__ = {...};）。"""
    decoder = json.JSONDecoder()
    results: list[Any] = []
    position = 0
    attempts = 0
    for match in SCRIPT_JSON_START_RE.finditer(text):
        start = match.end()
        if start < position:
            continue
        attempts += 1
        if attempts > MAX_SCRIPT_JSON_ATTEMPTS:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, (dict, list)) and value:
            results.append(value)
            position = end
    return results


def extract_embedded_json(html: str) -> list[Any]:
    """解析 HTML 裡內嵌的 JSON：data-react-props 等 data-* 屬性、JSON 型別的 script 與 script 內的 JSON。"""
    soup = BeautifulSoup(html, "html.parser")
    found: list[Any] = []
    for tag in soup.find_all(True):
        for name, value in tag.attrs.items():
            if not str(name).startswith("data-") or not isinstance(value, str):
                continue
            text = value.strip()
            if text[:1] not in ("{", "[") or len(text) > MAX_EMBEDDED_JSON_CHARS:
                continue
            try:
                found.append(json.loads(text))
            except ValueError:
                continue
    for script in soup.find_all("script"):
        text = script.string if isinstance(script.string, str) else script.get_text()
        if not text or len(text) > MAX_EMBEDDED_JSON_CHARS:
            continue
        if "json" in str(script.get("type") or "").lower():
            try:
                found.append(json.loads(text))
            except ValueError:
                pass
            continue
        found.extend(_json_in_script(text))
    return [data for data in found if isinstance(data, (dict, list)) and data]


def _json_str(data: dict[str, Any], keys: Sequence[str]) -> str:
    """依序找第一個非空字串欄位。"""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def _url_path(url: str) -> str:
    """網址的路徑部分（比對重複用）。"""
    return urlsplit(url.strip()).path.rstrip("/") if url else ""


def _front_href(href: Any) -> str:
    """前台連結原樣回傳；#、javascript:、mailto:、tel: 與後台（/admin）連結回傳空字串。"""
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:", "tel:")):
        return ""
    parts = urlsplit(href)
    if parts.path.startswith("/admin") and (not parts.netloc or parts.netloc.lower() == ADMIN_HOST):
        return ""
    return href


def _field_key(tag: Tag) -> str:
    """欄位的 name、id、class、placeholder 合併成小寫字串（判斷欄位用途）。"""
    parts = [str(tag.get("name") or ""), str(tag.get("id") or ""), str(tag.get("placeholder") or "")]
    parts.extend(str(c) for c in tag.get("class") or [])
    return " ".join(parts).lower()


def _outside(tag: Any, excluded: Sequence[Tag]) -> bool:
    """tag 不是 excluded 裡的任何元素，也不在它們裡面。"""
    return not any(tag is ex or _is_inside(tag, ex) for ex in excluded)


def _own_text(element: Tag, excluded: Sequence[Tag]) -> str:
    """元素的文字，不含 excluded 元素（例如子選單）與按鈕、下拉選項、script 的文字。"""
    parts: list[str] = []
    for string in element.find_all(string=True):
        if isinstance(string, Comment) or not _outside(string, excluded):
            continue
        if string.find_parent(["button", "select", "option", "script", "style", "template"]) is not None:
            continue
        parts.append(str(string))
    return _clean_text(" ".join(parts))


# ---------------------------------------------------------------------------
# menus：選單樹
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    """選單中的一個項目（level 從 1 開始）。"""

    level: int
    title: str
    url: str


@dataclass(frozen=True)
class MenuGroup:
    """一個選單（例如主選單、頁尾選單）與它底下依序排列的項目。"""

    name: str
    source: str
    items: tuple[MenuItem, ...]


MENU_TITLE_KEYS = ("title", "name", "label", "text", "display_name")
MENU_URL_KEYS = ("url", "href", "path", "link", "link_url", "target_url", "address")
MENU_CHILD_KEYS = (
    "children",
    "items",
    "links",
    "menu_items",
    "sub_menus",
    "submenus",
    "sub_items",
    "subitems",
    "child_links",
    "nodes",
)
# DOM：項目名稱元素的 class 線索（包含即可）
MENU_TITLE_CLASS_HINTS = ("dd-handle", "dd-content", "title", "name")
URL_FIELD_HINTS = ("url", "href", "path")
TITLE_FIELD_HINTS = ("title", "name", "label")
LINK_DATA_ATTRS = ("data-url", "data-href", "data-link", "data-path", "data-link-url")
GROUP_NAME_ATTRS = ("data-menu-title", "data-menu-name", "data-title", "data-name", "aria-label")
TREE_NODE_TOKENS = frozenset({"tree-node", "tree-item", "treenode", "menu-item", "menu_item", "menu-link", "link-item"})
LEVEL_TOKEN_RE = re.compile(r"(?:level|depth|indent|lvl)[-_]?(\d+)")
INDENT_RE = re.compile(r"(?:padding|margin)-left\s*:\s*([\d.]+)")
PATH_TEXT_RE = re.compile(r"https?://[^\s<>\"'|]+|(?<![\w/])/[A-Za-z0-9_\-][^\s<>\"'|]*")
NO_MENU_MESSAGE = (
    "（沒有找到選單樹。可能是資料由 POST 請求載入而被唯讀攔截器擋下，"
    "請查看 explore.log 中「已擋下非 GET 請求」的紀錄）"
)


def _json_url(data: dict[str, Any]) -> str:
    """選單項目的連結：url、href、path、link…；值是物件時再往裡面找一層。"""
    for key in MENU_URL_KEYS:
        value = data.get(key)
        if isinstance(value, dict):
            value = _json_str(value, MENU_URL_KEYS)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _json_children(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """子項目清單（children、items、links…，必須是非空的物件陣列）。"""
    for key in MENU_CHILD_KEYS:
        value = data.get(key)
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            return value
    return None


def _json_has_url(nodes: Sequence[Any], depth: int) -> bool:
    """這些節點（含子孫）有沒有任何連結。"""
    if depth > MAX_JSON_DEPTH:
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _json_url(node):
            return True
        children = _json_children(node)
        if children and _json_has_url(children, depth + 1):
            return True
    return False


def _json_looks_like_items(nodes: list[Any]) -> bool:
    """陣列是否像選單項目：全是物件、至少一個有連結、過半有名稱或連結。"""
    if not nodes or not all(isinstance(n, dict) for n in nodes):
        return False
    if not any(_json_url(n) for n in nodes):
        return False
    labelled = sum(1 for n in nodes if _json_str(n, MENU_TITLE_KEYS) or _json_url(n))
    return labelled * 2 >= len(nodes)


def _json_menu_items(nodes: Sequence[Any], level: int, depth: int) -> list[MenuItem]:
    """把 JSON 選單節點（含子項目）攤平成依序排列、帶層級的項目。"""
    items: list[MenuItem] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        title, url = _json_str(node, MENU_TITLE_KEYS), _json_url(node)
        child_level = level
        if title or url:
            items.append(MenuItem(level, title, url))
            child_level = level + 1
        children = _json_children(node)
        if children and depth < MAX_JSON_DEPTH:
            items.extend(_json_menu_items(children, child_level, depth + 1))
    return items


def _json_group_name(hint: str) -> str:
    """JSON 選單沒有名稱時，用欄位名稱標示來源。"""
    if not hint:
        return "未命名選單"
    return f"JSON 欄位：{hint}" if hint.isascii() else hint


def menu_groups_from_json(data: Any, source: str) -> list[MenuGroup]:
    """從 JSON（data-react-props、script JSON 或 GET 回應）找出所有選單樹。

    有名稱與子項目清單、本身沒有連結的物件視為一個選單群組；
    直接是項目陣列的，以所在欄位名稱（或上層物件的名稱）當群組名稱。
    """
    groups: list[MenuGroup] = []

    def walk(node: Any, hint: str, depth: int) -> None:
        """遞迴尋找選單。"""
        if depth > MAX_JSON_DEPTH:
            return
        if isinstance(node, dict):
            children = _json_children(node)
            if children is not None and not _json_url(node) and _json_has_url(children, 0):
                name = _json_str(node, MENU_TITLE_KEYS) or _json_group_name(hint)
                groups.append(MenuGroup(name, source, tuple(_json_menu_items(children, 1, 0))))
                return
            title = _json_str(node, MENU_TITLE_KEYS)
            for key, value in node.items():
                walk(value, title if title and isinstance(value, list) else str(key), depth + 1)
        elif isinstance(node, list):
            if _json_looks_like_items(node):
                groups.append(MenuGroup(_json_group_name(hint), source, tuple(_json_menu_items(node, 1, 0))))
                return
            for value in node:
                walk(value, hint, depth + 1)

    walk(data, "", 0)
    return groups


def _is_dd_list(tag: Any) -> bool:
    """是否為 nestable 的 .dd-list。"""
    return isinstance(tag, Tag) and "dd-list" in _tokens(tag)


def _is_dd_item(tag: Any) -> bool:
    """是否為 nestable 的 .dd-item。"""
    return isinstance(tag, Tag) and "dd-item" in _tokens(tag)


def _is_plain_list(tag: Any) -> bool:
    """是否為 <ul>/<ol>。"""
    return isinstance(tag, Tag) and tag.name in ("ul", "ol")


def _is_li(tag: Any) -> bool:
    """是否為 <li>。"""
    return isinstance(tag, Tag) and tag.name == "li"


def _is_tree_node(tag: Any) -> bool:
    """是否為樹狀節點：有 aria-level／data-level／data-depth、role=treeitem，或 class 為 tree-node、menu-item 等。"""
    if not isinstance(tag, Tag) or tag.name in ("ul", "ol", "table"):
        return False
    role = str(tag.get("role") or "").lower()
    if role == "heading":
        return False
    if role == "treeitem" or any(tag.has_attr(attr) for attr in ("aria-level", "data-level", "data-depth")):
        return True
    return bool(_tokens(tag) & TREE_NODE_TOKENS)


def _link_from_attrs(tag: Tag) -> str:
    """data-url、data-href 等屬性裡的連結。"""
    for attr in LINK_DATA_ATTRS:
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_title_field(tag: Tag) -> bool:
    """欄位是否是名稱（title、name、label，且不是網址欄位）。"""
    key = _field_key(tag)
    return any(h in key for h in TITLE_FIELD_HINTS) and not any(h in key for h in URL_FIELD_HINTS)


def _is_url_field(tag: Tag) -> bool:
    """欄位是否是連結網址（url、href、path，或含 link 但不是名稱欄位）。"""
    key = _field_key(tag)
    return any(h in key for h in URL_FIELD_HINTS) or ("link" in key and not _is_title_field(tag))


def _dom_item(node: Tag, nested: Sequence[Tag]) -> tuple[str, str]:
    """一個 DOM 選單節點的名稱與連結（不含子選單的內容）。"""
    own = [t for t in node.find_all(True) if _outside(t, nested)]
    title = ""
    for tag in own:
        if tag.name in ("input", "select", "textarea", "button"):
            continue
        if any(hint in token for token in _tokens(tag) for hint in MENU_TITLE_CLASS_HINTS):
            title = _own_text(tag, nested)
            if title:
                break
    if not title:
        for tag in own:
            if tag.name == "input" and _is_title_field(tag) and str(tag.get("value") or "").strip():
                title = _clean_text(str(tag.get("value")))
                break
    if not title:
        for tag in own:
            if tag.name == "a":
                title = _own_text(tag, nested)
                if title:
                    break
    if not title:
        title = _own_text(node, nested)

    url = _link_from_attrs(node)
    if not url:
        for tag in own:
            url = _link_from_attrs(tag)
            if not url and tag.name == "a":
                url = _front_href(tag.get("href"))
            if not url and tag.name == "input" and _is_url_field(tag):
                url = str(tag.get("value") or "").strip()
            if url:
                break
    if not url:
        match = PATH_TEXT_RE.search(_own_text(node, nested))
        if match and not match.group(0).startswith("/admin"):
            url = match.group(0)
    return title, url


def _tree_items(root: Tag, level: int, is_list: Callable[[Any], bool], is_item: Callable[[Any], bool]) -> list[MenuItem]:
    """把巢狀清單（ul/ol/li 或 .dd-list/.dd-item）攤平成依序排列、帶層級的項目。"""
    items: list[MenuItem] = []
    for item in root.find_all(is_item):
        if item.find_parent(is_list) is not root:
            continue
        nested = [sub for sub in item.find_all(is_list) if sub.find_parent(is_item) is item]
        title, url = _dom_item(item, nested)
        child_level = level
        if title or url:
            items.append(MenuItem(level, title, url))
            child_level = level + 1
        for sub in nested:
            items.extend(_tree_items(sub, child_level, is_list, is_item))
    return items


def _dom_group_name(element: Tag, skip: Callable[[Any], bool] | None = None) -> str:
    """DOM 選單的群組名稱：自己或上層的 data-menu-title／aria-label 等屬性，否則用前面最近的區塊標題。"""
    candidates = [element, *list(element.parents)[:6]]
    for tag in candidates:
        if not isinstance(tag, Tag) or (skip is not None and skip(tag)):
            continue
        for attr in GROUP_NAME_ATTRS:
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                return _clean_text(value)
    title = element.find_previous(lambda t: isinstance(t, Tag) and _is_title(t))
    if isinstance(title, Tag):
        text = _clean_text(title.get_text(" "))
        if text and len(text) <= MAX_TITLE_CHARS:
            return text
    return ""


def _explicit_level(tag: Tag) -> int | None:
    """節點明確標示的層級：aria-level、data-level、data-depth 或 class 的 level-2、depth-1 等。"""
    for attr in ("aria-level", "data-level", "data-depth"):
        value = str(tag.get(attr) or "").strip()
        if value.isdigit():
            return int(value)
    for token in _tokens(tag):
        match = LEVEL_TOKEN_RE.fullmatch(token)
        if match:
            return int(match.group(1))
    return None


def _indent(tag: Tag) -> float:
    """style 裡的 padding-left／margin-left 數值（沒有時為 0）。"""
    match = INDENT_RE.search(str(tag.get("style") or ""))
    return float(match.group(1)) if match else 0.0


def _tree_node_items(nodes: Sequence[Tag]) -> list[MenuItem]:
    """把一組樹狀節點（縮排 div、treeitem、.tree-node 等）轉成帶層級的項目。

    層級優先用明確標示；沒有時用節點的巢狀深度；都是同一層時改用縮排大小排序。
    最後把最小層級調整成第 1 層。
    """
    node_ids = {id(n) for n in nodes}
    explicit = [_explicit_level(n) for n in nodes]
    levels: list[int] = []
    for node, level in zip(nodes, explicit):
        if level is None:
            level = 1 + sum(1 for parent in node.parents if id(parent) in node_ids)
        levels.append(level)
    if all(level is None for level in explicit) and len(set(levels)) == 1:
        indents = sorted({_indent(n) for n in nodes})
        if len(indents) > 1:
            levels = [indents.index(_indent(n)) + 1 for n in nodes]
    shift = min(levels) - 1 if levels else 0

    items: list[MenuItem] = []
    for node, level in zip(nodes, levels):
        nested = [d for d in node.find_all(True) if id(d) in node_ids]
        title, url = _dom_item(node, nested)
        if title or url:
            items.append(MenuItem(max(1, level - shift), title, url))
    return items


def _table_header_and_rows(table: Tag) -> tuple[list[str], list[list[Tag]]]:
    """表格的標題列文字與內容列儲存格（不含巢狀表格）。"""
    headers: list[str] = []
    body: list[list[Tag]] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if not headers and not body and (tr.find_parent("thead") is not None or all(c.name == "th" for c in cells)):
            headers = [_clean_text(c.get_text(" ")) for c in cells]
            continue
        body.append(cells)
    return headers, body


def _find_column(headers: Sequence[str], words: Sequence[str], avoid: Sequence[str] = ()) -> int | None:
    """找標題含 words 任一字、且不含 avoid 任一字的第一個欄位。"""
    for index, header in enumerate(headers):
        lowered = header.lower()
        if any(w in lowered for w in words) and not any(a in lowered for a in avoid):
            return index
    return None


def _cell_link(cell: Tag) -> str:
    """儲存格裡的前台連結：<a href>、網址欄位的值、data-url 或文字中的路徑。"""
    for tag in [cell, *cell.find_all(True)]:
        url = _link_from_attrs(tag)
        if not url and tag.name == "a":
            url = _front_href(tag.get("href"))
        if not url and tag.name == "input" and _is_url_field(tag):
            url = str(tag.get("value") or "").strip()
        if url:
            return url
    match = PATH_TEXT_RE.search(_own_text(cell, ()))
    return match.group(0) if match and not match.group(0).startswith("/admin") else ""


def _menu_items_from_table(table: Tag) -> list[MenuItem]:
    """標題列有「名稱」與「連結／網址」欄的表格，每列是一個選單項目（有「層級」欄時照用）。"""
    headers, rows = _table_header_and_rows(table)
    url_col = _find_column(headers, ("連結", "網址", "路徑", "url", "link", "href", "path"), ("名稱", "標題", "title", "name"))
    title_col = _find_column(headers, ("名稱", "標題", "項目", "title", "name"), ("網址", "url", "href"))
    if url_col is None or title_col is None:
        return []
    level_col = _find_column(headers, ("層級", "level", "depth"))
    items: list[MenuItem] = []
    for cells in rows:
        if max(url_col, title_col) >= len(cells):
            continue
        title = _own_text(cells[title_col], ())
        url = _cell_link(cells[url_col])
        level = 1
        if level_col is not None and level_col < len(cells):
            digits = re.search(r"\d+", cells[level_col].get_text(" "))
            level = int(digits.group(0)) if digits else 1
        if title or url:
            items.append(MenuItem(max(1, level), title, url))
    return items


def menu_groups_from_dom(content: BeautifulSoup) -> list[MenuGroup]:
    """從渲染後的主內容區找出所有選單樹（依出現順序）。

    依序處理：.dd-list/.dd-item（nestable）、有名稱與連結欄的表格、樹狀節點
    （aria-level、data-level、.tree-node、縮排 div 等），最後是一般巢狀 ul/ol/li。
    已處理過的元素不重複處理；分頁清單略過。
    """
    order = {id(tag): index for index, tag in enumerate(content.find_all(True))}
    found: list[tuple[int, str, list[MenuItem]]] = []
    consumed: set[int] = set()

    def consume(tag: Tag) -> None:
        """標記元素與其子孫已處理。"""
        consumed.add(id(tag))
        consumed.update(id(t) for t in tag.find_all(True))

    for root in content.find_all(_is_dd_list):
        if id(root) in consumed or root.find_parent(_is_dd_list) is not None:
            continue
        found.append((order[id(root)], _dom_group_name(root), _tree_items(root, 1, _is_dd_list, _is_dd_item)))
        consume(root)

    for table in content.find_all("table"):
        if id(table) in consumed:
            continue
        table_items = _menu_items_from_table(table)
        if table_items:
            found.append((order[id(table)], _dom_group_name(table), table_items))
            consume(table)

    nodes = [tag for tag in content.find_all(_is_tree_node) if id(tag) not in consumed]
    by_name: dict[str, list[Tag]] = {}
    for node in nodes:
        by_name.setdefault(_dom_group_name(node, skip=_is_tree_node), []).append(node)
    for name, group_nodes in by_name.items():
        found.append((order[id(group_nodes[0])], name, _tree_node_items(group_nodes)))
        for node in group_nodes:
            consume(node)

    for root in content.find_all(_is_plain_list):
        if id(root) in consumed or root.find_parent(_is_plain_list) is not None or "pagination" in _tokens(root):
            continue
        if any(id(t) in consumed for t in root.find_all(True)):
            continue
        found.append((order[id(root)], _dom_group_name(root), _tree_items(root, 1, _is_plain_list, _is_li)))
        consume(root)

    found.sort(key=lambda entry: entry[0])
    return [
        MenuGroup(name or f"選單 {number}", "畫面 DOM", tuple(items))
        for number, (_, name, items) in enumerate(found, start=1)
    ]


def dedupe_menu_groups(groups: Iterable[MenuGroup]) -> list[MenuGroup]:
    """去掉沒有任何連結的群組，以及項目完全相同的重複群組（保留先出現的）。"""
    seen: set[tuple[MenuItem, ...]] = set()
    result: list[MenuGroup] = []
    for group in groups:
        if not group.items or not any(item.url for item in group.items) or group.items in seen:
            continue
        seen.add(group.items)
        result.append(group)
    return result


def extract_menu_groups(html: str, captured: Sequence[CapturedJson] = ()) -> tuple[list[MenuGroup], dict[str, int]]:
    """整合渲染後 DOM、頁面內嵌 JSON 與 GET JSON 回應的選單樹；回傳 (去重後的群組, 各來源群組數)。"""
    content = _main_content_soup(html)
    dom_groups = menu_groups_from_dom(content)
    embedded_groups = [g for data in extract_embedded_json(html) for g in menu_groups_from_json(data, "頁面內嵌 JSON")]
    xhr_groups = [g for c in captured for g in menu_groups_from_json(c.data, f"GET JSON {urlsplit(c.url).path}")]
    counts = {"畫面 DOM": len(dom_groups), "內嵌 JSON": len(embedded_groups), "GET JSON": len(xhr_groups)}
    return dedupe_menu_groups([*dom_groups, *embedded_groups, *xhr_groups]), counts


def _md_cell(text: str) -> str:
    """Markdown 表格儲存格：跳脫 |、去掉換行。"""
    return _clean_text(text).replace("|", "\\|")


def menu_tree_markdown(groups: Sequence[MenuGroup]) -> list[str]:
    """選單樹的階層縮排清單：每個群組一個小標題，項目依層級縮排。"""
    lines: list[str] = []
    for group in groups:
        lines.extend(["", f"#### {group.name}（來源：{group.source}，共 {len(group.items)} 個項目）", ""])
        for item in group.items:
            indent = "  " * (item.level - 1)
            lines.append(f"{indent}- {item.title or '（無名稱）'} → {item.url or '（無連結）'}")
    return lines


def menu_table_markdown(groups: Sequence[MenuGroup]) -> list[str]:
    """選單項目表（選單群組 | 層級 | 項目名稱 | 連結網址）。"""
    lines = ["| 選單群組 | 層級 | 項目名稱 | 連結網址 |", "| --- | --- | --- | --- |"]
    for group in groups:
        for item in group.items:
            lines.append(
                f"| {_md_cell(group.name)} | 第 {item.level} 層 | {_md_cell(item.title)} | {_md_cell(item.url)} |"
            )
    return lines


def _captured_lines(captured: Sequence[CapturedJson]) -> list[str]:
    """列出被動收集到的 GET JSON 回應路徑（不列 query，避免夾帶 token）。"""
    lines = [f"- 被動收集到的同網域 GET JSON 回應：{len(captured)} 筆"]
    lines.extend(f"  - {urlsplit(c.url).path}" for c in captured)
    return lines


def _other_content_lines(content: BeautifulSoup, base_url: str) -> list[str]:
    """主內容區其他內容（標題、段落、表格、清單與表單欄位），供對照。"""
    blocks = extract_main_blocks(content, base_url)
    fields = extract_form_fields(content)
    lines: list[str] = []
    if blocks:
        lines.extend(["### 主內容區其他內容（標題、表格與清單）", *blocks, ""])
    if fields:
        lines.extend(["### 表單欄位設定", "", *fields_to_markdown(fields), ""])
    return lines


def render_menus_page(
    html: str, url: str, final_url: str, page_number: int, captured: Sequence[CapturedJson] = ()
) -> tuple[str, int]:
    """把 menus 頁整理成 Markdown（選單樹狀清單＋選單項目表），回傳 (段落, 選單群組數)。"""
    groups, counts = extract_menu_groups(html, captured)
    source_text = "、".join(f"{name} {count}" for name, count in counts.items())
    lines = _page_meta_lines(url, final_url, page_number)
    lines.extend(_captured_lines(captured))
    lines.append(f"- 選單群組：共 {len(groups)} 個（找到 {source_text}；已去除重複與沒有連結的群組）")
    lines.extend(["", "### 選單樹狀結構"])
    if groups:
        lines.extend(menu_tree_markdown(groups))
        lines.extend(["", "### 選單項目表", "", *menu_table_markdown(groups), ""])
    else:
        lines.extend(["", NO_MENU_MESSAGE, ""])
    lines.extend(_other_content_lines(_main_content_soup(html), final_url))
    return _finish_markdown(lines), len(groups)


# ---------------------------------------------------------------------------
# custom_pages_index：自訂頁面列表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomPage:
    """一個自訂頁面。"""

    title: str
    url: str
    status: str
    extra: str = ""


PAGE_PATH_RE = re.compile(r"(?:https?://[^\s<>\"'|]+)?/pages/[^\s<>\"'|]+")
PAGE_TITLE_HEADERS = ("標題", "名稱", "頁面", "title", "name")
PAGE_URL_HEADERS = ("網址", "連結", "路徑", "url", "link", "handle", "path", "slug")
PAGE_STATUS_HEADERS = ("狀態", "發佈", "發布", "顯示", "隱藏", "可見", "上架", "公開", "status", "visible", "publish")
ACTION_HEADERS = ("操作", "動作", "action")
# 「未發佈」含「發佈」，所以隱藏類的字要先比對
HIDDEN_WORDS = ("未發佈", "未發布", "不發佈", "不顯示", "隱藏", "草稿", "下架", "unpublished", "hidden", "draft")
SHOWN_WORDS = ("已發佈", "已發布", "發佈", "發布", "顯示", "公開", "上架", "published", "visible")
STATUS_CLASS_HINTS = ("status", "badge", "state")
ROW_CLASS_HINTS = ("row", "item", "card")
PAGE_JSON_TITLE_KEYS = ("title", "name", "page_title")
PAGE_JSON_URL_KEYS = ("url", "full_url", "page_url", "public_url", "href", "path", "link")
PAGE_SHOWN_KEYS = (
    "published",
    "is_published",
    "visible",
    "is_visible",
    "display",
    "is_display",
    "show",
    "is_show",
    "enabled",
    "is_enabled",
    "active",
    "is_active",
    "online",
)
PAGE_HIDDEN_KEYS = ("hidden", "is_hidden", "hide", "is_hide")
PAGE_STATUS_KEYS = ("status", "state", "publish_status", "visibility", "display_status")
PAGE_STATUS_WORDS = {
    "published": "發佈",
    "publish": "發佈",
    "visible": "發佈",
    "active": "發佈",
    "online": "發佈",
    "show": "發佈",
    "hidden": "隱藏",
    "hide": "隱藏",
    "unpublished": "隱藏",
    "inactive": "隱藏",
    "offline": "隱藏",
    "draft": "隱藏（草稿）",
}
PAGE_EXTRA_KEYS = ("id", "handle", "template", "template_suffix", "author", "created_at", "updated_at", "published_at")


def _status_from_element(element: Tag, exclude: Sequence[Tag] = ()) -> str:
    """從 DOM 判斷發佈／隱藏狀態：發佈或顯示類的勾選開關、data-status 屬性、
    class 含 status／badge／label 的標記文字，最後才用文字關鍵字（不看按鈕與連結的文字）。
    """
    for field_tag in element.find_all("input"):
        if not _outside(field_tag, exclude) or _field_kind(field_tag) not in ("checkbox", "radio"):
            continue
        key = _field_key(field_tag)
        checked = field_tag.has_attr("checked")
        if "hidden" in key or "hide" in key:
            return "隱藏" if checked else "發佈"
        if any(w in key for w in ("publish", "visible", "show", "display", "status", "enable", "active")):
            return "發佈" if checked else "隱藏"
    for tag in [element, *element.find_all(True)]:
        if not _outside(tag, exclude) and tag is not element:
            continue
        for attr in ("data-status", "data-state", "data-published", "data-visible"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                raw = value.strip().lower()
                if raw in ("true", "false"):
                    return "發佈" if raw == "true" else "隱藏"
                return PAGE_STATUS_WORDS.get(raw, value.strip())
    for tag in element.find_all(True):
        if tag.name in ("button", "a", "input", "select", "option") or not _outside(tag, exclude):
            continue
        tokens = _tokens(tag)
        if any(h in token for token in tokens for h in STATUS_CLASS_HINTS) or any(
            token == "label" or token.startswith("label-") for token in tokens
        ):
            text = _clean_text(tag.get_text(" "))
            if text and len(text) <= 20:
                return text
    parts: list[str] = []
    for string in element.find_all(string=True):
        if isinstance(string, Comment) or not _outside(string, exclude):
            continue
        if string.find_parent(["button", "a", "option", "script", "style"]) is not None:
            continue
        parts.append(str(string))
    text = " ".join(parts).lower()
    for word in (*HIDDEN_WORDS, *SHOWN_WORDS):
        if word in text:
            return word
    return ""


def _first_page_link(element: Tag) -> str:
    """元素裡第一個 /pages/ 前台連結，沒有時找文字中的 /pages/ 路徑。"""
    for anchor in element.find_all("a", href=True):
        href = _front_href(anchor.get("href"))
        if "/pages/" in href:
            return href
    match = PAGE_PATH_RE.search(_own_text(element, ()))
    return match.group(0) if match else ""


def _custom_pages_from_table(table: Tag) -> list[CustomPage]:
    """標題列有「標題／名稱」欄的表格：每列一個自訂頁面（網址、狀態欄沒有時從整列推斷）。"""
    headers, rows = _table_header_and_rows(table)
    if not headers:
        return []
    status_col = _find_column(headers, PAGE_STATUS_HEADERS)
    url_col = _find_column(headers, PAGE_URL_HEADERS, PAGE_STATUS_HEADERS)
    title_col = _find_column(headers, PAGE_TITLE_HEADERS, PAGE_URL_HEADERS + PAGE_STATUS_HEADERS)
    if title_col is None:
        return []
    action_cols = {i for i, h in enumerate(headers) if any(w in h.lower() for w in ACTION_HEADERS)}

    pages: list[CustomPage] = []
    for cells in rows:
        row = cells[0].parent if isinstance(cells[0].parent, Tag) else cells[0]

        def cell(index: int | None) -> Tag | None:
            """取第 index 欄（沒有時 None）。"""
            return cells[index] if index is not None and index < len(cells) else None

        title_cell, url_cell, status_cell = cell(title_col), cell(url_col), cell(status_col)
        title = _own_text(title_cell, ()) if title_cell is not None else ""
        url = ""
        if url_cell is not None:
            url = _cell_link(url_cell) or _own_text(url_cell, ())
        if not url:
            url = _first_page_link(row)
        if status_cell is not None:
            status = _status_from_element(status_cell)
        else:
            excluded = [c for i, c in enumerate(cells) if i in action_cols or c is title_cell or c is url_cell]
            status = _status_from_element(row, excluded)
        extra = "；".join(
            f"{headers[i]}：{text}"
            for i, c in enumerate(cells)
            if i < len(headers)
            and i not in (title_col, url_col, status_col)
            and i not in action_cols
            and (text := _own_text(c, ()))
        )
        if title or url:
            pages.append(CustomPage(title, url, status, extra))
    return pages


def _row_container(marker: Tag) -> Tag:
    """連結所在的「一列」：tr、li、role=row，或 class 含 row／item／card 的元素（往上最多 8 層）。"""
    node: Tag = marker
    for _ in range(8):
        tokens = _tokens(node)
        if (
            node.name in ("tr", "li")
            or str(node.get("role") or "").lower() == "row"
            or any(token != "row" and any(h in token for h in ROW_CLASS_HINTS) for token in tokens)
        ):
            return node
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in ("[document]", "html", "body", "main"):
            break
        node = parent
    return marker.parent if isinstance(marker.parent, Tag) and marker.parent.name != "[document]" else marker


def _custom_page_from_row(row: Tag, marker: Tag, url: str) -> CustomPage:
    """從一列（React div 列、卡片、li…）取出標題、網址與狀態。"""
    title_tag = next(
        (
            t
            for t in row.find_all(True)
            if t.name not in ("input", "button", "select", "textarea")
            and any("title" in token or "name" in token for token in _tokens(t))
            and _clean_text(t.get_text(" "))
        ),
        None,
    )
    title = _clean_text(title_tag.get_text(" ")) if title_tag is not None else ""
    if not title:
        marker_text = _clean_text(marker.get_text(" "))
        if marker_text and not PAGE_PATH_RE.search(marker_text):
            title = marker_text
    if not title:
        for string in row.find_all(string=True):
            text = _clean_text(str(string))
            if isinstance(string, Comment) or not text or string.find_parent(["button", "script", "style"]) is not None:
                continue
            if PAGE_PATH_RE.search(text) or text.lower() in (*HIDDEN_WORDS, *SHOWN_WORDS):
                continue
            title = text
            break
    status = _status_from_element(row, [t for t in (title_tag, marker) if t is not None])
    return CustomPage(title, url, status)


def custom_pages_from_dom(content: BeautifulSoup) -> list[CustomPage]:
    """從渲染後的主內容區找自訂頁面：有標題欄的表格，以及含 /pages/ 前台連結或路徑文字的列（React div 列、卡片）。"""
    pages: list[CustomPage] = []
    consumed: set[int] = set()
    for table in content.find_all("table"):
        table_pages = _custom_pages_from_table(table)
        if table_pages:
            pages.extend(table_pages)
            consumed.add(id(table))
            consumed.update(id(t) for t in table.find_all(True))

    order = {id(tag): index for index, tag in enumerate(content.find_all(True))}
    markers: list[tuple[Tag, str]] = []
    for anchor in content.find_all("a", href=True):
        href = _front_href(anchor.get("href"))
        if href and "/pages/" in href:
            markers.append((anchor, href))
    for string in content.find_all(string=PAGE_PATH_RE):
        parent = string.parent
        if not isinstance(parent, Tag) or parent.name in ("script", "style") or parent.name == "a":
            continue
        if parent.find_parent("a") is not None:
            continue
        match = PAGE_PATH_RE.search(str(string))
        if match:
            markers.append((parent, match.group(0)))
    markers.sort(key=lambda m: order.get(id(m[0]), 0))

    seen_rows: set[int] = set()
    for marker, url in markers:
        if id(marker) in consumed:
            continue
        row = _row_container(marker)
        if id(row) in seen_rows:
            continue
        seen_rows.add(id(row))
        pages.append(_custom_page_from_row(row, marker, url))
    return pages


def _bool_like(value: Any) -> bool | None:
    """true/false、1/0 轉成布林；其他回傳 None。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _json_page_status(data: dict[str, Any]) -> str:
    """JSON 裡的發佈／隱藏狀態：published、visible、hidden、status、published_at 等欄位。"""
    for key in PAGE_SHOWN_KEYS:
        flag = _bool_like(data.get(key))
        if flag is not None:
            return "發佈" if flag else "隱藏"
    for key in PAGE_HIDDEN_KEYS:
        flag = _bool_like(data.get(key))
        if flag is not None:
            return "隱藏" if flag else "發佈"
    for key in PAGE_STATUS_KEYS:
        value = data.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            raw = str(value).strip()
            return PAGE_STATUS_WORDS.get(raw.lower(), raw)
    if "published_at" in data:
        value = data.get("published_at")
        return f"發佈（{value}）" if value else "未發佈"
    return ""


def _json_custom_page(data: dict[str, Any]) -> CustomPage | None:
    """把一個 JSON 物件轉成自訂頁面；沒有標題，或沒有網址、handle、狀態任何一項時回傳 None。"""
    title = _json_str(data, PAGE_JSON_TITLE_KEYS)
    if not title:
        return None
    url = _json_str(data, PAGE_JSON_URL_KEYS)
    handle = _json_str(data, ("handle", "slug"))
    if not url and handle:
        url = handle if "/" in handle else f"/pages/{handle}"
    status = _json_page_status(data)
    if not status and not handle and "/pages/" not in url:
        return None
    extra = "；".join(
        f"{key}={value}"
        for key in PAGE_EXTRA_KEYS
        if isinstance(value := data.get(key), (str, int, float)) and not isinstance(value, bool) and str(value).strip()
    )
    return CustomPage(title, url, status, extra)


def custom_pages_from_json(data: Any) -> list[CustomPage]:
    """從 JSON 找自訂頁面陣列（物件陣列、過半能轉成自訂頁面）。"""
    pages: list[CustomPage] = []

    def walk(node: Any, depth: int) -> None:
        """遞迴尋找。"""
        if depth > MAX_JSON_DEPTH:
            return
        if isinstance(node, list):
            if node and all(isinstance(n, dict) for n in node):
                valid = [p for p in (_json_custom_page(n) for n in node) if p is not None]
                if valid and len(valid) * 2 >= len(node):
                    pages.extend(valid)
                    return
            for value in node:
                walk(value, depth + 1)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, depth + 1)

    walk(data, 0)
    return pages


def merge_custom_pages(pages: Iterable[CustomPage]) -> list[CustomPage]:
    """合併重複的自訂頁面（網址路徑相同，或標題相同且其中一筆沒有網址），缺的欄位互相補上。"""
    merged: list[CustomPage] = []
    for page in pages:
        path = _url_path(page.url)
        index = next(
            (
                i
                for i, m in enumerate(merged)
                if (path and _url_path(m.url) == path) or (page.title and m.title == page.title and (not path or not m.url))
            ),
            None,
        )
        if index is None:
            merged.append(page)
            continue
        old = merged[index]
        merged[index] = CustomPage(
            old.title or page.title, old.url or page.url, old.status or page.status, old.extra or page.extra
        )
    return merged


def extract_custom_pages(html: str, captured: Sequence[CapturedJson] = ()) -> tuple[list[CustomPage], dict[str, int]]:
    """整合渲染後 DOM、頁面內嵌 JSON 與 GET JSON 回應的自訂頁面；回傳 (合併後的頁面, 各來源筆數)。"""
    dom_pages = custom_pages_from_dom(_main_content_soup(html))
    embedded_pages = [p for data in extract_embedded_json(html) for p in custom_pages_from_json(data)]
    xhr_pages = [p for c in captured for p in custom_pages_from_json(c.data)]
    counts = {"畫面 DOM": len(dom_pages), "內嵌 JSON": len(embedded_pages), "GET JSON": len(xhr_pages)}
    return merge_custom_pages([*dom_pages, *embedded_pages, *xhr_pages]), counts


def custom_pages_markdown(pages: Sequence[CustomPage]) -> list[str]:
    """自訂頁面表（標題 | 網址 | 狀態 | 其他資訊）。"""
    lines = ["| 標題 | 網址 | 狀態 | 其他資訊 |", "| --- | --- | --- | --- |"]
    for page in pages:
        lines.append(
            f"| {_md_cell(page.title)} | {_md_cell(page.url) or '（未取得）'} | "
            f"{_md_cell(page.status) or '（未取得）'} | {_md_cell(page.extra)} |"
        )
    return lines


def render_custom_pages_page(
    html: str, url: str, final_url: str, page_number: int, captured: Sequence[CapturedJson] = ()
) -> tuple[str, int]:
    """把 custom_pages_index 的一頁整理成 Markdown（自訂頁面表），回傳 (段落, 頁面數)。"""
    pages, counts = extract_custom_pages(html, captured)
    source_text = "、".join(f"{name} {count} 筆" for name, count in counts.items())
    lines = _page_meta_lines(url, final_url, page_number)
    lines.extend(_captured_lines(captured))
    lines.append(f"- 自訂頁面：共 {len(pages)} 個（找到 {source_text}；已合併重複）")
    lines.extend(["", "### 自訂頁面列表", ""])
    if pages:
        lines.extend([*custom_pages_markdown(pages), ""])
    else:
        lines.extend([NO_MENU_MESSAGE.replace("選單樹", "自訂頁面"), ""])
    lines.extend(_other_content_lines(_main_content_soup(html), final_url))
    return _finish_markdown(lines), len(pages)


def dynamic_list_url(url: str) -> str | None:
    """--dynamic 模式的網址屬於哪個主題（menus 或 custom_pages_index）；都不是回傳 None。"""
    return DYNAMIC_LIST_PATHS.get(strip_query(url))


def dynamic_pagination_links(html: str, page_url: str) -> list[str]:
    """自訂頁面的分頁連結：/admin/custom_pages_index?page=N 或 /admin/custom_pages?page=N（N≥2）。"""
    found: dict[str, None] = {}
    for list_url in (CUSTOM_PAGES_URL, CUSTOM_PAGES_ALT_URL):
        for link in pagination_links(html, page_url, list_url):
            found[link] = None
    return list(found)


def dynamic_file_header(topic: str, list_url: str) -> str:
    """--dynamic 模式主題檔開頭說明。"""
    title = {"menus": "選單設定", "custom_pages_index": "自訂頁面"}.get(topic, topic)
    return (
        f"# 後台{title}：{topic}\n\n"
        f"- 列表網址：{list_url}\n"
        "- 產生方式：scripts/admin_explore.py --dynamic（唯讀；等待 JS 動態載入後讀取畫面 DOM，"
        "並整合頁面內嵌 JSON 與被動收集的同網域 GET JSON 回應；不點進單一項目）\n"
        "- email、電話、API 金鑰、secret、token 已遮蔽為 ***\n\n"
    )


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
    on_page: Callable[[str, str, str], Iterable[str] | None],
    sleep: Callable[[float], None] = time.sleep,
    random_delay: Callable[[], float] = random_page_delay,
    max_pages: int = MAX_PAGES,
    before_content: Callable[[Any], None] | None = None,
) -> CrawlResult:
    """用同一個分頁依序讀取 urls，每讀完一頁存一次進度。

    on_page(原網址, 最終網址, HTML) 在頁面正常讀取後呼叫；可回傳要接著讀的網址
    （例如分頁連結），會排到佇列最後。before_content(page) 在讀 HTML 前呼叫。
    已讀過、非後台網域、敏感頁面會跳過；遇到停止條件立即結束，不重試。
    """
    pages_read = 0
    consecutive_404 = 0
    queue = [clean_url(u) for u in urls]
    queued = set(queue)
    index = 0

    def stop(reason: str, finished: bool = False) -> CrawlResult:
        """結束本次執行。"""
        return finish_run(CrawlResult(reason, pages_read, pages_read, finished), progress, progress_path)

    while index < len(queue):
        url = queue[index]
        index += 1
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

        if before_content is not None:
            try:
                before_content(page)
            except Exception as exc:  # noqa: BLE001
                say(f"讀取前準備（等待動態內容／同步表單欄位值）失敗（{type(exc).__name__}），改用目前的 HTML")
        try:
            html = str(page.content())
        except Exception as exc:  # noqa: BLE001
            return stop(f"讀取頁面內容失敗（{type(exc).__name__}）")
        if has_captcha(html):
            return stop("頁面出現驗證碼")

        consecutive_404 = 0
        extra = on_page(url, final_url, html)
        progress.visited_urls.append(url)
        progress.save(progress_path)
        for new_url in extra or ():
            new_url = clean_url(new_url)
            if new_url not in queued:
                queued.add(new_url)
                queue.append(new_url)

    if pages_read == 0:
        return stop("沒有待讀頁面（都已讀過）", finished=True)
    return stop("全部讀完", finished=True)


def _run_with_page(
    browser: Any,
    get_cookies: Callable[[list[str]], Any],
    progress: Progress,
    progress_path: Path,
    run: Callable[[Any], CrawlResult],
) -> CrawlResult:
    """取得並注入 cookie、開一個只放行 GET 的分頁，交給 run 讀頁面；結束時關閉 context。"""
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
        return run(page)
    finally:
        context.close()


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

    def save_menu(url: str, final_url: str, html: str) -> None:
        """解析左側選單並寫出 menu.csv。"""
        links = extract_menu_links(html, final_url)
        write_menu_csv(links, menu_path)
        say(
            f"左側選單共 {len(links)} 個連結，已寫入 {menu_path}"
            f"（排除敏感頁面後可供下一步讀取 {len(safe_queue(links))} 個）"
        )

    def run(page: Any) -> CrawlResult:
        """只讀首頁。"""
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

    return _run_with_page(browser, get_cookies, progress, progress_path, run)


# ---------------------------------------------------------------------------
# 第二步：讀 9 個列表頁
# ---------------------------------------------------------------------------


def explore_lists(
    browser: Any,
    get_cookies: Callable[[list[str]], Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sleep: Callable[[float], None] = time.sleep,
    random_delay: Callable[[], float] = random_page_delay,
    max_pages: int = MAX_LIST_PAGES,
    menu_csv: Path | None = None,
) -> CrawlResult:
    """注入 cookie，依序讀列表頁（含分頁），每個主題寫成 research/admin/<主題>.md。

    只讀列表頁本身與 page=N 分頁，不點進單一項目；本次最多 MAX_LIST_PAGES 頁。
    """
    progress_path = output_dir / "progress.json"
    progress = Progress.load(progress_path)
    targets = list_targets(menu_csv if menu_csv is not None else output_dir / "menu.csv")
    target_set = set(targets)

    def save_list(url: str, final_url: str, html: str) -> list[str]:
        """整理一個列表頁並寫入主題檔，回傳同一列表的下一批分頁網址。"""
        list_url = strip_query(url)
        page_number = list_page_number(url)
        if list_url not in target_set or page_number is None:
            say(f"不是指定的列表頁，不整理：{url}")
            return []
        section = render_list_page(html, url, final_url, page_number)
        path = write_list_page(output_dir, list_url, page_number, section)
        next_pages = pagination_links(html, final_url, list_url)
        say(f"已寫入 {path.name}（第 {page_number} 頁），發現 {len(next_pages)} 個分頁連結")
        return next_pages

    def run(page: Any) -> CrawlResult:
        """依序讀列表頁。"""
        return crawl(
            page,
            targets,
            progress,
            progress_path,
            on_page=save_list,
            sleep=sleep,
            random_delay=random_delay,
            max_pages=min(max_pages, MAX_LIST_PAGES),
            before_content=sync_form_values,
        )

    return _run_with_page(browser, get_cookies, progress, progress_path, run)


# ---------------------------------------------------------------------------
# 第三步：重新讀 menus 與 custom_pages_index（JS 動態載入）
# ---------------------------------------------------------------------------


def reset_dynamic_progress(progress: Progress) -> int:
    """把 menus、custom_pages_index（含 /admin/custom_pages）與其分頁從已讀與 404 紀錄移除，回傳移除筆數。"""
    before = len(progress.visited_urls) + len(progress.not_found_urls)
    progress.visited_urls = [u for u in progress.visited_urls if dynamic_list_url(u) is None]
    progress.not_found_urls = [u for u in progress.not_found_urls if dynamic_list_url(u) is None]
    return before - len(progress.visited_urls) - len(progress.not_found_urls)


def explore_dynamic(
    browser: Any,
    get_cookies: Callable[[list[str]], Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sleep: Callable[[float], None] = time.sleep,
    random_delay: Callable[[], float] = random_page_delay,
    max_pages: int = MAX_LIST_PAGES,
) -> CrawlResult:
    """重新只讀 menus 與 custom_pages_index：等待 JS 動態內容後，整合 DOM、內嵌 JSON 與 GET JSON。

    會先把這兩頁（與分頁）從 progress.json 的已讀紀錄移除，確保重新讀取；讀完照常存回。
    menus 寫成 menus.md（選單樹）；custom_pages_index 寫成 custom_pages_index.md（自訂頁面表），
    有 page=N 分頁時接著讀。本次最多 MAX_LIST_PAGES 頁；只放行 GET、被動監聽回應，不發額外請求。
    """
    progress_path = output_dir / "progress.json"
    progress = Progress.load(progress_path)
    removed = reset_dynamic_progress(progress)
    say(f"已從進度紀錄移除 {removed} 筆 menus／custom_pages_index 網址，重新讀取")
    recorder = JsonResponseRecorder()

    def save_dynamic(url: str, final_url: str, html: str) -> list[str]:
        """整理一頁並寫入主題檔；自訂頁面回傳下一批分頁網址。"""
        captured = recorder.drain()
        list_url = dynamic_list_url(url)
        page_number = list_page_number(url)
        if list_url is None or page_number is None:
            say(f"不是指定的動態載入頁，不整理：{url}")
            return []
        say(f"被動收集到 {len(captured)} 筆同網域 GET JSON 回應")
        header = dynamic_file_header(list_topic_name(list_url), list_url)
        if list_url == MENUS_URL:
            section, count = render_menus_page(html, url, final_url, page_number, captured)
            path = write_list_page(output_dir, list_url, page_number, section, header)
            say(f"已寫入 {path.name}（第 {page_number} 頁），選單群組 {count} 個")
            return []
        section, count = render_custom_pages_page(html, url, final_url, page_number, captured)
        path = write_list_page(output_dir, list_url, page_number, section, header)
        next_pages = dynamic_pagination_links(html, final_url)
        say(f"已寫入 {path.name}（第 {page_number} 頁），自訂頁面 {count} 個，發現 {len(next_pages)} 個分頁連結")
        return next_pages

    def run(page: Any) -> CrawlResult:
        """開頁前先註冊被動回應監聽，再依序讀兩頁（含自訂頁面分頁）。"""
        if hasattr(page, "on"):
            page.on("response", recorder.handle)
        return crawl(
            page,
            list(DYNAMIC_PAGE_URLS),
            progress,
            progress_path,
            on_page=save_dynamic,
            sleep=sleep,
            random_delay=random_delay,
            max_pages=min(max_pages, MAX_LIST_PAGES),
            before_content=wait_for_dynamic_content,
        )

    return _run_with_page(browser, get_cookies, progress, progress_path, run)


MODE_LABELS = {"menu": "左側選單", "lists": "列表頁", "dynamic": "動態載入頁（menus、custom_pages_index）"}


def run_mode(mode: str, browser: Any, get_cookies: Callable[[list[str]], Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> CrawlResult:
    """依模式執行：menu 讀左側選單，lists 讀列表頁，dynamic 重新讀 menus 與 custom_pages_index。"""
    if mode == "lists":
        return explore_lists(browser, get_cookies, output_dir)
    if mode == "dynamic":
        return explore_dynamic(browser, get_cookies, output_dir)
    return explore_admin(browser, get_cookies, output_dir)


def parse_args(argv: Sequence[str] | None = None) -> str:
    """解析命令列參數，回傳模式（menu、lists 或 dynamic）。"""
    parser = argparse.ArgumentParser(description="Cyberbiz 後台唯讀探索")
    parser.add_argument(
        "--mode",
        choices=("menu", "lists", "dynamic"),
        default="menu",
        help="menu：讀左側選單（預設）；lists：讀列表頁；dynamic：重新讀 menus 與 custom_pages_index",
    )
    shortcut = parser.add_mutually_exclusive_group()
    shortcut.add_argument("--lists", action="store_true", help="等同 --mode lists")
    shortcut.add_argument("--dynamic", action="store_true", help="等同 --mode dynamic")
    args = parser.parse_args(argv)
    if args.dynamic:
        return "dynamic"
    return "lists" if args.lists else str(args.mode)


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


def main(argv: Sequence[str] | None = None) -> int:
    """命令列進入點。任何錯誤都只顯示例外類型，避免訊息夾帶 cookie。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mode = parse_args(argv)
    setup_file_log(DEFAULT_OUTPUT_DIR / "explore.log")
    say(f"模式：{MODE_LABELS.get(mode, mode)}")
    try:
        get_cookies = load_get_cookies(xinchi_tools_path_from_env())
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                result = run_mode(mode, browser, get_cookies)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        say(f"程式中止：{type(exc).__name__}（為避免洩漏 cookie，不顯示詳細訊息）")
        return 1
    return 0 if result.finished else 1


if __name__ == "__main__":
    raise SystemExit(main())
