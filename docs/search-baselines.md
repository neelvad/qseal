# Search Baselines

Snowprove includes deterministic non-learning baselines for exploring the
structured rewrite action space:

- fixed-order applies the first available action until the episode ends
- random selects actions from a seeded pseudo-random generator
- greedy evaluates every immediate action and stops when none improves reward
- beam search retains the best cumulative paths at each depth
- exhaustive search explores unique SQL states breadth-first up to a node limit

These are library APIs rather than CLI commands. Each search accepts an
`EnvironmentTask` and a factory that creates a fresh `RewriteEnvironment`:

```python
from snowprove.environment import EnvironmentTask, RewriteEnvironment
from snowprove.search import beam_search

task = EnvironmentTask(task_id="example", sql="SELECT DISTINCT user_id FROM users")


def create_environment() -> RewriteEnvironment:
    return RewriteEnvironment(
        verifier=shared_cached_verifier,
        performance_evaluator=shared_cached_evaluator,
    )


result = beam_search(task, create_environment, beam_width=4)
```

Fresh environments isolate mutable episode state. Shared cached verifier and
performance-evaluator wrappers avoid repeating equivalent oracle work across
branches.

Every `SearchResult` records the selected action IDs, SQL and reward at each
step, cumulative reward, environment termination state, and number of explored
nodes. Random results include their seed. Beam and exhaustive results include
their configured limits.

Beam and exhaustive search treat the unchanged root query as a valid result.
They can therefore conclude that no rewrite is better when all explored
transitions have negative reward. Fixed-order and random are forced-rollout
baselines. Greedy stops early when its best immediate candidate does not
increase cumulative reward.

Exhaustive search's `max_nodes` bounds evaluated child nodes, including solver
and benchmark calls. It is intended only for short episodes and small action
spaces.
