# Rewrite Environment

`RewriteEnvironment` is a framework-neutral state machine for search and
reinforcement-learning experiments. It has no dependency on Gymnasium, Ray,
PyTorch, or another training framework.

```python
from snowprove.environment import EnvironmentTask, RewriteEnvironment

environment = RewriteEnvironment()
observation = environment.reset(
    EnvironmentTask(
        task_id="example",
        sql="SELECT DISTINCT user_id FROM users",
        constraints=constraints,
    )
)
transition = environment.step(observation.actions[0].action_id)
```

`reset()` returns:

- initial and current SQL
- dialect and step index
- task metadata
- deterministic structured actions with globally unique
  `rule_name::match_id` identifiers

`step()`:

1. Applies exactly one structured rewrite action.
2. Verifies equivalence between the current and next query.
3. Refuses to advance when equivalence is not proven.
4. Optionally benchmarks the current and next query.
5. Re-parses the next query and enumerates its next actions.
6. Reports reward, termination, truncation, verification, and benchmark data.

Optional cached verifier/evaluator wrappers and a JSONL recorder can be
injected without changing the environment. See
[`caching-and-trajectories.md`](caching-and-trajectories.md).

The default verifier is Snowprove's builtin backend. A different verifier and
performance evaluator can be injected through protocols.

## Reward

For a completed benchmark:

```text
reward = log(current_median / next_median)
```

This is positive for speedups, negative for regressions, and additive across a
rewrite sequence. Fast queries are measured in calibrated execution batches to
amortize timer noise. Low-confidence benchmark results receive zero reward if
the batching safety cap cannot reach the configured sample duration. Raw
timings and speedup remain in the benchmark artifact. Proven transitions
without performance data also receive zero.

`RewriteEnvironment(reward_model="transition")` uses a direct benchmark for
each rewrite edge. `reward_model="state"` measures each distinct SQL state once
through the content-addressed cache and derives edge rewards from the two state
runtimes. State rewards eliminate order-dependent cumulative rewards for paths
that reach the same final SQL.

DuckDB state measurements are interleaved in related pairs. When one state is
already cached, Snowprove uses it as an anchor: the new state's paired timing is
normalized onto the cached state's timing scale before the new state is stored.
This reduces session-to-session drift while preserving one stable cache entry
per SQL state. State mode fails explicitly if the configured evaluator cannot
benchmark individual queries.

`NOT_EQUIVALENT` receives `-1`; other unproven results receive `-0.25` and
terminate the episode without advancing state.

An episode terminates when no actions remain or verification rejects a step. It
is truncated when `max_steps` is reached while actions remain. A completed
episode requires `reset()` before another `step()`.
