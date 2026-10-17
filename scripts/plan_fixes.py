"""依健檢結果產生後台修改單（changes/YYYY-MM-DD-問題編號.yaml），給 admin_edit.py 使用。

讀取：
- ISSUES.md「一、網站內容問題」表格的 S 編號問題
- research/audit/quick_audit.csv、s1_affected.txt、orphans.txt
- research/admin/*.md（admin_explore.py 的輸出），用來把前台網址對到後台編輯網址與目前狀態

支援的修正類型：
- 隱藏頁面（重複頁「保留 X，淘汰 Y」→ 把 Y 設為隱藏）與新增轉址（Y → X）
- 文字取代（「A」誤植為「B」、meta description 開頭殘留的 AI 提示詞、空白的 <h1></h1>）
- 把文章開頭的 <style> 移到文末
- 補 H1、補 JSON-LD（LocalBusiness）、補或改寫過短的 meta description

不支援（只記錄在 ISSUES.md「六、plan_fixes 無法自動處理」請使用者手動處理）：
刪除頁面、修改價格、修改商品、修改訂單或會員，以及上面沒列到的類型（例如需要真實問答的 FAQPage）。

程式產生的新文字（H1、meta description、JSON-LD）一律標 note: 'AI 撰寫，請確認內容'。
本腳本完全不連網；找不到後台編輯網址的頁面不會猜網址，只列在修改單的 skipped。

用法：
    python scripts/plan_fixes.py --issue S12
    python scripts/plan_fixes.py --all
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
ISSUES_PATH = ROOT / "ISSUES.md"
AUDIT_DIR = ROOT / "research" / "audit"
ADMIN_DIR = ROOT / "research" / "admin"
CHANGES_DIR = ROOT / "changes"

ADMIN_HOST = "sinchih.cyberbiz.co"
SITE_URL = "https://www.sinchih.com.tw"
REDIRECT_NEW_URL = f"https://{ADMIN_HOST}/admin/redirections/new"
SITE_NAME = "炘馳通訊"
AI_NOTE = "AI 撰寫，請確認內容"
SHORT_DESC_CHARS = 10

# 來源：ISSUES.md S7（已更正「數化路」誤植）
STORE_ADDRESS = {
    "@type": "PostalAddress",
    "streetAddress": "敦化路一段493號",
    "addressLocality": "北屯區",
    "addressRegion": "台中市",
    "addressCountry": "TW",
}

FORBIDDEN_WORDS = ("刪除頁面", "刪除商品", "刪除自訂頁", "價格", "售價", "定價", "改價", "/products/", "商品資料", "訂單", "會員")
FORBIDDEN_REASON = "屬於禁止自動修改的類型（刪除頁面／修改價格／修改商品／修改訂單或會員）"
UNSUPPORTED_REASON = "不在 plan_fixes 支援的修正類型"
FAQ_REASON = "FAQPage 的問答必須是真實內容並顯示在頁面上，不能由 AI 編造"
MANUAL_SECTION = "## 六、plan_fixes 無法自動處理（請使用者手動處理）"

PATH_RE = re.compile(r"`(/[^`\s]*)`")
KEEP_DROP_RE = re.compile(r"保留\s*`([^`]+)`\s*[，,]\s*淘汰\s*`([^`]+)`")
TYPO_RE = re.compile(r"「([^」]+)」誤植為「([^」]+)」")
PROMPT_PREFIX_RE = re.compile(r"開頭為：`([^`]*?：[ \t]*)")
EXCEPT_RE = re.compile(r"除(.*?)外")
EMPTY_H1 = "<h1></h1>"


# ---------------------------------------------------------------------------
# 讀取資料
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """ISSUES.md 的一列問題。"""

    id: str
    problem: str
    location: str
    fix: str = ""

    @property
    def text(self) -> str:
        """問題與位置合起來的文字（分類用）。"""
        return f"{self.problem}\n{self.location}"


@dataclass(frozen=True)
class AdminPage:
    """前台網址對應的後台資訊。"""

    admin_url: str
    title: str = ""
    status: str = ""


def _cells(line: str) -> list[str]:
    """把 Markdown 表格的一列拆成儲存格（去掉頭尾的 |）。"""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_issues(text: str) -> list[Issue]:
    """從 ISSUES.md 讀出所有 S 編號的問題列。"""
    issues: list[Issue] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 3 or not re.fullmatch(r"S\d+", cells[0]):
            continue
        issues.append(Issue(cells[0], cells[1], cells[2], cells[-1] if len(cells) >= 7 else ""))
    return issues


def front_path(url: str) -> str:
    """把前台網址或路徑統一成解碼後的路徑（去結尾斜線，首頁為 /）。"""
    path = unquote(urlsplit(url.strip()).path) if "://" in url else unquote(url.strip().split("?")[0].split("#")[0])
    path = path.rstrip("/")
    return path or "/"


def load_audit_rows(path: Path) -> dict[str, dict[str, str]]:
    """讀 quick_audit.csv，回傳 {前台路徑: 列}。"""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {front_path(row.get("decoded_url") or row.get("url") or ""): row for row in csv.DictReader(fh)}


def load_url_list(path: Path) -> list[str]:
    """讀 s1_affected.txt、orphans.txt 這類一行一個網址的清單，回傳前台路徑。"""
    if not path.is_file():
        return []
    return [front_path(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_admin_pages(admin_dir: Path) -> dict[str, AdminPage]:
    """從 research/admin/*.md 的表格找出「前台路徑 → 後台編輯網址」。

    只用表格裡實際出現的資料：同一列有 /admin/…/edit 連結就用它；
    自訂頁面列表（/pages/ 且有 id=）對到 /admin/custom_pages/<id>/edit。不自己猜其他網址。
    """
    pages: dict[str, AdminPage] = {}
    if not admin_dir.is_dir():
        return pages
    for md in sorted(admin_dir.glob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = _cells(line)
            path_cell = next((c for c in cells if re.match(r"^/(pages|blogs)/", c)), None)
            if not path_cell:
                continue
            edit = re.search(rf"https://{re.escape(ADMIN_HOST)}/admin/[^\s)|]+/edit", line)
            page_id = re.search(r"\bid=(\d+)", line)
            if edit:
                admin_url = edit.group(0)
            elif page_id and path_cell.startswith("/pages/"):
                admin_url = f"https://{ADMIN_HOST}/admin/custom_pages/{page_id.group(1)}/edit"
            else:
                continue
            status = next((c for c in cells if c in ("發佈", "隱藏")), "")
            pages.setdefault(front_path(path_cell), AdminPage(admin_url, cells[0], status))
    return pages


@dataclass
class Sources:
    """plan_fixes 用到的所有資料。"""

    audit: dict[str, dict[str, str]]
    s1_affected: list[str]
    orphans: list[str]
    admin: dict[str, AdminPage]

    @classmethod
    def load(cls, audit_dir: Path = AUDIT_DIR, admin_dir: Path = ADMIN_DIR) -> Sources:
        """從 research/ 讀取所有資料。"""
        return cls(
            audit=load_audit_rows(audit_dir / "quick_audit.csv"),
            s1_affected=load_url_list(audit_dir / "s1_affected.txt"),
            orphans=load_url_list(audit_dir / "orphans.txt"),
            admin=load_admin_pages(admin_dir),
        )


# ---------------------------------------------------------------------------
# 分類
# ---------------------------------------------------------------------------

KINDS = ("hide_redirect", "style_to_end", "typo", "prompt_prefix", "empty_h1", "add_h1", "add_desc", "short_desc", "local_business")


def classify(issue: Issue) -> tuple[list[str], str]:
    """判斷問題屬於哪些修正類型。回傳 (類型清單, 不能自動處理的原因)。"""
    text = issue.text
    if any(word in issue.problem for word in FORBIDDEN_WORDS):
        return [], FORBIDDEN_REASON
    kinds: list[str] = []
    if "重複" in issue.problem and KEEP_DROP_RE.search(issue.location):
        kinds.append("hide_redirect")
    if "<style>" in issue.problem:
        kinds.append("style_to_end")
    if TYPO_RE.search(issue.problem):
        kinds.append("typo")
    if "提示詞" in issue.problem and PROMPT_PREFIX_RE.search(issue.location):
        kinds.append("prompt_prefix")
    if EMPTY_H1 in issue.problem:
        kinds.append("empty_h1")
    if "沒有 H1" in text:
        kinds.append("add_h1")
    if "meta description" in text and "空白" in text and "<style>" not in issue.problem:
        kinds.append("add_desc")
    if "僅重複標題" in issue.location:
        kinds.append("short_desc")
    if "LocalBusiness" in issue.problem:
        kinds.append("local_business")
    if kinds:
        return kinds, ""
    if "FAQPage" in issue.problem:
        return [], FAQ_REASON
    return [], UNSUPPORTED_REASON


# ---------------------------------------------------------------------------
# 產生修改
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    """一個問題的修改單內容。"""

    issue: Issue
    changes: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def skip(self, path: str, reason: str) -> None:
        """記錄一個無法產生修改的頁面。"""
        self.skipped.append({"url": SITE_URL + path if path.startswith("/") else path, "reason": reason})


def explicit_paths(location: str) -> list[str]:
    """位置欄位中明確寫出的頁面路徑（「除…外」裡的不算；首頁寫成 `/`）。"""
    excluded = set(excluded_paths(location))
    seen: list[str] = []
    for raw in PATH_RE.findall(location):
        path = front_path(raw)
        if path.startswith("/research/") or path in excluded or path in seen:
            continue
        seen.append(path)
    return seen


def excluded_paths(location: str) -> list[str]:
    """位置欄位「除 `A` 與 `B` 外」裡的路徑。"""
    match = EXCEPT_RE.search(location)
    return [front_path(p) for p in PATH_RE.findall(match.group(1))] if match else []


def page_title(sources: Sources, path: str) -> str:
    """頁面名稱：用 quick_audit 的 title 去掉店名，沒有就用後台列表的標題。"""
    row = sources.audit.get(path)
    title = (row or {}).get("title", "").strip()
    if not title and path in sources.admin:
        title = sources.admin[path].title
    title = re.sub(rf"\s*[-|｜]?\s*{SITE_NAME}\s*$", "", title).strip()
    return title


def target_paths(issue: Issue, sources: Sources, condition: Any) -> list[str]:
    """這個問題要處理的頁面。

    位置欄位有「除…外」時，用 quick_audit.csv 中符合 condition 的自訂頁面（扣掉除外的頁面）；
    否則用位置欄位明確寫出的路徑。
    """
    if EXCEPT_RE.search(issue.location):
        excluded = set(excluded_paths(issue.location))
        return [p for p, row in sources.audit.items() if p.startswith("/pages/") and p not in excluded and condition(row)]
    return explicit_paths(issue.location)


def _admin(plan: Plan, sources: Sources, path: str) -> AdminPage | None:
    """查後台編輯網址；查不到就記在 skipped。"""
    page = sources.admin.get(path)
    if page is None:
        plan.skip(path, "找不到後台編輯網址（research/admin/ 裡沒有這頁，需先用 admin_explore.py 讀取列表），不猜網址")
    return page


def _change(issue: Issue, page: AdminPage, path: str, field_name: str, label: str, before: Any, after: Any, reason: str, **extra: Any) -> dict[str, Any]:
    """組出修改單上的一筆。"""
    item: dict[str, Any] = {
        "url": page.admin_url,
        "front_url": SITE_URL + path,
        "title": page.title or path,
        "field": field_name,
        "field_label": label,
    }
    op = extra.pop("op", "set")
    if op != "set":
        item["op"] = op
    item.update({"before": before, "after": after, "reason": f"{issue.id}：{reason}"})
    item.update({k: v for k, v in extra.items() if v})
    return item


def plan_hide_redirect(plan: Plan, sources: Sources) -> None:
    """重複頁：把淘汰的頁面設為隱藏，並新增 301 轉址到保留的頁面。"""
    issue = plan.issue
    for keep_raw, drop_raw in KEEP_DROP_RE.findall(issue.location):
        keep, drop = front_path(keep_raw), front_path(drop_raw)
        page = _admin(plan, sources, drop)
        if page is not None:
            if page.status == "隱藏":
                plan.skip(drop, "後台列表顯示已經是隱藏")
            else:
                plan.changes.append(
                    _change(issue, page, drop, "status", "頁面狀態", page.status or "發佈", "隱藏", f"重複頁面，保留 {keep}，將此頁設為隱藏")
                )
        plan.changes.append(
            {
                "url": REDIRECT_NEW_URL,
                "title": f"新增轉址 {drop} → {keep}",
                "field": "redirect",
                "field_label": "網站轉址（舊網址 → 新網址）",
                "before": {"path": "", "target": ""},
                "after": {"path": drop, "target": keep},
                "reason": f"{issue.id}：重複頁面淘汰後，把舊網址 301 轉址到保留的 {keep}",
            }
        )


def plan_style_to_end(plan: Plan, sources: Sources) -> None:
    """文章開頭的 <style> 移到文末；頁面清單用 s1_affected.txt。"""
    paths = sources.s1_affected or [p for p, r in sources.audit.items() if r.get("has_css_in_desc") == "True"]
    for path in paths:
        page = _admin(plan, sources, path)
        if page is not None:
            plan.changes.append(
                _change(
                    plan.issue, page, path, "body_html", "文章內容（HTML）", "（開頭是 <style>…</style>）", "（把開頭的 <style> 移到文末）",
                    "開頭的 <style> 污染搜尋摘要與 BlogPosting 的 description", op="move_style_to_end",
                )
            )


def plan_replace(plan: Plan, sources: Sources, field_name: str, label: str, before: str, after: str, reason: str) -> None:
    """在位置欄位寫明的頁面做文字取代。"""
    for path in explicit_paths(plan.issue.location):
        page = _admin(plan, sources, path)
        if page is not None:
            plan.changes.append(_change(plan.issue, page, path, field_name, label, before, after, reason, op="replace"))


def h1_text(sources: Sources, path: str) -> str:
    """補 H1 用的文字（取頁面標題）。"""
    return page_title(sources, path) or path.rsplit("/", 1)[-1]


def description_text(sources: Sources, path: str) -> str:
    """補 meta description 用的文字（範本產生，需人工確認）。"""
    name = page_title(sources, path) or path.rsplit("/", 1)[-1]
    if "收購" in name:
        return f"想賣掉您的 {name.replace('二手收購價', '').strip()} 嗎？{SITE_NAME}提供透明公開的二手收購行情，台中北屯實體門市現金收購。"
    return f"{name}｜{SITE_NAME}位於台中北屯，提供二手手機收購、維修、門號與新機銷售服務，歡迎到店或線上詢問。"


def plan_add_h1(plan: Plan, sources: Sources) -> None:
    """沒有 H1 的頁面：在內容最前面加上 <h1>頁面標題</h1>。"""
    paths = target_paths(plan.issue, sources, lambda row: row.get("h1_count") == "0")
    for path in paths:
        page = _admin(plan, sources, path)
        if page is not None:
            plan.changes.append(
                _change(
                    plan.issue, page, path, "body_html", "頁面內容（HTML）", "（內容沒有 <h1>）", f"<h1>{h1_text(sources, path)}</h1>",
                    "頁面沒有 H1，在內容最前面補上", op="prepend", absent="<h1", note=AI_NOTE,
                )
            )


def plan_add_desc(plan: Plan, sources: Sources, short: bool) -> None:
    """meta description 空白（或只有幾個字）的頁面：補上範本產生的描述。"""
    def condition(row: dict[str, str]) -> bool:
        desc = (row.get("meta_description") or "").strip()
        return bool(desc) and len(desc) <= SHORT_DESC_CHARS if short else not desc

    if short and not EXCEPT_RE.search(plan.issue.location):
        paths = [p for p in explicit_paths(plan.issue.location) if condition(sources.audit.get(p, {}))]
    else:
        paths = target_paths(plan.issue, sources, condition)
    for path in paths:
        page = _admin(plan, sources, path)
        if page is None:
            continue
        before = (sources.audit.get(path, {}).get("meta_description") or "").strip()
        reason = "meta description 過短（只重複標題），改寫" if short else "meta description 空白，補上"
        plan.changes.append(
            _change(plan.issue, page, path, "seo_description", "SEO 描述（meta description）", before, description_text(sources, path), reason, note=AI_NOTE)
        )


def local_business_jsonld(path: str) -> str:
    """門市頁的 MobilePhoneStore（LocalBusiness）JSON-LD；只放已知資料，不編造電話與營業時間。"""
    data = {
        "@context": "https://schema.org",
        "@type": "MobilePhoneStore",
        "name": SITE_NAME,
        "url": SITE_URL + path,
        "address": STORE_ADDRESS,
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{body}\n</script>'


def plan_local_business(plan: Plan, sources: Sources) -> None:
    """補 LocalBusiness JSON-LD：加在自訂頁面內容最後面。"""
    for path in explicit_paths(plan.issue.location):
        page = _admin(plan, sources, path)
        if page is not None:
            plan.changes.append(
                _change(
                    plan.issue, page, path, "body_html", "頁面內容（HTML）", "（內容沒有 JSON-LD）", local_business_jsonld(path),
                    "補上 MobilePhoneStore（LocalBusiness）結構化資料", op="append", absent="application/ld+json", note=AI_NOTE,
                )
            )


def build_plan(issue: Issue, kinds: Sequence[str], sources: Sources) -> Plan:
    """依分類產生一個問題的所有修改。"""
    plan = Plan(issue)
    for kind in kinds:
        if kind == "hide_redirect":
            plan_hide_redirect(plan, sources)
        elif kind == "style_to_end":
            plan_style_to_end(plan, sources)
        elif kind == "typo":
            correct, wrong = TYPO_RE.search(issue.problem).groups()  # type: ignore[union-attr]
            field_name, label = ("seo_description", "SEO 描述（meta description）") if "描述" in issue.problem else ("body_html", "頁面內容（HTML）")
            plan_replace(plan, sources, field_name, label, wrong, correct, f"錯字「{wrong}」改為「{correct}」")
        elif kind == "prompt_prefix":
            prefix = PROMPT_PREFIX_RE.search(issue.location).group(1)  # type: ignore[union-attr]
            plan_replace(plan, sources, "seo_description", "SEO 描述（meta description）", prefix, "", "刪掉 meta description 開頭殘留的 AI 提示詞")
        elif kind == "empty_h1":
            plan_replace(plan, sources, "body_html", "文章內容（HTML）", EMPTY_H1, "", "刪除多餘的空白 <h1></h1>")
        elif kind == "add_h1":
            plan_add_h1(plan, sources)
        elif kind == "add_desc":
            plan_add_desc(plan, sources, short=False)
        elif kind == "short_desc":
            plan_add_desc(plan, sources, short=True)
        elif kind == "local_business":
            plan_local_business(plan, sources)
    return plan


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    """多行文字用 | 區塊格式輸出，方便閱讀。"""


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """多行字串用 | 格式。"""
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def change_file_path(changes_dir: Path, issue_id: str, today: date) -> Path:
    """修改單檔名：changes/YYYY-MM-DD-問題編號.yaml。"""
    return changes_dir / f"{today.isoformat()}-{issue_id}.yaml"


def existing_file(path: Path) -> Path | None:
    """同名檔（不分大小寫）是否已存在。"""
    if not path.parent.is_dir():
        return None
    return next((p for p in path.parent.iterdir() if p.name.lower() == path.name.lower()), None)


def write_plan(plan: Plan, changes_dir: Path, today: date) -> Path | None:
    """把修改寫成 YAML；沒有任何修改、或同名檔已存在（不覆蓋）時回傳 None。"""
    if not plan.changes:
        return None
    path = change_file_path(changes_dir, plan.issue.id, today)
    if (found := existing_file(path)) is not None:
        print(f"⚠ {found} 已存在，不覆蓋（要重新產生請先自行改名或移走舊檔）")
        return None
    data: dict[str, Any] = {
        "description": f"{plan.issue.id}：{plan.issue.problem.replace('**', '')}",
        "created_at": today.isoformat(),
        "generated_by": "scripts/plan_fixes.py",
        "changes": plan.changes,
    }
    if plan.skipped:
        data["skipped"] = plan.skipped
    changes_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    return path


def record_manual(issues_path: Path, entries: Sequence[tuple[str, str]], today: date) -> int:
    """把不能自動處理的問題記在 ISSUES.md 最後的「六」節（已記過的不重複），回傳新增筆數。"""
    if not entries:
        return 0
    text = issues_path.read_text(encoding="utf-8")
    if MANUAL_SECTION not in text:
        text = text.rstrip("\n") + f"\n\n{MANUAL_SECTION}\n\n| 編號 | 原因 | 記錄日期 |\n|---|---|---|\n"
    section = text[text.index(MANUAL_SECTION) :]
    added = 0
    for issue_id, reason in entries:
        if f"| {issue_id} |" in section:
            continue
        line = f"| {issue_id} | {reason} | {today.isoformat()} |\n"
        text = text if text.endswith("\n") else text + "\n"
        text += line
        section += line
        added += 1
    issues_path.write_text(text, encoding="utf-8")
    return added


@dataclass
class Outcome:
    """一次執行的結果。"""

    written: list[Path] = field(default_factory=list)
    manual: list[tuple[str, str]] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)


def run(
    issue_ids: Sequence[str] | None,
    issues_path: Path = ISSUES_PATH,
    audit_dir: Path = AUDIT_DIR,
    admin_dir: Path = ADMIN_DIR,
    changes_dir: Path = CHANGES_DIR,
    today: date | None = None,
) -> Outcome:
    """產生修改單。issue_ids 為 None 表示全部（--all）。"""
    today = today or date.today()
    issues = parse_issues(issues_path.read_text(encoding="utf-8"))
    if issue_ids is not None:
        wanted = {i.upper() for i in issue_ids}
        unknown = wanted - {i.id for i in issues}
        for issue_id in sorted(unknown):
            print(f"⚠ ISSUES.md 沒有問題 {issue_id}")
        issues = [i for i in issues if i.id in wanted]
    sources = Sources.load(audit_dir, admin_dir)
    outcome = Outcome()
    for issue in issues:
        kinds, reason = classify(issue)
        if not kinds:
            print(f"{issue.id}：無法自動處理（{reason}），記錄在 ISSUES.md")
            outcome.manual.append((issue.id, reason))
            continue
        plan = build_plan(issue, kinds, sources)
        outcome.plans.append(plan)
        path = write_plan(plan, changes_dir, today)
        print(f"{issue.id}：{len(plan.changes)} 筆修改、{len(plan.skipped)} 頁無法產生")
        for item in plan.skipped[:5]:
            print(f"    略過 {item['url']}：{item['reason']}")
        if len(plan.skipped) > 5:
            print(f"    ……另有 {len(plan.skipped) - 5} 頁，詳見修改單的 skipped")
        if path is not None:
            outcome.written.append(path)
            print(f"    修改單：{path}")
            print(f"    預覽：python scripts/admin_edit.py --file {path.relative_to(changes_dir.parent).as_posix()}")
            print(f"    執行：python scripts/admin_edit.py --file {path.relative_to(changes_dir.parent).as_posix()} --apply")
    added = record_manual(issues_path, outcome.manual, today)
    if added:
        print(f"已在 ISSUES.md 新增 {added} 筆需手動處理的問題")
    return outcome


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析命令列參數：--issue 編號 或 --all（二選一）。"""
    parser = argparse.ArgumentParser(description="依 ISSUES.md 與健檢結果產生後台修改單")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue", action="append", help="問題編號，例如 S12（可重複）")
    group.add_argument("--all", action="store_true", help="處理 ISSUES.md 所有 S 編號問題")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """命令列進入點。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    run(None if args.all else args.issue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
