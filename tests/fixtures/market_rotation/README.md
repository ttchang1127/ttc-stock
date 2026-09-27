# 市場輪動測試 fixture

全部為合成資料：不連網、不含隨機數，也不複製任何一天的正式行情。正式行情每天會變，不適合當單元測試標準答案。

| 目錄／檔案 | 用途 |
|---|---|
| `make_fixtures.py` | 以固定算式重新產生 `quadrants/` 的輸入；重跑必須得到位元組相同的檔案 |
| `quadrants/` | 四象限、綜合分數、廣度、量能、持續性、軌跡與領漲／落後個股的現況基準 |
契約錯誤案例（NaN、缺欄位、未知象限、排序錯誤等）在 `tests/test_market_rotation_contracts.py` 內由 golden 複製後
改壞一處產生，不另存大型錯誤 JSON，避免 golden 更新時錯誤範例跟著過期。

邊界案例（74／75 日、22／24 涵蓋率、群組最少成員、零成交量、非有限價格、點號 ticker 等）在
`tests/test_market_rotation_boundaries.py` 內以「複製 quadrants 後明確修改一處」的方式建立，讓每個案例刻意製造的條件
直接寫在測試裡。

## Golden 更新規則

`quadrants/expected_v1.json` 是目前 v1 計算的基準輸出，只忽略 `generated_at`。一般測試**不會**自動更新它。

```bash
python3 tests/market_rotation_fixture.py                  # 只顯示差異；有差異時以非零狀態結束
python3 tests/market_rotation_fixture.py --update-golden  # 顯示差異後寫入
```

只有下列情況可以更新：經確認的公式規格改變、schema 欄位改變、修復會影響既有數值的明確 bug、排序
tie-breaker 正式改變。commit 說明必須列出原因、受影響案例、受影響欄位與預期使用者可見變化。

不得因為「某台機器測試失敗但原因未查清」、「只有日期或空白不同」或「想讓測試變綠」而更新。
