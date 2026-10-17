# 三方討論紀錄

新的寫在最上面。格式：

```
## 2026-10-20｜發言者｜主題
內容……
→ 回覆（發言者）：……
→ 決定（使用者）：……
```

發言者：使用者、網頁版 Claude、Claude Code、agy

---

## 2026-10-17｜Claude Code｜safety_gate.py 與 admin_edit.py 真人防護的幾個選擇
規格沒寫明的地方，我選了偏嚴格的做法：
- **Hook 輸入格式不確定**：工具名稱接受 `tool_name`／`toolName`；參數接受 `tool_input`／`toolInput`／`arguments`（也接受 JSON 字串）；指令欄位接受 `CommandLine`／`command`，路徑接受 `TargetFile`／`AbsolutePath`／`path` 等。同時給多個欄位時全部判定、取最嚴格。**請 agy 確認 Antigravity 實際送出的欄位名稱**。
- 指令有串接（`;`、`&&`、`||`、`|`、`&`、換行）時每一段分開判定、取最嚴格；含 `$(...)`、反引號或寫檔重新導向（`>`）一律詢問。`2>&1`、`2>$null` 不算寫檔。
- 引號會先去掉再比對，所以 `git commit -m "rm 舊檔"` 這類訊息裡出現刪除字眼也會被詢問（寧可多問）。
- `admin_edit.py` 黑名單不會擋到 `tests/test_admin_edit.py`，跑測試仍是 allow；`cookie` 是關鍵字比對，任何提到 cookie 的指令都會被擋。
- `admin_edit.py` 在預覽模式也要求終端機（規格寫「啟動時檢查」）；非終端機時回傳結束碼 2。確認 y 改成按一個鍵即可（不用按 Enter），讀取前會先清掉鍵盤緩衝區。

---

## 2026-10-17｜Claude Code｜scripts/admin_edit.py（依修改單改後台）與 scripts/plan_fixes.py（產生修改單）的幾個選擇
使用者要求的任務（不在任務清單上）。共 407 項 pytest 全數通過（新增 test_admin_edit.py 59 項、test_plan_fixes.py 36 項）；`admin_explore.py` 完全沒改。規格沒寫明的地方這樣處理：
- **修改方式（op）**：修改單多一個選填欄位 `op`。`set`（預設）＝目前的值要等於 before；`replace`＝目前的值要剛好含 1 次 before，換成 after（修錯字）；`prepend`／`append`＝目前的值不含 `absent`（例如 `<h1`、`application/ld+json`）才加上去；`move_style_to_end`＝目前內容要以 `<style>` 開頭。不符一律跳過並警告。既有的 `changes/2026-10-17-s12.yaml` 不用改就能用。
- **允許範圍**：網址只接受 `https://sinchih.cyberbiz.co/admin/custom_pages/`、`/admin/blogs/`、`/admin/redirections/` 開頭，且不能是 admin_explore 認定的敏感網址；欄位只接受 `status`、`body_html`、`seo_description`、`redirect`。其他一律拒絕。
- **找欄位**：還沒看過編輯頁的 HTML，所以依序用修改單的 `selector` → name/id 關鍵字（例如 `[status]`、`body_html`）→ 標籤文字（`field_label`、「狀態」）。下拉選單和單選鈕比對的是畫面上的文字（「發佈」「隱藏」）。內容欄位如果是 TinyMCE／CKEditor 會透過編輯器讀寫。**第一次請先跑預覽模式**，確認每筆都找得到欄位、目前的值也正確。
- **只放行一次儲存**：使用者輸入 y 後，只放行「送到同一頁路徑（編輯頁去掉 `/edit`、新增頁去掉 `/new`，可多 `.json`）」的第一個非 GET 請求，放行後立即恢復封鎖；按完儲存後不管成功與否都恢復封鎖。其他網址、其他網域的非 GET 一律擋下。
- **備份**：`backups/YYYY-MM-DD/HHMMSS_<頁面代號>_<欄位>.html`（整頁 HTML，CSRF token 已清空）＋ `.json`（欄位原本的值與該筆修改）。只在使用者確認 y 後、修改前備份。
- **轉址驗證**：新增轉址的表單送出後沒有「同一頁」可重新載入，改成開 `/admin/redirections` 列表，檢查新舊網址有沒有出現。若新轉址被排到列表第 2 頁以後，可能誤判失敗，屆時請人工確認。另外不會先檢查同一個舊網址是否已經有轉址。
- **沒給 --file**：會讀 `changes/` 底下所有修改單。已執行過的項目因為目前的值已經變了，會被當成「不符」跳過，不會重複修改。
- **plan_fixes 對後台網址的找法**：只用 `research/admin/*.md` 裡實際出現的資料（自訂頁面列表的 `id=` → `/admin/custom_pages/<id>/edit`，或同一列的 `/edit` 連結），不猜網址。目前 research/admin 沒有部落格文章的編輯連結，所以 **S1（70 篇）、S13、S14 都產生不了修改單**，只列在終端機與修改單的 `skipped`。首頁（S5）不是自訂頁面，也一樣跳過。要處理 S1 得先讀取部落格文章列表（需要另外讓 admin_explore 讀文章列表，**請使用者決定要不要做**）。
- **AI 撰寫的文字**：plan_fixes 不呼叫任何 AI，新文字用範本產生（H1 取頁面標題；meta description 仿照現有收購頁的寫法；LocalBusiness JSON-LD 只放店名、網址和 S7 更正後的地址，不編造電話和營業時間），一律標 `note: 'AI 撰寫，請確認內容'`，admin_edit 確認時會顯示這個備註。
- **不能自動處理的問題**：S2、S9（FAQ 需要真實問答）、S11，以及刪除頁面、價格、商品、訂單、會員相關問題，記在 ISSUES.md 最後新增的「六、plan_fixes 無法自動處理」表格，同一個編號不重複記錄。
- **不覆蓋**：同名修改單（不分大小寫）已存在就不覆蓋。所以 `--issue S12` 遇到現有的 `2026-10-17-s12.yaml` 會跳過；那份檔案只有隱藏、沒有轉址，要補轉址請先把舊檔改名。
- 本機試跑 `--all`（在暫存資料夾，沒動到正式的 ISSUES.md 和 changes/）會產生 S3、S4、S6、S7、S8、S10（35 筆）、S12 共 7 份修改單。

## 2026-10-17｜使用者 / agy｜iPhone 17 Pro Max 重複頁保留決定
針對 iPhone 17 Pro Max 256GB 與 512GB 的同名重複頁，使用者決定「各保留一個就好」：
- **256GB**：保留 `/pages/17-pro-max-256g`，淘汰帶時間戳記的 `/pages/17-pro-max-256g-20260414171746`。
- **512GB**：保留英文短網址 `/pages/17-pro-max-512g`，淘汰中文網址 `/pages/iphone-17-pro-max-512gb-二手收購價`。
→ 執行：已更新 `research/output/buyback_hub.html` 與 `buyback_hub_check.csv` 移除被淘汰的 2 頁，收購清單收斂為 138 頁。
→ 後續動作：請使用者在 Cyberbiz 後台將淘汰的 2 頁設為「隱藏」，並在 `/admin/redirections` 新增 301 轉址指向保留的網址。

## 2026-10-17｜Claude Code｜scripts/build_buyback_hub.py（收購價總覽 HTML）的幾個選擇
使用者要求的任務（不在任務清單上），完全不連網。規格沒寫明的地方這樣處理：
- **來源**：以 `custom_pages_index.md` 為主（有發佈／隱藏狀態，隱藏頁不收），`quick_audit.csv` 只補列表沒有的頁面（狀態碼 200）。目前兩邊都是 140 頁、網址代碼完全一致。
- **篩選**：標題含「收購價」、含 iPhone／iPad／air數字／Apple Watch、有容量（Apple Watch 例外），且不含「導覽列、收購表、總表、門市、據點、估價」。
- **連結文字**：去掉店名與「標準規格」；`air4` → `iPad Air 4`、`iPad Mini` → `iPad mini`、Apple Watch 尺寸補 `mm`（例如 `Series 10 42mm (GPS)`）；保留原標題的「二手收購價」。
- **網址**：href 用加引號的 `href="/pages/…"`，中文代碼做百分比編碼（與前台實際網址相同），避免編輯器改寫中文網址。
- **排序**：系列 iPhone 17 → 11 → SE/XR/XS → iPad → Apple Watch。iPhone 組內 Pro Max → Pro → Plus → 標準 → mini → e（16e 歸在 iPhone 16 系列），容量小到大；SE/XR/XS、iPad、Apple Watch 依上市時間由新到舊。**不確定**：「iPad Air 11」（沒標晶片）我當成 2024 年 M2 版，排在 iPad Pro M4 後面。
- **同名頁**：iPhone 17 Pro Max 512GB、256GB 各有兩頁（`/pages/17-pro-max-512g` 與 `/pages/iphone-17-pro-max-512gb-二手收購價`；`/pages/17-pro-max-256g` 與 `/pages/17-pro-max-256g-20260414171746`），兩邊前台都是 200。為了湊滿 140 頁兩頁都列出，核對 CSV 的 `note` 欄有標註。**請使用者決定保留哪一頁**（另一頁建議隱藏或轉址，總覽頁就刪掉那一行）。

## 2026-10-16｜agy｜審查 scripts/admin_explore.py（--dynamic 動態載入頁模式）通過
審查 `scripts/admin_explore.py` 與 `tests/test_admin_explore.py`（共 274 項 pytest 測試全數通過）：
- **只重讀指定的兩頁**：`--dynamic`（或 `--mode dynamic`）啟動時透過 `reset_dynamic_progress` 將 `/admin/menus` 與 `/admin/custom_pages_index`（含 `/admin/custom_pages` 分頁）從 `progress.json` 的已讀與 404 紀錄移除，只重抓這兩頁，不影響其他已讀紀錄。
- **動態等待與唯讀監聽（無問題）**：依序執行 `wait_for_load_state("networkidle")`（15 秒）→ `wait_for_selector(DYNAMIC_CONTENT_SELECTOR)`（10 秒）→ `wait_for_timeout(2000)` → `sync_form_values`，並以 `JsonResponseRecorder` 被動監聽同網域 `GET` 2xx JSON 回應（不發送任何額外請求，且維持 `RequestGuard` 攔截所有非 GET 請求）。
- **結構解析與遮蔽（無問題）**：修正 `_main_content_soup` 避免誤刪主內容區內的選單編輯元件；`menus.md` 整合 DOM、內嵌 JSON 與 GET JSON 輸出選單樹狀階層與表格（名稱、連結網址、層級），`custom_pages_index.md` 輸出自訂頁面表格（標題、網址、發佈/隱藏狀態），且所有輸出維持 `mask_sensitive` 遮蔽與 cookie 記憶體保護。

## 2026-10-16｜Claude Code｜admin_explore.py 新增 --dynamic（重讀 menus、custom_pages_index）的幾個選擇
使用者要求的任務（不在任務清單上）。上次 --lists 讀這兩頁只抓到說明文字（內容由 JS 動態載入）。規格沒寫明的地方這樣處理：
- **重讀**：啟動時把 `/admin/menus`、`/admin/custom_pages_index`、`/admin/custom_pages` 及其任何 query 版本從 progress.json 的已讀與 404 紀錄移除，其他紀錄不動。
- **等待**：每頁 `networkidle`（15 秒）→ `wait_for_selector`（10 秒，`table tbody tr`、`.dd-item`、`.tree-node`、`[data-react-class] *`、`a[href*='/pages/']` 等任一出現）→ 固定 2 秒；逾時只記錄、不中斷。
- **GET JSON**：用 `page.on("response")` 被動篩選同網域、GET、2xx、content-type 含 json、非敏感網址的回應，離開事件處理後才讀內容；不發任何額外請求，headers 只看 content-type。輸出只列路徑，不列 query。
- **主內容區**：只移除 `find_menu_container` 找到的那一個左側選單；若它在 `<main>`／主內容區裡面（非退回整頁）就視為選單編輯元件而保留。頂部導覽列只認 navbar 等 class、role=banner，以及直接放在 body 下的 header/nav。
- **選單來源**：DOM（巢狀 ul/li、.dd-list、aria-level／data-level／縮排 div、有名稱與連結欄的表格）＋內嵌 JSON＋GET JSON，各自標示來源，項目完全相同的群組只留一份。後台連結（/admin/…）不當成選單目標；沒有任何連結的群組不輸出。JSON 裡沒有名稱的項目陣列以「JSON 欄位：xxx」標示，可能混入編輯器的「連結目標選項」（例如所有頁面清單），看來源欄判斷。
- **分頁**：只跟 HTML 上實際有的 `custom_pages_index?page=N`／`custom_pages?page=N` 連結（N≥2），兩者都寫進 custom_pages_index.md；若分頁是沒有 href 的 JS 按鈕就讀不到（依規則不點擊、不自己拼網址）。
- **限制**：若 Cyberbiz 用 POST 載入這兩頁的資料（像 custom_collections 的 `search_products`），會被唯讀攔截器擋下而抓不到，輸出檔會寫明，請看 explore.log 的「已擋下非 GET 請求」。

## 2026-10-16｜agy｜審查 scripts/admin_explore.py（--lists 列表頁模式）通過
審查 `scripts/admin_explore.py` 與 `tests/test_admin_explore.py`（共 240 項 pytest 測試全數通過）：
- **唯讀與請求攔截（無問題）**：選單模式與列表頁模式共用 `_run_with_page`，在開啟任何頁面前即註冊 `page.route("**/*", guard.handle)`，僅放行 `GET`，其餘 HTTP 方法一律 `route.abort()`。`sync_form_values` 僅在本地 DOM 將欄位 property 同步至 attribute 供 `page.content()` 讀取，不觸發任何表單送出或網路請求。
- **範圍與分頁限制（無問題）**：僅讀取指定的 9 個列表頁（並支援從 `menu.csv` 讀取「商品標籤管理」網址 `https://sinchih.cyberbiz.co/admin/product_tags`），分頁僅跟隨同路徑 `?page=N`（N≥2），不進入 `/edit`、`/new` 或單一項目子路徑，且單次執行上限強制鎖定 `MAX_LIST_PAGES = 50` 頁。
- **Cookie 與敏感資訊遮蔽（無問題）**：cookie 注入後立即 `cookies.clear()`，不印出、不寫檔；輸出 Markdown 前透過 `mask_sensitive` 與 `mask_field_value` 將 email、市話、手機、API 金鑰、secret、token 遮蔽為 `***`，同時保留 `G-`、`GTM-` 追蹤 ID 與站內路徑。

## 2026-10-16｜Claude Code｜admin_explore.py 新增 --lists（讀 9 個列表頁）的幾個選擇
使用者要求的任務（不在任務清單上），規格沒寫明的地方這樣處理：
- **分頁判定很嚴格**：只接受同一路徑、query 只有 `page=N`（N≥2）的連結；`?page=2&sort=…`、子路徑（如 `/blogs/12/articles?page=2`）一律不跟。若實跑發現 Cyberbiz 分頁帶其他參數，再放寬。
- **主內容區怎麼找**：先找 `<main>`／`role=main`，其次 id/class 為 `content-wrapper`、`main-content`、`page-content` 等的元素（取文字最多、且不含左側選單者），都找不到才用整頁並移除 `<header>`、`<nav>` 與選單。第一次實跑後要人工看一下輸出的 .md 是否混進選單文字。
- **表單欄位值**：讀 HTML 前用 `page.evaluate` 把欄位目前的值寫回 HTML 屬性（只改瀏覽器裡的 DOM，不送出、不發請求），否則 Vue/JS 填的值在 `page.content()` 看不到。隱藏欄位、密碼、按鈕與 CSRF token 不輸出。
- **遮蔽規則**：email、台灣手機與市話、`API Key:`／`token=` 這類寫法的值、常見金鑰格式（`AIza…`、`sk_live_…`）、32 字元以上英數混合長字串，以及欄位名稱或標籤含 key/secret/token/password/金鑰/密碼的欄位值，一律換成 `***`。`G-`、`GTM-`、`UA-`、`AW-` 追蹤 ID 與網址路徑不遮，網址只遮 query 中的敏感值。保守起見，以 0 開頭、8～10 位的數字（例如某些商品編號）也可能被當成電話遮掉。
- **續傳的限制**：分頁網址是讀第 1 頁時才發現的；若上次讀完第 1 頁就中斷，下次第 1 頁會被跳過，後面的分頁也就不會讀到。要完整重讀請刪除 `research/admin/progress.json`（第 1 頁會重寫整個主題檔，分頁接在後面）。
- 列表頁模式與選單模式共用同一個 `progress.json`。

## 2026-10-16｜Claude Code｜scripts/admin_explore.py（後台唯讀探索第一步）的幾個選擇
使用者要求的任務（不在任務清單上），規格沒寫明的地方這樣處理：
- **cookie 格式**：沒有權限讀 `elevated_cookies.py` 原始碼，所以 `to_playwright_cookies` 同時接受 `{name: value}`、dict 清單、有 name/value 屬性的物件；只留 `cyberbiz.co` 網域，且不帶 `expires`（瀏覽器關閉即失效）。第一次實跑若格式不符，會停在「沒有取得 cookie」或「注入 cookie 失敗」，不會印出內容。
- **左側選單怎麼找**：還沒看過 Cyberbiz 後台的 HTML，先用 id/class 含 `sidebar`、`side-menu`、`sidenav` 等線索的元素，其次 `<aside>`、`<nav>`，同分取連結最多的；都找不到就用整頁連結並在終端機提示。第一次實跑後要人工看一下 `menu.csv` 是否正確。
- **停止條件多加幾項（保守）**：401、其他非預期的 4xx、載入逾時或失敗、被導到後台以外的網址，也一律立即停止不重試。
- **驗證碼偵測**用字串比對（`recaptcha`、`captcha`、`驗證碼` 等）；若後台每頁都內嵌 reCAPTCHA 腳本會造成誤停，屆時再調整。
- **敏感路徑過濾器**除了訂單、會員、金流，也排除登出（`logout`、`sign_out`）與 `delete`、`destroy`，因為用 GET 開登出網址就會把帳號登出。
- **續傳**：404 的頁面也算「處理過」，下次不再重試；要重讀首頁請刪除 `research/admin/progress.json`。
- 終端機訊息同時寫到 `research/admin/explore.log`（已在 .gitignore）；任何例外只顯示例外類型，不顯示訊息，避免夾帶 cookie。

## 2026-10-16｜Claude Code｜quick_audit.py 改為隨機等待 2～5 秒
依 CLAUDE.md 規則，每頁間隔改為 `random.uniform(2.0, 5.0)`，robots.txt 的 Crawl-delay 更長時以它為準。原本的 `--delay` 參數拿掉了，避免有人設成低於 2 秒。

## 2026-10-16｜Claude Code｜scripts/quick_audit.py 的幾個選擇
使用者要求的一次性只讀檢查腳本（不在任務清單上），規格沒寫明的地方這樣處理：
- robots.txt 讀不到（5xx 或連線失敗）時整站不爬；404 視為全允許；Crawl-delay 若大於 1 秒以它為準。
- 不跟隨轉址，只記錄狀態碼與轉址目標（sitemap 裡的網址照理不該轉址）。
- 孤兒頁的候選只用這次受檢的網址（首頁、部落格、自訂頁），且只看受檢頁面上的連結；被商品頁或分類頁連到的頁面仍可能被列為孤兒。頁面連到自己不算。
- 網址比對：統一 https、忽略 www.、路徑解碼、去掉 query、# 與結尾斜線。
- orphans.txt 寫解碼後的網址方便閱讀；CSV 用 UTF-8 with BOM，Excel 開啟不亂碼；多一個 `error` 欄位記錄被 robots 擋下、轉址、連線失敗等。

## 2026-10-16｜agy｜根據 R1 與 R3 研究結果，建議調整健檢規格
根據 `research/cyberbiz.md`（R1）與 `research/site-snapshot.md`（R3）的實測結論，建議在實作 `checks/` 健檢規則時做以下規格調整：
1. **`canonical` 與 `noindex`（J5）**：Cyberbiz 系統會為每個頁面自動產生預設指向自身的 `<link rel="canonical">`，且單頁後台編輯器沒有獨立欄位可手動修改 `canonical` 或勾選 `noindex`（除非下架頁面或改底層 Liquid 模板）。建議將 J5 標註為 **`can_fix_in_cyberbiz = False`（無法直接在後台修改）**，並將嚴重度設為「低」（僅在發現異常指向其他網域或意外出現 `noindex` 時提醒）。
2. **`robots.txt` 與 `sitemap.xml`**：兩者皆由 Cyberbiz 系統底層自動產生與託管，後台無法編輯，爬蟲只需讀取遵守，不必列為需要人工修改的健檢問題。
3. **JSON-LD 結構化資料（J4）**：
   - 商品頁（`/products/`）系統已內建 `Product`，部落格（`/blogs/`）已內建 `BlogPosting`（應視為符合 `Article` 要求）。
   - 門市頁（`/pages/來訪我們`）缺 `LocalBusiness`、收購頁（`/pages/...`）缺 `FAQPage`，皆可透過頁面編輯器的「自訂 HTML」區塊貼入 `<script type="application/ld+json">` 補齊，因此這兩項應標為 **`can_fix_in_cyberbiz = True`（可修改）**。
4. **新增 J9（檢查 `meta description` 與 JSON-LD `description` 是否含 CSS / 程式碼）**：R3 實測發現部落格文章因開頭寫了 `<style>`，導致舊文章的 `meta description` 與新舊文章 `BlogPosting` JSON-LD 的 `description` 誤抓 `body { font-family...` 或 `.article-content { ...` 等 CSS 語法。這在後台只要把 `<style>` 移到文章底部並手寫 SEO 簡述即可修復（**可修改，嚴重度：高**），已新增至 `TASKS.md` 的 J9。

## 2026-10-16｜Claude Code｜C1 骨架的幾個選擇
規格沒寫明的地方，我選了最簡單的做法：
- pytest 設定放在 `pyproject.toml`（`pythonpath = ["src"]`），不用安裝套件就能跑測試。
- 多加了一個 `src/seo_radar/config.py`，統一從 `.env` 讀設定，之後 C3、C5、C8 都從這裡取值。環境變數優先於 `.env`。
- 執行和測試的套件都放在同一個 `requirements.txt`，沒有另外拆開發用清單。
- 爬蟲預設網址用 `https://www.sinchih.com.tw`，GSC 資源預設 `sc-domain:sinchih.com.tw`；等 R2、R3 確認後再調整 `.env.example`。

## 2026-10-16｜網頁版 Claude｜開工
規格書和任務清單已完成。順序：
1. 使用者完成階段 0 的準備
2. agy 先做 R1～R4 研究
3. Claude Code 讀完研究報告後從 C1 開始
4. C6 完成後，使用者把 J1～J8 貼給 Jules
