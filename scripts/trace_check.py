"""检查一条完整的顺序执行轨迹是否符合声明的有限模型。"""

from model_check import matches, validate_model, validate_state


def check_trace(model, trace):
    """输入错误抛出 ValueError；行为违规返回 FAIL；合法未终止返回 INCONCLUSIVE。"""
    validate_model(model)
    if not model.get("terminals"):
        raise ValueError("轨迹检查必须声明非空 terminals")
    if not isinstance(trace, dict) or set(trace) != {"steps"}:
        raise ValueError("轨迹必须是仅含 steps 的 JSON 对象")
    steps = trace["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps 必须是非空列表，不能空跑后判 PASS")
    domains = model["variables"]
    # 先校验整份输入，避免较早的行为违例掩盖后续损坏的记录。
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) != {"action", "before", "after"}:
            raise ValueError(f"step {index}: 必须且只能包含 action/before/after")
        if not isinstance(step["action"], str) or not step["action"]:
            raise ValueError(f"step {index}: action 必须是非空字符串")
        for phase in ("before", "after"):
            validate_state(domains, step[phase], f"step {index}.{phase}")

    actions = {action["id"]: action for action in model["transitions"]}

    def violations(state, phase):
        found = []
        for inv in model["invariants"]:
            if matches(state, inv.get("when", {})) and not matches(state, inv["assert"]):
                item = {"id": inv["id"], "phase": phase,
                        "when": inv.get("when", {}), "assert": inv["assert"]}
                if inv.get("requirement"):
                    item["requirement"] = inv["requirement"]
                found.append(item)
        return found

    def result(verdict, checked, **details):
        return {"verdict": verdict, "ok": verdict == "PASS", "complete": verdict == "PASS",
                "scope": "observed_execution_trace", "total_steps": len(steps),
                "steps_checked": checked, **details}

    def failure(index, step, reason, broken, **expected):
        details = {"reason": reason, "step": index, **step, **expected,
                   "invariant_violations": broken, "execution_prefix": steps[:index]}
        if broken:
            details["violated_invariant"] = broken[0]["id"]
            if "requirement" in broken[0]:
                details["requirement"] = broken[0]["requirement"]
        return result("FAIL", index, **details)

    previous = model["initial"]
    for index, step in enumerate(steps, 1):
        before, after = step["before"], step["after"]
        before_broken = violations(before, "before")
        broken = before_broken + violations(after, "after")
        if before != previous:
            reason = "initial_state_mismatch" if index == 1 else "trace_discontinuity"
            return failure(index, step, reason, broken, expected_before=previous)
        if before_broken:
            return failure(index, step, "invariant_violation", broken)
        action = actions.get(step["action"])
        if action is None:
            return failure(index, step, "unknown_action", broken,
                           expected_actions=list(actions))
        if not matches(before, action.get("guard", {})):
            return failure(index, step, "guard_not_satisfied", broken,
                           expected_guard=action.get("guard", {}))
        expected_after = {**before, **action["set"]}
        if after != expected_after:
            return failure(index, step, "state_mismatch", broken, expected_after=expected_after)
        if broken:
            return failure(index, step, "invariant_violation", broken)
        previous = after

    if not any(matches(previous, terminal) for terminal in model["terminals"]):
        return result("INCONCLUSIVE", len(steps), reason="trace_not_terminal", final_state=previous)
    return result("PASS", len(steps), final_state=previous)
