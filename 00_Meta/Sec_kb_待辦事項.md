---
title: Sec_kb 待辦事項
updated: 2026-08-09
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

### B-1. 排程的完整路徑仍未在 CI 上執行過

`.github/workflows/update-prices.yml` 的 `changed=true` 分支
（重算 → `check_integrity.py` → 未預期檔案守門 → commit）**到目前為止一次都沒有跑過**。
唯一一次手動觸發在 `changed=false` 就短路了。

其中 `check_integrity.py` 這一步是後來才加的，**從未在 runner 上執行**。

cron 是 `0 23 * * 1-5`（週末不跑），因此下一次機會是 **2026-08-10（週一）23:00 UTC**。

要看結果：GitHub 的 Actions 頁面，或直接看 `main` 上有沒有出現
`chore: refresh market and filing data (...)` 這筆 bot commit。

---

## C. 不在這份清單上的東西

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
