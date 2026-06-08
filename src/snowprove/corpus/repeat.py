from __future__ import annotations

from pathlib import Path

from snowprove.corpus.aggregate import (
    CorpusRunAggregate,
    aggregate_corpus_runs,
    write_corpus_aggregate,
)
from snowprove.corpus.model import LoadedTaskCorpus
from snowprove.corpus.runner import CorpusRunConfig, CorpusRunReport, run_task_corpus


def run_repeated_task_corpus(
    corpus: LoadedTaskCorpus,
    output_dir: Path,
    *,
    runs: int,
    config: CorpusRunConfig | None = None,
    neutral_threshold: float = 0.01,
) -> CorpusRunAggregate:
    if runs < 2:
        raise ValueError("Repeated corpus evaluation requires at least two runs.")
    if neutral_threshold < 0:
        raise ValueError("neutral_threshold must be zero or greater.")

    config = config or CorpusRunConfig()
    run_dirs = tuple(
        output_dir / f"run-{index:03d}"
        for index in range(1, runs + 1)
    )
    report_paths = tuple(run_dir / "corpus-run.json" for run_dir in run_dirs)
    aggregate_path = output_dir / "corpus-aggregate.json"
    existing = tuple(
        path for path in (*run_dirs, aggregate_path) if path.exists()
    )
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise ValueError(f"Repeat output already exists: {rendered}.")

    reports: list[CorpusRunReport] = []
    for index, report_path in enumerate(report_paths, start=1):
        report = run_task_corpus(
            corpus,
            report_path.parent,
            config=config,
            report_path=report_path,
        )
        reports.append(report)
        if any(summary.error_count for summary in report.strategy_summaries):
            raise ValueError(
                f"Corpus repeat run {index:03d} contains strategy errors. "
                f"Report retained at {report_path}."
            )

    aggregate = aggregate_corpus_runs(
        tuple(reports),
        source_reports=tuple(str(path) for path in report_paths),
        neutral_threshold=neutral_threshold,
    )
    write_corpus_aggregate(aggregate, aggregate_path)
    return aggregate
