# Glassdoor Viability Report

**Generated:** 2026-02-06 04:49 UTC  
**Board:** `glassdoor`  
**Config:** `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/config/reliability_smoke.yaml`  
**Warmup Runs:** 1  
**Measured Runs:** 20  
**Spread:** `immediate`  
**Sleep Between Runs:** 45s (base)  
**Target Success Rate:** 80.0%  
**Success Rate (95% CI, Wilson):** 75.0% (CI: 53.1% - 88.8%)  
**Artifact Dir:** `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260206_041218`

## Viability Criteria (Defaults)

- Minimum measured runs for decision: **20**
- GO threshold: **80.0%** (basis: CI lower bound)
- Stability gate: longest consecutive-failure streak **< 3**
- Latency gate: p50 ≤ **180s**, p95 ≤ **420s**
- Cost gate: report `capsolver_solved` count; multiply by your solver $/solve to estimate $/successful run

## Results

- Successes: **15/20** (**75.0%**) (pass = `jobs_unique_collected >= 1`)
- Duration p50: **60.2s**
- Duration p95: **107.2s**
- Longest success streak: **8**
- Longest failure streak: **2**
- Captcha encounters (sum): **19**
- Blocked pages (sum): **19**
- CapSolver solved (sum): **17**
- Solver failures (sum): **2**

## Attempts (Measured)

| Run | Pass | jobs_unique_collected | failure_stage | failure_kind | duration_s | captcha_encounters | blocked_pages | capsolver_solved | solver_failures | exit_code | run_metrics |
|---:|:---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | ❌ | 0 | results | selector | 37.1 | 0 | 0 | 0 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041340.json` |
| 2 | ✅ | 5 |  |  | 61.2 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041502.json` |
| 3 | ✅ | 5 |  |  | 58.7 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041649.json` |
| 4 | ✅ | 5 |  |  | 129.7 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041833.json` |
| 5 | ✅ | 5 |  |  | 58.3 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_042129.json` |
| 6 | ✅ | 5 |  |  | 82.5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_042312.json` |
| 7 | ✅ | 5 |  |  | 61.7 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_042520.json` |
| 8 | ✅ | 5 |  |  | 62.0 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_042707.json` |
| 9 | ✅ | 5 |  |  | 57.8 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_042855.json` |
| 10 | ❌ | 0 | results | selector | 35.6 | 0 | 0 | 0 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043038.json` |
| 11 | ❌ | 0 | results | selector | 36.3 | 0 | 0 | 0 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043159.json` |
| 12 | ✅ | 5 |  |  | 60.5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043321.json` |
| 13 | ✅ | 5 |  |  | 61.4 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043507.json` |
| 14 | ✅ | 5 |  |  | 58.4 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043654.json` |
| 15 | ❌ | 0 | search | challenge | 106.0 | 2 | 2 | 1 | 1 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_043838.json` |
| 16 | ✅ | 5 |  |  | 61.1 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_044109.json` |
| 17 | ❌ | 0 | search | challenge | 99.8 | 2 | 2 | 1 | 1 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_044256.json` |
| 18 | ✅ | 5 |  |  | 59.8 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_044521.json` |
| 19 | ✅ | 5 |  |  | 57.1 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_044707.json` |
| 20 | ✅ | 5 |  |  | 55.6 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_044849.json` |

## Failure Breakdown

- pass: 15
- selector: 3
- challenge: 2

## Failure Breakdown (Stage)

- results: 3
- search: 2

## Failure Breakdown (Stage:Kind)

- results:selector: 3
- search:challenge: 2

## Failure Notes (Best-Effort)

- timeout: 5

## Example Artifacts

- Success stdout: `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260206_041218/measured_run_02.stdout.log`
- Success metrics: `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041502.json`
- Failure stdout: `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260206_041218/measured_run_01.stdout.log`
- Failure metrics: `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260206_041340.json`
- Failure note: timeout

## Decision

**NO-GO**

Basis: CI lower bound (53.1%) vs threshold 80.0%.
Criteria: stability=PASS, latency=PASS.

### What Would Change This Decision

- Increase sample size to 50 measured runs (preferably time-spread) and re-evaluate CI.
- If failures are mostly `timeout`: test with lower-latency proxies and consider timeout tuning (navigation/page).
- If failures are mostly `selector`: re-run recon and update selectors for results cards/details.
- If failures are mostly `challenge`: treat as not production-viable; prefer alternate sources or reduce automation surface area.
