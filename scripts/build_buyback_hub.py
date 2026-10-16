"""產生「各機型收購價格一覽」HTML 區塊（完全不連網）。

資料來源只有本機檔案：
- research/admin/custom_pages_index.md（後台自訂頁面列表，主要來源，含發佈／隱藏狀態）
- research/audit/quick_audit.csv（前台健檢結果，補上列表沒有的頁面）

篩出單機「二手收購價」頁面，依產品系列分組（由新到舊），輸出：
- research/output/buyback_hub.html：可直接貼入 Cyberbiz 自訂 HTML 區塊
- research/output/buyback_hub_check.csv：UTF-8 with BOM，給人工核對

用法：
    python scripts/build_buyback_hub.py
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = ROOT / "research" / "admin" / "custom_pages_index.md"
DEFAULT_AUDIT = ROOT / "research" / "audit" / "quick_audit.csv"
DEFAULT_OUTPUT_DIR = ROOT / "research" / "output"

HUB_HEADING = "各機型收購價格一覽"
STORE_NAMES = ("炘馳通訊", "炘馳")
# 標題含這些字的不是單機頁（導覽列、收購總表、門市、估價頁等）
EXCLUDE_KEYWORDS = ("導覽列", "收購表", "總表", "門市", "據點", "估價")
PRODUCT_PATTERN = re.compile(r"iPhone|iPad|Apple Watch|\bair\s*\d", re.IGNORECASE)
CAPACITY_PATTERN = re.compile(r"(?<![\w.])(\d+)\s*(GB|TB|G|T)(?![\w])", re.IGNORECASE)
IPHONE_NUMBER_PATTERN = re.compile(r"^iPhone (\d+)")

SE_SERIES = "iPhone SE / XR / XS 系列"
IPAD_SERIES = "iPad 系列"
WATCH_SERIES = "Apple Watch 系列"
OTHER_SERIES = "其他"

# iPhone 數字系列內的型號順序（高階在前）
IPHONE_VARIANT_ORDER = ("Pro Max", "Pro", "Air", "Plus", "", "mini", "e")
# 非數字系列依上市時間由新到舊；較精確的名稱要排在它的前綴之前
MODEL_ORDER: dict[str, tuple[str, ...]] = {
    SE_SERIES: (
        "iPhone SE 3",
        "iPhone SE 2",
        "iPhone XS Max",
        "iPhone XS",
        "iPhone XR",
        "iPhone X",
    ),
    IPAD_SERIES: (
        "iPad Air 11 (M3)",
        "iPad 11",
        "iPad mini 7",
        "iPad Pro 13 (M4)",
        "iPad Pro 11 (M4)",
        "iPad Air 11",
        "iPad Pro 12.9 (M2)",
        "iPad Pro 11 (M2)",
        "iPad 10",
        "iPad Air 5",
        "iPad mini 6",
        "iPad 9",
        "iPad Pro 11 (M1)",
        "iPad Air 4",
        "iPad 8",
        "iPad mini 5",
    ),
    WATCH_SERIES: (
        "Apple Watch Ultra 3",
        "Apple Watch Series 11",
        "Apple Watch Series 10",
        "Apple Watch Ultra 2",
        "Apple Watch Ultra 1",
    ),
}


@dataclass(frozen=True)
class SourcePage:
    """來源檔案中的一個自訂頁：原始標題與網址代碼（已解碼）。"""

    title: str
    handle: str


@dataclass(frozen=True)
class HubEntry:
    """整理後的一筆收購價連結。"""

    series: str
    model: str
    capacity: str
    suffix: str
    handle: str

    @property
    def title(self) -> str:
        """機型與容量，例如「iPhone 17 Pro Max 512GB」。"""
        return " ".join(part for part in (self.model, self.capacity) if part)

    @property
    def link_text(self) -> str:
        """連結文字，例如「iPhone 17 Pro Max 512GB 二手收購價」。"""
        return f"{self.title} {self.suffix}"

    @property
    def url(self) -> str:
        """站內相對網址，非 ASCII 字元做百分比編碼。"""
        return "/pages/" + quote(self.handle, safe="-_.~")


# ---------------------------------------------------------------------------
# 讀取來源
# ---------------------------------------------------------------------------


def handle_from_url(url: str) -> str:
    """從 /pages/xxx 或完整網址取出解碼後的網址代碼；不是自訂頁回傳空字串。"""
    path = unquote(urlsplit(url.strip()).path)
    if not path.startswith("/pages/"):
        return ""
    return path[len("/pages/") :].strip("/")


def read_custom_pages_index(path: Path) -> list[tuple[SourcePage, str]]:
    """讀取 custom_pages_index.md 的自訂頁面表格，回傳 (頁面, 狀態) 清單。"""
    rows: list[tuple[SourcePage, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "標題" or set(cells[0]) <= {"-", " "}:
            continue
        handle = handle_from_url(cells[1])
        if handle:
            rows.append((SourcePage(title=cells[0], handle=handle), cells[2]))
    return rows


def read_quick_audit(path: Path) -> list[SourcePage]:
    """讀取 quick_audit.csv 中狀態碼 200 的自訂頁。"""
    pages: list[SourcePage] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("status_code") or "").strip() != "200":
                continue
            handle = handle_from_url(row.get("decoded_url") or row.get("url") or "")
            if handle:
                pages.append(SourcePage(title=(row.get("title") or "").strip(), handle=handle))
    return pages


def load_pages(index_path: Path | None, audit_path: Path | None) -> list[SourcePage]:
    """合併兩個來源（以網址代碼去重），列表為主、健檢 CSV 補缺；隱藏頁不收。"""
    merged: dict[str, SourcePage] = {}
    hidden: set[str] = set()
    if index_path and index_path.exists():
        for page, status in read_custom_pages_index(index_path):
            if status == "隱藏":
                hidden.add(page.handle)
            else:
                merged.setdefault(page.handle, page)
    if audit_path and audit_path.exists():
        for page in read_quick_audit(audit_path):
            if page.handle not in hidden:
                merged.setdefault(page.handle, page)
    return list(merged.values())


# ---------------------------------------------------------------------------
# 篩選與整理
# ---------------------------------------------------------------------------


def clean_title(title: str) -> str:
    """去掉店名、「｜」之後的贅字與「標準規格」，並壓縮空白。"""
    text = re.split(r"\s[|｜–-]\s|｜", title)[0]
    for name in STORE_NAMES:
        text = text.replace(name, " ")
    text = text.replace("標準規格", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_single_buyback(title: str) -> bool:
    """判斷是否為單機收購價頁（標題含「收購價」、有產品名、不是導覽／總表等）。"""
    if "收購價" not in title:
        return False
    if any(keyword in title for keyword in EXCLUDE_KEYWORDS):
        return False
    if not PRODUCT_PATTERN.search(title):
        return False
    return bool(CAPACITY_PATTERN.search(title)) or "Apple Watch" in title


def normalize_capacity(number: str, unit: str) -> str:
    """把 128G、1T 等容量統一成 128GB、1TB。"""
    unit = unit.upper()
    return f"{int(number)}{'TB' if unit.startswith('T') else 'GB'}"


def capacity_in_gb(capacity: str) -> int:
    """容量換算成 GB 以便排序；沒有容量回傳 0。"""
    match = CAPACITY_PATTERN.fullmatch(capacity)
    if not match:
        return 0
    size = int(match.group(1))
    return size * 1024 if match.group(2).upper().startswith("T") else size


def normalize_model(model: str) -> str:
    """統一機型寫法：air4 → iPad Air 4、iPad Mini → iPad mini、手錶尺寸補 mm。"""
    model = re.sub(r"\s+", " ", model).strip()
    model = re.sub(r"^air\s*(\d+)$", r"iPad Air \1", model, flags=re.IGNORECASE)
    model = re.sub(r"\bmini\b", "mini", model, flags=re.IGNORECASE)
    model = re.sub(r"^iphone\b", "iPhone", model, flags=re.IGNORECASE)
    model = re.sub(r"^ipad\b", "iPad", model, flags=re.IGNORECASE)
    model = re.sub(r"\b(Series \d+) (\d{2})(?=\s|$)", r"\1 \2mm", model)
    return re.sub(r"\s+", " ", model).strip()


def detect_series(model: str) -> str:
    """依機型判斷所屬系列名稱。"""
    match = IPHONE_NUMBER_PATTERN.match(model)
    if match:
        return f"iPhone {match.group(1)} 系列"
    if re.match(r"^iPhone (SE|X)", model):
        return SE_SERIES
    if model.startswith("iPad"):
        return IPAD_SERIES
    if model.startswith("Apple Watch"):
        return WATCH_SERIES
    return OTHER_SERIES


def parse_entry(page: SourcePage) -> HubEntry | None:
    """把一個來源頁整理成 HubEntry；不是單機收購價頁回傳 None。"""
    if not is_single_buyback(page.title):
        return None
    text = clean_title(page.title)
    suffix = "二手收購價" if "二手收購價" in text else "收購價"
    text = re.sub(r"(二手)?收購價(格)?(查詢)?", " ", text)
    capacity = ""
    match = CAPACITY_PATTERN.search(text)
    if match:
        capacity = normalize_capacity(match.group(1), match.group(2))
        text = text[: match.start()] + " " + text[match.end() :]
    model = normalize_model(text)
    return HubEntry(
        series=detect_series(model),
        model=model,
        capacity=capacity,
        suffix=suffix,
        handle=page.handle,
    )


def series_sort_key(series: str) -> tuple[int, int]:
    """系列排序：iPhone 數字大到小 → SE/XR/XS → iPad → Apple Watch → 其他。"""
    match = re.match(r"^iPhone (\d+) 系列$", series)
    if match:
        return (0, -int(match.group(1)))
    order = (SE_SERIES, IPAD_SERIES, WATCH_SERIES)
    return (1 + order.index(series), 0) if series in order else (len(order) + 1, 0)


def model_rank(entry: HubEntry) -> int:
    """系列內的機型排名（數字越小越前面）。"""
    match = IPHONE_NUMBER_PATTERN.match(entry.model)
    if match:
        variant = entry.model[match.end() :].strip()
        if variant in IPHONE_VARIANT_ORDER:
            return IPHONE_VARIANT_ORDER.index(variant)
        return len(IPHONE_VARIANT_ORDER)
    order = MODEL_ORDER.get(entry.series, ())
    for rank, name in enumerate(order):
        if entry.model == name or entry.model.startswith(name + " "):
            return rank
    return len(order)


def group_entries(entries: Iterable[HubEntry]) -> list[tuple[str, list[HubEntry]]]:
    """依系列分組並排序：系列由新到舊，組內依機型排名、容量由小到大。"""
    groups: dict[str, list[HubEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.series, []).append(entry)
    result: list[tuple[str, list[HubEntry]]] = []
    for series in sorted(groups, key=series_sort_key):
        items = sorted(
            groups[series],
            key=lambda e: (model_rank(e), e.model, capacity_in_gb(e.capacity), e.url),
        )
        result.append((series, items))
    return result


def find_duplicates(entries: Iterable[HubEntry]) -> dict[str, list[str]]:
    """找出連結文字相同但網址不同的頁面，回傳 {連結文字: [網址…]}。"""
    seen: dict[str, list[str]] = {}
    for entry in entries:
        seen.setdefault(entry.link_text, []).append(entry.url)
    return {text: urls for text, urls in seen.items() if len(urls) > 1}


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------


def render_html(groups: list[tuple[str, list[HubEntry]]]) -> str:
    """產生可貼入 Cyberbiz 自訂 HTML 區塊的純 HTML（無 JavaScript）。"""
    lines = [f"<h2>{HUB_HEADING}</h2>"]
    for series, items in groups:
        lines.append(f"<h3>{html.escape(series)}</h3>")
        lines.append("<ul>")
        for entry in items:
            lines.append(
                f'  <li><a href="{html.escape(entry.url, quote=True)}">'
                f"{html.escape(entry.link_text)}</a></li>"
            )
        lines.append("</ul>")
    return "\n".join(lines) + "\n"


def write_check_csv(path: Path, groups: list[tuple[str, list[HubEntry]]]) -> None:
    """寫出 UTF-8 with BOM 的核對表；同名頁面在 note 欄提醒。"""
    all_entries = [entry for _, items in groups for entry in items]
    duplicates = find_duplicates(all_entries)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["series", "title", "url", "link_text", "note"])
        for series, items in groups:
            for entry in items:
                others = [u for u in duplicates.get(entry.link_text, []) if u != entry.url]
                note = f"與 {'、'.join(others)} 同名，請確認保留哪一頁" if others else ""
                writer.writerow([series, entry.title, entry.url, entry.link_text, note])


def build(
    index_path: Path | None, audit_path: Path | None, output_dir: Path
) -> list[tuple[str, list[HubEntry]]]:
    """讀取來源、整理並寫出 HTML 與核對 CSV，回傳分組結果。"""
    entries = [e for e in (parse_entry(p) for p in load_pages(index_path, audit_path)) if e]
    groups = group_entries(entries)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "buyback_hub.html").write_text(render_html(groups), encoding="utf-8")
    write_check_csv(output_dir / "buyback_hub_check.csv", groups)
    return groups


def main(argv: list[str] | None = None) -> int:
    """命令列進入點。"""
    parser = argparse.ArgumentParser(description="產生各機型收購價格一覽 HTML（不連網）")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="custom_pages_index.md 路徑")
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help="quick_audit.csv 路徑")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="輸出資料夾")
    args = parser.parse_args(argv)

    if not args.index.exists() and not args.audit.exists():
        print("找不到任何來源檔案（custom_pages_index.md 或 quick_audit.csv）", file=sys.stderr)
        return 1

    groups = build(args.index, args.audit, args.output_dir)
    total = sum(len(items) for _, items in groups)
    print(f"共 {total} 個單機收購價頁，{len(groups)} 個系列：")
    for series, items in groups:
        print(f"  {series}：{len(items)} 頁")
    duplicates = find_duplicates(entry for _, items in groups for entry in items)
    for text, urls in duplicates.items():
        print(f"  注意：「{text}」有 {len(urls)} 頁同名：{'、'.join(urls)}")
    print(f"已輸出 {args.output_dir / 'buyback_hub.html'}")
    print(f"已輸出 {args.output_dir / 'buyback_hub_check.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
