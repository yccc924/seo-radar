# 任務清單

標記：🔍 agy　🛠 Claude Code　🐙 Jules　👤 你

狀態：`[ ]` 未開始　`[~]` 進行中　`[x]` 完成

## 階段 0：準備（👤 你）
- [ ] 在 GitHub 建立私有 repo `seo-radar`，把這些文件放進去並 push
- [ ] 安裝 agy 並登入
- [ ] 在 Google Cloud 建立專案、開啟 Search Console API、建立服務帳戶並下載 JSON 金鑰（研究 R2 會給詳細步驟）
- [ ] 到 Search Console 把服務帳戶的 email 加為「受限使用者」
- [ ] 申請 Gmail 應用程式密碼（寄週報用）

## 階段 1：研究（🔍 agy，結果寫進 `research/`）
- [ ] R1 `research/cyberbiz.md`：Cyberbiz 上哪些東西改得動？
      商品頁 title / description、部落格、自訂 HTML / head、JSON-LD、圖片 alt、網址、robots、sitemap 位置。
      每項標註「可改 / 不能改 / 要付費方案」，附官方說明連結。
- [ ] R2 `research/gsc-api.md`：Search Console API 用服務帳戶連線的完整步驟（給完全沒做過的人看），以及 searchanalytics 查詢的欄位與限制。
- [ ] R3 `research/site-snapshot.md`：實際瀏覽 sinchih.com.tw 的首頁、一個商品頁、一篇文章、收購價目頁，記錄目前的 title、description、H1、JSON-LD 狀況。
- [ ] R4 `research/keywords.md`：整理三類關鍵字的分類規則（收購類 / 商品類 / 內容類），各列 20 個例子。

## 階段 2：骨架（🛠 Claude Code）
- [ ] C1 專案骨架、requirements、`.gitignore`、`.env.example`、pytest 設定
- [ ] C2 `db.py`：SQLite 資料表（gsc_rows、pages、issues、runs）
- [ ] C3 `gsc.py`：抓 28 天資料存進資料庫（依 R2）
- [ ] C4 `opportunities.py`：三種機會的計算與排序
- [ ] C5 `crawler.py`：sitemap 爬蟲，限速、遵守 robots.txt
- [ ] C6 `checks/` 規則介面與第一條規則 `title.py`（當作範本給 Jules 照著寫）
- [ ] C7 `dashboard/app.py`：四個頁面
- [ ] C8 `report.py` + `run_weekly.py`：週報與寄信
- [ ] C9 Windows 工作排程器設定說明（寫進 README）

## 階段 3：健檢規則（🐙 Jules，照 C6 的範本，一條一個任務）
- [ ] J1 meta description
- [ ] J2 H1
- [ ] J3 圖片 alt
- [ ] J4 JSON-LD 存在與類型（Product / LocalBusiness / Article / FAQPage）
- [ ] J5 canonical 與 noindex
- [ ] J6 壞掉的連結
- [ ] J7 重複 title / description（跨頁檢查）
- [ ] J8 為 C4 補完整測試

## 階段 4：審查與上線
- [ ] 🔍 agy 審查整個專案，寫進 `DISCUSSION.md`
- [ ] 🛠 Claude Code 修正審查意見
- [ ] 👤 第一次手動執行、看儀表板、設定排程
- [ ] 👤 把第一份週報帶回網頁版 Claude 討論
