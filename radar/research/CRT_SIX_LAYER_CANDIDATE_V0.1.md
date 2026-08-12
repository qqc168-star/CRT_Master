# CRT 六層 Research-only Candidate（僅研究候選模型）V0.1

## 狀態與權限邊界

- `status`: `RESEARCH_ONLY_NOT_APPROVED`
- `base_sha`: `a267ea84e797d41a5e973523d7d013fdf00ba773`
- Production（正式生產）: `NOT_APPROVED`
- External Action Authority（外部行動權限）: `NONE`
- `action_output`: `NONE`
- 最終資本決定權：`USER_ONLY`

這份規格只建立可重播、可反證的 candidate score（候選分數）。它不修改或取代 formal model（正式模型），不產生 BTC season（比特幣季節）、asset role（資產角色）、capital strategy（資本策略）、`BUY`、`SELL` 或任何外部動作。

## 設計目的

六個 layer score（層級分數）都在 `[-100, 100]`：正值表示在本候選假說下，證據對 BTC market weather（比特幣市場天氣）較支持；負值表示較不支持；零表示混合或相對歷史普通。它描述 evidence（證據），不是 decision（決策）。

候選總分使用 formal seal（正式封印）已存在的 `20 / 20 / 17 / 25 / 13 / 5` 做 offline comparison（離線比較），沒有改動這組數字。任何必要 feature（特徵）缺失、過期、無法驗證或歷史不足時，該層與整體都 `BLOCKED`；不得 zero-fill（補零）、stale reuse（沿用過期值）或 reweight（重新配權）。

## 六層結構

| Layer（層級） | 內部權重 | Candidate hypothesis（候選假說） |
|---|---:|---|
| L1 Macro（宏觀） | 核心通膨加速度 40%；失業惡化 30%；實質政策利率 30% | 通膨壓力下降、勞動市場未急速惡化、政策限制減輕時較支持。 |
| L2 USD / Rates（美元／利率） | 廣義美元 40%；10 年實質利率 35%；2 年名目利率 25% | 20 日美元與利率壓力下降時較支持。`DTWEXBGS` 不得稱為 `DXY`。 |
| L3 Credit / Liquidity（信用／流動性） | 穩定幣供給 35%；現貨 BTC ETP（交易所交易產品）淨申贖 35%；High Yield OAS（高收益債選擇權調整利差）30% | Crypto-native liquidity（加密原生流動性）、regulated-wrapper demand（受監管包裝工具需求）與廣義信用壓力共同判斷。 |
| L4 Leverage（槓桿） | OI / market cap（未平倉量／市值）30%；Funding（資金費率）極端 25%；清算強度 20%；清算方向 25% | 擁擠與強制流越大越不支持；short liquidation（空單清算）相對 long liquidation（多單清算）較支持，但只作方向證據。 |
| L5 On-chain Value（鏈上價值） | `MVRV` 週期分位 70%；realized cap growth（實現市值成長）30% | 較低的週期相對估值與擴張中的鏈上成本基礎較支持。 |
| L6 Price Structure（價格結構） | 價格／200 日均線 30%；50／200 日均線 25%；波動調整動能 25%；`CVD` 20% | 趨勢、動能與 signed-volume confirmation（帶方向成交量確認）一致時較支持。 |

所有 raw formula（原始公式）、series ID（序列識別碼）、方向、歷史窗與來源前置條件，以 `CRT_SIX_LAYER_CANDIDATE_V0.1.json` 為 machine-readable SSOT（機器可讀唯一真實來源）。

## 正規化與聚合

### `ROBUST_Z`

只使用 current observation（目前觀測）之前的歷史：

\[
z_t=\frac{x_t-\operatorname{median}(H_t)}{1.4826\operatorname{MAD}(H_t)}
\]

把 \(z_t\) 截在 `[-3, 3]`，乘上 feature direction（特徵方向），再線性映射到 `[-100, 100]`。`MAD=0` 時 fail closed（失敗關閉）。

### `PERCENTILE`

使用 mid-rank empirical percentile（中秩經驗分位）：

\[
p_t=\frac{\#(H_t<x_t)+0.5\#(H_t=x_t)}{|H_t|},\qquad s_t=d(2p_t-1)100
\]

### `TANH_FIXED`

只用於已具有明確無量綱尺度的 L6 feature（第六層特徵）：

\[
s_t=100\tanh(d x_t/k)
\]

其中 \(k\) 是 candidate parameter（候選參數），不得在 final evaluation sample（最終評估樣本）上調整。

### 聚合

\[
L_i=\sum_j w_{ij}s_{ij},\qquad C=0.20L_1+0.20L_2+0.17L_3+0.25L_4+0.13L_5+0.05L_6
\]

`-60 / -35 / 35 / 60` 只生成 `C0`～`C4` non-formal bucket（非正式分桶）。這些分桶不是正式燈號，更不是動作指令。

## 刻意不重複計票

若 `MVRV = CapMrktCurUSD / CapRealUSD`，則：

\[
NUPL=\frac{CapMrktCurUSD-CapRealUSD}{CapMrktCurUSD}=1-\frac{1}{MVRV}
\]

因此 `NUPL` 沒有第二份 scoring weight（計分權重）；它只作 `L5_MVRV_NUPL_IDENTITY` 一致性檢查。把兩者各自加權會形成 hidden duplicate vote（隱藏重複投票）。

## 適用期與已知弱點

- L3 的現貨 BTC ETP（交易所交易產品）適用期從 `2024-01-11` 開始；更早日期整體 `BLOCKED`，不得把剩餘兩項重新配權。
- L3 的 ETP universe（交易所交易產品集合）、穩定幣 universe（穩定幣集合）、point-in-time shares（當時可得份額）與 split adjustment（拆分調整）仍需 source contract（來源契約）。
- L4 的 Binance OI contract multiplier（幣安未平倉量合約乘數）與跨來源時間對齊仍需鎖定。
- L6 的 spot composite（現貨綜合價）與 aggressor-side trade feed（主動方成交資料）尚無批准來源。
- L1 的通膨與實質政策利率共享通膨資料血統；L2 的兩項利率也可能高度相關，必須做 correlation / redundancy audit（相關性／冗餘稽核）。
- 本設計的方向是假說，不是自然定律；例如降息可能是流動性利多，也可能是衰退警報。模型若無法在不同 regime（市場狀態）下站住，應淘汰而非修辭補妝。

## 驗證分界

目前可由 repository test（儲存庫測試）證明的只有：

1. registry（登錄表）結構、權限與正式常數未變；
2. 正規化、聚合、閾值邊界與 hash replay（雜湊重播）具決定性；
3. 缺失資料不重新配權；
4. `MVRV`／`NUPL` 同源檢查會 fail closed（失敗關閉）；
5. research module（研究模組）未被 `radar/src` 匯入。

這些測試不能證明 predictive validity（預測有效性）。升格前仍需：

1. 鎖定全部 source contract（來源契約）與 point-in-time fixture（當時可得測試資料）；
2. 在看結果前預註冊 walk-forward protocol（走勢前推驗證協定）、7／30／90 日 horizon（預測期間）、bucket test（分桶測試）與 block bootstrap（區塊拔靴法）；
3. 完整評估 post-2024 applicability period（2024 年後適用期），不做 survivorship bias（存活偏誤）與 lookahead bias（前視偏誤）；
4. 完成 prospective read-only shadow（前瞻唯讀影子觀測）；backtest（回測）不能單獨批准模型；
5. 由使用者另行批准精確 registry hash（登錄表雜湊值）。Merge（合併）本身不構成正式批准。

## 第一方資料定義參考

- [Federal Reserve / FRED（聯準會／聖路易聯準銀行）廣義美元 `DTWEXBGS`](https://fred.stlouisfed.org/series/DTWEXBGS)
- [Federal Reserve / FRED（聯準會／聖路易聯準銀行）10 年實質利率 `DFII10`](https://fred.stlouisfed.org/series/DFII10)
- [BLS / FRED（美國勞工統計局／聖路易聯準銀行）CPI（消費者物價指數）](https://fred.stlouisfed.org/series/CPIAUCSL)
- [BLS / FRED（美國勞工統計局／聖路易聯準銀行）失業率 `UNRATE`](https://fred.stlouisfed.org/series/UNRATE)
- [Coin Metrics（鏈上資料供應商）Market Cap / MVRV / Realized Cap（市值／市場價值與實現價值比／實現市值）定義](https://docs.coinmetrics.io/asset-metrics/market/capact1yrusd)
- [Coin Metrics（鏈上資料供應商）NUPL（淨未實現損益）定義](https://docs.coinmetrics.io/asset-metrics/economics/rvtadj)
- [SEC（美國證券交易委員會）2024 現貨 BTC ETP（交易所交易產品）核准命令](https://www.sec.gov/files/rules/sro/nysearca/2024/34-99306.pdf)

## Candidate data plane（候選資料面）V0.1

`CRT_CANDIDATE_SOURCE_CONTRACT_V0.1.json` 現在逐一綁定 19 個 raw-feature calculator（原始特徵計算器）的來源、point-in-time rule（當時可得規則）、revision rule（修訂規則）、資料授權狀態與缺口。`candidate_data.py` 是離線 reference implementation（參考實作），不接 `radar/src`、collector（蒐集器）或 runtime（執行期）。

`CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.1.json` 在讀取歷史結果前預先鎖定 `7 / 30 / 90` 日 horizon（預測期間）、30 日 primary statistic（主要統計量）、moving block bootstrap（移動區塊拔靴法）、缺失政策與 prospective shadow（前瞻影子觀測）門檻。模型設計日以前的歷史只能作 exploratory falsification（探索性反證），不能冒充 untouched holdout（未觸碰保留樣本）。

目前 walk-forward readiness（走勢前推就緒狀態）仍為 `BLOCKED`：尚無 hash-bound point-in-time dataset（雜湊綁定的當時可得資料集），且穩定幣 universe（集合）、ETP feed（交易所交易產品資料流）、Binance contract multiplier（幣安合約乘數）、BTC spot composite（比特幣現貨綜合價）與 trade-aggressor feed（成交主動方資料流）仍待批准。Synthetic fixture（合成測試資料）只能證明公式機械正確，不能計入 predictive evidence（預測證據）。
