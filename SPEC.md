# SEO 雷達（seo-radar）規格書 v1

## 一、目標

幫 炘馳通訊（sinchih.com.tw，架在 Cyberbiz 上）增加自然搜尋流量與 AI 引用率。

- 現況：Cyberbiz 後台顯示每天約 1,100～1,200
- 目標：每天至少 5,000
- 三個方向都要：多賣商品、多收購手機、品牌曝光

工具本身不會帶來流量。它的工作是**自動找出該改哪裡、該寫什麼**，並每週提醒。

## 二、第一版範圍（MVP）

### 功能 1：關鍵字機會雷達
- 串接 Google Search Console API，抓最近 28 天的「查詢字詞 × 頁面」資料
- 找出三種機會並排序：
  1. **快上首頁**：平均排名 5～20 名、曝光數高的字詞
  2. **點擊率太低**：曝光高但 CTR 明顯低於同排名平均的頁面（標題或描述要改）
  3. **新冒出的字詞**：本週才出現、曝光成長中的字詞
- 每個字詞自動分類：收購類 / 商品類 / 內容類（用關鍵字規則，之後可改成 AI 分類）

### 功能 2：網站健檢
- 爬整個網站（從 sitemap 開始，限速每秒 1 頁，遵守 robots.txt）
- 每頁檢查：
  - title 有無、長度、是否重複
  - meta description 有無、長度、是否重複
  - H1 有無、是否只有一個
  - 圖片 alt 缺漏比例
  - 結構化資料（JSON-LD）：商品頁要有 Product、門市要有 LocalBusiness、文章要有 Article、可加 FAQPage
  - canonical、noindex、壞掉的連結（4xx / 5xx）
- 每個問題標註嚴重度（高 / 中 / 低）與**在 Cyberbiz 能不能改**（依 agy 的研究結果）

### 功能 3：儀表板
- 本機網頁儀表板（Streamlit），打開瀏覽器就能看
- 頁面：總覽、關鍵字機會、健檢問題、歷史趨勢

### 功能 4：每週自動報告
- 每週一早上自動執行功能 1、2，存進資料庫
- 寄一封 Email 摘要：本週前 10 個優先處理項目、與上週比較

## 三、第二版再做（先不要碰）
- AI 能見度追蹤（用官方 API 問各家 AI，記錄是否提到炘馳）
- 內容建議：根據機會字詞產生文章主題，接到現有的部落格改寫流程
- GA4 串接、自動產生 FAQ 與結構化資料片段

## 四、技術選擇
| 項目 | 選擇 | 原因 |
|---|---|---|
| 語言 | Python 3.12 | 使用者熟悉，三個 AI 都擅長 |
| 儀表板 | Streamlit | 不用寫前端就有圖表 |
| 資料庫 | SQLite（單一檔案） | 不用架伺服器 |
| 爬蟲 | requests + BeautifulSoup | 簡單、夠用 |
| Search Console | 官方 API + 服務帳戶 | 可無人值守執行 |
| 排程 | Windows 工作排程器 | 本機每週執行 |
| 寄信 | Gmail SMTP + 應用程式密碼 | 免費、設定簡單 |
| 測試 | pytest | Jules 可在雲端執行 |

## 五、資料夾結構
```
seo-radar/
├── CLAUDE.md            給 Claude Code 的規則
├── AGENTS.md            給 agy 的規則
├── SPEC.md
├── TASKS.md
├── DISCUSSION.md              三方討論紀錄
├── research/            agy 的研究報告
├── src/seo_radar/
│   ├── gsc.py           Search Console 串接
│   ├── opportunities.py 機會計算
│   ├── crawler.py       爬蟲
│   ├── checks/          健檢規則，一條規則一個檔案
│   ├── db.py            資料庫
│   ├── report.py        週報
│   └── run_weekly.py    排程進入點
├── dashboard/app.py     Streamlit 儀表板
├── tests/
├── .env.example         設定範本（真正的 .env 不進 git）
└── requirements.txt
```

## 六、安全規則
- 金鑰、密碼只放 `.env` 與 `credentials/`，兩者都列入 `.gitignore`
- 爬蟲只爬 sinchih.com.tw，限速，不爬後台
- 工具只「讀」網站與 Search Console，不自動修改 Cyberbiz 上的任何東西
