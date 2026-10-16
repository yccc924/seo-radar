# R2：Google Search Console API 服務帳戶連線教學與查詢規格

## 重點結論（三行摘要）
1. **無人值守自動化的唯一標準作法**：透過 Google Cloud 建立「服務帳戶（Service Account）」並下載 JSON 金鑰檔，再將服務帳戶的 Email（結尾為 `@...iam.gserviceaccount.com`）加進 Search Console 後台的「使用者和權限（受限使用者）」，Python 即可每週自動抓資料，完全不需要人工打開瀏覽器登入。
2. **`searchanalytics.query` 核心查詢參數**：抓取過去 28 天資料時，`dimensions` 應設為 `["query", "page"]`（查詢字詞 × 頁面），單次請求上限 `rowLimit` 最大為 `25000` 筆（超過需用 `startRow` 分頁），並注意 GSC 資料預設有 2～3 天的延遲（建議 `endDate` 設為今天減 3 天，或加上 `dataState="all"`）。
3. **資源網址（`siteUrl`）格式必須完全吻合**：若 Search Console 驗證的是「網域資源」，`siteUrl` 必須寫成 `sc-domain:sinchih.com.tw`；若是「網址前置字元資源」，則必須寫成 `https://www.sinchih.com.tw/`（連結尾斜線都要一模一樣），否則 API 會回傳 `403 Forbidden`。

---

## 一、給完全沒做過的人：5 步驟完成服務帳戶設定（圖文邏輯一步一步照著做）

為什麼需要「服務帳戶（Service Account）」？
一般我們自己看 Search Console 是用個人的 Google 帳號登入，但程式每週一早上要自己跑，總不能每次都跳出視窗叫你輸入密碼跟手機驗證碼。所以我們要在 Google Cloud 幫程式辦一個「機器人專用帳號（服務帳戶）」，發給它一張通行證（JSON 金鑰檔），再把這個機器人加進你的 Search Console 裡當「受限使用者（唯讀）」。

### 步驟 1：建立 Google Cloud 專案（免費）
1. 打開瀏覽器，前往 [Google Cloud Console（雲端控制台）](https://console.cloud.google.com/)，用你的 Google 帳號登入。
2. 點擊畫面最上方導覽列左邊的「選取專案」下拉選單 ➔ 點擊右上角的「**新增專案（New Project）**」。
3. **專案名稱**輸入：`seo-radar`（或任何好記的名字），點擊「**建立**」。
4. 等待幾秒鐘建立完成後，確認畫面最上方的專案已經切換成剛剛建立的 `seo-radar`。

### 步驟 2：開啟 Google Search Console API
1. 在左側選單點擊「**API 和服務（APIs & Services）**」➔「**已啟用的 API 和服務**」（或點擊「程式庫 Library」）。
2. 在上方的搜尋框輸入：`Google Search Console API`。
3. 點進「**Google Search Console API**」，按下藍色的「**啟用（Enable）**」按鈕。

### 步驟 3：建立「服務帳戶」並下載 JSON 金鑰檔
1. 啟用後，在左側選單點擊「**API 和服務**」➔「**憑證（Credentials）**」。
2. 點擊畫面上方的「**+ 建立憑證（Create Credentials）**」➔ 選擇「**服務帳戶（Service account）**」。
3. **服務帳戶詳細資料**：
   - **服務帳戶名稱**：輸入 `seo-radar-reader`
   - **服務帳戶 ID**：系統會自動帶入（例如 `seo-radar-reader`），下方會顯示一串像 Email 的網址（例如 `seo-radar-reader@seo-radar-xxxx.iam.gserviceaccount.com`）。
   - 點擊「**建立並繼續**」。
4. **授予這個服務帳戶專案存取權**（選填）：這邊不用選任何角色，直接點「**繼續**」，再點「**完成**」。
5. 回到憑證列表，你會在下方的「服務帳戶」表格看到剛剛建好的 `seo-radar-reader@...iam.gserviceaccount.com`：
   - **先把這整串 Email 複製起來**（等一下步驟 4 要用）。
   - 點擊這串 Email 點進去 ➔ 切換到上方的「**金鑰（Keys）**」頁籤。
   - 點擊「**新增金鑰（Add Key）**」➔「**建立新的金鑰（Create new key）**」。
   - 金鑰類型選擇「**JSON**」，點擊「**建立**」。
6. 這時瀏覽器會自動下載一個 `.json` 檔案。
   - 請把這個檔案改名為 `gsc-service-account.json`。
   - 放進本專案的 `credentials/` 資料夾裡（完整路徑：`seo-radar/credentials/gsc-service-account.json`）。
   - ⚠️ **安全提醒**：這個 JSON 檔就等於機器人的密碼，絕對不可以傳給別人或放上 GitHub（我們的 `.gitignore` 已經幫你把 `credentials/` 擋住了）。

### 步驟 4：到 Search Console 把機器人加為「受限使用者」
1. 打開 [Google Search Console](https://search.google.com/search-console)，在左上角選取你的網站資源（`sinchih.com.tw` 或 `https://www.sinchih.com.tw/`）。
2. 點擊左下角選單最底部的「**設定（Settings）**」。
3. 點擊「**使用者和權限（Users and permissions）**」。
4. 點擊右上角的藍色按鈕「**新增使用者（Add user）**」。
5. **電子郵件地址**：貼上剛剛步驟 3 複製的那串服務帳戶 Email（`seo-radar-reader@...iam.gserviceaccount.com`）。
6. **權限**：選擇「**受限（Restricted）**」（代表只能讀取資料，不能亂改設定，最安全）。
7. 點擊「**新增**」。大功告成！

### 步驟 5：確認 `.env` 裡的 `GSC_SITE_URL` 怎麼填
看一下你 Search Console 左上角資源選單顯示的字樣：
- 如果上面寫「網域資源」`sinchih.com.tw`，那 `.env` 的 `GSC_SITE_URL` 要填：`sc-domain:sinchih.com.tw`
- 如果上面寫 `https://www.sinchih.com.tw/`，那 `.env` 的 `GSC_SITE_URL` 要填：`https://www.sinchih.com.tw/`（結尾的 `/` 不能少）
- 如果不確定，之後跑 Python 時可以先呼叫 `service.sites().list().execute()`，它會直接印出這個服務帳戶有權限讀取的正確 `siteUrl` 字串！

---

## 二、`searchanalytics.query` API 查詢欄位與限制詳解（給工程師 C3 實作參考）

### 1. 認證與建立 Client（Python 套件）
使用 `google-auth` 與 `google-api-python-client`：
- **Scope（權限範圍）**：唯讀即可，使用 `https://www.googleapis.com/auth/webmasters.readonly`
- **API 名稱與版本**：`build("searchconsole", "v1", credentials=creds)`（註：舊稱 `("webmasters", "v3")` 亦可，但 Google 官方現行文件推薦使用 `searchconsole` `v1`）。

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

creds = service_account.Credentials.from_service_account_file(
    "credentials/gsc-service-account.json", scopes=SCOPES
)
service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
```

### 2. Request Body（請求參數）規格

呼叫 `service.searchanalytics().query(siteUrl=site_url, body=payload).execute()` 時，`body` 支援以下關鍵欄位：

| 參數名稱 | 型別 | 是否必填 | 專案建議設定值 | 說明與注意事項 |
| :--- | :--- | :---: | :--- | :--- |
| `startDate` | `str` | 必填 | `YYYY-MM-DD` | 起始日期（太平洋時間 PT）。抓 28 天資料時，由結束日往前推 27 天（含首尾共 28 天）。 |
| `endDate` | `str` | 必填 | `YYYY-MM-DD` | 結束日期（太平洋時間 PT）。因 GSC 正式資料通常有 2～3 天延遲，建議設為 `today - 3 days`（或搭配 `dataState="all"` 抓到昨日）。 |
| `dimensions` | `list[str]` | 選填 | `["query", "page"]` | 分組維度。可選值：`query`、`page`、`country`、`device`、`searchAppearance`、`date`。本專案規格（SPEC.md 功能 1）需抓「查詢字詞 × 頁面」，因此設為 `["query", "page"]`（若需算「本週才出現的新字詞」，可抓兩個 7 天區間或比較前期與本期區間，亦可加 `date` 維度）。 |
| `type` | `str` | 選填 | `"web"` | 搜尋類型，預設為 `"web"`（網頁搜尋），另有 `"image"`、`"video"`、`"news"`、`"discover"`。 |
| `rowLimit` | `int` | 選填 | `25000` | 單次請求最多回傳幾筆。預設為 `1000`，**上限為 `25000`**。 |
| `startRow` | `int` | 選填 | `0` | 分頁起始列（0-based）。若第一批回傳滿 `25000` 筆，下一批設 `startRow=25000` 繼續抓，直到回傳筆數小於 `rowLimit` 或無 `rows`。 |
| `dataState` | `str` | 選填 | `"final"` 或 `"all"` | `"final"`（預設）只回傳已穩定結算的資料（約落後 2～3 天）；`"all"` 會包含最近 1～2 天尚未最終結算的搶先資料（Fresh data）。 |

### 3. Response（回傳資料）欄位結構

當查到資料時，API 回傳的 JSON 結構如下：

```json
{
  "rows": [
    {
      "keys": [
        "台中二手手機收購",
        "https://www.sinchih.com.tw/pages/second-hand-apple"
      ],
      "clicks": 18,
      "impressions": 320,
      "ctr": 0.05625,
      "position": 6.4
    }
  ],
  "responseAggregationType": "byPage"
}
```

**回傳欄位重點提醒**：
1. **`rows` 可能不存在**：如果該日期區間完全沒有曝光資料，回傳的 `dict` **不會有 `"rows"` 這個 key**（因此程式必須寫 `response.get("rows", [])`）。
2. **`keys` 順序與 `dimensions` 完全一致**：當 `dimensions=["query", "page"]` 時，`row["keys"][0]` 就是 `query`（查詢字詞），`row["keys"][1]` 就是 `page`（完整網址）。
3. **`ctr`（點擊率）是 0～1 的浮點數**：例如 `0.05625` 代表 `5.625%`（在儀表板顯示時記得乘以 100，或在資料庫統一存 0～1 的小數並在 docstring 註明）。
4. **`position`（平均排名）**：浮點數，`1.0` 代表第一名，數字越小排名越前面。

---

## 三、API 限制與常見陷阱（必讀）

1. **匿名化查詢（Anonymized Queries）過濾機制**：
   - Google 為了保護隱私並節省儲存空間，當查詢維度包含 `"query"` 時，搜尋次數極少或涉及個資的長尾查詢會被隱藏（不包含在回傳的 `rows` 中）。這屬於 GSC 官方正常現象，把所有 `query` 的點擊加總通常會比不指定 `dimensions` 的全站總點擊略少。
2. **多維度組合的資料截斷與分頁**：
   - 當同時指定 `["query", "page"]`（若再加上 `"date"`），資料列數會倍增。對於目前每日約 1,100～1,200 流量的網站，28 天的 `["query", "page"]` 彙總通常在數千至一兩萬筆之間，單次 `rowLimit=25000` 大多可抓完，但 `gsc.py` 仍建議寫一個簡單的 `while` 迴圈支援 `startRow` 分頁以防超過 25,000 筆。
3. **如何支援 SPEC 功能 1 的三種機會（快上首頁 / 點擊率太低 / 新冒出的字詞）**：
   - 若要判斷「**3. 新冒出的字詞（本週才出現、曝光成長中的字詞）**」，有兩種乾淨做法：
     - **做法 A（推薦、資料量小）**：在 `gsc.py` 支援依指定日期區間抓取，或直接抓包含 `date` 維度（或分別抓「最近 28 天」加上「最近 7 天 vs 前 7～21 天」），讓 `opportunities.py` 能比對「本週（近 7 天）有曝光，但前幾週沒有曝光（或曝光大幅成長）」的字詞。
     - **做法 B（每日明細）**：查詢時 `dimensions=["date", "query", "page"]` 存入 `gsc_rows`，由 SQLite 聚合計算近 28 天與近 7 天。注意：加上 `"date"` 維度會讓Google 的隱私門檻以「單日」計算，可能會濾掉更多低曝光字詞。因此**分區間查詢 `["query", "page"]` 或每週定期存檔比對歷史 `runs`** 是更準確的做法。
4. **配額限制（Quota Limits）**：
   - Search Console API 免費，配額上限非常寬裕（每分鐘每網站 1,200 次請求、每天數千萬次），我們每週執行一次完全不會撞到配額上限。

---

## 四、常見錯誤排解表

| 錯誤代碼 | 錯誤訊息關鍵字 | 原因與解決辦法 |
| :--- | :--- | :--- |
| `403 Forbidden` | `User does not have sufficient permission for site` | 1. 服務帳戶 Email 還沒加進 Search Console「使用者和權限」。<br>2. `.env` 的 `GSC_SITE_URL` 格式打錯（例如網域資源忘了加 `sc-domain:`，或網址資源少了 `www.` 或結尾 `/`）。 |
| `403 Forbidden` | `Google Search Console API has not been used in project ... before or it is disabled` | 步驟 2 的 Google Search Console API 忘了按「啟用」，點錯誤訊息裡的連結去開啟即可。 |
| `FileNotFoundError` | `No such file or directory: 'credentials/...'` | JSON 金鑰檔沒放到正確位置，或 `.env` 的 `GSC_CREDENTIALS_PATH` 路徑寫錯。 |

---

## 五、參考來源連結
- [Google Search Console API 官方總覽與快速入門](https://developers.google.com/webmaster-tools/v1/how-tos/search_analytics)
- [Search Analytics：`query` 方法官方參數與回傳規格文件](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
- [Google Cloud 官方文件：建立與管理服務帳戶金鑰](https://cloud.google.com/iam/docs/keys-create-delete?hl=zh-tw)
- [Search Console 說明中心：管理擁有者、使用者和權限](https://support.google.com/webmasters/answer/7687615?hl=zh-Hant)
