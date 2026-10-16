"""scripts/build_buyback_hub.py 的測試。只用暫存資料夾裡的假檔案，不連任何網站。"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "build_buyback_hub", ROOT / "scripts" / "build_buyback_hub.py"
)
assert _spec and _spec.loader
bh = importlib.util.module_from_spec(_spec)
sys.modules["build_buyback_hub"] = bh
_spec.loader.exec_module(bh)


def entry(title: str, handle: str = "x") -> "bh.HubEntry":
    """用標題建立 HubEntry，必須是單機收購價頁。"""
    result = bh.parse_entry(bh.SourcePage(title=title, handle=handle))
    assert result is not None, title
    return result


INDEX_MD = """# 後台自訂頁面

| 標題 | 網址 | 狀態 | 其他資訊 |
| --- | --- | --- | --- |
| iPhone 15 128GB 二手收購價 | /pages/15-128g | 發佈 | id=1 |
| iPhone 17 Pro Max 512GB 二手收購價 | /pages/iphone-17-pro-max-512gb-二手收購價 | 發佈 | id=2 |
| iPhone 17 Pro Max 512GB 二手收購價 | /pages/17-pro-max-512g | 發佈 | id=3 |
| air4 64GB 二手收購價 | /pages/air4-64g | 發佈 | id=4 |
| Apple Watch Series 10 42 (GPS) 標準規格 二手收購價 | /pages/series-10-42-gps-標準規格 | 發佈 | id=5 |
| iPhone 14 128GB 二手收購價 | /pages/14-128g | 隱藏 | id=6 |
| APPLE 手機二手-導覽列 | /pages/second-hand-apple | 發佈 | id=7 |
| 收購表ANDROID | /pages/收購表-apple | 發佈 | id=8 |
| 炘馳據點 | /pages/來訪我們 | 發佈 | id=9 |
"""

AUDIT_HEADER = "url,decoded_url,page_type,status_code,title,meta_description\n"
AUDIT_ROWS = (
    "https://www.example.com,https://www.example.com,home,200,炘馳通訊 -全方位手機服務,\n"
    "https://www.example.com/pages/15-128g,https://www.example.com/pages/15-128g,page,200,"
    "iPhone 15 128GB 二手收購價 炘馳通訊,\n"
    "https://www.example.com/pages/se-3-64g,https://www.example.com/pages/se-3-64g,page,200,"
    "iPhone SE 3 64GB 二手收購價 炘馳通訊,\n"
    "https://www.example.com/pages/14-128g,https://www.example.com/pages/14-128g,page,200,"
    "iPhone 14 128GB 二手收購價 炘馳通訊,\n"
    "https://www.example.com/pages/gone,https://www.example.com/pages/gone,page,404,"
    "iPhone 13 128GB 二手收購價 炘馳通訊,\n"
)


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    """在暫存資料夾建立假的 custom_pages_index.md 與 quick_audit.csv。"""
    index = tmp_path / "custom_pages_index.md"
    index.write_text(INDEX_MD, encoding="utf-8")
    audit = tmp_path / "quick_audit.csv"
    audit.write_text(AUDIT_HEADER + AUDIT_ROWS, encoding="utf-8-sig")
    return index, audit


# ---------------------------------------------------------------------------
# 連結文字整理
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "model", "capacity", "link_text"),
    [
        (
            "iPhone 17 Pro Max 512GB 二手收購價",
            "iPhone 17 Pro Max",
            "512GB",
            "iPhone 17 Pro Max 512GB 二手收購價",
        ),
        (
            "iPhone 17 Pro Max 512GB 二手收購價 炘馳通訊",
            "iPhone 17 Pro Max",
            "512GB",
            "iPhone 17 Pro Max 512GB 二手收購價",
        ),
        ("iPhone 13 Pro 1TB 二手收購價", "iPhone 13 Pro", "1TB", "iPhone 13 Pro 1TB 二手收購價"),
        ("iPhone 16e 128GB 二手收購價", "iPhone 16e", "128GB", "iPhone 16e 128GB 二手收購價"),
        ("air4 256GB 二手收購價", "iPad Air 4", "256GB", "iPad Air 4 256GB 二手收購價"),
        ("iPad Mini 5 64GB 二手收購價", "iPad mini 5", "64GB", "iPad mini 5 64GB 二手收購價"),
        (
            "iPad Pro 12.9 (M2) 128GB 二手收購價",
            "iPad Pro 12.9 (M2)",
            "128GB",
            "iPad Pro 12.9 (M2) 128GB 二手收購價",
        ),
        ("iPad 8 32GB 二手收購價", "iPad 8", "32GB", "iPad 8 32GB 二手收購價"),
        ("iPhone 12 mini 64G 收購價｜炘馳通訊", "iPhone 12 mini", "64GB", "iPhone 12 mini 64GB 收購價"),
        (
            "Apple Watch Series 10 42 (GPS) 標準規格 二手收購價 炘馳通訊",
            "Apple Watch Series 10 42mm (GPS)",
            "",
            "Apple Watch Series 10 42mm (GPS) 二手收購價",
        ),
        (
            "Apple Watch Ultra 2 49mm 二手收購價",
            "Apple Watch Ultra 2 49mm",
            "",
            "Apple Watch Ultra 2 49mm 二手收購價",
        ),
    ],
)
def test_parse_entry_cleans_link_text(title: str, model: str, capacity: str, link_text: str) -> None:
    """連結文字去掉店名與贅字，正確抓出機型、容量、收購價。"""
    result = entry(title)
    assert result.model == model
    assert result.capacity == capacity
    assert result.link_text == link_text
    assert "炘馳" not in result.link_text
    assert result.title == f"{model} {capacity}".strip()


@pytest.mark.parametrize(
    "title",
    [
        "APPLE 手機二手-導覽列",
        "收購表ANDROID",
        "收購表-導覽列",
        "手機線上估價",
        "炘馳據點",
        "iPhone 17 配件",
        "炘馳通訊 -全方位手機服務，隨時滿足您的需求！",
        "iPhone 收購價總表",
        "",
    ],
)
def test_non_single_pages_are_excluded(title: str) -> None:
    """首頁、導覽列、收購表、門市頁等不是單機頁，要排除。"""
    assert bh.parse_entry(bh.SourcePage(title=title, handle="x")) is None


def test_url_is_percent_encoded() -> None:
    """網址代碼中的中文要百分比編碼，英數與連字號不變。"""
    result = entry("iPhone 17 512GB 二手收購價", handle="iphone-17-512gb-二手收購價")
    assert result.url == "/pages/iphone-17-512gb-%E4%BA%8C%E6%89%8B%E6%94%B6%E8%B3%BC%E5%83%B9"
    assert entry("iPhone 15 128GB 二手收購價", handle="15-128g").url == "/pages/15-128g"


@pytest.mark.parametrize(
    ("url", "handle"),
    [
        ("/pages/15-128g", "15-128g"),
        ("https://www.example.com/pages/15-128g/", "15-128g"),
        ("https://www.example.com/pages/se-%E6%A8%99%E6%BA%96", "se-標準"),
        ("https://www.example.com", ""),
        ("/blogs/news/1", ""),
    ],
)
def test_handle_from_url(url: str, handle: str) -> None:
    """只取 /pages/ 後面的網址代碼並解碼。"""
    assert bh.handle_from_url(url) == handle


# ---------------------------------------------------------------------------
# 分組與排序
# ---------------------------------------------------------------------------


def test_detect_series() -> None:
    """機型對應到正確系列；16e 歸在 iPhone 16 系列。"""
    assert entry("iPhone 17 Pro 256GB 二手收購價").series == "iPhone 17 系列"
    assert entry("iPhone 16e 128GB 二手收購價").series == "iPhone 16 系列"
    assert entry("iPhone 11 64GB 二手收購價").series == "iPhone 11 系列"
    assert entry("iPhone SE 2 64GB 二手收購價").series == bh.SE_SERIES
    assert entry("iPhone XR 64GB 二手收購價").series == bh.SE_SERIES
    assert entry("iPhone XS Max 64GB 二手收購價").series == bh.SE_SERIES
    assert entry("air5 64GB 二手收購價").series == bh.IPAD_SERIES
    assert entry("Apple Watch Ultra 3 49mm 二手收購價").series == bh.WATCH_SERIES


def test_groups_sorted_new_to_old() -> None:
    """系列由新到舊：iPhone 數字大到小 → SE/XR/XS → iPad → Apple Watch。"""
    titles = [
        "Apple Watch Ultra 1 49mm 二手收購價",
        "iPhone 11 64GB 二手收購價",
        "iPad 9 64GB 二手收購價",
        "iPhone XR 64GB 二手收購價",
        "iPhone 13 128GB 二手收購價",
        "iPhone 17 256GB 二手收購價",
        "iPhone 12 64GB 二手收購價",
        "iPhone 16 128GB 二手收購價",
        "iPhone 14 128GB 二手收購價",
        "iPhone 15 128GB 二手收購價",
    ]
    groups = bh.group_entries(entry(t, handle=str(i)) for i, t in enumerate(titles))
    assert [series for series, _ in groups] == [
        "iPhone 17 系列",
        "iPhone 16 系列",
        "iPhone 15 系列",
        "iPhone 14 系列",
        "iPhone 13 系列",
        "iPhone 12 系列",
        "iPhone 11 系列",
        bh.SE_SERIES,
        bh.IPAD_SERIES,
        bh.WATCH_SERIES,
    ]


def test_iphone_group_order_by_variant_then_capacity() -> None:
    """同系列內 Pro Max → Pro → Plus → 標準 → mini → e，容量小到大（1TB 排在 512GB 後）。"""
    titles = [
        "iPhone 16 128GB 二手收購價",
        "iPhone 16 Pro Max 1TB 二手收購價",
        "iPhone 16e 128GB 二手收購價",
        "iPhone 16 Pro 128GB 二手收購價",
        "iPhone 16 Pro Max 512GB 二手收購價",
        "iPhone 16 Plus 128GB 二手收購價",
        "iPhone 16 Pro Max 256GB 二手收購價",
    ]
    [(series, items)] = bh.group_entries(entry(t, handle=str(i)) for i, t in enumerate(titles))
    assert series == "iPhone 16 系列"
    assert [e.title for e in items] == [
        "iPhone 16 Pro Max 256GB",
        "iPhone 16 Pro Max 512GB",
        "iPhone 16 Pro Max 1TB",
        "iPhone 16 Pro 128GB",
        "iPhone 16 Plus 128GB",
        "iPhone 16 128GB",
        "iPhone 16e 128GB",
    ]


def test_other_groups_order_new_to_old() -> None:
    """SE/XR/XS、iPad、Apple Watch 組內依上市時間由新到舊。"""
    titles = [
        "iPhone XR 64GB 二手收購價",
        "iPhone SE 2 64GB 二手收購價",
        "iPhone SE 3 64GB 二手收購價",
        "iPhone XS Max 64GB 二手收購價",
        "iPad Mini 5 64GB 二手收購價",
        "iPad Air 11 128GB 二手收購價",
        "iPad Air 11 (M3) 128GB 二手收購價",
        "iPad Pro 13 (M4) 256GB 二手收購價",
        "Apple Watch Ultra 1 49mm 二手收購價",
        "Apple Watch Series 11 46 (GPS) 標準規格 二手收購價",
        "Apple Watch Series 11 42 (GPS) 標準規格 二手收購價",
        "Apple Watch Ultra 3 49mm 二手收購價",
    ]
    groups = dict(bh.group_entries(entry(t, handle=str(i)) for i, t in enumerate(titles)))
    assert [e.model for e in groups[bh.SE_SERIES]] == [
        "iPhone SE 3",
        "iPhone SE 2",
        "iPhone XS Max",
        "iPhone XR",
    ]
    assert [e.model for e in groups[bh.IPAD_SERIES]] == [
        "iPad Air 11 (M3)",
        "iPad Pro 13 (M4)",
        "iPad Air 11",
        "iPad mini 5",
    ]
    assert [e.model for e in groups[bh.WATCH_SERIES]] == [
        "Apple Watch Ultra 3 49mm",
        "Apple Watch Series 11 42mm (GPS)",
        "Apple Watch Series 11 46mm (GPS)",
        "Apple Watch Ultra 1 49mm",
    ]


def test_find_duplicates() -> None:
    """同名不同網址的頁面要被找出來。"""
    entries = [
        entry("iPhone 17 Pro Max 512GB 二手收購價", handle="a"),
        entry("iPhone 17 Pro Max 512GB 二手收購價", handle="b"),
        entry("iPhone 17 Pro Max 256GB 二手收購價", handle="c"),
    ]
    assert bh.find_duplicates(entries) == {
        "iPhone 17 Pro Max 512GB 二手收購價": ["/pages/a", "/pages/b"]
    }


# ---------------------------------------------------------------------------
# 讀取來源
# ---------------------------------------------------------------------------


def test_load_pages_merges_sources(sources: tuple[Path, Path]) -> None:
    """列表為主、CSV 補缺，同網址代碼只留一筆；隱藏頁與非 200 頁不收。"""
    index, audit = sources
    handles = {p.handle for p in bh.load_pages(index, audit)}
    assert "15-128g" in handles
    assert "se-3-64g" in handles  # 只在 CSV 裡
    assert "14-128g" not in handles  # 列表標示隱藏
    assert "gone" not in handles  # 404
    pages = bh.load_pages(index, audit)
    assert len(pages) == len(handles)


def test_load_pages_with_only_one_source(sources: tuple[Path, Path], tmp_path: Path) -> None:
    """只有其中一個來源檔時也能運作。"""
    index, audit = sources
    missing = tmp_path / "missing.csv"
    only_index = {p.handle for p in bh.load_pages(index, missing)}
    only_audit = {p.handle for p in bh.load_pages(missing, audit)}
    assert "se-3-64g" not in only_index
    assert "air4-64g" in only_index
    assert "se-3-64g" in only_audit
    assert "14-128g" in only_audit


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------


def test_render_html_structure() -> None:
    """HTML 有 h2 主標題、每組一個 h3 與 ul/li，且沒有 JavaScript。"""
    groups = bh.group_entries(
        [
            entry("iPhone 17 Pro Max 512GB 二手收購價", handle="17-pro-max-512g"),
            entry("iPad 9 64GB 二手收購價", handle="9-64g"),
        ]
    )
    output = bh.render_html(groups)
    assert output.startswith("<h2>各機型收購價格一覽</h2>\n")
    assert output.count("<h3>") == 2
    assert output.count("<ul>") == output.count("</ul>") == 2
    assert (
        '<li><a href="/pages/17-pro-max-512g">iPhone 17 Pro Max 512GB 二手收購價</a></li>'
        in output
    )
    assert output.index("<h3>iPhone 17 系列</h3>") < output.index("<h3>iPad 系列</h3>")
    assert "<script" not in output.lower()
    assert "onclick" not in output.lower()


def test_render_html_escapes_text() -> None:
    """特殊字元要跳脫，避免破壞 HTML。"""
    item = bh.HubEntry(
        series="iPhone 17 系列", model="iPhone <17>", capacity="256GB", suffix="收購價", handle="a&b"
    )
    output = bh.render_html([("iPhone 17 系列", [item])])
    assert "iPhone &lt;17&gt;" in output
    assert "<17>" not in output


def test_build_writes_html_and_csv(sources: tuple[Path, Path], tmp_path: Path) -> None:
    """build 寫出 HTML 與 UTF-8 BOM 的核對 CSV，欄位與內容正確。"""
    index, audit = sources
    out = tmp_path / "output"
    groups = bh.build(index, audit, out)

    html_text = (out / "buyback_hub.html").read_text(encoding="utf-8")
    assert "<h2>各機型收購價格一覽</h2>" in html_text
    assert "導覽列" not in html_text
    assert "炘馳" not in html_text

    raw = (out / "buyback_hub_check.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with (out / "buyback_hub_check.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == ["series", "title", "url", "link_text", "note"]
    total = sum(len(items) for _, items in groups)
    assert len(rows) == total == 6  # 15-128g、兩個 17 Pro Max 512GB、air4、Watch、SE 3
    assert html_text.count("<li>") == total

    assert rows[0]["series"] == "iPhone 17 系列"
    assert rows[0]["title"] == "iPhone 17 Pro Max 512GB"
    assert rows[0]["link_text"] == "iPhone 17 Pro Max 512GB 二手收購價"
    assert "同名" in rows[0]["note"]
    by_url = {row["url"]: row for row in rows}
    assert by_url["/pages/air4-64g"]["link_text"] == "iPad Air 4 64GB 二手收購價"
    assert by_url["/pages/air4-64g"]["note"] == ""
    assert [row["series"] for row in rows][-1] == bh.WATCH_SERIES


def test_main_returns_error_without_sources(tmp_path: Path) -> None:
    """兩個來源都不存在時回傳 1，不產生輸出。"""
    out = tmp_path / "output"
    code = bh.main(
        [
            "--index",
            str(tmp_path / "none.md"),
            "--audit",
            str(tmp_path / "none.csv"),
            "--output-dir",
            str(out),
        ]
    )
    assert code == 1
    assert not out.exists()


def test_main_runs(sources: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """命令列執行成功並印出統計。"""
    index, audit = sources
    out = tmp_path / "output"
    code = bh.main(["--index", str(index), "--audit", str(audit), "--output-dir", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "共 6 個單機收購價頁" in printed
    assert "同名" in printed
    assert (out / "buyback_hub.html").exists()
