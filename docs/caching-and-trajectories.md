# Caching and Trajectories

Search and policy training can reach the same SQL transition through different
episodes. Snowprove provides protocol wrappers that avoid rerunning identical
solver and benchmark work.

```python
from pathlib import Path

from snowprove.cache import JsonFileCache
from snowprove.environment import (
    CachedPerformanceEvaluator,
    CachedVerifier,
    JsonlTrajectoryRecorder,
    RewriteEnvironment,
)

cache = JsonFileCache(Path(".snowprove-cache"))
environment = RewriteEnvironment(
    verifier=CachedVerifier(
        verifier,
        cache,
        namespace="qed-commit-abc123",
    ),
    performance_evaluator=CachedPerformanceEvaluator(
        evaluator,
        cache,
        namespace="duckdb-policy-v1",
        context={"fixture_fingerprint": fixture_fingerprint},
    ),
    trajectory_recorder=JsonlTrajectoryRecorder(
        Path("snowprove-runs/trajectories.jsonl")
    ),
)
```

## Cache Keys

Keys are SHA-256 hashes over canonical JSON.

Verification keys include:

- original and rewritten SQL
- dialect
- trusted constraints
- backend name
- caller-supplied solver namespace/version
- optional additional context

Benchmark keys include:

- original and rewritten SQL
- caller-supplied namespace/version and context
- evaluator identity and settings when provided

The benchmark context must identify immutable fixture contents. For generated
fixtures, use the table fingerprints from the `duckdb_fixture` manifest. A
database path alone is not a content identity because the file may change.

Values are stored atomically under:

```text
<cache>/<kind>/<first-two-hash-characters>/<sha256>.json
```

Changing solver code, semantics, fixture contents, or benchmark methodology
requires a new namespace or context. The wrappers expose in-process `hits` and
`misses` counters.

## Trajectories

`JsonlTrajectoryRecorder` appends one versioned JSON object per attempted
transition. Each line includes:

- task, step, dialect, and task metadata
- current SQL and action ID
- proposed SQL and actual next-state SQL
- verification and optional benchmark artifacts
- reward, termination, truncation, and reason

For rejected transitions, proposed SQL records what the verifier considered,
while next-state SQL remains unchanged. `load_trajectory()` parses the JSONL
file into validated immutable records.
