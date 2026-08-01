# Radar Dependency Graph

```text
P0-01 Registry
  -> P0-02 Isolated baseline
  -> P0-03 Safety Contract
  -> P0-04 Unified Sources
  -> P0-05 Evidence Ledger
  -> P0-06 Quality Engine
       -> P1-01 L4
       -> P1-02 L1
       -> P1-03 L2
       -> P1-04 L3
       -> P1-05 L5
       -> P1-06 L6
            -> P1-07 Locked scoring
            -> P1-08 Season / Path Router
            -> P1-09 Daily Radar
                 -> P2 Asset Radars
                 -> P3 Event / Shadow Research
                 -> P4 Scheduling / Monitoring / Alerts / E2E
```

Current critical path: `P1-01 External 24h Live Shadow` and `P0-04 expansion to the remaining source families`.
