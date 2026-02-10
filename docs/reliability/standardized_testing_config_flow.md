# Standardized Testing and Config Flow (All Supported Boards)

This is the canonical flow for reliability testing. Do not create bespoke batteries per run.

## Scope

Standardized boards in this flow:

- `remotejobs`
- `remoteafrica`
- `linkedin`

## Required Config Levels

Each board must have these config files under `boards/<board>/config/`:

1. `battery.smoke.noproxy.yaml`
2. `battery.standard.noproxy.yaml`
3. `soak.production.noproxy.dedupe_off.yaml` (collector reliability)
4. `soak.production.noproxy.dedupe_on.yaml` (novelty trend)

Optional proxy fallbacks:

1. `soak.production.proxy.dedupe_off.yaml`
2. `soak.production.proxy.dedupe_on.yaml`

## Non-Negotiable Rules

1. Reliability pass/fail is based on **dedupe-off** runs only.
2. Dedupe-on runs are for **novelty trend** only and must not be used as collector availability signal.
3. `output.vault_sync.enabled` must be `false` in all battery/soak test configs.
4. `ai_filter.enabled` must be `false` in battery and dedupe-off soak configs.
5. Proxy credentials must be sourced from environment variables only.

## Validation Gate (Must Run First)

```bash
cd /root/covalent-dev/job-search-automation-agent
python3 scripts/validate_standard_test_configs.py
```

Optional single-board validation:

```bash
python3 scripts/validate_standard_test_configs.py --board remotejobs
```

## Standard Execution Sequence

Use this exact order every time.

Preferred one-command runner:

```bash
./scripts/run_standard_test_flow.sh <board> --mode full --warmup-runs 2 --measured-runs 10 --sleep-seconds 75
```

### 0) Compile Gate

```bash
python3 -m compileall -q shared boards scripts
```

### 1) Battery Gate (No Proxy)

```bash
./scripts/run_board.sh <board> boards/<board>/config/battery.smoke.noproxy.yaml
./scripts/run_board.sh <board> boards/<board>/config/battery.standard.noproxy.yaml
```

### 2) Collector Reliability Soak (Dedupe Off)

- Warmup + measured repeated runs using:
  - `boards/<board>/config/soak.production.noproxy.dedupe_off.yaml`
- Success metric for run-level availability:
  - `jobs_count >= 1`

### 3) Novelty Trend Soak (Dedupe On)

- Repeat using:
  - `boards/<board>/config/soak.production.noproxy.dedupe_on.yaml`
- Use only for:
  - duplicate pressure and new-item yield trend

### 4) Proxy Fallback (Only if Dedupe-Off Misses Target)

- Use:
  - `boards/<board>/config/soak.production.proxy.dedupe_off.yaml`
- Compare reliability against no-proxy dedupe-off results.

## Reporting Contract (Every Run)

Report must include:

1. Exact config paths used.
2. Separate tables for:
   - dedupe-off (reliability)
   - dedupe-on (novelty)
3. Pass-rate summary from dedupe-off only.
4. Artifact references (logs, debug files, run tables).
5. Final recommendation label:
   - `READY_FOR_24_7_PILOT`
   - `READY_WITH_PROXY`
   - `NOT_READY_NEEDS_HARDENING`

## Session/Profile Gate for Cloudflare-Prone Boards

If persistent profile is required and missing:

```bash
cd /root/covalent-dev/job-search-automation-agent
JOB_BOT_BOARD=<board> python3 shared/setup_session.py
```

Then re-run the sequence above.
