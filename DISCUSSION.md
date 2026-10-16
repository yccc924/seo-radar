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
