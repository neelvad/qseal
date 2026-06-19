from __future__ import annotations

from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.ir.model import Predicate, SelectQuery
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.research.policy.examples import _StateExample
from qseal.research.policy.model import STOP_ACTION_ID


def _features(example: _StateExample, action_id: str) -> tuple[str, ...]:
    return _feature_values(
        fixture_id=example.fixture_id,
        tags=example.tags,
        step_index=example.step_index,
        action_id=action_id,
        available_action_ids=example.available_action_ids,
        state_sql=example.state_sql,
    )


def _feature_values(
    *,
    fixture_id: str,
    tags: tuple[str, ...],
    step_index: int,
    action_id: str,
    available_action_ids: tuple[str, ...] = (),
    state_sql: str | None = None,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> tuple[str, ...]:
    rule_name = _rule_name(action_id)
    target_kind, target_index = _action_target(action_id)
    real_action_ids = tuple(
        item for item in available_action_ids if item != STOP_ACTION_ID
    )
    stop_available = STOP_ACTION_ID in available_action_ids
    available_rules = tuple(sorted({_rule_name(item) for item in real_action_ids}))
    policy_available_rules = tuple(
        sorted({_rule_name(item) for item in available_action_ids})
    )
    same_rule_actions = tuple(
        sorted(item for item in real_action_ids if _rule_name(item) == rule_name)
    )
    same_rule_position = (
        same_rule_actions.index(action_id) if action_id in same_rule_actions else None
    )
    available_rule_key = "+".join(available_rules) if available_rules else "none"
    policy_available_rule_key = (
        "+".join(policy_available_rules) if policy_available_rules else "none"
    )
    return (
        f"action:{action_id}",
        f"rule:{rule_name}",
        f"fixture_action:{fixture_id}:{action_id}",
        f"step_action:{step_index}:{action_id}",
        f"target_kind:{target_kind}",
        f"rule_target_kind:{rule_name}:{target_kind}",
        f"available_rules:{available_rule_key}",
        f"action_available_rules:{action_id}:{available_rule_key}",
        f"rule_available_rules:{rule_name}:{available_rule_key}",
        *(f"competes_with:{rule_name}:{other}" for other in available_rules if other != rule_name),
        *(
            (
                "stop_available:true",
                f"action_stop_available:{action_id}:true",
                f"rule_stop_available:{rule_name}:true",
                f"policy_available_rules:{policy_available_rule_key}",
                f"action_policy_available_rules:{action_id}:{policy_available_rule_key}",
                f"rule_policy_available_rules:{rule_name}:{policy_available_rule_key}",
            )
            if stop_available
            else ()
        ),
        *(
            f"policy_competes_with:{rule_name}:{other}"
            for other in policy_available_rules
            if stop_available and other != rule_name
        ),
        *(
            (f"target_index:{target_index}", f"rule_target_index:{rule_name}:{target_index}")
            if target_index is not None
            else ()
        ),
        *(
            (
                f"same_rule_count:{rule_name}:{len(same_rule_actions)}",
                f"same_rule_position:{rule_name}:{same_rule_position}",
            )
            if same_rule_position is not None and len(same_rule_actions) > 1
            else ()
        ),
        *(f"tag_action:{tag}:{action_id}" for tag in tags),
        *_sql_context_features(
            state_sql=state_sql,
            dialect=dialect,
            action_id=action_id,
            rule_name=rule_name,
            target_index=target_index,
        ),
    )


def _rule_name(action_id: str) -> str:
    if action_id == STOP_ACTION_ID:
        return STOP_ACTION_ID
    return action_id.split("::", 1)[0]


def _action_target(action_id: str) -> tuple[str, int | None]:
    if action_id == STOP_ACTION_ID:
        return "stop", None
    if "::" not in action_id:
        return "unknown", None
    match_id = action_id.split("::", 1)[1]
    if ":" not in match_id:
        return match_id, None
    target_kind, raw_index = match_id.split(":", 1)
    try:
        return target_kind, int(raw_index)
    except ValueError:
        return target_kind, None


def _sql_context_features(
    *,
    state_sql: str | None,
    dialect: SqlDialect,
    action_id: str,
    rule_name: str,
    target_index: int | None,
) -> tuple[str, ...]:
    if state_sql is None:
        return ()
    try:
        query = parse_select(state_sql, dialect=dialect)
    except UnsupportedSqlError:
        return ()

    projection_columns = _direct_projection_columns(query)
    not_null_columns = _not_null_predicate_columns(query)
    action_column = _action_column(
        query,
        rule_name=rule_name,
        target_index=target_index,
    )
    projection_key = "+".join(projection_columns) if projection_columns else "none"
    not_null_key = "+".join(not_null_columns) if not_null_columns else "none"
    features = [
        f"state_projection_columns:{projection_key}",
        f"state_not_null_columns:{not_null_key}",
        f"state_distinct:{str(query.distinct).lower()}",
        f"state_projection_count:{len(projection_columns)}",
        f"action_projection_columns:{action_id}:{projection_key}",
        f"action_not_null_columns:{action_id}:{not_null_key}",
        f"rule_projection_columns:{rule_name}:{projection_key}",
        f"rule_not_null_columns:{rule_name}:{not_null_key}",
    ]

    if query.distinct:
        has_not_null_on_projection = bool(set(projection_columns) & set(not_null_columns))
        features.extend(
            [
                (
                    "state_distinct_has_not_null_projection:"
                    f"{str(has_not_null_on_projection).lower()}"
                ),
                (
                    "rule_distinct_has_not_null_projection:"
                    f"{rule_name}:{str(has_not_null_on_projection).lower()}"
                ),
            ]
        )

    if action_column is not None:
        action_column_projected = action_column in projection_columns
        action_column_is_only_projection = projection_columns == (action_column,)
        features.extend(
            [
                f"action_column:{action_id}:{action_column}",
                f"rule_action_column:{rule_name}:{action_column}",
                f"target_column:{action_column}",
                f"action_column_projected:{action_id}:{str(action_column_projected).lower()}",
                f"rule_action_column_projected:{rule_name}:{str(action_column_projected).lower()}",
                (
                    "rule_action_column_is_only_projection:"
                    f"{rule_name}:{str(action_column_is_only_projection).lower()}"
                ),
            ]
        )

    return tuple(features)


def _direct_projection_columns(query: SelectQuery) -> tuple[str, ...]:
    return tuple(
        projection.name
        for projection in query.projections
        if projection.is_direct_column()
    )


def _not_null_predicate_columns(query: SelectQuery) -> tuple[str, ...]:
    return tuple(
        predicate.left.name
        for predicate in query.predicates
        if isinstance(predicate, Predicate) and predicate.operator == "IS NOT NULL"
    )


def _action_column(
    query: SelectQuery,
    *,
    rule_name: str,
    target_index: int | None,
) -> str | None:
    if rule_name == "remove_redundant_distinct":
        projection_columns = _direct_projection_columns(query)
        if len(projection_columns) == 1:
            return projection_columns[0]
        return None
    if rule_name != "remove_redundant_not_null_filter" or target_index is None:
        return None
    if target_index < 0 or target_index >= len(query.predicates):
        return None
    predicate = query.predicates[target_index]
    if not isinstance(predicate, Predicate) or predicate.operator != "IS NOT NULL":
        return None
    return predicate.left.name
