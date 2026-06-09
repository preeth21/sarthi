# sArthI Simulation Findings — Jun 5–8, 2026

## Context
Testing the autonomous fetch → investigate → resolve pipeline using the simulator DAG
`INTLDLDAT-ET360-SIMULATOR-TEST-DAG` on `ET360-CL-DEV` (Chile dev Airflow).

Files involved:
- `/Users/akiran/.wibey/agents/sarthi/simulator.py` — scenario harness
- `/Users/akiran/.wibey/agents/sarthi/check.sh` — 3-stage pipeline orchestrator
- `/Users/akiran/.wibey/agents/sarthi/fetcher.py` — Stage 1: fetch DAG failures
- `/Users/akiran/.wibey/agents/sarthi/investigate.md` — Stage 2: AI classification
- `/Users/akiran/.wibey/agents/sarthi/executor.py` — Stage 3: execute actions

---

## Simulation Run: Jun 5, 2026

### What happened
Triggered `INTLDLDAT-ET360-SIMULATOR-TEST-DAG` on `ET360-CL-DEV` multiple times.
`sim.sensor` kept getting stuck, requiring manual `clear_task_with_deps` + `set_dag_run_state` 3 times.
This was testing the ops MCP tools interactively before the automated pipeline was ready.

| Time (UTC) | Action | Task |
|------------|--------|------|
| 08:41 | trigger_dag_run | — |
| 08:58 | trigger_dag_run | — |
| 09:25 | trigger_dag_run | — |
| 09:29 | clear_task_with_deps | sim.sensor ⚠️ |
| 09:29 | set_dag_run_state | — |
| 09:35 | clear_task_with_deps | sim.sensor ⚠️ (again) |
| 09:35 | set_dag_run_state | — |
| 09:56 | trigger_dag_run | — |
| 10:16 | trigger_dag_run | — |
| 10:21 | clear_task_with_deps | sim.sensor ⚠️ |

Also on Jun 5: `simulator.py` was heavily refactored (260 lines removed, 72 added) and
`fetcher.py` was updated with mail fallback and conf-based log synthesis.

---

## Simulation Run: Jun 8, 2026

### PASS 1 — gcs_absent scenario ✅ PASSED

**Setup**: Done file removed from GCS (`gs://wmt-intl-dp-etrans-360-dev-resources/ET360/s0d0gak/pipeline-resources/simulator-test/sim.done`)

**DAG run**: `manual__2026-06-08T09:17:51.162466+00:00`  
**Result**: DAG failed at `sim.sensor` (09:18:29 UTC, ~38s)

**check.sh result**:
- Stage 1 (fetch): Found 1 failure
- Stage 2 (investigate): Classified as Pattern D — dependency_failure
- Stage 3 (execute): No actions (correct — wait for upstream)

```json
// actions.json
[]

// manual_review.json
[{
  "type": "dependency_failure",
  "env_name": "ET360-CL-DEV",
  "dag_id": "INTLDLDAT-ET360-SIMULATOR-TEST-DAG",
  "run_id": "manual__2026-06-08T09:17:51.162466+00:00",
  "task_id": "sim.sensor",
  "gcs_path": "gs://wmt-intl-dp-etrans-360-dev-resources/ET360/s0d0gak/pipeline-resources/simulator-test/sim.done",
  "gcs_confirmed_absent": true,
  "reason": "Done file confirmed absent — upstream dependency not yet delivered. No Airflow action; wait for upstream.",
  "log_snippet": "[log unavailable — synthesised from dag_run.conf]\n[sim.sensor] Checking existence of: gs://..."
}]
```

**Verdict**: ✅ Correct behavior. sArthI correctly:
1. Detected the failure
2. Extracted the GCS path from `dag_run.conf`
3. Confirmed file absent via `gcs_stat`
4. Routed to `manual_review` (no auto-action — wait for upstream)

---

### PASS 2 — gcs_present scenario ❌ BUG FOUND → FIXED

**Original behavior (buggy)**:  
`simulator.py` used `fail_at_task=sim.sensor` in the conf. Expected: sensor task would fail with injected message.  
Actual: sensor task SUCCEEDED because `_sensor_fn` uses `GCSHook.exists()` directly — it does NOT call `_should_fail()`.  
DAG ran fully clean (all 6 tasks success). Nothing for sArthI to resolve.

**Root cause**:  
The simulator DAG has two types of task functions:
- `_sensor_fn` — uses `GCSHook.exists()` for real GCS check; ignores `fail_at_task` conf
- `_make_task_fn` — respects `fail_at_task` conf via `_should_fail()`

`gcs_present` scenario incorrectly targeted `sim.sensor` (uses `_sensor_fn`) instead of a `_make_task_fn` task.

**Fix applied** (`simulator.py` — Jun 8, 2026):
```python
# Before (broken):
conf = {
    "fail_at_task": "sim.sensor",   # _sensor_fn ignores this
    "fail_message": f"GCSObjectExistenceSensor timeout: done file absent at {GCS_DONE_PATH}",
    "gcs_sensor_path": GCS_DONE_PATH,
}

# After (fixed):
conf = {
    "fail_at_task": "sim.task_a",  # first _make_task_fn task — respects _should_fail()
    "fail_message": f"GCSObjectExistenceSensor timeout: done file absent at {GCS_DONE_PATH}",
    "gcs_sensor_path": GCS_DONE_PATH,
}
```

**Expected behavior after fix**:
- Sensor passes (file is present in GCS)
- `sim.task_a` fails with the injected sensor-like message
- Investigator extracts `gcs_sensor_path` from `dag_run.conf`
- `gcs_stat` confirms file IS present
- Auto-resolves: `clear_task_with_deps(sim.task_a)` + `set_dag_run_state(queued)`
- `manual_review.json` → empty

**Status**: Fixed in code, not yet re-validated live.

---

## Key Technical Findings

### 1. Log unavailability fallback chain (fetcher.py)
When Airflow task logs are unavailable (Elasticsearch error or empty):
1. Try `get_dag_run_conf` → synthesise log from `gcs_sensor_path` field
2. Try `mail_search` for recent Airflow alert emails for that DAG
3. Fall back to `[log unavailable — no mail alerts found]`

This fallback is what made `gcs_absent` work — the sensor log was unavailable,
but `dag_run.conf.gcs_sensor_path` was used to synthesise a meaningful log line.

### 2. Simulator DAG task types
```
sim.sensor  → _sensor_fn (GCSHook.exists, ignores fail_at_task conf)
sim.task_a  → _make_task_fn (respects fail_at_task conf)  ← use for gcs_present
sim.task_b  → _make_task_fn + execution_timeout=10s       ← use for timeout scenario
sim.task_c  → _make_task_fn                               ← use for consecutive scenario
sim.task_d  → _make_task_fn                               ← use for sql_error scenario
sim.task_e  → _make_task_fn
```

### 3. Airflow session management
- Session expired (302 redirect) breaks `trigger_dag_run` silently
- Fix: call `mcp__sarthi-airflow-auth__refresh_session` before simulator runs
- Duration: ~84s (headless Playwright)
- Refreshes all environments at once (53 cookies written)

### 4. Auth note on Jun 5 ops.jsonl
Early Jun 3 runs (`dag.modlr.mx.bq_data_load` on `MX-MODLR-DEV`) were separate from the simulator — those were MODLR pipeline testing, not sArthI simulation.

---

---

## Simulation Run: Jun 8, 2026 (afternoon — 4-scenario batch)

### Infrastructure fix: check.sh --sim flag

`check.sh` was skipping the simulator DAG because `fetcher.py` filters out DAGs
marked `test_dag: true` in config.yaml (correct for prod monitoring).

Fix: added `--sim` flag to both `check.sh` and `fetcher.py`:
```bash
./check.sh --sim   # includes test DAGs — use for simulation
./check.sh         # production mode — skips test DAGs (unchanged)
```

fetcher.py `fetch_all_failed_dags(sim_mode=True)` bypasses `_TEST_DAG_IDS` filter.

---

### PASS 2 — gcs_present ✅ VALIDATED (re-run after fix)

**DAG run**: `manual__2026-06-08T14:13:22.184712+00:00`

Sequence:
- `sim.sensor` → success (GCS file present ✅)
- `sim.task_a` → failed (injected: `fail_at_task=sim.task_a` ✅)

**check.sh --sim result**:
```json
// actions.json
[
  { "action": "clear_task_with_deps", "task_id": "sim.task_a" },
  { "action": "set_dag_run_state", "state": "queued" }
]
// manual_review.json → []
```
**Verdict**: ✅ Correct. Auto-resolved. `gcs_stat` confirmed file present → clear + requeue.

---

### PASS 3 — sql_error ✅ VALIDATED

**DAG run**: `manual__2026-06-08T14:20:43.497596+00:00`
**conf**: `fail_at_task=sim.task_d`, BigQuery column-not-found error message

**check.sh --sim result**:
```json
// manual_review.json
[{
  "type": "code_or_data_error",
  "task_id": "sim.sensor",     // ← task_id attribution off (sensor not task_d) — cosmetic
  "reason": "Schema mismatch — column 'item_id' not found in table ...",
  "log_snippet": "column not found: item_id at [3:15]\nBigQueryException: ..."
}]
// actions.json → []
```
**Verdict**: ✅ Correct classification and routing. No auto-action for code errors.
Minor: task_id shows `sim.sensor` instead of `sim.task_d` — log synthesis attributes
to sensor because conf-fallback path doesn't distinguish which task the message came from.

---

### PASS 4 — timeout ⚠️ MISCLASSIFIED

**DAG run**: `manual__2026-06-08T14:23:09.462084+00:00`
**conf**: `fail_at_task=sim.task_b`, `AirflowTaskTimeout` message

**check.sh --sim result**:
```json
// manual_review.json
[{
  "type": "dependency_failure",   // ← WRONG: should be transient_error / Pattern A
  "reason": "Sensor/dependency failure ... ⚠️ 3 consecutive failures",
  "log_snippet": "... AirflowTaskTimeout: airflow.exceptions.AirflowTaskTimeout"
}]
// actions.json → []   // ← WRONG: should be clear_task_with_deps + requeue
```
**Verdict**: ❌ Misclassified. `AirflowTaskTimeout` should trigger Pattern A (transient/auto-retry).
Investigator fell through to dependency_failure because it couldn't extract a GCS path.

**Root cause**: investigate.md pattern matching for Pattern A needs to explicitly include
`AirflowTaskTimeout` as a transient trigger, separate from GCS path extraction logic.

---

### PASS 5 — ssl_eof ⚠️ MISCLASSIFIED (new scenario, based on real COIM incident)

**DAG run**: `manual__2026-06-08T14:26:19.292110+00:00`
**conf**: `fail_at_task=sim.task_b`, real SSL EOF error from COIM BQ-to-Hive job

**check.sh --sim result**:
```json
// manual_review.json
[{
  "type": "dependency_failure",   // ← WRONG: should be transient_error
  "reason": "... SSL/network error (SSLEOFError) against bigquery.googleapis.com.
             ⚠️ 4 consecutive failures — PERSISTENT FAILURE",
  "log_snippet": "HTTPSConnectionPool(host='bigquery.googleapis.com') ... SSLEOFError ..."
}]
// actions.json → []   // ← WRONG: should be clear_task_with_deps + requeue
```
**Verdict**: ❌ Investigator detected SSL EOF correctly in the reason text but still
routed to manual_review. Pattern A classification for SSL/network errors not firing.

**Note on consecutive counter**: All 4 scenarios used the same DAG — streak counter
shows 4 consecutive failures. This is expected behaviour (same DAG ID = same streak).
In practice this is correct; a team would investigate streak after 3+ failures.

---

## Bugs Found and Fixed (Jun 8 afternoon)

### BUG-SIM-001: Pattern A not firing for AirflowTaskTimeout ✅ FIXED
- **Scenario**: `timeout`
- **Root cause**: `investigate.md` Pattern D (sensor/dependency) matched first because
  task name contained "sensor" — Pattern A keyword list lacked `AirflowTaskTimeout`
- **Fix**: Added `AirflowTaskTimeout`, `AirflowSensorTimeout`, `execution_timeout` to
  Pattern A triggers. Also moved Pattern A BEFORE Pattern D in classification priority
  for SSL/network/timeout keywords (log content > task name for these cases)
- **Re-validated**: ✅ Jun 8 — `actions.json` now shows `clear_task_with_deps` + requeue

### BUG-SIM-002: Pattern A not firing for SSLEOFError ✅ FIXED
- **Scenario**: `ssl_eof`
- **Root cause**: Same priority bug — Pattern D fired before Pattern A
- **Fix**: Added `SSLError`, `SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING`, `SSL: `,
  `HTTPSConnectionPool`, `Max retries exceeded` to Pattern A triggers
- **Re-validated**: ✅ Jun 8 — `actions.json` shows `clear_task_with_deps` + requeue,
  `manual_review.json` empty

---

## Scenarios Status

| Scenario | Status | Notes |
|----------|--------|-------|
| `gcs_absent` | ✅ Validated Jun 8 AM | Works correctly end-to-end |
| `gcs_present` | ✅ Validated Jun 8 PM | Auto-resolves correctly after fix |
| `sql_error` | ✅ Validated Jun 8 PM | manual_review correct, task_id attribution cosmetic |
| `timeout` | ✅ Validated Jun 8 PM (after fix) | AirflowTaskTimeout → Pattern A → auto-resolves |
| `ssl_eof` | ✅ Validated Jun 8 PM (after fix) | SSLEOFError → Pattern A → auto-resolves (new scenario) |
| `consecutive` | ⏳ Not tested | 3 runs at 2s gap — streak detection |

---

## Next Steps
1. ~~Fix `investigate.md`: add `AirflowTaskTimeout` + SSL keywords~~ ✅ Done
2. ~~Re-validate `timeout` + `ssl_eof`~~ ✅ Done
3. Run `consecutive` scenario
4. Fix task_id attribution in log-synthesis path (cosmetic — conf fallback always says `sim.sensor`)
