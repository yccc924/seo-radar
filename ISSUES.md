# 問題總表

最後更新：2026-10-16（依 `scripts/quick_audit.py` 全站 289 頁實測結果更新）

**確認程度**：✅ 已確認　❌ 不存在　🔎 抽查發現，範圍未知　❓ 待使用者確認
**修法**：👤 手動　🤖 Playwright 批量　🚫 無法修改

---

## 一、網站內容問題

| 編號 | 問題 | 位置 | 嚴重度 | 確認程度 | 修法 |
|---|---|---|---|---|---|
| S1 | 文章開頭的 `<style>` 污染搜尋摘要與 BlogPosting 的 description | 部落格（共 124 篇文章 + 1 個列表頁，**70 篇受影響**：其中 10 篇同時污染 `meta description` 與 `BlogPosting`，60 篇污染 `BlogPosting`；完整清單見 `research/audit/s1_affected.txt`） | 高 | ✅ 已確認（70 / 124 篇） | 🤖 後台 `/admin/blogs` 把 `body_html` 的 `<style>` 移到文末（未填 `article-seo-description` 者一併補齊） |
| S2 | 標題為「收購表ANDROID 炘馳通訊」（導覽列將此頁作為「Android 收購表」，但網址 Slug 設為 `/pages/收購表-apple` 造成網址與內容不一致） | `/pages/收購表-apple` | 高 | ✅ 已確認（1 頁） | 👤 修正網址 Slug 或標題（若改網址可在 `/admin/redirections` 新增轉址） |
| S3 | meta description 空白 | `/pages/收購表-apple` | 高 | ✅ 已確認（1 頁） | 👤 |
| S4 | 沒有 H1 | `/pages/收購表-apple` | 中 | ✅ 已確認（1 頁） | 👤 |
| S5 | 沒有 H1 | 首頁 `/` | 中 | ✅ 已確認（1 頁） | 👤 |
| S6 | 沒有 H1 | `/pages/來訪我們` | 中 | ✅ 已確認（1 頁） | 👤 |
| S7 | 描述中「敦化路」誤植為「數化路」（實際內容為：`台中市北屯區數化路一段493號`） | `/pages/來訪我們` | 中 | ✅ 已確認（1 頁） | 👤 |
| S8 | 沒有 LocalBusiness（MobilePhoneStore）結構化資料 | `/pages/來訪我們` | 高 | ✅ 已確認（0 個 JSON-LD） | 👤 自訂 HTML |
| S9 | 自訂頁完全沒有結構化資料，可補 FAQPage | 163 個自訂頁（實測 **163 / 163 頁**皆為 0 個 JSON-LD，其中含 140 個單機收購頁） | 中 | ✅ 已確認（163 / 163 頁） | 🤖 自訂 HTML |
| S10 | 其他自訂頁（`/pages/`）的標題、描述、H1 問題 | 除 `/pages/收購表-apple` 與 `/pages/來訪我們` 外之 161 個自訂頁：<br>• **無空白 title，亦無 CSS 污染（0 頁）**<br>• **11 頁 `meta description` 完全空白**（含單機收購頁 `/pages/14-256g` 及 10 個導覽/說明頁）<br>• **7 頁 `meta description` 僅重複標題 4～6 字**（如 `/pages/常見問題` 描述僅「常見問題」4 字）<br>• **17 頁沒有 H1**（含 `/pages/phone-valuation` 手機線上估價、`/pages/second-hand-apple` 等導覽與條款頁；其餘 140 個單機收購頁皆已有 1 個 H1） | 中～高 | ✅ 已確認（缺描述 11 頁、過短描述 7 頁、缺 H1 17 頁） | 👤 手動補齊這 20 餘個非單機自訂頁 + `/pages/14-256g` |
| S11 | **【新發現】140 個單機收購價目頁全部是「孤兒頁」（無任何站內 `<a href>` 連結指向）** | 140 個單機型收購頁（加上未放到選單的頁面共 147 個 `/pages/` 與 110 篇舊文章，清單見 `research/audit/orphans.txt`）。主因是 `/pages/phone-valuation` 用 JS 互動估價，沒有透過標準 `<a href>` 連到各單機收購頁，導致 Google 僅能靠 Sitemap 發現、無內部連結權重傳遞 | 高 | ✅ 已確認（147 個自訂頁、110 篇部落格） | 👤 / 🛠 在估價頁或收購總表下方加入各機型收購頁的 `<a href>` 連結清單 |
| S12 | **【新發現】重複的單機收購頁（Title、Meta Description 與內容完全重複）** | 共 2 組（4 頁）：<br>1. `iPhone 17 Pro Max 512GB`：保留 `/pages/17-pro-max-512g`，淘汰 `/pages/iphone-17-pro-max-512gb-二手收購價`<br>2. `iPhone 17 Pro Max 256GB`：保留 `/pages/17-pro-max-256g`，淘汰 `/pages/17-pro-max-256g-20260414171746`<br>（另有首頁與 `/pages/about-us` 的 `meta description` 完全重複） | 中 | ✅ 已定案待執行（總覽 HTML 已移除淘汰頁） | 👤 後台將淘汰頁設為隱藏，並在 `/admin/redirections` 新增 301 轉址 |
| S13 | **【新發現】AI 提示詞（Prompt）未刪乾淨，直接連同冒號貼進 `meta description`** | `/blogs/手機知識學堂/20260301`，目前 `meta description` 開頭為：`建議字數控制在 150 字以內，包含核心亮點與行動呼籲： 蘋果史上最平價 MacBook...` | 中 | ✅ 已確認（1 篇） | 👤 後台刪掉開頭提示詞 |
| S14 | **【新發現】部落格文章出現 2 個 H1（多出一個空白 `<h1></h1>`）** | `/blogs/手機知識學堂/20260321-1`（H1 數量為 2） | 低 | ✅ 已確認（1 篇） | 👤 後台刪除文章內多餘的空 `<h1>` |

**S9 注意**：FAQPage 的問答內容必須同時顯示在頁面上，不能只放在程式碼裡。要先準備好每類收購頁的真實問答（例如估價方式、需要帶什麼證件、付款方式），不能讓 AI 編造。

## 二、無法修改（不列入待辦）

| 項目 | 原因 |
|---|---|
| robots.txt | Cyberbiz 系統產生，狀態正常 |
| sitemap.xml | Cyberbiz 系統自動更新 |
| 網址第一層路徑（`/products/`、`/pages/`） | 平台固定 |
| 單頁 canonical | 平台預設，後台無欄位 |

## 三、流程與工具問題

| 編號 | 問題 | 確認程度 | 影響 | 處理方式 |
|---|---|---|---|---|
| P1 | Gemini 文章技能把 `<style>` 放在 HTML 最上方 | ✅ 已確認 | 修完舊文章後，新文章會繼續產生 S1 問題 | 👤 修改 Gemini 那邊的技能，把樣式改放文末 |
| P2 | 發文時可能沒有填 Cyberbiz 的 SEO 描述欄位 | ✅ 已確認（後台欄位為 `article-seo-description`；124 篇文章中，**早期 11 篇未填**導致 `meta description` 直接抓 `body_html` 前 50 字且其中 10 篇抓到 CSS；**近期 113 篇皆有填寫**，故近期文章 `meta description` 正常，僅 `BlogPosting` JSON-LD 仍直接抓 `body_html` 開頭而受 `<style>` 影響） | 欄位空白時 Cyberbiz 會抓文章開頭當描述 | 👤 繼續維持發文必填「網站描述」的習慣，並補齊早期 11 篇未填的文章 |
| P3 | 沒有 GA4，只有 Cyberbiz 後台瀏覽量 | ❌ 不存在（✅ 後台 `/admin/platforms/google` 已綁定 `GTM-N9D7WM2X` 與 Google Ads 轉換追蹤 `16883831324`，且前台 **289 / 289 頁 HTML 皆已載入 `G-F37J0MY28N`**） | 若該衡量 ID 為店家自有則不需重裝，只需確認權限 | 👤 請使用者確認 `G-F37J0MY28N` 是否為自己 Google 帳號下的 GA4 資源 |
| P4 | Search Console 服務帳戶尚未設定 | ❓ 待使用者確認 | 擋住 C3 之後的開發 | 👤 照 `research/gsc-api.md` 設定 |
| P5 | 沒有 Open API 模組 | ✅ 已確認（後台 `/admin/shop_add_ons` 顯示已安裝擴充服務為 **0 個**，且左側選單無任何 Open API 項目） | 無法用官方 API 批量修改 | 改走 Playwright；👤 詢問客服是否允許自動化操作後台 |

## 四、Playwright 批量修改的規則

適用於 S1、S9 及之後所有會修改正式網站的腳本：

1. **預覽模式為預設**：只列出每頁會改什麼，不存檔；要加參數才會真的執行
2. **先備份**：修改前把原始 HTML 存到 `backups/日期/`，此資料夾加入 `.gitignore`
3. **先 1 篇、再 5 篇、再全部**，每階段使用者確認前台正常才繼續
4. **只改清單上的頁面**：清單來自爬蟲與健檢結果，不憑推測全部套用
5. **限速**：每頁間隔至少 3 秒
6. **登入由使用者手動完成**：腳本使用 Playwright 持久化瀏覽器設定檔，帳號密碼不寫進程式、`.env` 或任何檔案
7. **每次執行都留紀錄**：哪些頁面、改了什麼、成功或失敗

## 五、建議處理順序

1. 👤 手動修 S2～S8、S12～S14，以及 S10 中缺描述的單機收購頁 `/pages/14-256g`（約 25 分鐘）
2. 👤 處理 P4（Search Console）與確認 P3（`G-F37J0MY28N` GA4 帳號歸屬）
3. 🛠 做出爬蟲與健檢（C5、C6、J9）
4. 🛠 寫 Playwright 修正腳本，依第四節規則處理 `research/audit/s1_affected.txt` 的 70 篇部落格文章（S1）
5. 👤 準備收購頁 FAQ 真實內容與內部連結清單 → 🛠 批量處理 S9 與 S11（孤兒頁內部連結）
6. 👤 修改 Gemini 文章技能（P1），避免新文章再出問題
