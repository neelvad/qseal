# Run LLM-candidate verification on Modal with the full prover cascade.
#
# The image bakes the QED toolchain (Rust prover + Calcite parser) and the
# SQLSolver jar at pinned commits, all native x86 - no emulation. Each shard
# container runs the same scripts/verify_llm_candidates.py used locally, so
# local and cloud runs share one code path.
#
#   uv run modal run scripts/modal_verify.py \
#       --bundles-dir snowprove-runs/llm-candidates/gitlab-full \
#       --report-file snowprove-runs/llm-candidates/modal-report.json --shards 20
import json
import subprocess
from collections import Counter
from pathlib import Path

import modal

QED_PROVER_COMMIT = "31f4b6c271440942ecaca1e1111d4beeabf1f14c"
QED_PARSER_COMMIT = "684daf23e5c2595726d3411ff3dc04b1c38a4409"
SQLSOLVER_COMMIT = "dcc2a91d8971a4c4d30b055f99d7d8428a1b754b"

REPO_ROOT = Path(__file__).resolve().parents[1]

app = modal.App("snowprove-verify")

image = (
    modal.Image.from_registry("ubuntu:22.04", add_python="3.12")
    .apt_install(
        "git",
        "curl",
        "unzip",
        "build-essential",
        "clang",
        "libclang-dev",
        "libz3-dev",
        "z3",
        "openjdk-17-jdk-headless",
        "openjdk-21-jdk-headless",
        "maven",
    )
    .run_commands(
        # cvc5 static binary (QED runtime dependency)
        "curl -sL -o /tmp/cvc5.zip https://github.com/cvc5/cvc5/releases/latest/download/"
        "cvc5-Linux-x86_64-static.zip"
        " && unzip -q /tmp/cvc5.zip -d /tmp/cvc5x"
        " && cp $(find /tmp/cvc5x -name cvc5 -type f | head -1) /usr/local/bin/cvc5"
        " && chmod +x /usr/local/bin/cvc5 && rm -rf /tmp/cvc5.zip /tmp/cvc5x",
        # QED prover (nightly Rust)
        "curl https://sh.rustup.rs -sSf | sh -s -- -y --default-toolchain nightly",
        f"git clone https://github.com/qed-solver/prover /opt/qed-prover"
        f" && cd /opt/qed-prover && git checkout {QED_PROVER_COMMIT}"
        " && . $HOME/.cargo/env && cargo build --release",
        # QED parser (Java 19 preview features are final in 21; patch the pom)
        f"git clone https://github.com/qed-solver/parser /opt/qed-parser"
        f" && cd /opt/qed-parser && git checkout {QED_PARSER_COMMIT}"
        " && sed -i 's|<source>19</source>|<source>21</source>|;"
        "s|<target>19</target>|<target>21</target>|;"
        "s|<compilerArgs>--enable-preview</compilerArgs>||;"
        "s|<argument>--enable-preview</argument>||' pom.xml"
        " && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 mvn -q package -DskipTests",
        # SQLSolver fat jar (builds with JDK 17)
        f"git clone https://github.com/SJTU-IPADS/SQLSolver /opt/sqlsolver"
        f" && cd /opt/sqlsolver && git checkout {SQLSOLVER_COMMIT}"
        " && JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ./gradlew fatjar",
        # uv for running the repo's verification script
        "curl -LsSf https://astral.sh/uv/install.sh | sh"
        " && cp $HOME/.local/bin/uv /usr/local/bin/uv",
    )
    .env(
        {
            "SNOWPROVE_QED_PARSER_JAR": (
                "/opt/qed-parser/target/qed-parser-1.0-SNAPSHOT-jar-with-dependencies.jar"
            ),
            "SNOWPROVE_QED_PROVER": "/opt/qed-prover/target/release/qed-prover",
            "SNOWPROVE_QED_JAVA": "/usr/lib/jvm/java-21-openjdk-amd64/bin/java",
            "SQLSOLVER_DIR": "/opt/sqlsolver",
            "JAVA_HOME": "/usr/lib/jvm/java-17-openjdk-amd64",
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


@app.function(image=image, timeout=3600, cpu=2.0, memory=4096)
def verify_shard(shard: dict[str, dict[str, str]], options: dict) -> list[dict]:
    """Verify one shard of bundles; returns the report rows."""
    bundles_dir = Path("/tmp/bundles")
    for bundle_name, files in shard.items():
        bundle_path = bundles_dir / bundle_name
        bundle_path.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            (bundle_path / filename).write_text(content)
    (bundles_dir / "constraints.json").write_text(options["constraints"])

    command = [
        "uv",
        "run",
        "python",
        "scripts/verify_llm_candidates.py",
        str(bundles_dir),
        "--dialect",
        options["dialect"],
        "--report-file",
        "/tmp/report.json",
        "--qed",
    ]
    if options.get("sqlsolver", True):
        command += [
            "--solver-command",
            "/snowprove/scripts/sqlsolver_command.sh",
            "--solver-timeout",
            str(options.get("solver_timeout", 60)),
        ]
    completed = subprocess.run(
        command, cwd="/snowprove", capture_output=True, text=True, check=False
    )
    report_path = Path("/tmp/report.json")
    if not report_path.exists():
        raise RuntimeError(
            f"verification failed (exit {completed.returncode}): {completed.stderr[-2000:]}"
        )
    return json.loads(report_path.read_text())["results"]


@app.local_entrypoint()
def main(
    bundles_dir: str,
    report_file: str,
    shards: int = 20,
    dialect: str = "snowflake",
    sqlsolver: bool = True,
    solver_timeout: int = 60,
) -> None:
    bundles_path = Path(bundles_dir)
    options = {
        "dialect": dialect,
        "sqlsolver": sqlsolver,
        "solver_timeout": solver_timeout,
        "constraints": (bundles_path / "constraints.json").read_text(),
    }

    bundle_dirs = sorted(
        path.parent for path in bundles_path.glob("*/metadata.json")
    )
    shard_payloads: list[dict[str, dict[str, str]]] = [{} for _ in range(shards)]
    for index, bundle in enumerate(bundle_dirs):
        shard_payloads[index % shards][bundle.name] = {
            file.name: file.read_text() for file in bundle.iterdir() if file.is_file()
        }
    shard_payloads = [shard for shard in shard_payloads if shard]

    rows: list[dict] = []
    for shard_rows in verify_shard.map(
        shard_payloads, kwargs={"options": options}, order_outputs=False
    ):
        rows.extend(shard_rows)
        print(f"collected {len(rows)} verdicts...", flush=True)

    rows.sort(key=lambda row: (row["model"], row["candidate"]))
    buckets = Counter(row["bucket"] for row in rows)
    report = {
        "artifact_type": "llm_candidate_verification",
        "schema_version": 1,
        "dialect": dialect,
        "solver_enabled": sqlsolver,
        "qed_enabled": True,
        "runner": "modal",
        "candidate_count": len(rows),
        "buckets": dict(sorted(buckets.items())),
        "results": rows,
    }
    output = Path(report_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"candidates": len(rows), **dict(sorted(buckets.items()))}, indent=2))
