# 🏛️ Sec_kb - SEC 財務報告與美股研究 Obsidian 知識庫

歡迎使用 **Sec_kb**！本知識庫專門為美股研究、SEC（美國證券交易委員會）財報分析（10-K, 10-Q, 8-K 等）與公司基本面研究所設計，已整合至你的 `Crucial X8/Jarvis Obsidian` 主庫中。

---

## 📂 Vault 目錄結構 (`/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb`)

```
Sec_kb/
├── 00_Meta/                     # 知識庫元數據與模板
│   ├── Templates/               # Obsidian 筆記模板
│   └── README.md                # 知識庫說明文件
├── 10_Companies/                # 公司主頁 (AAPL, NVDA 等)
│   ├── AAPL/
│   │   └── AAPL_Company_Profile.md
│   └── NVDA/
│       └── NVDA_Company_Profile.md
├── 20_Filings/                  # SEC 申報報告筆記 (10-K / 10-Q)
│   ├── AAPL/ (2023, 2024, 2025 10-K)
│   └── NVDA/ (2024, 2025, 2026 10-K)
├── 30_Analysis/                 # 跨年度/跨公司對比與專題分析
│   └── AAPL_3Year_Financial_Trend.md
└── scripts/                     # 自動化下載與筆記生成腳本
    └── fetch_sec.py
```

---

## 🤖 給維護本庫的 AI 助理

處理 `dashboard.html` / `prices.json` / 股價更新相關工作前，**必須先讀**：

> [[ttc-stock_Dashboard_維運SOP]] — 機械化操作手冊，照步驟執行即可，內含絕對禁止事項。

---

## 🚀 快速上手與擴充指南

在終端機中可直接為任何美股標的生成近 $N$ 年 10-K 報告與公司主頁筆記：

```bash
# 抓取台積電 (TSM) 近 3 年 10-K
python3 "/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb/scripts/fetch_sec.py" TSM --years 3

# 抓取微軟 (MSFT) 近 5 年 10-K
python3 "/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb/scripts/fetch_sec.py" MSFT --years 5
```

---

## 💡 Obsidian 使用技巧
由於 `Sec_kb` 直接位於你外接硬碟的 `Jarvis Obsidian` Vault 目錄下，你不需要另外開 Vault，在 Obsidian 側邊欄即可直接開啓 `Sec_kb` 中的資料夾與雙向連結（如 `[[AAPL_Company_Profile]]`）。
