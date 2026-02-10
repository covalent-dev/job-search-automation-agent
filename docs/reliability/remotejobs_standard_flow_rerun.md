# RemoteJobs Standardized Flow Rerun

Date: 2026-02-10  
Board: `remotejobs`  
Standard flow: `./scripts/run_standard_test_flow.sh remotejobs --mode full --warmup-runs 2 --measured-runs 10 --sleep-seconds 75`

## Run Artifacts

Primary completed run:
- Run ID: `20260210_035109`
- Artifact dir: `docs/reliability/artifacts/remotejobs_standard_flow/20260210_035109`
- Started (UTC): `2026-02-10 03:51:09`
- Finished (UTC): `2026-02-10 06:08:04`
- Run table: `docs/reliability/artifacts/remotejobs_standard_flow/20260210_035109/run_table.tsv`

Note:
- An earlier attempt (`20260210_031541`) ended early due a transient shell error and was superseded by the completed rerun above.

## Battery (No-Proxy)

| Suite | RC | Jobs | Desc Nonempty | Salary Nonempty | Company Known |
|---|---:|---:|---:|---:|---:|
| smoke | 0 | 5 | 5 | 3 | 0 |
| standard | 0 | 20 | 20 | 11 | 0 |

## Soak Dedupe-Off (Availability Signal)

Scope used for reliability verdict:
- `suite == soak_dedupe_off`
- `phase == measured`
- Measured runs: `10`

### Measured Summary

| Metric | Result | Target | Pass |
|---|---:|---:|---:|
| Pass rate (`jobs_count >= 1`) | `10/10 = 100%` | `>= 85%` | ✅ |
| Description active (`desc_nonempty >= 1`) | `10/10 = 100%` | `>= 80%` | ✅ |
| Company active (`company_known > 0`) | `10/10` | `>= 1 run` | ✅ |

Additional context (measured dedupe-off):
- `jobs_count` range: `60-61` (avg `60.7`)
- `dedupe_removed` range: `0-0` (expected for dedupe-off)
- All measured run RCs: `0`

## Soak Dedupe-On (Novelty Trend Only)

Scope:
- `suite == soak_dedupe_on`
- `phase == measured`
- Measured runs: `10`

Measured novelty trend:
- `jobs_count >= 1`: `0/10`
- `jobs_count` avg: `0.0`
- `dedupe_removed` range: `60-61` (avg `60.4`)
- All measured run RCs: `0`

Interpretation:
- Dedupe-on rapidly exhausts novelty against the current candidate pool.
- This is expected and does **not** determine reliability readiness.
- Availability readiness remains based on dedupe-off only.

## Proxy Dedupe-Off Comparison

Not executed.

Reason:
- No-proxy dedupe-off already met all standardized availability gates with margin.
- Per standardized flow, proxy comparison is only required when no-proxy dedupe-off misses targets and proxy variables are available.

## Final Recommendation

`READY_FOR_24_7_PILOT`

Rationale:
- Standardized availability gates all pass on dedupe-off measured runs (`100%` across required checks).
- No-proxy configuration demonstrates stable extraction at production-shape cadence.
- Dedupe-on collapse is treated correctly as novelty depletion, not availability failure.
