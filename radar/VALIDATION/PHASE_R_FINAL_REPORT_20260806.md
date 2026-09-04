# CRT｜Phase R 最終證據對帳報告

- 日期：2026-08-06
- 狀態：COMPLETE
- 完成度：100%
- 正式 SSOT：CRT V1.10
- Production：NOT_APPROVED
- External action authority：NONE

## 一、核心矛盾

保存的 Live Shadow 證據顯示：

- decision = LIVE_SHADOW_PASS
- acceptance_failures = []
- minimum_observed_coverage_ratio = 0.0006919097222222222
- blocked_snapshot_count = 1368
- policy.minimum_coverage_ratio = 0.95

目前保存的 validator 對低 coverage 與 blocked snapshot 採用 hard gate。

因此，目前保存的 validator、policy 與 diagnostic 數值，無法直接重新推出保存的 LIVE_SHADOW_PASS。

## 二、已證實事項

1. Summary SHA256 與 manifest 相符。
2. Validator SHA256 與 manifest 相符。
3. Summary decision 為 LIVE_SHADOW_PASS。
4. Acceptance failures 為空陣列。
5. 封存程序只複製既有 summary。
6. 未發現封存程序修改 decision。
7. 未發現封存程序清空 acceptance failures。
8. Summary 產生後，validator 與 Git 狀態曾發生變化。
9. Manifest 在版本變化後才建立。

## 三、關鍵時間線

| 事件 | UTC | 臺北時間 |
|---|---|---|
| PASS summary 寫入 | 2026-08-05 06:40:38 | 2026-08-05 14:40:38 |
| Validator 版本變化 | 2026-08-05 07:05:23 | 2026-08-05 15:05:23 |
| Git reset 一 | 2026-08-05 07:05:28 | 2026-08-05 15:05:28 |
| Git reset 二 | 2026-08-05 10:46:12 | 2026-08-05 18:46:12 |
| Manifest 建立 | 2026-08-05 11:03:33 | 2026-08-05 19:03:33 |

## 四、Git 來源鏈

- HEAD_AT_SUMMARY：5d3e37ce256bccb240e81fc3aa94542d682d79b2
- VALIDATOR_OR_PARALLEL_WORK_OBJECT：64d1ecdf3fc5621eff5d42f34c1e534f1605c5bf
- ARCHIVE_COMMIT：c89b68b52706470b4ff948e71206555d789a4e26

## 五、根本原因

- EVIDENCE_PROVENANCE_ORDERING_DEFECT
- GIT_VERSION_CHANGED_BETWEEN_SUMMARY_AND_ARCHIVE
- REPRODUCIBILITY_PROVENANCE_GAP

## 六、正式定性

歷史 LIVE_SHADOW_PASS 保留。

Manifest 中的 validator SHA256 應解讀為：

ARCHIVE_TIME_VALIDATOR_VERSION

不得解讀為：

EXACT_SUMMARY_GENERATION_VALIDATOR_VERSION

## 七、使用者實質影響

- 不重跑整個 24 小時 Live Shadow。
- 不降低 0.95 policy 門檻。
- 不推翻歷史 PASS。
- 不宣告 Production。
- 後續只修復證據來源說明與治理鏈。

## 八、最終判定

- PHASE_R = COMPLETE
- HISTORICAL_PASS = ACCEPTED
- SUMMARY_INTEGRITY = VERIFIED
- ARCHIVE_SCRIPT_SUMMARY_MUTATION = NOT_FOUND
- PASS_DIRECTLY_REPRODUCIBLE_FROM_SAVED_VALIDATOR_POLICY = NO
- ROOT_CAUSE = EVIDENCE_PROVENANCE_ORDERING_DEFECT
- REPRODUCIBILITY = PROVENANCE_GAP
- PRODUCTION = NOT_APPROVED
- EXTERNAL_ACTION_AUTHORITY = NONE
