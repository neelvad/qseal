# Search Baselines

Snowprove includes deterministic non-learning baselines for exploring the
structured rewrite action space:

- fixed-order applies the first available action until the episode ends
- random selects actions from a seeded pseudo-random generator
- greedy evaluates every immediate action and stops when none improves reward
- beam search retains the best cumulative paths at each depth
- exhaustive search explores unique SQL states breadth-first up to a node limit
- policy-baseline scores available actions with a trained baseline policy model
  and applies the highest-scoring action until the episode ends
- policy-baseline-abstain scores available actions, evaluates only the top
  action, and stops if that action does not beat the current state by the
  reward margin

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


result = beam_search(
    task,
    create_environment,
    beam_width=4,
    reward_margin=0.05,
)
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
increase cumulative reward. Policy-baseline is also a forced rollout, but its
action order comes from the supplied policy model instead of registry order or
random sampling. Policy-baseline-abstain is closer to greedy, but evaluates
only the top-scored policy action at each state instead of every immediate
action.

`reward_margin` sets the minimum cumulative reward improvement required to
prefer a longer or more complex path. Rewards remain unmodified in artifacts;
the margin only affects search decisions. Fixed-order and random record the
margin for provenance but remain forced-rollout baselines.

Every result also records a `tie_policy`. Transition-reward corpus runs use
`shorter`, preserving the existing preference for fewer rewrites when rewards
are within the margin. State-reward corpus runs use `endpoint`: a terminal or
truncated endpoint is preferred over an active partial path when their rewards
are within the margin. An endpoint that is worse by more than the margin still
loses.

Exhaustive search's `max_nodes` bounds evaluated child nodes, including solver
and benchmark calls. It is intended only for short episodes and small action
spaces.
