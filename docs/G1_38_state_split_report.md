# G1.38 - State Hot/Cold Split (Protocol 1.4) - Report

- generated_at: 2026-10-12T11:25:59Z
- original_size_bytes: 285786
- new_hot_size_bytes: 75493
- defects_total: 38 (was 37 + G1.38)
- run_log_count_cold: 64
- decisions_count_cold: 70
- task_ledger_count_cold: 29
- full_backup: _archive/PROJECT_STATE.full_pre_1_4.json
- round_trip_defects: OK (rebuilt == original + G1.38)

## Cold store files
- state/defects/<id>.json (per defect)
- state/run_log.jsonl
- state/decisions_log.json
- state/task_ledger.full.json

