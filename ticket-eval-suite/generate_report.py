#!/usr/bin/env python3
"""Markdown regression report generator for ticket-eval-suite runs.

Reads run logs written by run_suite.py (eval_results/run_<timestamp>.json),
compares two runs (baseline vs current, or the two most recent), and emits a
Markdown summary table highlighting regressions — score drops, pass->fail
flips, and verifier sub-score losses.

Examples:

    python generate_report.py                          # two latest runs
    python generate_report.py --baseline eval_results/run_A.json \
                              --current  eval_results/run_B.json
    python generate_report.py --current run_B.json     # single-run report
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from run_suite import DEFAULT_RESULTS_DIR

REGRESSION_MARKER = "[REGRESSION]"


def load_run(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or "tasks" not in data:
        raise SystemExit(f"not a run log: {path}")
    return data


def discover_runs(results_dir: Path, n: int = 2) -> list[Path]:
    if not results_dir.is_dir():
        raise SystemExit(f"results directory not found: {results_dir}")
    runs = sorted(results_dir.glob("run_*.json"))
    if not runs:
        raise SystemExit(f"no run_*.json logs found under {results_dir}")
    return runs[-n:]


def _fmt_reward(reward) -> str:
    if reward is None:
        return "-"
    return f"{float(reward):.2f}"


def _fmt_status(status: str) -> str:
    return status.upper() if status in {"pass", "fail", "error"} else str(status)


def _fmt_scores(section) -> str:
    if not section:
        return "-"
    passed, total = section.get("passed"), section.get("total")
    if passed is None or total is None:
        return "-"
    return f"{passed}/{total}"


def _fmt_duration(sec) -> str:
    if sec is None:
        return "-"
    if sec < 60:
        return f"{sec:.0f}s"
    return f"{sec/60:.1f}m"


def _task_label(task: dict) -> str:
    status = _fmt_status(task.get("status", "error"))
    return f"{status} ({_fmt_reward(task.get('reward'))})"


def _delta(a, b) -> str:
    if a is None or b is None:
        return "-"
    diff = round(float(b) - float(a), 2)
    if abs(diff) < 1e-9:
        return "0.00"
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.2f}"


def detect_regressions(base: dict, cur: dict) -> list[dict]:
    """Compare task-level metrics; return one record per regression/improvement."""
    notes: list[dict] = []
    all_tasks = sorted(set(base["tasks"]) | set(cur["tasks"]))

    for name in all_tasks:
        b = base["tasks"].get(name)
        c = cur["tasks"].get(name)
        if b is None:
            notes.append({"task": name, "kind": "new", "details": "task added in current run"})
            continue
        if c is None:
            notes.append({"task": name, "kind": "removed", "details": "task removed from current run"})
            continue

        b_status, c_status = b.get("status"), c.get("status")
        status_rank = {"pass": 2, "fail": 1, "error": 0}

        if c_status != b_status:
            if status_rank.get(c_status, 0) < status_rank.get(b_status, 0):
                notes.append({
                    "task": name,
                    "kind": "regression",
                    "details": (
                        f"status flipped {_fmt_status(b_status)} -> "
                        f"{_fmt_status(c_status)} (reward {_fmt_reward(b.get('reward'))} -> {_fmt_reward(c.get('reward'))})"
                    ),
                })
                continue
            notes.append({
                "task": name,
                "kind": "improvement",
                "details": (
                    f"status improved {_fmt_status(b_status)} -> "
                    f"{_fmt_status(c_status)} (reward {_fmt_reward(b.get('reward'))} -> {_fmt_reward(c.get('reward'))})"
                ),
            })
            continue

        b_r, c_r = b.get("reward"), c.get("reward")
        if b_r is not None and c_r is not None and float(c_r) < float(b_r):
            notes.append({
                "task": name,
                "kind": "regression",
                "details": f"reward dropped {_fmt_reward(b_r)} -> {_fmt_reward(c_r)}",
            })
            continue

        for section, label in (("deterministic", "deterministic"), ("llm_judge", "LLM judge")):
            bs, cs = (b.get(section) or {}), (c.get(section) or {})
            bp, cp = bs.get("passed"), cs.get("passed")
            if bp is None or cp is None:
                continue
            if int(cp) < int(bp):
                notes.append({
                    "task": name,
                    "kind": "regression",
                    "details": (
                        f"{label} passed dropped {bp}/{bs.get('total')} -> {cp}/{cs.get('total')}"
                    ),
                })
                break
    return notes


def summary_table(base: dict, cur: dict) -> str:
    def row(label, key, fmt):
        return f"| {label} | {fmt(base.get('summary', {}).get(key))} | {fmt(cur.get('summary', {}).get(key))} |"

    base_s, cur_s = base.get("summary", {}), cur.get("summary", {})

    def rate(s):
        pr = s.get("pass_rate")
        return "-" if pr is None else f"{float(pr) * 100:.1f}%"

    def n(v):
        return "-" if v is None else str(v)

    return "\n".join(
        [
            "| Metric | Baseline | Current |",
            "|---|---|---|",
            row("Tasks", "total", n),
            row("Passed", "passed", n),
            row("Failed", "failed", n),
            row("Errors", "errors", n),
            f"| Pass rate | {rate(base_s)} | {rate(cur_s)} |",
        ]
    )


def comparison_table(base: dict, cur: dict) -> str:
    header = (
        "| Task | Baseline | Current | Reward Δ | Deterministic | LLM judge | Verdict |"
    )
    sep = "|---|---|---|---|---|---|---|"
    rows = []
    all_tasks = sorted(set(base["tasks"]) | set(cur["tasks"]))
    for name in all_tasks:
        b, c = base["tasks"].get(name), cur["tasks"].get(name)
        b_label = _task_label(b) if b else "-"
        c_label = _task_label(c) if c else "-"
        reward_delta = _delta(b.get("reward") if b else None, c.get("reward") if c else None)
        det = _fmt_scores((c or {}).get("deterministic"))
        llm = _fmt_scores((c or {}).get("llm_judge"))
        if b and c:
            bd, cd = b.get("deterministic"), c.get("deterministic")
            bp, cp = (bd or {}).get("passed"), (cd or {}).get("passed")
            bsr = [r for r in detect_regressions(base, cur) if r["task"] == name]
            verdict = REGRESSION_MARKER if bsr and bsr[0]["kind"] == "regression" else "ok"
        else:
            bp = cp = None
            verdict = REGRESSION_MARKER if c and b is None else "removed"
        det_cell = det
        if bp is not None and cp is not None and int(cp) < int(bp):
            det_cell = f"**{det}**"
        rows.append(f"| {name} | {b_label} | {c_label} | {reward_delta} | {det_cell} | {llm} | {verdict} |")
    return "\n".join([header, sep, *rows])


def single_run_table(run: dict) -> str:
    header = "| Task | Status | Reward | Deterministic | LLM judge | Duration | Exception |"
    sep = "|---|---|---|---|---|---|---|"
    rows = []
    for name, task in sorted(run.get("tasks", {}).items()):
        rows.append(
            f"| {name} | {_fmt_status(task.get('status'))} | {_fmt_reward(task.get('reward'))} "
            f"| {_fmt_scores(task.get('deterministic'))} | {_fmt_scores(task.get('llm_judge'))} "
            f"| {_fmt_duration(task.get('duration_sec'))} "
            f"| {(task.get('exception') or {}).get('type', '-')} |"
        )
    return "\n".join([header, sep, *rows])


def _env_line(run: dict) -> str:
    cfg = run.get("config", {})
    agent = cfg.get("agent", {})
    return (
        f"**Agent:** `{agent.get('name')} / {agent.get('model')}` "
        f"**(label: {run.get('label', 'unlabeled')})**"
    )


def render_comparison(base: dict, cur: dict) -> str:
    notes = detect_regressions(base, cur)
    regressions = [n for n in notes if n["kind"] == "regression"]
    improvements = [n for n in notes if n["kind"] in {"new", "improvement"}]

    lines = [
        "# Regression Report",
        "",
        f"- Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- Baseline: `{base.get('run_id')}` " + _env_line(base),
        f"- Current : `{cur.get('run_id')}` " + _env_line(cur),
        "",
        "## Summary",
        "",
        summary_table(base, cur),
        "",
        "## Per-task comparison",
        "",
        comparison_table(base, cur),
        "",
    ]

    if regressions:
        lines += [
            "## Regressions",
            "",
            "| Task | Detail |",
            "|---|---|",
            *[f"| {n['task']} | {n['details']} |" for n in regressions],
            "",
        ]
    else:
        lines += ["## Regressions", "", "None detected.", ""]

    if improvements:
        lines += [
            "## Improvements / new tasks",
            "",
            "| Task | Detail |",
            "|---|---|",
            *[f"| {n['task']} | {n['details']} |" for n in improvements],
            "",
        ]

    lines += [
        "## Reproduce",
        "",
        "```bash",
        f"# baseline",
        f"python run_suite.py {base.get('command', '').split('python run_suite.py', 1)[-1].strip()}",
        f"# current",
        f"python run_suite.py {cur.get('command', '').split('python run_suite.py', 1)[-1].strip()}",
        "```",
    ]
    return "\n".join(lines)


def render_single(run: dict) -> str:
    summary = run.get("summary", {})
    rate = "-" if summary.get("pass_rate") is None else f"{float(summary['pass_rate']) * 100:.1f}%"
    counts_line = (
        f"{summary.get('passed')} passed, {summary.get('failed')} failed, "
        f"{summary.get('errors')} errors of {summary.get('total')} tasks "
        f"(pass rate {rate})"
    )
    return "\n".join(
        [
            f"# Run Report: {run.get('run_id')}",
            "",
            f"- Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
            f"- Label: {run.get('label', 'unlabeled')}",
            f"- " + _env_line(run),
            f"- Results: {counts_line}",
            f"- Command: `{run.get('command', '-')}`",
            "",
            "## Per-task results",
            "",
            single_run_table(run),
            "",
        ]
    )


def render(base: dict | None, cur: dict) -> str:
    return render_single(cur) if base is None else render_comparison(base, cur)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Markdown regression report from run logs.")
    parser.add_argument("--baseline", type=Path, default=None, help="Baseline run log (default: second-latest)")
    parser.add_argument("--current", type=Path, default=None, help="Current run log (default: latest)")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Directory of run logs")
    parser.add_argument("--out", type=Path, default=None, help="Write the report to this file")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.baseline and args.current:
        base_path, cur_path = args.baseline, args.current
        base = load_run(base_path)
        cur = load_run(cur_path)
    elif args.current:
        base, base_path = None, None
        cur_path = args.current
        cur = load_run(cur_path)
    else:
        runs = discover_runs(args.results_dir, n=2)
        if len(runs) == 1:
            base, base_path = None, None
            cur_path = runs[0]
            cur = load_run(cur_path)
        else:
            base_path, cur_path = runs[-2], runs[-1]
            base, cur = load_run(base_path), load_run(cur_path)

    markdown = render(base, cur)

    out = args.out
    if out is None:
        out = args.results_dir / f"report_{cur.get('run_id')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown)

    print(markdown)
    print(f"\n(save file: {out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())