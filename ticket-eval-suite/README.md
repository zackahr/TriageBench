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