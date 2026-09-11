# Live Shadow PASS｜Evidence Provenance Addendum

- Date: `2026-08-06`
- Phase: `Phase F｜Evidence Provenance Repair`
- Historical process run ID: `17cccceb-d819-4fca-aab0-45f6dc9275f1`
- Historical result: `LIVE_SHADOW_PASS`
- Production: `NOT_APPROVED`
- External action authority: `NONE`

## 1. Purpose

本附錄正式保存 Phase R 唯讀證據對帳結果。

本附錄不修改、不取代，也不覆寫原始
`EVIDENCE_MANIFEST.json` 或既有 Live Shadow 證據。

## 2. Historical result retained

2026-08-05 Live Shadow 結果保留為已接受的歷史驗收結果：

- `decision = LIVE_SHADOW_PASS`
- `acceptance_failures = []`
- summary SHA256：
  `3ed0737f8e8c0bd44440ed11f2c4f91bcee154c3bb6eaaaf0b67a2d11be8e1bc8`

Phase R 未發現封存程序修改 summary decision
或清空 acceptance failures 的證據。

## 3. Provenance limitation

Phase R 已確認以下時間順序：

1. PASS summary 先產生。
2. Validator 與 Git 狀態其後發生變化。
3. Git reset／版本切換事件發生。
4. Evidence manifest 最後才建立。
5. Manifest 記錄的是封存當時存在的 validator。

因此，manifest 中的 validator SHA256 可證明：

`ARCHIVE_TIME_VALIDATOR_VERSION`

但不能證明該版本就是：

`EXACT_SUMMARY_GENERATION_VALIDATOR_VERSION`

## 4. Diagnostic conflict

封存證據顯示：

- minimum observed coverage ratio：
  `0.0006919097222222222`
- blocked snapshot count：
  `1368`
- saved policy minimum coverage ratio：
  `0.95`

目前保存的 validator 對低 coverage 與 blocked snapshot
採用 hard gate。

所以歷史 PASS 無法由目前保存的 validator、policy
及 diagnostic 數值直接重現。

## 5. Formal classification

- Primary：
  `EVIDENCE_PROVENANCE_ORDERING_DEFECT`
- Secondary：
  `GIT_VERSION_CHANGED_BETWEEN_SUMMARY_AND_ARCHIVE`
- Reproducibility：
  `REPRODUCIBILITY_PROVENANCE_GAP`

## 6. Governance effect

歷史 `LIVE_SHADOW_PASS` 保留。

不得宣稱：

- 目前保存的 validator＋policy 能完整重現歷史 PASS。
- Manifest validator SHA256 已證明是原始 summary 產生版本。
- 歷史 PASS 等同 Production 核准。

## 7. Operational boundary

本附錄不授權：

- Production promotion
- Trading 或 account access
- Email、webhook 或 notification
- Policy、threshold 或 validator 邏輯修改
- Live Shadow 重跑
- Preserved stash 的 pop、apply、drop 或改寫

`EXTERNAL_ACTION_AUTHORITY=NONE`
