# Run the proven-candidate DuckDB benchmarks on Modal, sharded by model.
#
#   uv run modal run scripts/modal_benchmark.py \
#       --report-path snowprove-runs/llm-candidates/gitlab-full-verification-final.json \
#       --bundles-dir snowprove-runs/llm-candidates/gitlab-full \
#       --report-file snowprove-runs/llm-candidates/bench-report.json --shards 40
import json
import subprocess
from collections import Counter
from pathlib import Path

import modal

REPO_ROOT = Path(__file__).resolve().parents[1]

app = modal.App("snowprove-benchmark")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .run_commands(
        "curl -LsSf https://astral.sh/uv/install.sh | sh"
        " && cp $HOME/.local/bin/uv /usr/local/bin/uv",
    )
    .env(
        {
            "UV_PROJECT_ENVIRONMENT": "/tmp/snowprove-venv",
            "UV_CACHE_DIR": "/tmp/snowprove-uv-cache",
            "UV_LINK_MODE": "copy",
        }
    )
    .add_local_dir(
        str(REPO_ROOT),
        "/snowprove",
        ignore=[".git", ".venv", ".uv-cache", "snowprove-runs", "dist", "**/__pycache__"],
    )
)


@app.function(image=image, timeout=3600, cpu=2.0, memory=8192)
def benchmark_shard(shard: dict[str, dict[str, str]], options: dict) -> list[dict]:
    bundles_dir = Path("/tmp/bundles")
    for bundle_name, files in shard.items():
        bundle_path = bundles_dir / bundle_name
        bundle_path.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            (bundle_path / filename).write_text(content)
    (bundles_dir / "constraints.json").write_text(options["constraints"])
    Path("/tmp/report-input.json").write_text(options["report"])

    command = [
        "uv",
        "run",
        "python",
        "scripts/benchmark_proven_candidates.py",
        "/tmp/report-input.json",
        str(bundles_dir),
        "--report-file",
        "/tmp/bench.json",
        "--rows",
        options["rows"],
        "--only",
        ",".join(shard),
        "--timeout",
        str(options["timeout"]),
    ]
    completed = subprocess.run(
        command, cwd="/snowprove", capture_output=True, text=True, check=False
    )
    bench_path = Path("/tmp/bench.json")
    if not bench_path.exists():
        raise RuntimeError(
            f"benchmark failed (exit {completed.returncode}): {completed.stderr[-2000:]}"
        )
    return json.loads(bench_path.read_text())["results"]


@app.local_entrypoint()
def main(
    report_path: str,
    bundles_dir: str,
    report_file: str,
    shards: int = 40,
    rows: str = "100000,1000000",
    timeout: float = 30.0,
) -> None:
    report_text = Path(report_path).read_text()
    bundles_path = Path(bundles_dir)
    proven_models = sorted(
        {
            row["model"]
            for row in json.loads(report_text)["results"]
            if row["bucket"] == "proven"
        }
    )

    shard_payloads: list[dict[str, dict[str, str]]] = [{} for _ in range(shards)]
    for index, model in enumerate(proven_models):
        bundle = bundles_path / model
        shard_payloads[index % shards][model] = {
            file.name: file.read_text() for file in bundle.iterdir() if file.is_file()
        }
    shard_payloads = [shard for shard in shard_payloads if shard]

    options = {
        "constraints": (bundles_path / "constraints.json").read_text(),
        "report": report_text,
        "rows": rows,
        "timeout": timeout,
    }

    results: list[dict] = []
    for shard_rows in benchmark_shard.map(
        shard_payloads, kwargs={"options": options}, order_outputs=False
    ):
        results.extend(shard_rows)
        print(f"collected {len(results)} measurements...", flush=True)

    results.sort(key=lambda row: (row["model"], row["candidate"], row["rows"]))
    outcomes = Counter(row["outcome"] for row in results)
    output = Path(report_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "artifact_type": "proven_candidate_benchmarks",
                "schema_version": 1,
                "engine": "duckdb",
                "runner": "modal",
                "measurement_count": len(results),
                "outcomes": dict(sorted(outcomes.items())),
                "results": results,
            },
            indent=2,
        )
    )
    print(json.dumps({"measurements": len(results), **dict(sorted(outcomes.items()))}, indent=2))
