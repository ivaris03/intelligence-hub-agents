from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import langsmith as ls

from app.core.config import Settings
from app.evaluation.datasets import DATASETS, sync_datasets
from app.evaluation.evaluators import evaluators_for
from app.evaluation.targets import Variant, target_for
from app.observability.langsmith import langsmith_client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Intelligence Hub LangSmith evaluation runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync-datasets", help="Create or upsert all LangSmith datasets")
    run = subparsers.add_parser("run", help="Run one or all evaluation suites")
    run.add_argument(
        "--suite",
        choices=["all", *DATASETS],
        default="all",
        help="Evaluation suite to run",
    )
    run.add_argument(
        "--variant",
        choices=["baseline", "optimized"],
        default="optimized",
        help="Application/prompt variant",
    )
    run.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Maximum concurrent target/evaluator rows (default: 1)",
    )
    rescore = subparsers.add_parser(
        "rescore", help="Apply the current evaluators to an existing experiment"
    )
    rescore.add_argument("--suite", choices=list(DATASETS), required=True)
    rescore.add_argument("--experiment", required=True, help="Existing experiment name")
    return parser


def _evaluation_result_values(row: dict) -> list[Any]:
    container = row.get("evaluation_results") or {}
    return list(container.get("results") or [])


async def _run_suite(
    suite: str,
    variant: Variant,
    settings: Settings,
    max_concurrency: int = 1,
) -> dict[str, Any]:
    client = langsmith_client(settings)
    evaluators, summary_evaluators = evaluators_for(suite, settings)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    experiment_prefix = f"intelligence-hub-{suite}-{variant}-{timestamp}"
    results = await client.aevaluate(
        target_for(suite, settings, variant),
        data=DATASETS[suite].name,
        evaluators=evaluators,
        summary_evaluators=summary_evaluators,
        experiment_prefix=experiment_prefix,
        description=f"{suite} {variant} evaluation for Intelligence Hub",
        metadata={
            "suite": suite,
            "variant": variant,
            "generation_model": settings.qwen_agent_model,
            "judge_model": "qwen3.7-plus" if suite == "slides" else settings.qwen_agent_model,
            "metric_contract": "v1",
        },
        max_concurrency=max(1, max_concurrency),
        num_repetitions=1,
        blocking=True,
        error_handling="log",
    )
    return await _summarize_results(results, suite, variant)


async def _summarize_results(
    results: Any, suite: str, variant: str
) -> dict[str, Any]:
    rows = [row async for row in results]
    await results.wait()
    metric_values: dict[str, list[float]] = defaultdict(list)
    errors: list[str] = []
    for row in rows:
        run = row["run"]
        if run.error:
            errors.append(str(run.error))
        for item in _evaluation_result_values(row):
            score = item.score if hasattr(item, "score") else item.get("score")
            key = item.key if hasattr(item, "key") else item.get("key")
            if key and isinstance(score, (int, float)):
                metric_values[key].append(float(score))
    summary_values: dict[str, float] = {}
    summary_container = getattr(results, "_summary_results", []) or []
    summary_items = (
        summary_container.get("results", [])
        if isinstance(summary_container, dict)
        else summary_container
    )
    for item in summary_items:
        score = item.score if hasattr(item, "score") else item.get("score")
        key = item.key if hasattr(item, "key") else item.get("key")
        if key and isinstance(score, (int, float)):
            summary_values[key] = float(score)
    means = {
        key: round(sum(values) / len(values), 4)
        for key, values in sorted(metric_values.items())
        if values
    }
    means.update({key: round(value, 4) for key, value in summary_values.items()})
    return {
        "suite": suite,
        "variant": variant,
        "dataset": DATASETS[suite].name,
        "experiment": results.experiment_name,
        "experiment_url": results.url,
        "examples": len(rows),
        "metrics": means,
        "errors": errors,
    }


async def _rescore_suite(suite: str, experiment: str, settings: Settings) -> dict[str, Any]:
    client = langsmith_client(settings)
    evaluators, summary_evaluators = evaluators_for(suite, settings)
    project = await asyncio.to_thread(client.read_project, project_name=experiment)
    results = await client.aevaluate(
        project.id,
        evaluators=evaluators,
        summary_evaluators=summary_evaluators,
        max_concurrency=1,
        blocking=True,
        error_handling="log",
    )
    return await _summarize_results(results, suite, "rescore")


async def _main() -> None:
    args = _parser().parse_args()
    settings = Settings()
    if not settings.langsmith_ready:
        raise SystemExit("LANGSMITH_TRACING=true 且配置 LANGSMITH_API_KEY 后才能运行")
    client = langsmith_client(settings)
    ls.configure(client=client, enabled=True, project_name=settings.langsmith_project)
    if args.command == "sync-datasets":
        synced = await asyncio.to_thread(sync_datasets, client)
        print(json.dumps({"datasets": synced}, ensure_ascii=False, indent=2))
        return
    if args.command == "rescore":
        report = await _rescore_suite(args.suite, args.experiment, settings)
        print(json.dumps({"reports": [report]}, ensure_ascii=False, indent=2))
        return

    suites = list(DATASETS) if args.suite == "all" else [args.suite]
    reports = []
    for suite in suites:
        print(f"Running {suite} ({args.variant})...", flush=True)
        reports.append(
            await _run_suite(suite, args.variant, settings, args.max_concurrency)
        )
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
