---
title: Sec_kb 待辦事項
updated: 2026-08-28
---

# 📋 Sec_kb 待辦事項

這份清單只放**還沒完成、而且值得完成**的事。

已經決定「不做」且寫明理由的項目**不在這裡** —— 它們在
[[Sec_kb_資料維護SOP#5. 已知限制（不是 bug，不要「修」）|維護 SOP 的「已知限制」]]。
把它們搬進待辦，下一個人就會去「修」一個已經被判斷過不該修的東西。

> ⚠️ 完成任何一項後，請**同時刪掉這裡的條目**。一份沒人清理的待辦清單，
> 和一個沒人跑的檢查是同一種東西 —— 看起來有在管，實際上沒有。

---

## A. 例行維護（目前無需動作）

### A-1. 新申報之後要補譯文

抓進新年度的原文後，`risk_changes.json` 會出現沒翻過的段落，報告頁顯示「尚未翻譯」。

```bash
python3 scripts/list_untranslated.py      # 待翻清單
# 補進 risk_zh.json 的 zh 欄後：
python3 scripts/build_reports.py
```

> 🚫 **不要為了消除「尚未翻譯」而改用機器直譯，或把該段從比對結果刪掉。**
> 標示本身就是誠實的狀態，空白與假譯文才是問題。

---

## B. 等結果，不用動手

目前沒有等待驗證的項目。每日資料管線已自 2026-08-10 起連續在 CI 完整執行；
SEC 申報雷達另由 `.github/workflows/sec-filing-alerts.yml` 於台北時間週二至週六中午檢查，
並同步更新 10-Q、Form 4、募資稀釋、財報附件、會計審閱、13D／13G、治理薪酬、
Form 144＋3／4／5、併購與 SEC 執法／停牌雷達。完整 13F 另以
`.github/workflows/sec-13f-radar.yml` 每月檢查 SEC 新季度資料集。

---

## C. 未來強化：8-K 財報附件與電話會議整理

### C-1. 把已入庫的官方原文再整理成可判讀分析卡

適用範圍：**Sec_kb 網頁／報告內列到的全部追蹤公司**，不是只針對 META、NVDA 或單一公司。
目前報告頁已列到的公司包含 AAPL、AMZN、ARM、COHR、GOOGL/GOOG、INTC、META、MRVL、MSFT、NOK、NVDA、ONDS、TSLA、TSM；
後續若 dashboard/report 新增追蹤公司，也一併適用本項自動化強化。

10-Q／8-K／6-K 主筆記與安全章節拆分已由 `ingest_periodic_filings.py` 接進每日 SEC 流程；
剩下的是附件內容與電話會議的結構化整理。

希望未來可以做到：

- 自動下載 earnings call transcript。
- 自動整理電話會議重點。
- 自動把 8-K Exhibit 99.1 財報新聞稿變成分析卡。

成功條件：

- 任一追蹤公司有新 8-K 財報附件後，可從 SEC accession 追溯到原文筆記、Exhibit 99.1 與分析卡。
- 電話會議逐字稿來源必須可追溯，若官方 IR 只有 replay 或 CFO commentary，需明確標示來源型態。
- 8-K Exhibit 99.1 分析卡需至少包含營收、毛利率、EPS、分部營收、下一季指引、管理層關鍵語句與風險變化。
- 更新後需跑 `scripts/check_integrity.py`，並確認不會手動覆寫由腳本產生的 JSON 與報告檔。

---

## D. 不在這份清單上的東西

以下都是**已經判斷過、決定不修**的，理由記在
[[Sec_kb_資料維護SOP#5. 已知限制（不是 bug，不要「修」）|SOP 的「已知限制」]]：

| 項目 | 為什麼不做 |
|---|---|
| COHR 的 ROIC／Altman Z″／利息保障倍數 | 未標記營業利益，替代算法已測試並否決（差額等於稅前淨利，不是營業利益） |
| AAPL 的利息保障倍數 | 自 FY2023 起未標記利息費用，無法由其他科目推導 |
| TSM 的 Beneish M-Score | 缺 DEPI 與 SGAI，**不以 1.0 代入湊分數** |
| INTC 的 Item 1／Item 7 抽取 | 7 份申報中有 6 份在 25 萬字元處仍在目錄內，抽取器拒絕猜測 |
| INTC／NOK／TSM 的風險年度比對 | 各只有一個年度的原文拆解，**不為了湊出比對而放寬抽取規則** |
| 護城河章節沒有 SEC 出處 | 它沒有對應的單一原文章節，風險章節則 14/14 都已接上 |

---

## 🔗 關聯筆記

- [[Sec_kb_資料維護SOP|Sec_kb 資料維護 SOP]]
- [[ttc-stock_Dashboard_維運SOP|ttc-stock 儀表板維運 SOP]]
- [[00_Home|知識庫主頁]]
