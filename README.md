# TriageBench

TriageBench is a Harbor-based evaluation
suite that tests an AI agent's ability to **triage and resolve customer-support
tickets**. An agent is dropped into a container with a noisy end-user ticket, the
company's authoritative business rules, and a strict output contract — and must
produce a resolution that satisfies both the policy and the schema.

The goal is to benchmark agents on *judgment*, not on tool use: correct category /
priority / status classification, policy-exact decisions (identity verification,
refund limits, escalation paths), and — on the harder tasks — free-form
customer-facing writing that survives an LLM-as-a-Judge.

## Tasks

Three tasks of escalating difficulty live under
[`ticket-eval-suite/tasks/`](ticket-eval-suite/tasks/):

| Task | Difficulty | Probes |
|---|---|---|
| `easy-password-reset` | Easy | Rule-following triage: identity verification, correct classification, schema-conformant `resolution.json`. |
| `medium-billing-dispute` | Medium | Investigation + judgment: spot a duplicate charge in a messy CSV, compute a refund under policy, and write a customer reply graded by an LLM judge. |
| `hard-multi-step-escalation` | Hard | Multi-step recovery: work an incomplete P1 outage ticket, request clarification, apply a production config fix, and file an incident report graded by an LLM judge. |

## Regression testing

Beyond single-task runs, the suite ships a production-grade regression pipeline:

- **`run_suite.py`** — runs every task against any agent/model and records a
  structured run log (`eval_results/run_<ts>.json`).
- **`generate_report.py`** — diffs two runs and emits a Markdown report flagging
  score drops and pass-to-fail flips as `[REGRESSION]`.

```bash
# Baseline run
uv run --with harbor python run_suite.py \
  --agent claude-code --model anthropic/claude-sonnet-4-6 --label baseline-sonnet

# Candidate run
uv run --with harbor python run_suite.py \
  --agent claude-code --model anthropic/claude-haiku-4-5 --label canary-haiku

# Regression diff
uv run --with harbor python generate_report.py
```

This makes the suite usable as a **CI gate for agent and prompt changes**: swap a
model, tweak a prompt (`--extra-instruction file.md`), and the report tells you
exactly what broke.

## Layout

```
ticket-eval-suite/
├── shared/            # Authoritative policy + ticket schema (source of truth)
├── tasks/<name>/      # Independent Harbor tasks (instruction, env, tests, solution)
├── run_suite.py       # Regression runner (Harbor SDK)
└── generate_report.py # Markdown regression report generator
```

## Docs

- **[`ticket-eval-suite/README.md`](ticket-eval-suite/README.md)** — install,
  run commands, full option reference, task layout, and per-task file roles.