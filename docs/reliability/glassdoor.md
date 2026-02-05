# Glassdoor Reliability Benchmark

**Generated:** 2026-02-05 23:53 UTC  
**Board:** `glassdoor`  
**Config:** `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/config/reliability_smoke.yaml`  
**Warmup Runs:** 1  
**Measured Runs:** 10  
**Sleep Between Runs:** 45s  
**Target Success Rate:** 80.0%  
**Artifact Dir:** `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260205_233542`

## Results

- Successes: **8/10** (**80.0%**) (pass = `jobs_unique_collected >= 1`)
- Captcha encounters (sum): **8**
- Blocked pages (sum): **8**
- CapSolver solved (sum): **8**
- Solver failures (sum): **0**

## Attempts (Measured)

| Run | Pass | jobs_unique_collected | captcha_encounters | blocked_pages | capsolver_solved | solver_failures | exit_code | run_metrics |
|---:|:---:|---:|---:|---:|---:|---:|---:|---|
| 1 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_233703.json` |
| 2 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_233847.json` |
| 3 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234031.json` |
| 4 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234213.json` |
| 5 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234357.json` |
| 6 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234546.json` |
| 7 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234733.json` |
| 8 | ✅ | 5 | 1 | 1 | 1 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_234919.json` |
| 9 | ❌ | 0 | 0 | 0 | 0 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_235105.json` |
| 10 | ❌ | 0 | 0 | 0 | 0 | 0 | 0 | `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_235225.json` |

## Failure Breakdown

- pass: 8
- no_jobs_collected: 2

## Failure Notes (Best-Effort)

- timeout: 2

## Example Artifacts

- Success stdout: `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260205_233542/measured_run_01.stdout.log`
- Success metrics: `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_233703.json`
- Failure stdout: `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/glassdoor/benchmark_20260205_233542/measured_run_09.stdout.log`
- Failure metrics: `/root/covalent-dev/job-search-automation-agent/boards/glassdoor/output/run_metrics_20260205_235105.json`
- Failure note: timeout

## Recommendation

**KEEP provider** (threshold: 80.0%)

Next step: keep provider and monitor weekly; re-run this benchmark after any proxy pool/provider changes.
