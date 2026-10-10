# 科技股前瞻驗證｜調整後價格來源核查

查核時間：2026-10-10（美股 10-09 收盤後）。這是**來源與入場準備核查**，不是入場紀錄、回測或報酬結果。凍結名單與評分規則仍以 [10-10 原始檔](../tech_stock_validation_20261010.json)為準。

## 資料源與覆蓋

- 採用專案現有的 Yahoo Finance／`yfinance` 日線，明確指定 `auto_adjust=False`，取 `Adj Close`，同時保存 `Close`、`Dividends`、`Stock Splits`。Yahoo 的[調整收盤價說明](https://in.help.yahoo.com/kb/finance/adjusted-close-sln28256.html)涵蓋拆股與現金股息；[yfinance 下載參數](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)可取這些欄位。此為第三方資料，並非交易所官方結算檔。
- 10-10 查詢 2026-08-20 至 10-09：凍結池 **144/144** 檔與 SPY／VGT **2/2** 檔，均有 10-09 日線及至少 22 筆此前日線，可供入場前 21 個共同交易日動能計算。[原始查詢壓縮檔](../research/tech_stock_validation/price_source_probe_2026-10-10.json.gz)的解壓 JSON SHA-256：`cf821671ec7287d8cac0e21c4e501e9d0fbac13af04a04e083acf836dac48842`（壓縮檔 SHA-256：`bb473a56acda8c54d8ea90fe0da2e857d7ee6e02251d0c32a79068fde7f2e0df`）。入場時須重新擷取並另存，不把這次查詢當入場資料。
- 8 張卡的 10-09 `Close` 與當日[地圖原始價格快照](../tech_stock_map_history/2026-10/2026-10-09.json)逐檔核對，美元分位一致。此僅驗證對接，不能替代公司行為調整。

## 公司行為抽驗

- SPY 2026-09-18 的 Yahoo 配息欄為 **1.889 美元**；9-17 `Close` 762.600、`Adj Close` 760.711，與[基金配息日程](https://www.ssga.com/library-content/products/fund-data/etfs/us/distribution/SPDR_Dividend_Distribution_Schedule.pdf)的 9-18 除息日一致。VGT 9-23 的查詢配息欄為 **0.147 美元**；其前日 `Close` 126.410、`Adj Close` 126.263。VGT 金額僅由報價商資料確認，未做基金官方金額交叉核對。
- NVDA 的歷史拆股點抽驗：公司[投資人關係公告](https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2025/)載明 2024 年 10 拆 1；另行抓取的 Yahoo 公司行為欄在 2024-06-10 顯示 10。這是資料源可辨識已知拆股的點檢，不代表 146 檔所有歷史公司行為皆已人工逐筆核實。

## 首次入場與對照的執行門檻

1. **目前仍待入場**：凍結時點在 10-09 收盤後，10-09 不可起算；等凍結後 SPY 與 VGT 的第一個共同美股收盤日，並待隔天取得完整日線，才寫入不可覆寫的 `research/tech_stock_validation/entry_日期.json`；若缺價，保留原 8 檔並標明缺值。工具：[prepare_tech_stock_validation_entry.py](../scripts/prepare_tech_stock_validation_entry.py)。
2. **價格動能對照**：同一份凍結的 144 檔池，以入場前 21 個 SPY／VGT 共同交易日之 `Adj Close` 報酬，在同產業大類的無卡片公司中找絕對差最小者；平手代號字母序。依原卡片順序**不重複使用**對照公司。這是入場前補明的實作細節，沒有查看任何未來結果。
3. **成本與價格修訂**：本先導樣本只做觀察；屆時同報稅費／滑價的每邊 **0、10、25 bps** 敏感度，不把零成本當可交易績效。Yahoo 會在往後配息後追溯調整歷史 `Adj Close`，所以每次成果需用**同一次重新抓取**的入場與終點調整價計算，保留查詢時間與原始序列；不得把今天存下的入場價直接與未來新版本調整價相除。

8 張卡是人工選樣，且 136 檔「無卡片」不等於無題材。即使 20／60 日結果成熟，也只作描述，不宣稱勝率已驗證或題材卡有預測增益。
