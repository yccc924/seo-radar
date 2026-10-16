# R5：Cyberbiz Open API 讀寫部落格文章、自訂頁面與 SEO 欄位之可行性研究

## 重點結論（三行摘要）
1. **部落格文章（`/v1/blogs/{blog_id}/articles`）可透過 API 讀寫內文，但無單篇文章獨立的 SEO Meta Tag 端點**：API 支援讀取、新增、修改部落格文章的標題（`title`）、內文 HTML（`body_html`）、網址代碼（`handle`）與封面圖，並支援修改「整個部落格分類（`/v1/blogs/{blog_id}/seo_meta_tags`）」與「單一商品（`/v1/products/{product_id}/seo_meta_tags`）」的 SEO `title`/`description`，但官方 v1 API 並未開放「單篇部落格文章」的 `seo_meta_tags` 欄位。
2. **自訂頁面（`/pages/`，如收購價目頁）完全不支援 Open API**：經實測撈取官方 Swagger v1 規格（共 116 個 API 路徑），Cyberbiz 完全沒有提供任何 `/v1/pages` 或自訂頁面的 API 端點，因此收購價目頁與門市頁只能從後台手動修改，無法用正規 API 讀寫。
3. **方案門檻與重要限制**：Open API 僅在「**企業版**（內建）」或「**PLUS 方案**（選配模組，如 11 選 2）」提供，需聯繫開店顧問/客服開通；且修改文章 `body_html` 時，若 App 未獲特別授權會自動過濾部分 HTML 標籤（如 `<style>`、`<script>`），每秒請求上限為 5 次。

---

## 一、給新手的背景說明：我們能寫程式自動幫 Cyberbiz 改文章或收購頁嗎？

當我們的「SEO 雷達」找出某篇部落格文章的 `description` 被 `<style>` CSS 污染，或者想自動把改寫好的部落格文章發佈上去時，最理想的情況是讓 Python 直接透過 Cyberbiz 官方提供的 **Open API（應用程式介面）** 自動讀取並修改，不用人工打開瀏覽器一頁一頁貼上。

為了確認這件事能不能做到，我直接連線查詢了 Cyberbiz 官方的 **Swagger API 規格文件庫（`https://api.cyberbiz.co/v1/swagger_doc`）**，將全站 116 個 API 端點與資料模型（Model）全部盤點了一遍。以下為百分之百根據官方 API 結構整理的實測結果。

---

## 二、各項內容與 SEO 欄位的 API 支援度總表

| 資源類型 | 讀取內容 (`GET`) | 新增/修改內容 (`POST`/`PUT`) | 讀取/修改 SEO 欄位 (`title` / `description` / `keywords`) | 官方 API 端點路徑 |
| :--- | :---: | :---: | :---: | :--- |
| **1. 部落格專欄分類（Blogs）** | ✅ **支援** | ✅ **支援**（可改 `title`、`handle`） | ✅ **支援**（`GET` / `PUT`） | `/v1/blogs`<br>`/v1/blogs/{blog_id}`<br>`/v1/blogs/{blog_id}/seo_meta_tags` |
| **2. 部落格單篇文章（Articles）** | ✅ **支援** | ✅ **支援**（可改 `title`、`body_html`、`handle`、`published`、`tags`、封面圖） | ❌ **不支援獨立 SEO 欄位**（API 未提供單篇文章的 `seo_meta_tags`，僅能改文章本身的 `title` 與 `body_html`） | `/v1/blogs/{blog_id}/articles`<br>`/v1/blogs/{blog_id}/articles/{article_id}` |
| **3. 自訂頁面（Pages，如 `/pages/` 收購價目頁）** | ❌ **完全不支援** | ❌ **完全不支援** | ❌ **完全不支援** | 無對應端點（Swagger 全數 116 個路徑中無 `/v1/pages`） |
| **4. 商品（Products）** | ✅ **支援** | ✅ **支援**（可改 `title`、`body_html`、`brief`、`handle` 等） | ✅ **支援**（讀取在 `GET /v1/products/{id}` 的 `seo_meta_tags`；修改用 `PUT`） | `/v1/products/{product_id}`<br>`/v1/products/{product_id}/seo_meta_tags` |
| **5. 商品自訂分類群組（Custom Collections）** | ✅ **支援** | ✅ **支援**（可改 `title`、`handle`、`body_html`） | ❌ **不支援獨立 SEO 欄位** | `/v1/custom_collections`<br>`/v1/custom_collections/{id}` |

---

## 三、部落格與 SEO 相關 API 端點詳細規格（實測官方 Swagger v1）

### 1. 部落格專欄（Blogs）與專欄 SEO 標籤
- **`GET /v1/blogs`**：取得所有部落格專欄列表（例如「手機知識學堂」的 `blog_id`）。
- **`GET /v1/blogs/{blog_id}`** / **`PUT /v1/blogs/{blog_id}`**：讀取或更新部落格專欄的標題（`title`）、網址代碼（`handle`）、評論設定（`commentable`）。
- **`GET /v1/blogs/{blog_id}/seo_meta_tags`**：取得該部落格專欄分類頁的 SEO 標籤（回傳 `title`、`description`、`keywords`）。
- **`PUT /v1/blogs/{blog_id}/seo_meta_tags`**：更新該部落格專欄分類頁的 SEO 標籤（參數：`title`、`description`、`keywords`）。

### 2. 部落格單篇文章（Articles）
- **`GET /v1/blogs/{blog_id}/articles`**：取得該專欄下所有文章列表（支援依 `published`、`title`、`tag`、`created_at_min/max`、`page`、`per_page` 篩選）。
- **`GET /v1/blogs/{blog_id}/articles/{article_id}`**：取得單篇文章完整內容。
  - **回傳欄位**：`id`、`blog_id`、`title`（文章標題，即頁面 H1 與預設 Title）、`body_html`（文章 HTML 內文）、`author`、`handle`（網址後綴代碼）、`published`、`published_at`、`pinned`、`tags`、`cover_image_url`。
- **`POST /v1/blogs/{blog_id}/articles`**：建立新文章。
- **`PUT /v1/blogs/{blog_id}/articles/{article_id}`**：更新現有文章。
  - **可修改參數（`formData`）**：
    - `title`（字串）：文章標題
    - `body_html`（字串）：文章 HTML 內容
    - `handle`（字串）：文章網址代碼（Slug）
    - `author`、`published`、`published_at`、`published_end_at`、`pinned`、`tags_text`
  - **圖片與標籤附屬端點**：
    - `POST` / `DELETE /v1/blogs/{blog_id}/articles/{article_id}/cover_image`（上傳/刪除文章封面圖）
    - `GET` / `PUT /v1/blogs/{blog_id}/articles/{article_id}/tags`（管理文章標籤）

> [!WARNING]
> **關鍵發現：部落格單篇文章 API 的兩大限制**
> 1. **沒有單篇文章的 `seo_meta_tags` API**：雖然 Cyberbiz 後台介面可以手動填寫單篇文章的 SEO Title 與 Meta Description，但 `/v1/blogs/{blog_id}/articles/{article_id}` 的 API 參數與回傳 Model 中**沒有 `seo_meta_tags`**。不過，**修改 `body_html` 把文章開頭的 `<style>` 移到最底部**，就能直接透過 API 批量修復全站 126 篇部落格文章 `BlogPosting` JSON-LD 與未填 SEO 簡述文章被 CSS 污染的問題！
> 2. **`body_html` 的 HTML 過濾機制**：官方 API 規格明確註記：
>    `body_html: 文章 HTML 內容（依 app 授權，未授權時會過濾 HTML；已授權則原樣保存，請自行確保內容安全）`
>    這代表如果我們透過 API 送出含有 `<style>` 或 `<script type="application/ld+json">` 的文章內文，預設可能會被系統過濾掉，必須向 Cyberbiz 客服確認將該自訂 App 開通「原樣保存 HTML 授權」。

### 3. 商品 SEO 標籤（順帶盤點：全站唯一支援單頁 SEO Meta 修改的 API）
- **`PUT /v1/products/{product_id}/seo_meta_tags`**：
  - 可直接透過程式修改全站 649 個商品頁的 SEO `title`、`description`、`keywords`！這對未來批量優化二手機商品頁標題（例如自動補上「台中二手機」字樣）非常有用。

---

## 四、需要什麼方案？怎麼申請？

### 1. 方案資格要求
- **企業版（Enterprise）**：**直接內建** Open API 與 Webhook 串接功能。
- **PLUS 方案**：屬於**選配模組**（例如 PLUS 方案的「11 選 2」進階功能模組之一），需確認當初簽約時有選配 API 模組，或向開店顧問申請加購/換選。
- **基礎 / 專業版等入門方案**：預設不包含 Open API，需升級方案或洽詢專屬開店顧問。
- *(註：由於我們只看公開頁面、不登入後台，目前炘馳通訊的合約方案是否已開通 API 權限為「**不確定**」，老闆可依下方步驟登入後台看有沒有該選單即可一秒確認。)*

### 2. 申請與後台取得金鑰（API Token / Secret）步驟
1. **確認權限與申請開通**：
   - 用最高管理員帳號登入 Cyberbiz 後台，查看左側選單是否有「**APP MARKET**」➔「**我的擴充服務**」➔「**自訂**」分頁。
   - 若沒看到該選項，請直接聯繫 Cyberbiz 線上客服或專屬開店顧問，告知：「我們想開通後台『自訂應用程式（Open API）』功能，且需要授權部落格文章 `body_html` 原樣保存 HTML。」
2. **確認後台帳號權限**：
   - 到「**管理中心**」➔「**網站權限設定**」，確認操作人員的帳號有勾選「自訂應用程式」管理權限。
3. **建立自訂應用程式並取得金鑰**：
   - 前往「**APP MARKET**」➔「**我的擴充服務**」➔ 切換到「**自訂**」分頁。
   - 點擊「**建立自訂應用程式**」，輸入名稱（例如 `seo-radar-updater`）。
   - 勾選需要的 **API Scope（權限範圍）**：例如部落格文章讀寫（`read_blogs` / `write_blogs`）與商品讀寫（`read_products` / `write_products`）。
   - 儲存後，系統會產生一組 **`Username`（或 API Token）** 與 **`Secret`（APP Secret）**。

---

## 五、API 技術規範與使用限制

1. **連線位址與認證方式（HMAC-SHA256 簽章）**：
   - **正式環境 Base URL**：`https://api.cyberbiz.co`
   - **認證機制**：Cyberbiz API v1 採用嚴格的 **HTTP HMAC-SHA256 簽章認證**（而非單純帶一把固定 Bearer Token）。每次發送請求時，Header 必須帶上當前 GMT 時間 `X-Date`（若為 `POST`/`PUT` 還需計算 Body 的 SHA-256 `Digest`），並用 `Secret` 對 `x-date` 與 `request-line`（如 `GET /v1/blogs HTTP/1.1`）做 HMAC-SHA256 雜湊簽章放入 `Authorization` Header。
2. **流量與大小限制（Rate Limit & Payload Limit）**：
   - **頻率限制**：每秒最多 **5 個請求（5 requests / sec）**。
   - **單次傳輸上限**：每個 Request 最大 **2 MB**。
3. **官方測試沙盒**：
   - 官方提供公開的 Swagger 線上測試文件：`https://api-doc.cyberbiz.co/v1/api_document`
   - 測試帳密：`Username` 輸入 `apidemo`、`Secret` 輸入 `apidemo`，即可查看所有 API 參數並對測試商店發送請求。

---

## 六、參考來源連結
- [CYBERBIZ 官方 API 線上規格文件（Swagger UI）](https://api-doc.cyberbiz.co/v1/api_document)
- [CYBERBIZ 官方 API 端點規格 JSON（需 HMAC 認證讀取）](https://api.cyberbiz.co/v1/swagger_doc)
- [CYBERBIZ 幫助中心（支援文件庫：自訂應用程式與 API 串接說明）](https://support.cyberbiz.io/)
