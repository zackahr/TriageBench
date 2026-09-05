# ticket-eval-suite

Harbor-based evaluation suite that tests an AI agent's ability to triage and resolve
customer-support tickets against the business rules in `shared/company_policy.md`,
emitting tickets that conform-tothe schema in `shared/ticket_schema.json`.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Docker (Harbor runs the agent in a container)

## Install Harbor

```bash
uv tool install harbor
```

## Run the suite

Each directory under `tasks/` is an independent Harbor task. Run any task against a
supported agent (`harbor run --help` lists agents; `harbor datasets list` lists
available datasets):

```bash
export ANTHROPIC_API_KEY=your-key   # or the key for your agent provider

# Run one task
harbor run -p tasks/easy-password-reset -a claude-code -m anthropic/claude-sonnet-4-6

# Run every task in the suite
for t in tasks/*/; do
  harbor run -p "${t%/}" -a claude-code -m anthropic/claude-sonnet-4-6
done
```

## Regression testing

`run_suite.py` and `generate_report.py` provide a production-grade regression
pipeline: run every task under `tasks/` against any agent/model, record a
structured run log, and diff runs to flag regressions.

### Prerequisites

- The Harbor Python SDK is pulled in on demand via `uv` (`--with harbor`), so
  no manual install is needed.
- The LLM-as-a-Judge verifier on the medium and hard tasks needs an API key.
  `run_suite.py` auto-loads `./.env` (e.g. `OPENROUTER_API_KEY=...`), the same
  file the tasks expect.

### Execute a regression check

Run the suite against a specified agent configuration. Every invocation writes
a log to `eval_results/run_<timestamp>.json`:

```bash
# Baseline: standard Claude Sonnet
uv run --with harbor python run_suite.py \
  --agent claude-code --model anthropic/claude-sonnet-4-6 \
  --label baseline-sonnet

# Candidate change: lower-tier model (or --extra-instruction for prompt edits)
uv run --with harbor python run_suite.py \
  --agent claude-code --model anthropic/claude-haiku-4-5 \
  --label canary-haiku \
  --extra-instruction experiments/canary-prompt.md

# Generate the Markdown regression report comparing the two latest runs
uv run --with harbor python generate_report.py
```

The report (`eval_results/report_<run_id>.md`) contains a summary table, a
per-task comparison table (baseline vs current, reward delta, deterministic
and LLM-judge sub-scores), an explicit `[REGRESSION]` list for score drops or
pass-to-fail flips, and the exact commands to reproduce both runs.

#### `run_suite.py` options

| Option | Default | Purpose |
|---|---|---|
| `--agent` | `claude-code` | Harbor agent name (or `module.path:ClassName`). |
| `-m, --model` | `anthropic/claude-sonnet-4-6` | Model for the agent. |
| `--label` | `<agent>__<model>` | Human-readable tag recorded in the run log. |
| `-k, --n-attempts` | `1` | Attempts per task; best reward wins. |
| `-n, --n-concurrent` | `1` | Concurrent trials (keep low for stable LLM-judge runs). |
| `--extra-instruction` | — | Instruction file appended to every task (prompt-modification experiments). |
| `--ak key=value` | — | Agent kwarg (repeatable), e.g. `--ak temperature=0`. |
| `--task <name>` / `--exclude-task <name>` | — | Include/exclude tasks by directory name (repeatable). |
| `--dry-run` | — | Print the resolved Harbor `JobConfig` and task list, then exit. |

#### `generate_report.py` options

Run with no args to compare the two most recent logs. To pin specific runs:

```bash
uv run --with harbor python generate_report.py \
  --baseline eval_results/run_<ts>.json --current eval_results/run_<ts>.json \
  --out eval_results/report.md
```

A single log (`--current` only) renders a per-task results table instead of a
comparison. Run logs and reports live in `eval_results/` (git-ignored); raw
Harbor per-trial artifacts stay in `jobs/`.

## Task layout

Every `tasks/<name>/` follows the standard Harbor convention:

- `instruction.md` - the prompt shown to the agent
- `task.toml` - timeouts, resource limits, environment config
- `environment/Dockerfile` - the agent container
- `tests/` - `test.sh` (install + run verifiers) and pytest checks
- `solution/` - reference solution (optional)

`shared/` is not tested directly; it ships policy and schema context into each
agent's container so a correct response must respect company policy and the ticket contract.

## File roles

| File | Role |
|---|---|
| `.gitignore` | Keeps run artifacts out of git: `jobs/` (Harbor output), `.env` (API key), `_out.json`/`resolution.json`, Python caches. |
| `shared/company_policy.md` | **Authoritative business rules** the agent must follow. Source of truth for how password resets, refunds, and escalations work. |
| `shared/ticket_schema.json` | **Output contract** — JSON Schema defining valid `category`/`priority`/`status` enums and required fields. Shared by all tasks. |
| `tasks/<name>/instruction.md` | **Prompt shown to the agent**: read `/workspace/ticket.json`, consult `/workspace/company_policy.md`, write `resolution.json` with the required schema. |
| `tasks/<name>/task.toml` | **Harbor metadata**: task name/description, timeouts (agent, verifier, build), resources (CPU/mem), and network policy per phase. |
| `tasks/<name>/environment/Dockerfile` | Builds the agent container: base image, pinned test dependencies, creates `/workspace` as the working dir. |
| `tasks/<name>/environment/ticket.json` | **Task input** — the end-user ticket (possibly messy) the agent must triage; carries no category/priority. |
| `tasks/<name>/environment/company_policy.md` | Copy of the policy shipped **into the container** at `/workspace/company_policy.md` so the agent reads it at runtime. |
| `tasks/<name>/tests/test.py` | **Deterministic verifier** (pytest): checks `resolution.json` exists/is valid JSON, category, priority, and `action_taken` content. |
| `tasks/<name>/tests/test.sh` | Verifier entrypoint run by Harbor inside the container: runs pytest and writes `1`/`0` to `/logs/verifier/reward.txt` (the reward signal). |
| `tasks/<name>/solution/solve.sh` | **Golden oracle** — correct reference solution; writes the expected `resolution.json`, proving the task is solvable. |

Flow: `instruction.md` prompts the agent → agent reads `ticket.json` + `company_policy.md` → writes `resolution.json` → `test.sh` runs `test.py` → produces `reward.txt` → Harbor records the reward (1.0 = passed).

## Task: medium-billing-dispute

The medium task extends the generic layout with a **transaction-history input**
and an **LLM-as-a-Judge verifier**. The agent must investigate a duplicate
charge, compute the refund under policy Section 2, write a customer-facing
reply (free-text, graded by an LLM), and log the refund as structured JSON.

| File | Role |
|---|---|
| `tasks/medium-billing-dispute/instruction.md` | Prompts the agent: read `/workspace/ticket.json` + `/workspace/transactions.csv` + `company_policy.md`, spot the duplicate charge, then write `/workspace/reply.txt` (customer-facing) and `/workspace/refund_log.json` (exact 7-field schema documented inline). |
| `tasks/medium-billing-dispute/task.toml` | Harbor metadata; `[verifier.env]` maps `OPENROUTER_API_KEY` (and optional `OPENAI_API_KEY`) from the host so the LLM judge can call out; verifier network is `public`, agent stays on the `*.openrouter.ai` allowlist. |
| `tasks/medium-billing-dispute/environment/Dockerfile` | Agent container: `python:3.12-slim`, pinned `pytest==8.4.1`, `/workspace` as workdir. |
| `tasks/medium-billing-dispute/environment/ticket.json` | The noisy ticket: an angry enterprise customer reporting a second $45 charge on their plan. |
| `tasks/medium-billing-dispute/environment/transactions.csv` | Mock billing history: two identical `INV-5520` $45 charges on the same day (the duplicate signal) plus decoy renewal/add-on rows — defeats naive keyword matching. |
| `tasks/medium-billing-dispute/environment/company_policy.md` | Copy of `shared/company_policy.md` shipped into the container. |
| `tasks/medium-billing-dispute/tests/test.py` | **Hybrid verifier**: deterministic pytest checks (`refund_log.json` schema, exact `45.0` amount, exact duplicate `transaction_id`, status/method) + a single cached LLM call (stdlib `urllib`, no third-party deps) grading `reply.txt` on tone (≥4/5), no promises beyond policy, and explicit $45 refund confirmation. |
| `tasks/medium-billing-dispute/tests/test.sh` | Verifier entrypoint: runs pytest and writes `1`/`0` to `/logs/verifier/reward.txt`. |
| `tasks/medium-billing-dispute/solution/solve.sh` | Golden oracle: derives the duplicate charge from the CSV (not hardcoded), writes the ideal `reply.txt` and `refund_log.json` — proving the task is solvable. |

## Task: hard-multi-step-escalation

The hard task tests **multi-step escalation & failure recovery**: the agent must
work a P1 checkout-payments outage from an **incomplete ticket** (the affected
environment/region identifier is missing). Workflow — (1) detect the missing
info and log a clarification query, (2) apply the production `config.yaml` fix
once the on-call reply is available (or simulated), (3) file an executive
incident report graded by an LLM judge. Steps are enforced as a sequential
workflow inside one agent run (`workflow_steps = 3` in the task metadata).

| File | Role |
|---|---|
| `tasks/hard-multi-step-escalation/instruction.md` | Prompts the agent through all three steps: read `/workspace/outage_ticket.json`, spot that the environment/region is missing, write `/workspace/clarification_needed.txt`, then (with `/workspace/user_response.txt` present or simulated) repair `/workspace/config.yaml` and write `/workspace/incident_report.md`. |
| `tasks/hard-multi-step-escalation/task.toml` | Harbor metadata; `workflow_steps = 3` constraint, generous 600s agent timeout for the sequential steps, verifier network `public` with `OPENROUTER_API_KEY`/`OPENAI_API_KEY` for the LLM judge, agent on the `*.openrouter.ai` allowlist. |
| `tasks/hard-multi-step-escalation/environment/Dockerfile` | Agent container: `python:3.12-slim`, pinned `pytest==8.4.1` and `pyyaml==6.0.2`, `/workspace` as workdir seeding all inputs. |
| `tasks/hard-multi-step-escalation/environment/outage_ticket.json` | The **incomplete P1 incident report**: severity `P1`, 100% checkout failure, but `environment` left empty — the missing-system-identifier trap. |
| `tasks/hard-multi-step-escalation/environment/config.yaml` | The **corrupted config**: `staging` env/region, staging DB host, pool 16, and `auth_bypass_for_tests: true` — the misconfiguration the agent must repair. |
| `tasks/hard-multi-step-escalation/environment/user_response.txt` | Mock on-call escalation reply confirming the environment: production in `us-west-2`; may be pre-seeded (agent may also simulate it). |
| `tasks/hard-multi-step-escalation/environment/company_policy.md` | Copy of `shared/company_policy.md` shipped into the container (Section 3 governs escalation handling). |
| `tasks/hard-multi-step-escalation/tests/test.py` | **Hybrid verifier**: deterministic pytest checks (clarification log content, `config.yaml` valid YAML + correct production fix on all 5 fields) + an LLM-as-a-Judge call (stdlib `urllib`) grading `incident_report.md` on root-cause accuracy (≥4/5 for the staging/production misconfiguration), impact, fix, and clarification-noted. |
| `tasks/hard-multi-step-escalation/tests/test.sh` | Verifier entrypoint: runs pytest and writes `1`/`0` to `/logs/verifier/reward.txt`. |
| `tasks/hard-multi-step-escalation/solution/solve.sh` | Golden oracle: logs the clarification, rewrites `config.yaml` to production, and writes the ideal incident report — proving all three steps are solvable. |