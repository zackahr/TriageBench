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

`shared/` is not tested directly;it ships policy and schema context intox each
agent's container so a correct response must respect company policy and the ticket contract.