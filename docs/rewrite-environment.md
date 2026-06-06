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

The default verifier is Snowprove's builtin backend. A different verifier and
performance evaluator can be injected through protocols.

## Reward

For a completed benchmark:

```text
reward = log(current_median / next_median)
```

This is positive for speedups, negative for regressions, and additive across a
rewrite sequence. Proven transitions without performance data receive zero.
`NOT_EQUIVALENT` receives `-1`; other unproven results receive `-0.25` and
terminate the episode without advancing state.

An episode terminates when no actions remain or verification rejects a step. It
is truncated when `max_steps` is reached while actions remain. A completed
episode requires `reset()` before another `step()`.
