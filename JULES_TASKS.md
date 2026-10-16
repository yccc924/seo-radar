# 貼給 Jules 的任務

**等 Claude Code 完成 C6（第一條規則 title.py）之後再開始。**
到 jules.google 選 `seo-radar` repo，一次貼一段。每段都是獨立任務，可以同時丟好幾個。

---

### J1
在 `src/seo_radar/checks/` 新增 `meta_description.py`，照 `title.py` 的介面寫一條健檢規則：沒有 meta description 為「高」，長度少於 50 或多於 160 字元為「中」。在 `tests/checks/` 加對應的 pytest 測試，用假的 HTML 字串，不要連網。確保 `pytest` 全部通過。

### J2
在 `src/seo_radar/checks/` 新增 `h1.py`，照 `title.py` 的介面：沒有 H1 為「高」，超過一個 H1 為「中」。加 pytest 測試，用假的 HTML，確保全部通過。

### J3
在 `src/seo_radar/checks/` 新增 `image_alt.py`，照 `title.py` 的介面：計算缺少或空白 alt 的圖片比例，超過 50% 為「中」，有缺但未過半為「低」。加 pytest 測試，確保全部通過。

### J4
在 `src/seo_radar/checks/` 新增 `json_ld.py`，照 `title.py` 的介面：解析頁面中所有 `application/ld+json`，回報找到的 @type。依頁面類型判斷缺少什麼：網址含 `/products/` 的商品頁沒有 Product 為「高」；首頁沒有 LocalBusiness 或 Organization 為「中」；網址含 `/blogs/` 的文章頁沒有 Article 或 BlogPosting 為「中」。JSON 格式錯誤為「高」。加 pytest 測試，確保全部通過。

### J5
在 `src/seo_radar/checks/` 新增 `indexing.py`，照 `title.py` 的介面：頁面有 `noindex` 為「高」；canonical 指向其他網域為「高」；沒有 canonical 為「低」。加 pytest 測試，確保全部通過。

### J6
在 `src/seo_radar/checks/` 新增 `broken_links.py`：接收爬蟲已記錄的連結與狀態碼（不要自己發請求），站內連結 4xx / 5xx 為「高」。加 pytest 測試，確保全部通過。

### J7
在 `src/seo_radar/checks/` 新增 `duplicates.py`：這是跨頁規則，接收所有頁面的 title 與 description，找出重複的並回報「中」。如果 `title.py` 的介面不支援跨頁，新增一個 `SiteCheck` 介面並在 PR 說明中解釋。加 pytest 測試，確保全部通過。

### J8
閱讀 `src/seo_radar/opportunities.py`，為三種機會（快上首頁、點擊率太低、新冒出的字詞）的計算補齊 pytest 測試，包含邊界情況（空資料、排名剛好 5 或 20、曝光為 0）。只加測試；如果發現 bug，在 PR 說明中列出，不要直接改主程式。
