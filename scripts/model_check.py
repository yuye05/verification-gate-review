"""有限状态安全性检查：穷举可达状态，以 BFS 产生最短反例。只检查声明的模型。"""

from collections import deque
from math import prod


def matches(state, pattern):
    return all(state[name] == value for name, value in pattern.items())


def validate_pattern(domains, pattern, context, required=False):
    if not isinstance(pattern, dict) or (required and not pattern):
        raise ValueError(f"{context}: 必须是{'非空' if required else ''}变量映射")
    for name, value in pattern.items():
        if name not in domains or not any(type(value) is type(v) and value == v for v in domains[name]):
            raise ValueError(f"{context}: 未声明的变量或域外值 {name}={value!r}")


def validate_state(domains, state, context):
    validate_pattern(domains, state, context, required=True)
    if set(state) != set(domains):
        raise ValueError(f"{context}: 必须赋值全部变量")


def validate_model(model):
    """模型和轨迹检查共用同一套有限域、守卫及不变量语义。"""
    if not isinstance(model, dict):
        raise ValueError("模型必须是 JSON 对象")
    domains = model.get("variables")
    if not isinstance(domains, dict) or not domains:
        raise ValueError("模型必须声明非空 variables")
    for name, values in domains.items():
        if not isinstance(name, str) or not isinstance(values, list) or not values:
            raise ValueError("变量名必须是字符串，有限域必须是非空列表")
        kind = type(values[0])
        if kind not in (str, int, bool) or any(type(v) is not kind for v in values):
            raise ValueError(f"{name}: 有限域必须为同类型的字符串、整数或布尔值")
        if len(set(values)) != len(values):
            raise ValueError(f"{name}: 有限域包含重复值")

    initial = model.get("initial")
    validate_state(domains, initial, "initial")
    actions = model.get("transitions")
    invariants = model.get("invariants")
    if not isinstance(actions, list) or not actions:
        raise ValueError("必须配置非空 transitions")
    if not isinstance(invariants, list) or not invariants:
        raise ValueError("必须配置非空 invariants，不能空跑后判 PASS")
    for entries, label in ((actions, "transitions"), (invariants, "invariants")):
        ids = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                raise ValueError(f"{label}: 每项必须有非空字符串 id")
            if entry["id"] in ids:
                raise ValueError(f"{label}: id 重复 {entry['id']}")
            ids.add(entry["id"])
    for action in actions:
        if set(action) - {"id", "description", "guard", "set"}:
            raise ValueError(f"{action['id']}: 未知转换字段，不得忽略守卫拼写错误")
        validate_pattern(domains, action.get("guard", {}), f"{action['id']}.guard")
        validate_pattern(domains, action.get("set"), f"{action['id']}.set", required=True)
    for invariant in invariants:
        if set(invariant) - {"id", "description", "requirement", "when", "assert"}:
            raise ValueError(f"{invariant['id']}: 未知不变量字段")
        if not isinstance(invariant.get("requirement", ""), str):
            raise ValueError(f"{invariant['id']}: requirement 必须是字符串")
        validate_pattern(domains, invariant.get("when", {}), f"{invariant['id']}.when")
        validate_pattern(domains, invariant.get("assert"), f"{invariant['id']}.assert", required=True)
    terminals = model.get("terminals", [])
    if not isinstance(terminals, list):
        raise ValueError("terminals 必须是变量映射列表")
    for terminal in terminals:
        validate_pattern(domains, terminal, "terminals", required=True)


def check_model(model, max_states=10000):
    """JSON 有限域 + 等值守卫/赋值 + 条件不变量；不使用 eval 或外部求解器。"""
    if type(max_states) is not int or max_states < 1:
        raise ValueError("max_states 必须是正整数")
    validate_model(model)
    domains = model["variables"]
    names = tuple(domains)
    initial = model["initial"]
    actions = model["transitions"]
    invariants = model["invariants"]
    terminals = model.get("terminals", [])

    start = tuple(initial[name] for name in names)
    queue = deque([start])
    # ponytail: 显式状态枚举，达到 max_states 返回 INCONCLUSIVE；大模型再接符号求解器。
    parents = {start: (None, None)}
    fired = set()
    explored = edges = 0
    activated = set()

    def trace(key):
        path = []
        while key is not None:
            parent, action = parents[key]
            path.append({"action": action, "state": dict(zip(names, key))})
            key = parent
        return list(reversed(path))

    def result(verdict, complete, **details):
        return {
            "verdict": verdict, "ok": verdict == "PASS", "complete": complete,
            "scope": "declared_finite_model", "max_states": max_states,
            "theoretical_states": prod(len(v) for v in domains.values()),
            "visited_states": len(parents), "explored_states": explored,
            "checked_transitions": edges,
            "properties": [{"id": inv["id"], "requirement": inv.get("requirement", ""),
                            "activated": inv["id"] in activated} for inv in invariants],
            "unreachable_actions": [a["id"] for a in actions if a["id"] not in fired] if complete else [],
            **details,
        }

    while queue:
        key = queue.popleft()
        state = dict(zip(names, key))
        explored += 1
        for inv in invariants:
            if matches(state, inv.get("when", {})):
                activated.add(inv["id"])
                if not matches(state, inv["assert"]):
                    return result("FAIL", False, reason="invariant_violation",
                                  violated_invariant=inv["id"], requirement=inv.get("requirement", ""),
                                  counterexample=trace(key))
        enabled = [a for a in actions if matches(state, a.get("guard", {}))]
        if not enabled and not any(matches(state, t) for t in terminals):
            return result("FAIL", False, reason="deadlock", counterexample=trace(key))
        for action in enabled:
            fired.add(action["id"])
            edges += 1
            successor = {**state, **action["set"]}
            next_key = tuple(successor[name] for name in names)
            if next_key not in parents:
                if len(parents) >= max_states:
                    return result("INCONCLUSIVE", False, reason="state_limit")
                parents[next_key] = (key, action["id"])
                queue.append(next_key)
    return result("PASS", True)
