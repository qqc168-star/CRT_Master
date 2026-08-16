# CRT V1.10 Formal Candidate（正式候選版）Rebuild V0.1（重建版）

## 狀態

- Candidate rebuild（候選版重建）: `USER_APPROVED_2026-08-17`
- Exact candidate hash approval（候選版精確雜湊批准）: `NOT_YET_APPROVED`
- Formal model（正式模型）: `NOT_APPROVED`
- Production（正式生產）: `NOT_APPROVED`
- External Action Authority（外部行動權限）: `NONE`
- `action_output`: `NONE`
- Capital decision authority（資本決定權）: `USER_ONLY`

合併或執行本候選版，不等於正式模型批准，也不會啟動交易、帳戶、電郵、Webhook（網路回呼）或資金操作。

## 鎖定來源

- V1.10 Formal Seal（正式封印）: `RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md`
- Parent scoring registry（父計分規格）: `research/CRT_SIX_LAYER_CANDIDATE_V0.1.json`
- Parent canonical SHA-256（父規格標準化雜湊）: `62497bab3e7d551f45e6b3bc23b367575927d5be6be9f25a0956566e1d64c2ee`
- Runtime candidate contract canonical SHA-256（執行候選合約標準化雜湊）: `4fb559c5e0620f4c69a615b1bf2929193cddafc14bacdbe90d89f35081cd370f`
- Base main SHA（基準主分支提交）: `dc49442efa4a2b2cc442f77e13f4bb7b91b33e77`

## 不變常數

- Six-layer weights（六層權重）: `20 / 20 / 17 / 25 / 13 / 5`
- Light thresholds（燈號閾值）: `-60 / -35 / 35 / 60`
- mNAV semantics（資產淨值倍數語義）: `Diluted Equity mNAV`
- Missing-data policy（缺值政策）: `BLOCK_NO_RENORMALIZATION`
- Formal constant modification authority（正式常數修改權限）: `NONE`

## 可執行範圍

- `src/crt_radar/candidate_engine.py`: 共用 deterministic scoring engine（確定性計分引擎）。
- `src/crt_radar/v110_candidate.py`: Evidence Pack（證據包）與 ObservationStore（觀測歷史庫）接線、來源身分檢查、候選輸出及季節封閉路由。
- `CONFIG/V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json`: 19 個特徵的層級、指標與准許來源綁定。
- `src/crt_radar/evidence_pack.py`: 公開候選分數表面，但正式 `score` 與 `season` 維持 `null`。

## Season Router（季節路由器）邊界

目前只恢復可執行的 fail-closed router（失敗即封閉路由器）。找不到可驗證的 V1.10 season state transition contract（季節狀態轉移合約），因此：

- score-derived weather bucket（分數衍生天氣區間）可以作候選觀察；
- candidate score（候選分數）不得自行決定 BTC season（比特幣季節）；
- `season` 必須保持 `null`；
- 阻塞碼固定為 `V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED`。

## 2026-08-17 Live read-only replay（即時唯讀回放）

候選執行器正確封閉於：

- L3 official point-in-time ETP flow（第三層官方點時 ETP 資金流）缺值；
- L4 24-hour liquidation metrics（第四層 24 小時爆倉指標）尚未成熟；
- L6 formal three-venue composite and aggressor feed（第六層正式三交易所合成與成交方向來源）未接入；
- 多層 transform history（轉換歷史）不足；
- L4 OI history（第四層未平倉歷史）存在重複時間戳，需先完成 point-in-time revision policy（點時修訂政策）。

因此實況輸出為：

- `candidate_score = null`
- `formal_score = null`
- `season = null`
- `external_action_authority = NONE`
- `external_action_performed = false`

## 後續批准界線

候選版完成測試後，仍需使用者另外批准精確 registry hash（規格雜湊），才可另開 formal promotion（正式晉升）工程。資料與歷史阻塞未解除前，20 次 qualified run（合格運行）不得開始計數。
