# R3：炘馳通訊（sinchih.com.tw）公開頁面 SEO 現況快照

## 重點結論（三行摘要）
1. **網站地圖結構清晰，共 1,042 頁**：全站 `sitemap.xml` 收錄了 649 個商品頁（`/products/`）、163 個自訂頁面（`/pages/`，多為單機型二手收購價目頁）、126 篇部落格文章（`/blogs/`）、95 個商品集合頁（`/collections/`）、8 個分類頁與首頁。
2. **發現三大立即可修的高效益 SEO 漏洞**：① **首頁、收購總表頁與門市據點頁缺少 `<h1>` 標題**；② **部落格文章內建 `BlogPosting` JSON-LD（及舊文章的 `meta description`）因文章開頭寫了 `<style>` CSS，導致搜尋摘要變成 `body { font-family...` 程式碼**；③ **Apple 收購總表頁（`/pages/收購表-apple`）的 Title 誤植為 `收購表ANDROID 炘馳通訊` 且無 `meta description`**。
3. **結構化資料（JSON-LD）補齊空間大**：商品頁已有完整的 `Product` + `Offer` 標記，首頁已有 `Organization` + `WebSite`；但**所有收購價目頁與門市據點頁（`/pages/來訪我們`）目前皆為 0 個 JSON-LD**，非常適合透過 Cyberbiz 自訂 HTML 補上 `LocalBusiness` 與 `FAQPage`。

---

## 一、全站基本健檢與 Sitemap 結構概覽

- **檢查時間**：2026-10-16（依安全規則，僅讀取公開頁面，限速每秒不超過 1 頁）
- **`robots.txt` 狀態**：正常（`https://www.sinchih.com.tw/robots.txt`），允許搜尋引擎與 AI 引用（`Content-Signal: ai-train=no, search=yes, ai-input=yes`），並正確指向 Sitemap。
- **`sitemap.xml` 狀態**：正常（`https://www.sinchih.com.tw/sitemap.xml`），共 **1,042** 個網址：
  - 商品頁（`/products/...`）：**649 頁**（多為一機一況的二手機與配件）
  - 自訂頁面（`/pages/...`）：**163 頁**（絕大多數為各型號二手機/平板/手錶的獨立收購行情頁，另有門市據點、收購總表等）
  - 部落格文章（`/blogs/...`）：**126 頁**（主力專欄為 `/blogs/手機知識學堂/...`）
  - 商品集合與分類頁（`/collections/...`、`/categories/...`）：**103 頁**
  - 首頁（`/`）：**1 頁**

---

## 二、四大類代表頁面實際檢測紀錄表

以下為實際檢視首頁、商品頁、部落格文章、收購價目頁（含總表與單機頁）及門市頁的原始碼檢測結果：

| 頁面類型 | 實際檢測網址（解碼後） | Title（長度） | Meta Description（長度） | H1 數量與內容 | 圖片 Alt 缺漏（缺/總數） | JSON-LD 狀態與類型 |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **1. 首頁** | `https://www.sinchih.com.tw/` | `炘馳通訊 -全方位手機服務，隨時滿足您的需求！`（23 字） | `我們是位於台中的炘馳通訊行，擁有8年深耕經驗，致力於提供高品質的二手機買賣、精準的手機維修、門號續約以及全新手機銷售服務...`（129 字） | **0 個（缺 H1）** | 2 / 39 | **2 個**：`Organization`、`WebSite`（正常） |
| **2A. 商品頁（平板）** | `.../products/ipad-mini-7-lte-128gb-00479` | `IPAD MINI 7 LTE 128GB #00479 炘馳通訊`（33 字） | `【重點資訊】【!!下單前請先詢問!!】序號：#00479配件：傳輸線、旅充頭電池健康度：99%（循環57次）...`（161 字，略長） | **1 個**：`IPAD MINI 7 LTE 128GB #00479` | 0 / 18 | **1 個**：`Product` + `Offer`（含價格 17000 TWD、InStock） |
| **2B. 商品頁（手機）** | `.../products/iphone-13-pro-max-256gb-23676` | `IPHONE 13 PRO MAX 256GB #23676 炘馳通訊`（35 字） | `【重點資訊】【!!下單前請先詢問!!】序號：#23676配件：傳輸線電池健康度：82%機況：...`（151 字） | **1 個**：`IPHONE 13 PRO MAX 256GB #23676` | 10 / 29 | **1 個**：`Product` + `Offer`（含價格 11500 TWD、InStock） |
| **3A. 部落格文章（舊文）** | `.../blogs/手機知識學堂/185074` | `又有新招可以偷看LINE訊息不已讀了!使用方式居然如此簡單 炘馳通訊`（34 字） | ❌ `body { font-family: Arial, sans-serif; line-he`（50 字，**誤抓 CSS 語法**） | **1 個**：`又有新招可以偷看LINE訊息不已讀了!使用方式居然如此簡單` | 3 / 14 | **1 個**：`BlogPosting`（但 `description` 欄位同樣誤抓 `body { font-family...`） |
| **3B. 部落格文章（新文）** | `.../blogs/手機知識學堂/20261013` | `搭載A19晶片與免持Siri全新Apple TV 4K亮相！支援四揚聲器環繞家庭劇院，台灣售價與亮點總整理 炘馳通訊`（58 字） | `Apple 正式發表全新一代 Apple TV 4K（第 4 代）！搭載強悍 A19 晶片...`（143 字，正常） | **1 個**：與文章標題相同 | 正常 | **1 個**：`BlogPosting`（⚠️ 注意：`meta description` 雖正常，但 JSON-LD 內的 `description` 仍抓到 `.article-content { background...` CSS！） |
| **4A. 收購價目頁（單機頁）** | `.../pages/iphone-16-pro-max-512gb-二手收購價` | `iPhone 16 Pro Max 512GB 二手收購價 炘馳通訊`（34 字） | `想賣掉您的 iPhone 16 Pro Max 512GB 嗎？炘馳通訊提供透明公開的二手收購行情。台中北屯實體店面現金收購。`（63 字） | **1 個**：`iPhone 16 Pro Max 512GB 二手收購價格查詢` | 0 / 11 | **0 個（無 JSON-LD）** |
| **4B. 收購價目頁（Apple 總表）** | `.../pages/收購表-apple` | ❌ `收購表ANDROID 炘馳通訊`（15 字，**標題誤植為 ANDROID**） | ❌ **空白（0 字，缺 Meta Description）** | **0 個（缺 H1）** | 0 / 11 | **0 個（無 JSON-LD）** |
| **5. 門市據點頁（附加檢查）** | `.../pages/來訪我們` | `炘馳據點 炘馳通訊`（9 字，偏短且缺地區關鍵字） | `炘馳通訊地址：台中市北屯區數化路一段493號 營業時間：下午12:00～晚上9:00 電話：(04)22990931`（58 字，⚠️ 敦化路誤打為「數化路」？） | **0 個（缺 H1）** | 正常 | **0 個（缺 `LocalBusiness` JSON-LD）** |

---

## 三、深度問題分析與立即可做的改善建議

### 1. 首頁（`https://www.sinchih.com.tw/`）
- **現況優點**：
  - `title` 與 `meta description` 皆有設定，描述清楚點出「台中」、「二手機買賣」、「手機維修」、「門號續約」、「全新手機銷售」。
  - 內建 `Organization` 與 `WebSite` 兩組 JSON-LD。
- **發現問題**：
  - **沒有任何 `<h1>` 標籤**，且頁面中有 3 個空的 `<h2>` 標籤（`<h2></h2>`）。
  - `title` 目前為 `炘馳通訊 -全方位手機服務，隨時滿足您的需求！`，沒有包含「台中通訊行」、「二手機收購/買賣」等高搜尋量核心字詞。
  - 首頁雖有 `Organization` JSON-LD，但沒有包含台中北屯門市的 `LocalBusiness`（或 `MobilePhoneStore`）結構化資料（地址、電話、營業時間、座標）。

### 2. 商品頁（`/products/...`）
- **現況優點**：
  - 每個二手機單品都有獨立商品頁、`<h1>` 正常、且 Cyberbiz 自動產生了非常標準的 `Product` + `Offer` JSON-LD（包含台幣售價 `price` 與庫存狀態 `InStock`）。
- **發現問題**：
  - **二手機序號商品的標題策略**：因為二手機是一機一況（例如 `IPHONE 13 PRO MAX 256GB #23676`），同型號不同序號的頁面標題與內容高度相似，且缺少「二手 / 中古 / 福利機」等消費者實際會搜尋的字眼（消費者會搜「iPhone 13 Pro Max 256G 二手價格」，不會搜 `#23676`）。
  - **預設 Meta Description 帶入換行與符號**：未手寫 SEO 描述的商品，系統直接截取商品描述前 160 字（含 `【!!下單前請先詢問!!】序號：#...`），部分超過 160 字元。
  - **商品內文圖片缺 `alt`**：商品主圖有自動帶入商品名稱作為 `alt`，但商品描述下方插入的圖片（如門市宣傳圖、保固說明圖）有約 10 張未填寫 `alt`。

### 3. 部落格文章頁（`/blogs/手機知識學堂/...`）
- **現況優點**：
  - 近期新文章（如 `20261013`）已有手動填寫高品質的 `meta description`，且網址後綴已改為純數字日期（不再是舊版的內部流水號），`<h1>` 結構正確。
- **發現問題（極重要！）**：
  - **CSS 樣式碼污染 `meta description` 與 `BlogPosting` JSON-LD**：
    - 因為文章編輯器內文的第一行寫了 `<style> body { font-family: ... } </style>` 或 `.article-content { ... }`，Cyberbiz 系統在自動擷取文章前 50 字放進 `BlogPosting` JSON-LD 的 `"description"` 欄位（以及未手寫 SEO 描述的舊文章 `<meta name="description">`）時，直接把 CSS 程式碼原封不動貼進去了！
    - **解法**：在健檢規則（`checks/`）中，建議檢查 `meta description` 或 JSON-LD `description` 是否包含 `{`、`}`、`font-family`、`.article-content` 等 CSS 語法特徵；改文章時只要把 `<style>...</style>` 移到文章 HTML 的最末端，就能徹底解決。

### 4. 收購價目頁（`/pages/...`）與門市頁
- **現況優點**：
  - 單一機型收購頁（如 `/pages/iphone-16-pro-max-512gb-二手收購價`）的 SEO 做得很好！不僅有精準的 `title`、`meta description`（含「台中北屯實體店面現金收購」），頁面內也有清楚的 `<h1>`（`iPhone 16 Pro Max 512GB 二手收購價格查詢`）。
- **發現問題**：
  - **收購總表頁錯誤**：`/pages/收購表-apple` 的 `<title>` 竟然寫成 **`收購表ANDROID 炘馳通訊`**，且 `meta description` 完全空白、沒有 `<h1>`。
  - **網址命名不一致**：163 個收購頁中，有些網址帶中文（如 `...-二手收購價`），有些只有容量（如 `/pages/8-128g`、`/pages/11-256g-20260414180851`），甚至看不出是 iPhone 還是 iPad。
  - **缺少 JSON-LD**：所有 `/pages/` 自訂頁面都不會自動產生 JSON-LD。單機收購頁與總表頁非常適合加入 `FAQPage`（常見收購問答），而 `/pages/來訪我們`（門市頁）則應加入 `LocalBusiness` JSON-LD（並修正 meta description 中「數化路一段493號」是否為「敦化路一段493號」之錯字）。

---

## 四、參考來源連結（實際檢測頁面）
- [炘馳通訊首頁](https://www.sinchih.com.tw/)
- [商品頁範例 1：iPad mini 7 LTE 128GB #00479](https://www.sinchih.com.tw/products/ipad-mini-7-lte-128gb-00479)
- [商品頁範例 2：iPhone 13 Pro Max 256GB #23676](https://www.sinchih.com.tw/products/iphone-13-pro-max-256gb-23676)
- [部落格文章範例 1（舊文）：偷看 LINE 訊息不已讀](https://www.sinchih.com.tw/blogs/%E6%89%8B%E6%A9%9F%E7%9F%A5%E8%AD%98%E5%AD%B8%E5%A0%82/185074)
- [部落格文章範例 2（新文）：全新 Apple TV 4K 亮相](https://www.sinchih.com.tw/blogs/%E6%89%8B%E6%A9%9F%E7%9F%A5%E8%AD%98%E5%AD%B8%E5%A0%82/20261013)
- [收購價目頁範例 1（單機頁）：iPhone 16 Pro Max 512GB 二手收購價](https://www.sinchih.com.tw/pages/iphone-16-pro-max-512gb-%E4%BA%8C%E6%89%8B%E6%94%B6%E8%B3%BC%E5%83%B9)
- [收購價目頁範例 2（總表頁）：Apple 收購表](https://www.sinchih.com.tw/pages/%E6%94%B6%E8%B3%BC%E8%A1%A8-apple)
- [門市據點頁：來訪我們](https://www.sinchih.com.tw/pages/%E4%BE%86%E8%A8%AA%E6%88%91%E5%80%91)
