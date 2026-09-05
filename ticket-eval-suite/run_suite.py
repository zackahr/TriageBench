#!/usr/bin/env python3
"""Regression test runner for the ticket-eval-suite using the Harbor Python SDK.

Builds a Harbor JobConfig (tasks in tasks/, an agent + model, verifier env for
the LLM-as-a-Judge), runs all trials, collects per-task pass/fail, durations,
and deterministic-vs-LLM verifier sub-scores, then writes a structured run log
to eval_results/run_<timestamp>.json.

Run from anywhere; paths are resolved relative to this file:

    export OPENROUTER_API_KEY=...
    uv run --with harbor python run_suite.py \
        --agent claude-code --model anthropic/claude-sonnet-4-6 \
        --label baseline-sonnet
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS_DIR = REPO_ROOT / "tasks"
DEFAULT_JOBS_DIR = REPO_ROOT / "jobs"
DEFAULT_RESULTS_DIR = REPO_ROOT / "eval_results"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

_TS_FORMAT = "%Y-%m-%d__%H-%M-%S"
_SUMMARY_COUNT_RE = re.compile(r"(?P<count>\d+)\s+(?P<kind>passed|failed|errors|skipped)")
_FAILED_TEST_RE = re.compile(r"^(?:FAILED|ERROR)\s+\S+::([\w.]+)", re.MULTILINE)
_TEST_DEF_RE = re.compile(r"^def (test_\w+)\s*\(", re.MULTILINE)
_DURATION_RE = re.compile(r"in\s+([\d.]+)s")


def load_dotenv(path: Path | None) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overwrite)."""
    if path is None or not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def discover_tasks(tasks_dir: Path) -> list[Path]:
    """Locate every valid task (subdir containing task.toml) under tasks_dir."""
    if not tasks_dir.is_dir():
        raise SystemExit(f"tasks directory not found: {tasks_dir}")
    found = sorted(
        p
        for p in tasks_dir.iterdir()
        if p.is_dir() and (p / "task.toml").is_file()
    )
    if not found:
        raise SystemExit(f"no tasks found under {tasks_dir} (need task.toml)")
    return found


def task_name(path: Path) -> str:
    """Short task identifier, e.g. 'hard-multi-step-escalation'."""
    return path.name


def build_job_config(
    task_paths: list[Path],
    *,
    run_id: str,
    jobs_dir: Path,
    agent_name: str,
    model_name: str,
    agent_kwargs: dict[str, Any],
    n_attempts: int,
    n_concurrent: int,
    extra_instruction_paths: list[str],
) -> Any:
    """Construct a Harbor JobConfig that mirrors `harbor run -p tasks/ ...`."""
    from harbor.models.job.config import JobConfig

    config_data: dict[str, Any] = {
        "job_name": run_id,
        "jobs_dir": str(jobs_dir),
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent,
        "quiet": True,
        "agents": [
            {
                "name": agent_name,
                "model_name": model_name,
                "kwargs": agent_kwargs,
            }
        ],
        "tasks": [{"path": str(p)} for p in task_paths],
        "extra_instruction_paths": extra_instruction_paths,
    }
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        config_data["verifier"] = {
            "env": {"OPENROUTER_API_KEY": api_key}
        }
    return JobConfig.model_validate(config_data)


def run_preflight() -> None:
    """Mirror the CLI's environment preflight so config errors fail fast."""
    from harbor.environments.factory import EnvironmentFactory

    EnvironmentFactory.run_preflight(type=None, import_path=None)


async def run_job(job_config: Any) -> tuple[Any, Any]:
    """Run all trials and return (job, job_result)."""
    from harbor.job import Job

    job = await Job.create(job_config)
    job_result = await job.run()
    return job, job_result


def _parse_pytest_output(stdout: str) -> dict[str, Any]:
    """Extract aggregate counts and failed test names from pytest -q output."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for match in _SUMMARY_COUNT_RE.finditer(stdout):
        counts[match.group("kind")] = int(match.group("count"))
    duration_match = _DURATION_RE.search(stdout)
    return {
        "counts": counts,
        "failed_tests": sorted(
            {m.group(1) for m in _FAILED_TEST_RE.finditer(stdout)}
        ),
        "duration_sec": float(duration_match.group(1)) if duration_match else None,
    }


def _test_plan(task_dir: Path) -> dict[str, int | None]:
    """Count test functions and LLM-judge tests statically from the task's tests."""
    test_files = sorted((task_dir / "tests").glob("test*.py")) or sorted(
        (task_dir / "tests").glob("test_*.py")
    )
    if not test_files:
        return {"total": None, "llm": None}
    source = "\n".join(f.read_text() for f in test_files)
    total = len(_TEST_DEF_RE.findall(source))
    llm = len(re.findall(r"^def (test_llm_\w+)\s*\(", source, re.MULTILINE))
    return {"total": total, "llm": llm}


def _subscores(
    pytest: dict[str, Any], plan: dict[str, int | None]
) -> dict[str, Any]:
    """Split pytest results into deterministic vs LLM-judge sub-tables."""
    counts = pytest["counts"]
    names = pytest["failed_tests"]
    nonpass_total = counts["failed"] + counts["errors"]
    total = plan.get("total")
    llm_total = plan.get("llm")
    det_total = (total - llm_total) if (total is not None and llm_total is not None) else None

    named_llm = sum(1 for n in names if n.startswith("test_llm_"))
    named_det = sum(1 for n in names if not n.startswith("test_llm_"))
    named_total = named_llm + named_det

    def _section(tt: int | None, passed: int | None, nonpass: int) -> dict[str, Any]:
        return {"total": tt, "passed": passed, "failed": nonpass, "errors": 0}

    if nonpass_total == 0 and not names:
        return {
            "deterministic": _section(det_total, det_total, 0),
            "llm_judge": _section(llm_total, llm_total, 0),
            "raw": pytest,
        }

    if names and named_total == nonpass_total and det_total is not None and llm_total is not None:
        return {
            "deterministic": _section(det_total, det_total - named_det, named_det),
            "llm_judge": _section(llm_total, llm_total - named_llm, named_llm),
            "raw": pytest,
        }

    return {
        "deterministic": _section(det_total, None if det_total is None else det_total - named_det, named_det),
        "llm_judge": _section(llm_total, None if llm_total is None else llm_total - named_llm, named_llm),
        "raw": pytest,
    }


def _iso(value: str | None) -> str:
    return value or None


def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return max((dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds(), 0.0)
    except ValueError:
        return None


def collect_trial(trial_dir: Path, task_dir: Path | None) -> dict[str, Any]:
    """Collect one Harbor trial's result.json + verifier artifacts into a record."""
    result_path = trial_dir / "result.json"
    if not result_path.is_file():
        return {"trial_name": trial_dir.name, "status": "error", "error": "missing result.json"}
    result = json.loads(result_path.read_text())

    reward: float | None = None
    reward_file = trial_dir / "verifier" / "reward.txt"
    if reward_file.is_file():
        try:
            reward = float(reward_file.read_text().strip())
        except ValueError:
            reward = None
    if reward is None and result.get("verifier_result", {}).get("rewards"):
        reward = float(result["verifier_result"]["rewards"].get("reward", 0.0))

    exception = result.get("exception_info")
    if exception:
        status = "error"
    else:
        status = "pass" if reward == 1.0 else "fail"

    pytest_data = {"counts": dict.fromkeys(("passed", "failed", "errors", "skipped"), 0), "failed_tests": [], "duration_sec": None}
    stdout_path = trial_dir / "verifier" / "test-stdout.txt"
    if stdout_path.is_file():
        pytest_data = _parse_pytest_output(stdout_path.read_text())

    plan = _test_plan(task_dir) if task_dir else {"total": None, "llm": None}

    return {
        "trial_name": trial_dir.name,
        "task_name": result.get("task_name") or trial_dir.name,
        "status": status,
        "reward": reward,
        "tests": _subscores(pytest_data, plan),
        "exception": (
            {
                "type": exception.get("exception_type"),
                "message": (exception.get("exception_message") or "")[:500],
            }
            if exception
            else None
        ),
        "duration_sec": _seconds(result.get("started_at"), result.get("finished_at")),
        "agent_execution_sec": _seconds(
            result.get("agent_execution", {}).get("started_at"),
            result.get("agent_execution", {}).get("finished_at"),
        ),
        "verifier_execution_sec": _seconds(
            result.get("verifier", {}).get("started_at"),
            result.get("verifier", {}).get("finished_at"),
        ),
        "agent": {
            "name": result.get("agent_info", {}).get("name"),
            "model": (result.get("agent_info", {}).get("model_info") or {}).get("name"),
            "version": result.get("agent_info", {}).get("version"),
        },
        "started_at": _iso(result.get("started_at")),
        "finished_at": _iso(result.get("finished_at")),
    }


def aggregate_task(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse per-attempt records into a task-level result (best reward wins)."""
    keyed = sorted(attempts, key=lambda a: (a.get("reward") is None, -(a.get("reward") or -1.0)))
    best = keyed[0] if keyed else {}
    tests = best.get("tests", {})
    return {
        "status": best.get("status", "error"),
        "reward": best.get("reward"),
        "duration_sec": best.get("duration_sec"),
        "deterministic": tests.get("deterministic"),
        "llm_judge": tests.get("llm_judge"),
        "exception": best.get("exception"),
        "n_attempts": len(attempts),
    }


def collect_results(job_dir: Path, task_paths: list[Path]) -> dict[str, Any]:
    """Walk Harbor's job dir and group trial results by task."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    task_by_path = {task_name(p): p for p in task_paths}
    for trial_dir in sorted(job_dir.iterdir()):
        result_json = trial_dir / "result.json"
        if not result_json.is_file():
            continue
        result = json.loads(result_json.read_text())
        name = result.get("task_name") or trial_dir.name
        grouped.setdefault(name, []).append(
            collect_trial(trial_dir, task_by_path.get(name))
        )

    tasks = {name: aggregate_task(attempts) for name, attempts in grouped.items()}
    counts = {
        "passed": sum(1 for t in tasks.values() if t["status"] == "pass"),
        "failed": sum(1 for t in tasks.values() if t["status"] == "fail"),
        "errors": sum(1 for t in tasks.values() if t["status"] == "error"),
        "total": len(tasks),
    }
    counts["pass_rate"] = (
        round(counts["passed"] / counts["total"], 4) if counts["total"] else None
    )
    return {"counts": counts, "tasks": tasks, "raw_trials": grouped}


def write_run(
    results: dict[str, Any],
    *,
    run_id: str,
    label: str,
    created_at: str,
    command: str,
    config: dict[str, Any],
    results_dir: Path,
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "label": label,
        "created_at": created_at,
        "command": command,
        "config": config,
        "summary": results["counts"],
        "tasks": results["tasks"],
        "trials": results["raw_trials"],
    }
    path = results_dir / f"run_{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def print_summary(payload: dict[str, Any], results_dir: Path) -> None:
    summary = payload["summary"]
    print("\n=== Suite run complete ===")
    print(f"run_id   : {payload['run_id']}")
    print(f"label    : {payload['label']}")
    print(f"agent    : {payload['config']['agent']['name']} / {payload['config']['agent']['model']}")
    print(
        f"results  : {summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['errors']} errors of {summary['total']} tasks "
        f"(pass rate {summary.get('pass_rate', 0) * 100:.1f}%)"
    )
    for name, task in payload["tasks"].items():
        det = task["deterministic"] or {}
        llm = task["llm_judge"] or {}
        print(
            f"  - {name:<32} {task['status'].upper():<6} reward={task['reward']}  "
            f"deterministic={det.get('passed')}/{det.get('total')}  "
            f"llm={llm.get('passed')}/{llm.get('total')}"
        )
    print(f"log saved to {results_dir / ('run_' + payload['run_id'] + '.json')}")


def parse_kwargs(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--agent-kwarg must be key=value, got: {item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the ticket-eval-suite tasks against an agent/model via the "
            "Harbor SDK and record a structured regression run."
        )
    )
    parser.add_argument("--agent", default="claude-code", help="Harbor agent name (default: claude-code)")
    parser.add_argument(
        "-m", "--model",
        default="anthropic/claude-sonnet-4-6",
        help="Model name for the agent (default: anthropic/claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--label", default=None,
        help="Human-readable tag for this run, e.g. 'baseline-sonnet' or 'canary-haiku'",
    )
    parser.add_argument(
        "--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR,
        help="Directory containing tasks (default: tasks/)",
    )
    parser.add_argument(
        "--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR,
        help="Harbor output dir (default: jobs/)",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR,
        help="Where run logs are written (default: eval_results/)",
    )
    parser.add_argument("-k", "--n-attempts", type=int, default=1, help="Attempts per task (default: 1)")
    parser.add_argument(
        "-n", "--n-concurrent", type=int, default=1,
        help="Concurrent trials (default: 1; keep low for deterministic LLM-judge parity)",
    )
    parser.add_argument(
        "--extra-instruction", type=Path, default=None,
        help="Instruction file appended to every task (prompt-modification experiments)",
    )
    parser.add_argument(
        "--ak", "--agent-kwarg", dest="agent_kwargs", action="append",
        help="Agent kwarg as key=value (repeatable)",
    )
    parser.add_argument(
        "--exclude-task", action="append", default=[],
        help="Skip a task (directory name); repeatable",
    )
    parser.add_argument(
        "--task", action="append", default=[],
        help="Run only this task (directory name); repeatable",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Path to a .env file (default: ./.env)")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved config and task list, then exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv(args.env_file)

    task_paths = discover_tasks(args.tasks_dir)
    task_paths = [p for p in task_paths if task_name(p) not in args.exclude_task]
    if args.task:
        wanted = set(args.task)
        task_paths = [p for p in task_paths if task_name(p) in wanted]
    if not task_paths:
        raise SystemExit("no tasks selected after filters")

    run_id = dt.datetime.now().strftime(_TS_FORMAT)
    label = args.label or f"{args.agent}__{args.model.split('/')[-1]}"
    agent_kwargs = parse_kwargs(args.agent_kwargs)
    extra_instructions = [str(args.extra_instruction)] if args.extra_instruction else []

    config = {
        "agent": {"name": args.agent, "model": args.model, "kwargs": agent_kwargs},
        "tasks": [{"dir": str(p), "name": task_name(p)} for p in task_paths],
        "n_attempts": args.n_attempts,
        "n_concurrent": args.n_concurrent,
        "extra_instruction_paths": extra_instructions,
        "jobs_dir": str(args.jobs_dir),
    }

    print(f"tasks selected ({len(task_paths)}): {', '.join(task_name(p) for p in task_paths)}")
    print(f"agent: {args.agent} / {args.model}  label={label}")

    if args.dry_run:
        from harbor.models.job.config import JobConfig

        job_config = build_job_config(
            task_paths,
            run_id=run_id,
            jobs_dir=args.jobs_dir,
            agent_name=args.agent,
            model_name=args.model,
            agent_kwargs=agent_kwargs,
            n_attempts=args.n_attempts,
            n_concurrent=args.n_concurrent,
            extra_instruction_paths=extra_instructions,
        )
        print("\nResolved JobConfig:")
        print(JobConfig.model_dump_json(job_config, indent=2, exclude_defaults=False))
        return 0

    run_preflight()
    job_config = build_job_config(
        task_paths,
        run_id=run_id,
        jobs_dir=args.jobs_dir,
        agent_name=args.agent,
        model_name=args.model,
        agent_kwargs=agent_kwargs,
        n_attempts=args.n_attempts,
        n_concurrent=args.n_concurrent,
        extra_instruction_paths=extra_instructions,
    )

    started_wall = time.monotonic()
    job, job_result = asyncio.run(run_job(job_config))
    wall_sec = round(time.monotonic() - started_wall, 2)

    results = collect_results(job.job_dir, task_paths)
    command = " ".join(sys.argv)
    payload_kwargs = dict(
        run_id=run_id,
        label=label,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        command=command,
        config={**config, "wall_clock_sec": wall_sec},
        results_dir=args.results_dir,
    )
    path = write_run(results, **payload_kwargs)
    print_summary(json.loads(path.read_text()), args.results_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        raise SystemExit(130)