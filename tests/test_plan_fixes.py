"""scripts/plan_fixes.py 的測試。

全部用 tmp_path 裡的假 ISSUES.md、quick_audit.csv、research/admin/*.md，不連網，
也不會改到專案裡真正的 ISSUES.md 或 changes/。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("plan_fixes", ROOT / "scripts" / "plan_fixes.py")
assert _spec and _spec.loader
pf = importlib.util.module_from_spec(_spec)
sys.modules["plan_fixes"] = pf
_spec.loader.exec_module(pf)

_ae_spec = importlib.util.spec_from_file_location("admin_edit", ROOT / "scripts" / "admin_edit.py")
assert _ae_spec and _ae_spec.loader
admin_edit = importlib.util.module_from_spec(_ae_spec)
sys.modules.setdefault("admin_edit", admin_edit)
_ae_spec.loader.exec_module(admin_edit)

TODAY = date(2026, 10, 17)
SITE = "https://www.sinchih.com.tw"
ADMIN = "https://sinchih.cyberbiz.co"

ISSUES_MD = """# 問題總表

## 一、網站內容問題

| 編號 | 問題 | 位置 | 嚴重度 | 確認程度 | 修法 |
|---|---|---|---|---|---|
| S1 | 文章開頭的 `<style>` 污染搜尋摘要 | 部落格（清單見 `research/audit/s1_affected.txt`） | 高 | ✅ | 🤖 |
| S2 | 標題與網址 Slug 不一致 | `/pages/收購表-apple` | 高 | ✅ | 👤 |
| S3 | meta description 空白 | `/pages/收購表-apple` | 高 | ✅ | 👤 |
| S5 | 沒有 H1 | 首頁 `/` | 中 | ✅ | 👤 |
| S6 | 沒有 H1 | `/pages/來訪我們` | 中 | ✅ | 👤 |
| S7 | 描述中「敦化路」誤植為「數化路」（實際內容為：`台中市北屯區數化路一段493號`） | `/pages/來訪我們` | 中 | ✅ | 👤 |
| S8 | 沒有 LocalBusiness（MobilePhoneStore）結構化資料 | `/pages/來訪我們` | 高 | ✅ | 👤 |
| S9 | 自訂頁完全沒有結構化資料，可補 FAQPage | 163 個自訂頁 | 中 | ✅ | 🤖 |
| S10 | 其他自訂頁的標題、描述、H1 問題 | 除 `/pages/收購表-apple` 與 `/pages/來訪我們` 外之自訂頁：<br>• **1 頁 `meta description` 完全空白**<br>• **1 頁 `meta description` 僅重複標題 4～6 字**（如 `/pages/常見問題`）<br>• **1 頁沒有 H1** | 中 | ✅ | 👤 |
| S12 | 重複的單機收購頁 | 1. `iPhone 17 Pro Max 512GB`：保留 `/pages/17-pro-max-512g`，淘汰 `/pages/iphone-17-pro-max-512gb-二手收購價`<br>2. `256GB`：保留 `/pages/17-pro-max-256g`，淘汰 `/pages/17-pro-max-256g-20260414171746` | 中 | ✅ | 👤 |
| S13 | AI 提示詞未刪乾淨，貼進 `meta description` | `/pages/news`，目前 `meta description` 開頭為：`建議字數控制在 150 字以內，包含核心亮點與行動呼籲： 蘋果史上最平價 MacBook...` | 中 | ✅ | 👤 |
| S14 | 部落格文章出現 2 個 H1（多出一個空白 `<h1></h1>`） | `/blogs/手機知識學堂/20260321-1` | 低 | ✅ | 👤 |
| S20 | 商品頁價格標錯 | `/products/iphone-15` | 高 | ✅ | 👤 |
| S21 | 刪除頁面 `/pages/old` | `/pages/old` | 低 | ✅ | 👤 |

**S9 注意**：FAQ 不能編造。

## 二、無法修改（不列入待辦）

| 項目 | 原因 |
|---|---|
| robots.txt | 系統產生 |
"""

AUDIT_FIELDS = ["url", "decoded_url", "page_type", "status_code", "title", "meta_description", "h1_count"]
AUDIT_ROWS = [
    ("/", "home", "炘馳通訊 -全方位手機服務", "我們是位於台中的炘馳通訊行", "0"),
    ("/pages/收購表-apple", "page", "收購表ANDROID 炘馳通訊", "", "0"),
    ("/pages/來訪我們", "page", "炘馳據點 炘馳通訊", "台中市北屯區數化路一段493號", "0"),
    ("/pages/常見問題", "page", "常見問題 炘馳通訊", "常見問題", "1"),
    ("/pages/14-256g", "page", "iPhone 14 256GB 二手收購價 炘馳通訊", "", "1"),
    ("/pages/second-hand-apple", "page", "二手蘋果 炘馳通訊", "二手 Apple 手機買賣，台中北屯炘馳通訊提供保固", "0"),
    ("/pages/no-admin", "page", "後台沒有 炘馳通訊", "", "1"),
    ("/blogs/手機知識學堂/183781", "blog_article", "文章", "body { font-family: x }", "1"),
]

ADMIN_MD = """# 後台自訂頁面：custom_pages_index

| 標題 | 網址 | 狀態 | 其他資訊 |
| --- | --- | --- | --- |
| 收購表ANDROID | /pages/收購表-apple | 發佈 | id=232851；handle=收購表-apple |
| 炘馳據點 | /pages/來訪我們 | 發佈 | id=223357；handle=來訪我們 |
| 常見問題 | /pages/常見問題 | 發佈 | id=100001；handle=常見問題 |
| iPhone 14 256GB 二手收購價 | /pages/14-256g | 發佈 | id=271252；handle=14-256g |
| 二手蘋果 | /pages/second-hand-apple | 發佈 | id=100002；handle=second-hand-apple |
| iPhone 17 Pro Max 512GB 二手收購價 | /pages/iphone-17-pro-max-512gb-二手收購價 | 發佈 | id=271201 |
| iPhone 17 Pro Max 256GB 二手收購價 | /pages/17-pro-max-256g-20260414171746 | 隱藏 | id=271199 |
| 最新消息 | /pages/news | 發佈 | id=100003 |
"""

BLOG_MD = """# 文章列表

| 標題 | 網址 | 操作 |
| --- | --- | --- |
| 舊文章 | /blogs/手機知識學堂/183781 | [編輯](https://sinchih.cyberbiz.co/admin/blogs/5/articles/183781/edit) |
| 沒有編輯連結 | /blogs/手機知識學堂/20260321-1 | |
"""


@pytest.fixture()
def project(tmp_path: Path) -> dict[str, Path]:
    """在 tmp_path 建立假的 ISSUES.md、research/audit、research/admin、changes。"""
    issues = tmp_path / "ISSUES.md"
    issues.write_text(ISSUES_MD, encoding="utf-8")
    audit = tmp_path / "research" / "audit"
    audit.mkdir(parents=True)
    with (audit / "quick_audit.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(AUDIT_FIELDS)
        for path, kind, title, desc, h1 in AUDIT_ROWS:
            writer.writerow([SITE + path, SITE + path, kind, "200", title, desc, h1])
    (audit / "s1_affected.txt").write_text(
        f"{SITE}/blogs/手機知識學堂/183781\n{SITE}/blogs/手機知識學堂/999999\n", encoding="utf-8"
    )
    (audit / "orphans.txt").write_text(f"{SITE}/pages/14-256g\n", encoding="utf-8")
    admin = tmp_path / "research" / "admin"
    admin.mkdir(parents=True)
    (admin / "custom_pages_index.md").write_text(ADMIN_MD, encoding="utf-8")
    (admin / "blogs.md").write_text(BLOG_MD, encoding="utf-8")
    return {"issues": issues, "audit": audit, "admin": admin, "changes": tmp_path / "changes"}


def run(project: dict[str, Path], ids: list[str] | None) -> Any:
    """在假專案上執行 plan_fixes。"""
    return pf.run(ids, project["issues"], project["audit"], project["admin"], project["changes"], TODAY)


def load(path: Path) -> dict[str, Any]:
    """讀修改單。"""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def by_id(project: dict[str, Path], issue_id: str) -> dict[str, Any]:
    """讀某個問題的修改單。"""
    return load(project["changes"] / f"2026-10-17-{issue_id}.yaml")


# ---------------------------------------------------------------------------
# 讀取資料
# ---------------------------------------------------------------------------


def test_parse_issues_only_s_rows() -> None:
    issues = pf.parse_issues(ISSUES_MD)
    assert [i.id for i in issues][:3] == ["S1", "S2", "S3"]
    assert "robots.txt" not in [i.id for i in issues]
    assert issues[0].location.startswith("部落格")


def test_parse_real_issues_md() -> None:
    issues = pf.parse_issues((ROOT / "ISSUES.md").read_text(encoding="utf-8"))
    ids = [i.id for i in issues]
    assert ids[:3] == ["S1", "S2", "S3"]
    assert "S12" in ids


def test_front_path() -> None:
    assert pf.front_path(f"{SITE}/pages/%E5%B8%B8%E8%A6%8B%E5%95%8F%E9%A1%8C/") == "/pages/常見問題"
    assert pf.front_path(SITE) == "/"
    assert pf.front_path("/pages/a?x=1") == "/pages/a"


def test_load_admin_pages(project: dict[str, Path]) -> None:
    pages = pf.load_admin_pages(project["admin"])
    assert pages["/pages/來訪我們"].admin_url == f"{ADMIN}/admin/custom_pages/223357/edit"
    assert pages["/pages/17-pro-max-256g-20260414171746"].status == "隱藏"
    assert pages["/blogs/手機知識學堂/183781"].admin_url == f"{ADMIN}/admin/blogs/5/articles/183781/edit"
    assert "/blogs/手機知識學堂/20260321-1" not in pages, "沒有編輯連結就不猜網址"


def test_load_missing_sources(tmp_path: Path) -> None:
    sources = pf.Sources.load(tmp_path / "none", tmp_path / "none")
    assert sources.audit == {} and sources.s1_affected == [] and sources.admin == {}


# ---------------------------------------------------------------------------
# 分類
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("issue_id", "kinds", "reason"),
    [
        ("S1", ["style_to_end"], ""),
        ("S2", [], pf.UNSUPPORTED_REASON),
        ("S3", ["add_desc"], ""),
        ("S5", ["add_h1"], ""),
        ("S7", ["typo"], ""),
        ("S8", ["local_business"], ""),
        ("S9", [], pf.FAQ_REASON),
        ("S10", ["add_h1", "add_desc", "short_desc"], ""),
        ("S12", ["hide_redirect"], ""),
        ("S13", ["prompt_prefix"], ""),
        ("S14", ["empty_h1"], ""),
        ("S20", [], pf.FORBIDDEN_REASON),
        ("S21", [], pf.FORBIDDEN_REASON),
    ],
)
def test_classify(issue_id: str, kinds: list[str], reason: str) -> None:
    issue = next(i for i in pf.parse_issues(ISSUES_MD) if i.id == issue_id)
    assert pf.classify(issue) == (kinds, reason)


def test_classify_real_issues_md() -> None:
    issues = {i.id: i for i in pf.parse_issues((ROOT / "ISSUES.md").read_text(encoding="utf-8"))}
    assert pf.classify(issues["S12"])[0] == ["hide_redirect"]
    assert pf.classify(issues["S1"])[0] == ["style_to_end"]
    assert pf.classify(issues["S7"])[0] == ["typo"]
    assert pf.classify(issues["S9"]) == ([], pf.FAQ_REASON)
    assert pf.classify(issues["S11"]) == ([], pf.UNSUPPORTED_REASON)


# ---------------------------------------------------------------------------
# 產生修改單
# ---------------------------------------------------------------------------


def test_s12_hide_and_redirect(project: dict[str, Path]) -> None:
    outcome = run(project, ["s12"])
    assert outcome.written == [project["changes"] / "2026-10-17-S12.yaml"]
    data = by_id(project, "S12")
    assert data["created_at"] == "2026-10-17"
    hide, redirect_512, redirect_256 = data["changes"]
    assert hide["url"] == f"{ADMIN}/admin/custom_pages/271201/edit"
    assert (hide["field"], hide["before"], hide["after"]) == ("status", "發佈", "隱藏")
    assert hide["reason"].startswith("S12：")
    assert redirect_512["url"] == f"{ADMIN}/admin/redirections/new"
    assert redirect_512["after"] == {"path": "/pages/iphone-17-pro-max-512gb-二手收購價", "target": "/pages/17-pro-max-512g"}
    assert redirect_256["after"]["path"] == "/pages/17-pro-max-256g-20260414171746"
    assert data["skipped"][0]["reason"] == "後台列表顯示已經是隱藏"
    assert "note" not in hide


def test_s1_style_uses_affected_list(project: dict[str, Path]) -> None:
    run(project, ["S1"])
    data = by_id(project, "S1")
    assert len(data["changes"]) == 1
    change = data["changes"][0]
    assert change["op"] == "move_style_to_end"
    assert change["url"] == f"{ADMIN}/admin/blogs/5/articles/183781/edit"
    assert data["skipped"][0]["url"] == f"{SITE}/blogs/手機知識學堂/999999"
    assert "不猜網址" in data["skipped"][0]["reason"]


def test_s3_description_marked_ai(project: dict[str, Path]) -> None:
    run(project, ["S3"])
    change = by_id(project, "S3")["changes"][0]
    assert change["field"] == "seo_description"
    assert change["before"] == ""
    assert "收購表ANDROID" in change["after"]
    assert change["note"] == "AI 撰寫，請確認內容"


def test_s5_home_without_admin_url_writes_nothing(project: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    outcome = run(project, ["S5"])
    assert outcome.written == []
    assert outcome.plans[0].skipped[0]["url"] == f"{SITE}/"
    assert not project["changes"].exists()
    assert "0 筆修改、1 頁無法產生" in capsys.readouterr().out


def test_s6_h1_prepend(project: dict[str, Path]) -> None:
    run(project, ["S6"])
    change = by_id(project, "S6")["changes"][0]
    assert change["op"] == "prepend"
    assert change["after"] == "<h1>炘馳據點</h1>"
    assert change["absent"] == "<h1"
    assert change["note"] == "AI 撰寫，請確認內容"


def test_s7_typo_replace(project: dict[str, Path]) -> None:
    run(project, ["S7"])
    change = by_id(project, "S7")["changes"][0]
    assert (change["op"], change["before"], change["after"]) == ("replace", "數化路", "敦化路")
    assert change["field"] == "seo_description"
    assert "note" not in change


def test_s8_local_business_jsonld(project: dict[str, Path]) -> None:
    run(project, ["S8"])
    path = project["changes"] / "2026-10-17-S8.yaml"
    assert "after: |" in path.read_text(encoding="utf-8"), "多行內容用 | 格式方便閱讀"
    change = load(path)["changes"][0]
    assert change["op"] == "append" and change["absent"] == "application/ld+json"
    body = change["after"].split("\n", 1)[1].rsplit("\n", 1)[0]
    data = json.loads(body)
    assert data["@type"] == "MobilePhoneStore"
    assert data["address"]["streetAddress"] == "敦化路一段493號"
    assert "telephone" not in data and "openingHours" not in data
    assert change["note"] == "AI 撰寫，請確認內容"


def test_s10_uses_audit_csv_with_exclusions(project: dict[str, Path]) -> None:
    run(project, ["S10"])
    data = by_id(project, "S10")
    pairs = {(c["field"], c["front_url"].removeprefix(SITE)) for c in data["changes"]}
    assert pairs == {
        ("body_html", "/pages/second-hand-apple"),
        ("seo_description", "/pages/14-256g"),
        ("seo_description", "/pages/常見問題"),
    }
    short = next(c for c in data["changes"] if c["front_url"].endswith("常見問題"))
    assert short["before"] == "常見問題"
    blank = next(c for c in data["changes"] if c["front_url"].endswith("14-256g"))
    assert blank["after"].startswith("想賣掉您的 iPhone 14 256GB 嗎？")
    assert [s["url"] for s in data["skipped"]] == [f"{SITE}/pages/no-admin"]
    assert all(c["note"] == "AI 撰寫，請確認內容" for c in data["changes"])


def test_s13_prompt_prefix_removed(project: dict[str, Path]) -> None:
    run(project, ["S13"])
    change = by_id(project, "S13")["changes"][0]
    assert change["before"] == "建議字數控制在 150 字以內，包含核心亮點與行動呼籲： "
    assert change["after"] == ""
    assert change["op"] == "replace"


def test_s14_blog_without_edit_link_skipped(project: dict[str, Path]) -> None:
    outcome = run(project, ["S14"])
    assert outcome.written == []
    assert "不猜網址" in outcome.plans[0].skipped[0]["reason"]


def test_generated_changes_pass_admin_edit_validation(project: dict[str, Path]) -> None:
    outcome = run(project, None)
    assert outcome.written
    for path in outcome.written:
        raw_items = load(path)["changes"]
        assert len(admin_edit.load_changes([path])) == len(raw_items), path.name


# ---------------------------------------------------------------------------
# 不能自動處理的問題
# ---------------------------------------------------------------------------


def test_unsupported_recorded_in_issues_once(project: dict[str, Path]) -> None:
    outcome = run(project, None)
    manual = dict(outcome.manual)
    assert set(manual) == {"S2", "S9", "S20", "S21"}
    assert manual["S20"] == pf.FORBIDDEN_REASON
    assert not (project["changes"] / "2026-10-17-S20.yaml").exists()
    text = project["issues"].read_text(encoding="utf-8")
    assert text.count(pf.MANUAL_SECTION) == 1
    assert f"| S9 | {pf.FAQ_REASON} | 2026-10-17 |" in text
    assert text.startswith(ISSUES_MD.rstrip("\n"))

    for path in outcome.written:
        path.unlink()
    run(project, None)
    again = project["issues"].read_text(encoding="utf-8")
    assert again == text, "再跑一次不重複記錄"


def test_no_overwrite_existing_file_case_insensitive(project: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    project["changes"].mkdir()
    existing = project["changes"] / "2026-10-17-s12.yaml"
    existing.write_text("原本的內容\n", encoding="utf-8")
    outcome = run(project, ["S12"])
    assert outcome.written == []
    assert existing.read_text(encoding="utf-8") == "原本的內容\n"
    assert "不覆蓋" in capsys.readouterr().out


def test_unknown_issue_id(project: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    outcome = run(project, ["S99"])
    assert outcome.plans == [] and outcome.manual == []
    assert "沒有問題 S99" in capsys.readouterr().out


def test_prints_preview_and_apply_commands(project: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    run(project, ["S7"])
    out = capsys.readouterr().out
    assert "預覽：python scripts/admin_edit.py --file changes/2026-10-17-S7.yaml" in out
    assert "執行：python scripts/admin_edit.py --file changes/2026-10-17-S7.yaml --apply" in out


# ---------------------------------------------------------------------------
# 命令列
# ---------------------------------------------------------------------------


def test_parse_args() -> None:
    assert pf.parse_args(["--issue", "S12"]).issue == ["S12"]
    assert pf.parse_args(["--issue", "S1", "--issue", "S7"]).issue == ["S1", "S7"]
    assert pf.parse_args(["--all"]).all is True
    with pytest.raises(SystemExit):
        pf.parse_args([])
    with pytest.raises(SystemExit):
        pf.parse_args(["--all", "--issue", "S1"])


def test_main_passes_issue_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(pf, "run", lambda ids: calls.append(ids))
    assert pf.main(["--issue", "S12"]) == 0
    assert pf.main(["--all"]) == 0
    assert calls == [["S12"], None]
