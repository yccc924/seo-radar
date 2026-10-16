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
