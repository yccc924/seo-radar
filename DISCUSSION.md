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
