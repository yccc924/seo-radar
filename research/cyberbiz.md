# R1：Cyberbiz 平台 SEO 可修改項目盤點

## 重點結論（三行摘要）
1. **多數核心 SEO 欄位皆可直接修改**：商品頁、商品分類頁、部落格文章與自訂頁面（`/pages/`）的 `title`、`meta description`、網址後綴（Slug）、內文 H1 與圖片 `alt`，以及自訂 HTML / JSON-LD 結構化資料，皆可在 Cyberbiz 後台免費直接修改。
2. **系統底層檔案無法直接修改**：根目錄的 `robots.txt` 與自動產生的 `/sitemap.xml` 由 Cyberbiz 系統統一託管控制，後台不開放直接編輯檔案內容；但系統預設已自動產生標準 Sitemap 並放行搜尋引擎爬蟲。
3. **進階全站 `<head>` 與模板修改需視版型權限**：單頁插入 JSON-LD（如 `LocalBusiness`、`FAQPage`）可直接用「自訂 HTML」區塊免費完成；但若要直接修改底層 `theme.liquid` 全站模板或調整系統預設輸出的 `BlogPosting` / `Product` JSON-LD 邏輯，則取決於店家使用的版型與方案是否開放「CSS/HTML 原始碼編輯器」（部分進階權限需高階付費方案或聯繫客服確認）。

---

## 一、給新手的背景說明：在 Cyberbiz 改 SEO 是怎麼運作的？

Cyberbiz 是一套「開店平台（SaaS）」，就像租用一間裝潢好的店面：
- **你能自己佈置的部分（可改）**：每件商品的標題、簡介、照片說明（圖片 `alt`）、文章內容，以及在頁面裡貼入額外的程式碼區塊（例如自訂 HTML 與結構化資料 JSON-LD）。
- **大樓管委會統一管理的部分（不能改）**：網站最底層的系統設定檔（例如 `robots.txt` 爬蟲規則檔、`sitemap.xml` 網站地圖自動產生邏輯），這些由 Cyberbiz 官方維護，店家無法任意改寫，以免弄壞整個網站。

當我們的「SEO 雷達」做完網站健檢後，必須知道哪些問題是**我們自己進後台花 3 分鐘就能改好**的，哪些是**平台限制不用白費力氣**的。

---

## 二、Cyberbiz 各項 SEO 設定可修改性總表

| 檢查項目 | 狀態標註 | 在 Cyberbiz 後台怎麼改？（給新手的操作路徑） | 備註與限制說明 |
| :--- | :---: | :--- | :--- |
| **1. 首頁 Title / Meta Description** | **可改** | 後台 ➔「網站外觀」➔「套版主題管理」➔「網站設定（全站設定）」填寫網站標題與網站簡述；或至「管理中心」➔「一般設定」設定網站名稱。 | 系統會自動在各分頁 Title 後方加上全站網站名稱（例如：`... 炘馳通訊`）。 |
| **2. 商品頁 Title / Meta Description** | **可改** | 後台 ➔「商品」➔「所有商品」➔ 點選特定商品 ➔「設定」頁籤 ➔ 下滑至「**SEO 設定**」填寫「網頁標題 (Title)」與「網頁簡述 (Description)」。 | 若未手動填寫，系統會自動抓取商品名稱與商品描述前段文字作為預設值。 |
| **3. 商品分類頁（群組）Title / Description** | **可改** | 後台 ➔「商品」➔「商品自訂分類」或「條件分類」➔ 點選「編輯群組」➔「**Meta Tag 設定**」。 | 可針對 `/collections/...` 分類頁獨立設定關鍵字標題與描述。 |
| **4. 部落格文章與自訂頁（`/pages/`）Title / Description** | **可改** | 1. 部落格：後台 ➔「網站外觀」➔「部落格管理」➔ 編輯文章 ➔ 下滑至「**SEO 與轉貼圖片設定 (Meta Tags)**」。<br>2. 自訂頁：後台 ➔「網站外觀」➔「自訂頁面」➔ 編輯頁面內的 SEO 設定。 | **重要避坑**：部落格若未填寫或若系統抓取文章開頭作為 JSON-LD `description`，當文章開頭寫了 `<style>` CSS，會把 CSS 原始碼當成摘要輸出！務必手動填寫 SEO 描述並將 `<style>` 移至文末或改為行內樣式。 |
| **5. 網頁標題 H1（`<h1>`）** | **可改** | 1. **商品頁 / 部落格文章**：系統預設會將「商品名稱」與「文章標題」自動轉成頁面唯一的 `<h1>`。<br>2. **首頁 / 自訂頁面（如收購價目頁）**：在頁面編輯器（原始碼模式或自訂 HTML 區塊）中手動加入 `<h1>主標題文字</h1>`，或在拖拉式區塊將主標題標籤設為 H1。 | 實測發現 `sinchih.com.tw` 的**首頁**與部分**自訂頁面（如收購總表、門市頁）**沒有任何 `<h1>`，而**單機收購價目頁**（如 iPhone 16 Pro Max 收購頁）則已成功透過自訂 HTML 放入 `<h1>`。證明完全可改！ |
| **6. 自訂 HTML（頁面內嵌）** | **可改** | 在「自訂頁面」、「部落格文章」或「商品描述」的文字編輯器點選 `<>`（原始碼），或使用新版拖拉頁面的「**自訂 HTML**」元件直接貼入程式碼。 | 可用來製作收購價目表、按鈕、獨立 H1 標題，以及嵌入單頁專屬的 `<script type="application/ld+json">` 結構化資料。 |
| **7. 全站 `<head>` 語法與模板（`theme.liquid`）** | **可改 / 要付費方案（部分限制）** | 1. **透過 GTM / 第三方整合（可改）**：後台 ➔「第三方整合」➔「谷歌 Google 設定」填入 Google Tag Manager 容器 ID，即可間接往全站注入腳本。<br>2. **直接改 `theme.liquid`（視版型與方案而定）**：後台 ➔「網站外觀」➔「套版主題管理」➔「選擇操作」➔「CSS/HTML 編輯器」。 | 一般標準版型可透過「CSS/HTML 編輯器」修改 `theme.liquid` 的 `<head>`；但若使用新版視覺化拖拉版型或特定入門方案，是否開放直接改底層 Liquid 模板**不確定**（部分進階原始碼編輯權限需依合約方案或請 Cyberbiz 客服開啟）。 |
| **8. 結構化資料（JSON-LD）** | **可改（內建 + 手動擴充）** | 1. **系統自動內建（不能直接改底層格式）**：首頁內建 `Organization` 與 `WebSite`；商品頁（`/products/`）內建 `Product` 與 `Offer`；部落格文章（`/blogs/`）內建 `BlogPosting`。<br>2. **手動新增（可改）**：門市頁的 `LocalBusiness`、常見問題與收購頁的 `FAQPage`、文章補充的 `Article` / `FAQPage`，皆可在該頁面的「原始碼 / 自訂 HTML」貼入 `<script type="application/ld+json">...</script>`。 | Google 官方支援將 `<script type="application/ld+json">` 放在 `<body>` 內，與放在 `<head>` 效果完全相同。因此不需要改底層模板，直接在自訂頁面或文章內貼入即可生效！ |
| **9. 圖片替代文字（Image `alt`）** | **可改** | 1. **傳統編輯器（商品描述/文章）**：對圖片按滑鼠右鍵 ➔「影像屬性」➔ 在「**替代文字 (Alt)**」欄位輸入文字。<br>2. **拖拉式頁面元件**：點擊圖片區塊 ➔ 右側設定面板填寫「圖片替代文字」。<br>3. **商品主圖**：系統預設會自動帶入商品名稱作為主圖 `alt`。 | 實測發現商品頁的主圖系統已自動帶入商品名稱 `alt`，但商品描述內自行插入的圖片、部落格配圖或版型裝飾圖常漏填 `alt`，可從後台補齊。 |
| **10. 網址結構與自訂代號（URL Slug）** | **可改（後綴可改，前綴固定）** | 在商品、分類、部落格文章或自訂頁面的編輯畫面中，可自訂網址後綴（Slug / 自訂網址）。若改動舊網址，可至後台設定 **301 轉址**。 | **前綴固定不能改**：系統強制分為 `/products/`、`/collections/`、`/categories/`、`/blogs/`、`/pages/`。<br>**後綴可改**：建議新建頁面時一律使用英文與數字短代號（如 `/pages/iphone-16-pro-256g`），避免使用中文字元導致網址被轉碼為 `%E4%BA%8C...` 長串編碼。 |
| **11. Canonical（標準網址）與 `noindex`** | **不能改（單頁介面無獨立欄位）** | 系統會為每個頁面**自動產生預設的 `<link rel="canonical">`** 指向該頁自身網址。後台單頁編輯器沒有獨立的 Canonical 或 `noindex` 勾選欄位。 | 若有特殊頁面不想被收錄，最簡單的作法是將該商品/頁面改為「下架 / 隱藏」，或透過 Google Search Console 移除網址工具處理。至於能否透過頁面自訂 HTML 動態覆蓋，因爬蟲以 `<head>` 為主，單頁內嵌效果**不確定**。 |
| **12. `robots.txt` 檔案** | **不能改** | 位於 `https://www.sinchih.com.tw/robots.txt`，由 Cyberbiz 系統底層自動產生與託管，後台不開放手動編輯。 | 實測目前 `robots.txt` 內容非常健康：封鎖了 `/admin/`、`/cart`、`/account`、`/user/sign_in`，對所有搜尋引擎開放（`search=yes, ai-input=yes`），並在最下方正確宣告了 `Sitemap` 位置。 |
| **13. `sitemap.xml` 位置與內容** | **不能改（系統自動更新）** | 固定位置：`https://www.sinchih.com.tw/sitemap.xml` | 系統會在新增/上架商品、分類、文章與自訂頁面時**自動更新**此檔案（目前共收錄 1,042 個網址）。不需人工維護，只需將此網址提交至 Google Search Console 即可。 |

---

## 三、對「SEO 雷達（seo-radar）」開發團隊的實作建議

為了讓功能 2（網站健檢）標註「在 Cyberbiz 能不能改」時精準明確，建議在程式碼的健檢規則（`checks/`）中採用以下對應基準：

1. **可直接標註「可改（後台直接設定）」的問題**：
   - `title` 缺失、過長、過短或跨頁重複（後台 SEO 設定欄位可改）
   - `meta description` 缺失、過長、過短、跨頁重複，或抓到 CSS 語法開頭（後台 SEO 設定欄位可改）
   - `H1` 缺失或有多個 `H1`（頁面編輯器或自訂 HTML 區塊可改）
   - 圖片缺少 `alt` 屬性（編輯器影像屬性或拖拉元件設定可改）
   - 缺少 `LocalBusiness`（門市頁）或 `FAQPage`（問答/收購頁）等結構化資料（可在該頁透過自訂 HTML 貼入 `<script type="application/ld+json">` 補齊）
   - 頁面內出現壞掉的連結 `4xx / 5xx`（可在編輯器內修正連結，或設定 301 轉址）

2. **應標註「部分可改 / 系統內建」的問題**：
   - 部落格文章內建的 `BlogPosting` JSON-LD 若 `description` 欄位抓到文章開頭的 `<style>` CSS：雖然不能直接改 Cyberbiz 底層产生 `BlogPosting` 的程式邏輯，但**只要把文章內容開頭的 `<style>` 移到文章最底部（或先把摘要文字寫在最前面）**，系統自動抓取的前 50 字就會恢復正常文字！
   - `canonical` 與 `noindex`：Cyberbiz 系統已自動輸出標準 `canonical`，若檢查出異常需檢視網址結構或下架重複頁面，後台無單頁手動改寫欄位。

---

## 四、參考來源連結
- [炘馳通訊公開 robots.txt（實測驗證）](https://www.sinchih.com.tw/robots.txt)
- [炘馳通訊公開 sitemap.xml（實測驗證）](https://www.sinchih.com.tw/sitemap.xml)
- [CYBERBIZ 官方首頁與系統功能介紹](https://www.cyberbiz.io/)
- [CYBERBIZ 幫助中心（支援文件庫：SEO 設定、Meta Tag、部落格管理、GTM 第三方整合）](https://support.cyberbiz.io/)
- [Google 搜尋中心：結構化資料（JSON-LD）一般指南](https://developers.google.com/search/docs/appearance/structured-data/sd-policies?hl=zh-tw)
