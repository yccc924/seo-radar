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


def _main_content_soup(html: str) -> BeautifulSoup:
    """取出主內容區的副本，並移除左側選單、頂部導覽列、script、style 等。"""
    soup = BeautifulSoup(html, "html.parser")
    container, fallback = find_main_container(soup)
    content = BeautifulSoup(str(container), "html.parser")
    root = next((child for child in content.children if isinstance(child, Tag)), None)

    def remove(tag: Tag) -> None:
        """移除元素（不會移除主內容區本身）。"""
        if tag is not root and not getattr(tag, "decomposed", False):
            tag.decompose()

    for tag in content.find_all(["script", "style", "noscript", "template", "svg", "aside"]):
        remove(tag)
    for tag in list(content.find_all(True)):
        if getattr(tag, "decomposed", False) or tag is root:
            continue
        if _container_score(tag) == 3 or _tokens(tag) & TOP_NAV_TOKENS:
            remove(tag)
    if fallback:
        for tag in content.find_all(["header", "nav"]):
            remove(tag)
        menu = find_menu_container(content)
        if menu is not None:
            remove(menu)
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


def render_list_page(html: str, url: str, final_url: str, page_number: int) -> str:
    """把一個列表頁整理成 Markdown 段落（已遮蔽敏感資料）。"""
    content = _main_content_soup(html)
    blocks = extract_main_blocks(content, final_url)
    fields = extract_form_fields(content)

    lines = [f"## 第 {page_number} 頁", "", f"- 網址：{url}"]
    if clean_url(final_url) != clean_url(url):
        lines.append(f"- 實際網址：{final_url}")
    lines.append(f"- 讀取時間：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    if blocks:
        lines.extend(["### 區塊標題、表格與清單", *blocks, ""])
    if fields:
        lines.extend(["### 表單欄位設定", "", *fields_to_markdown(fields), ""])
    if not blocks and not fields:
        lines.extend(["（主內容區沒有可整理的標題、表格、清單或表單欄位）", ""])
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return mask_sensitive(text) + "\n"


def list_file_header(topic: str, list_url: str) -> str:
    """主題檔開頭說明。"""
    return (
        f"# 後台列表：{topic}\n\n"
        f"- 列表網址：{list_url}\n"
        "- 產生方式：scripts/admin_explore.py --lists（唯讀，只讀列表頁與分頁，不點進單一項目）\n"
        "- email、電話、API 金鑰、secret、token 已遮蔽為 ***\n\n"
    )


def write_list_page(output_dir: Path, list_url: str, page_number: int, section: str) -> Path:
    """寫入主題檔：第 1 頁重寫整個檔案，之後的分頁接在同一檔案後面。"""
    topic = list_topic_name(list_url)
    path = output_dir / f"{topic}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if page_number == 1 or not path.is_file():
        path.write_text(mask_sensitive(list_file_header(topic, list_url)) + section, encoding="utf-8")
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
                say(f"同步表單欄位值失敗（{type(exc).__name__}），改用原始 HTML")
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


def run_mode(mode: str, browser: Any, get_cookies: Callable[[list[str]], Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> CrawlResult:
    """依模式執行：menu 讀左側選單，lists 讀列表頁。"""
    if mode == "lists":
        return explore_lists(browser, get_cookies, output_dir)
    return explore_admin(browser, get_cookies, output_dir)


def parse_args(argv: Sequence[str] | None = None) -> str:
    """解析命令列參數，回傳模式（menu 或 lists）。"""
    parser = argparse.ArgumentParser(description="Cyberbiz 後台唯讀探索")
    parser.add_argument("--mode", choices=("menu", "lists"), default="menu", help="menu：讀左側選單（預設）；lists：讀列表頁")
    parser.add_argument("--lists", action="store_true", help="等同 --mode lists")
    args = parser.parse_args(argv)
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
    say(f"模式：{'列表頁' if mode == 'lists' else '左側選單'}")
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
