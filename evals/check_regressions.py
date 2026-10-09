"""一个可运行的回归入口；不需要测试框架。所有临时数据只写项目内。"""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_consistency import extract_tokens
from model_check import check_model
from synthetic_check import _estimate_error, test_generic
from trace_check import check_trace

sys.path.insert(0, str(ROOT / "examples/microservice_order"))
from order_program import Order, run_order


def run_checks():
    checks = []

    def check(name, condition):
        checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
        assert condition, name

    def invalid_model(name, model):
        try:
            check_model(model)
        except ValueError:
            check(name, True)
        else:
            check(name, False)

    example = ROOT / "examples/microservice_order"
    model = json.loads((example / "order_model.json").read_text(encoding="utf-8"))
    good = check_model(model)
    check("model_exhaustive_pass", good["ok"] and good["complete"] and good["explored_states"] == 3)
    check("model_scope_and_requirement", good["theoretical_states"] == 4 and good["properties"][0]["requirement"] == "REQ-ORDER-001")
    bad_model = json.loads((example / "order_model_buggy.json").read_text(encoding="utf-8"))
    bad = check_model(bad_model)
    check("shortest_counterexample", bad["verdict"] == "FAIL" and [s["action"] for s in bad["counterexample"]] == [None, "ship"])
    check("counterexample_requirement", bad["requirement"] == "REQ-ORDER-001" and bad["counterexample"][-1]["state"] == {"paid": False, "shipped": True})
    limited = check_model(model, 2)
    check("state_limit_blocks_pass", limited["verdict"] == "INCONCLUSIVE" and not limited["ok"] and not limited["complete"])
    deadlock = copy.deepcopy(model)
    deadlock["terminals"] = []
    check("deadlock_detection", check_model(deadlock)["reason"] == "deadlock")
    initial_bad = copy.deepcopy(model)
    initial_bad["initial"] = {"paid": False, "shipped": True}
    check("initial_invariant_violation", len(check_model(initial_bad)["counterexample"]) == 1)
    cycle = copy.deepcopy(model)
    cycle["transitions"].append({"id": "repeat_pay", "guard": {"paid": True}, "set": {"paid": True}})
    check("cycles_terminate", check_model(cycle)["complete"])
    check("exact_state_limit_can_finish", check_model(model, 3)["complete"])
    invalid = copy.deepcopy(model)
    invalid["invariants"] = []
    invalid_model("empty_invariants_rejected", invalid)
    invalid = copy.deepcopy(model)
    invalid["transitions"][0]["set"] = {"paid": "true"}
    invalid_model("out_of_domain_assignment_rejected", invalid)
    invalid = copy.deepcopy(model)
    invalid["transitions"][0]["guard"] = {"unknown": True}
    invalid_model("unknown_guard_rejected", invalid)
    invalid = copy.deepcopy(model)
    invalid["variables"]["paid"] = [False, 0]
    invalid_model("bool_integer_alias_rejected", invalid)
    invalid = copy.deepcopy(model)
    invalid["transitions"][1]["gaurd"] = invalid["transitions"][1].pop("guard")
    invalid_model("guard_typo_rejected", invalid)
    invalid_model("non_object_model_rejected", [])

    normal_trace = run_order("normal")
    trace_snapshot = copy.deepcopy(normal_trace)
    good_trace = check_trace(model, normal_trace)
    check("trace_full_program_pass", good_trace["ok"] and good_trace["complete"]
          and good_trace["steps_checked"] == 2 and good_trace["scope"] == "observed_execution_trace")
    check("trace_input_not_mutated", normal_trace == trace_snapshot)
    try:
        Order().ship()
    except ValueError:
        check("correct_program_rejects_unpaid_shipping", True)
    else:
        check("correct_program_rejects_unpaid_shipping", False)
    buggy_trace = run_order("unpaid_shipping")
    bad_trace = check_trace(model, buggy_trace)
    check("trace_correct_model_detects_buggy_program", good["ok"] and bad_trace["verdict"] == "FAIL"
          and bad_trace["reason"] == "guard_not_satisfied" and bad_trace["step"] == 1)
    check("trace_real_invariant_links_requirement", bad_trace["requirement"] == "REQ-ORDER-001"
          and bad_trace["invariant_violations"][0]["phase"] == "after"
          and bad_trace["execution_prefix"] == buggy_trace["steps"])
    guard_only = copy.deepcopy(buggy_trace)
    guard_only["steps"][0]["after"] = guard_only["steps"][0]["before"].copy()
    guard_result = check_trace(model, guard_only)
    check("trace_guard_failure_does_not_invent_requirement", guard_result["reason"] == "guard_not_satisfied"
          and "requirement" not in guard_result and not guard_result["invariant_violations"])
    wrong_state = copy.deepcopy(normal_trace)
    wrong_state["steps"][0]["after"]["paid"] = False
    state_result = check_trace(model, wrong_state)
    check("trace_assignment_mismatch", state_result["reason"] == "state_mismatch"
          and state_result["expected_after"] == {"paid": True, "shipped": False}
          and "requirement" not in state_result)
    wrong_state = copy.deepcopy(normal_trace)
    wrong_state["steps"][0]["after"]["shipped"] = True
    check("trace_unchanged_variable_mismatch", check_trace(model, wrong_state)["reason"] == "state_mismatch")
    discontinuous = copy.deepcopy(normal_trace)
    discontinuous["steps"][1]["before"]["paid"] = False
    gap_result = check_trace(model, discontinuous)
    check("trace_continuity_checked", gap_result["reason"] == "trace_discontinuity"
          and gap_result["step"] == 2 and gap_result["expected_before"] == normal_trace["steps"][0]["after"])
    wrong_initial = copy.deepcopy(normal_trace)
    wrong_initial["steps"][0]["before"]["paid"] = True
    check("trace_initial_state_checked", check_trace(model, wrong_initial)["reason"] == "initial_state_mismatch")
    unknown = copy.deepcopy(normal_trace)
    unknown["steps"][0]["action"] = "refund"
    check("trace_unknown_action_fails", check_trace(model, unknown)["reason"] == "unknown_action")
    prefix = {"steps": normal_trace["steps"][:1]}
    incomplete = check_trace(model, prefix)
    check("trace_prefix_inconclusive", incomplete["verdict"] == "INCONCLUSIVE"
          and not incomplete["ok"] and not incomplete["complete"])
    check("trace_checks_invariants_after", check_trace(bad_model, buggy_trace)["reason"] == "invariant_violation")
    initial_bad_trace = {"steps": [{"action": "pay", "before": initial_bad["initial"].copy(),
                                   "after": {"paid": True, "shipped": True}}]}
    check("trace_checks_initial_invariants", check_trace(initial_bad, initial_bad_trace)["reason"] == "invariant_violation")

    def invalid_trace(name, value, trace_model=model):
        try:
            check_trace(trace_model, value)
        except ValueError:
            check(name, True)
        else:
            check(name, False)

    invalid_trace("trace_non_object_rejected", [])
    invalid_trace("trace_empty_steps_rejected", {"steps": []})
    malformed = copy.deepcopy(normal_trace)
    del malformed["steps"][0]["action"]
    invalid_trace("trace_missing_field_rejected", malformed)
    malformed = copy.deepcopy(normal_trace)
    malformed["steps"][0]["after"]["paid"] = 1
    invalid_trace("trace_bool_integer_alias_rejected", malformed)
    malformed = copy.deepcopy(normal_trace)
    malformed["steps"][0]["after"]["paid"] = "true"
    invalid_trace("trace_out_of_domain_rejected", malformed)
    malformed = copy.deepcopy(normal_trace)
    del malformed["steps"][0]["before"]["shipped"]
    invalid_trace("trace_partial_state_rejected", malformed)
    malformed = copy.deepcopy(normal_trace)
    malformed["steps"][0]["after"]["unknown"] = False
    invalid_trace("trace_unknown_state_variable_rejected", malformed)
    malformed = copy.deepcopy(normal_trace)
    malformed["steps"][0]["actions"] = "ship"
    invalid_trace("trace_unknown_record_field_rejected", malformed)
    malformed = copy.deepcopy(buggy_trace)
    malformed["steps"].append({})
    invalid_trace("trace_validates_entire_input_before_behavior", malformed)
    invalid_trace("trace_requires_terminals", normal_trace, deadlock)
    check("relative_error_percent", _estimate_error(101, 100, "rel")[0] == 1.0)
    check("negative_truth_error", _estimate_error(-101, -100, "rel_abs")[0] == 1.0)
    check("zero_truth_exact", _estimate_error(0, 0)[0] == 0.0)
    check("zero_truth_mismatch_fails", _estimate_error(1, 0)[0] is None)
    check("nonfinite_estimate_fails", _estimate_error(float("nan"), 1)[0] is None)
    check("empty_estimate_fails", _estimate_error([], [])[0] is None)
    check("shape_mismatch_has_shapes", "(2,)" in _estimate_error([1, 2], 1)[1])
    check("number_sign_exponent_parentheses", extract_tokens("(-3.9105) 1e-3 +.5") == [-3.9105, 0.001, 0.5])
    check("explicit_equation_tag_filtered", extract_tokens(r"\tag{3.15} value 4") == [4.0])

    # Windows restricted tokens cannot reopen tempfile's mode=0o700 directory.
    scratch = (ROOT / (".gate-check-" + uuid.uuid4().hex)).resolve()
    assert scratch.parent == ROOT
    scratch.mkdir()
    try:
        (scratch / "docs").mkdir()
        (scratch / "truth.json").write_text('{"result": 42}', encoding="utf-8")
        (scratch / "docs/result.md").write_text("result 42; obsolete -3.8517", encoding="utf-8")
        config = {"authoritative_json": ["truth.json"], "scan_dirs": ["docs"],
                  "forbidden_numbers": [{"value": -3.8517}], "output_dir": "reports"}
        config_path = scratch / "custom_config.json"

        def cli(script, cfg):
            config_path.write_text(json.dumps(cfg), encoding="utf-8")
            return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / script),
                                   "--config", str(config_path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=120)

        proc = cli("check_consistency.py", config)
        report_path = scratch / "reports/门禁报告_一致性.md"
        check("consistency_fail_exit", proc.returncode == 1 and "判定：FAIL" in report_path.read_text(encoding="utf-8"))
        (scratch / "docs/result.md").write_text("result 42", encoding="utf-8")
        proc = cli("check_consistency.py", config)
        check("consistency_pass_exit", proc.returncode == 0 and "判定：PASS" in report_path.read_text(encoding="utf-8"))
        (scratch / "docs/result.md").write_text("no result", encoding="utf-8")
        proc = cli("check_consistency.py", config)
        check("consistency_warn_preserved", proc.returncode == 0 and "WARN: 1" in report_path.read_text(encoding="utf-8"))
        (scratch / "docs/result.md").write_text("result 1e999", encoding="utf-8")
        check("overflow_token_rejected", cli("check_consistency.py", config).returncode == 2)
        empty_scan = {**config, "scan_dirs": []}
        check("empty_scan_rejected", cli("check_consistency.py", empty_scan).returncode == 2)
        missing_scan = {**config, "scan_dirs": ["missing"]}
        check("missing_scan_rejected", cli("check_consistency.py", missing_scan).returncode == 2)
        (scratch / "docs/result.md").write_text("result 42", encoding="utf-8")
        self_scan = {**config, "scan_dirs": ["."], "forbidden_numbers": [{"value": -3.8517}]}
        check("custom_config_not_scanned", cli("check_consistency.py", self_scan).returncode == 0)
        (scratch / "algorithm.py").write_text(
            "def identity(x): return x\n"
            "def add(x, y): return x + y\n"
            "def generate(truth, offset=0): return [truth - offset, offset]\n"
            "def invalid(x): return float('nan')\n"
            "def explode(x): raise RuntimeError('negative control')\n", encoding="utf-8")
        generic = {"module": "algorithm.py", "algo": "identity", "error_fn": "rel",
                   "pass_threshold_pct": 0.5, "cases": [{"truth": 100, "inputs": [101]}]}
        check("generic_one_percent_fails", not test_generic(generic, scratch)[0]["ok"])
        generic_cfg = {"generic_check": generic, "output_dir": "reports"}
        proc = cli("synthetic_check.py", generic_cfg)
        synthetic_report = scratch / "reports/门禁报告_合成自检.json"
        check("synthetic_fail_exit", proc.returncode == 1 and json.loads(synthetic_report.read_text(encoding="utf-8"))["verdict"] == "FAIL")
        inherited = {"generic_check": {k: v for k, v in generic.items() if k != "pass_threshold_pct"},
                     "pass_threshold_pct": 0.1, "output_dir": "reports"}
        inherited["generic_check"]["cases"] = [{"truth": 100, "inputs": [100.2]}]
        check("generic_inherits_global_threshold", cli("synthetic_check.py", inherited).returncode == 1)
        callback = {"module": "algorithm.py", "algo": "add", "encoder": "callback", "generator": "generate",
                    "cases": [{"truth": 7, "inputs": {"offset": 2}}]}
        check("callback_really_generates_input", test_generic(callback, scratch)[0]["estimate"] == 7)
        keyword = {"module": "algorithm.py", "algo": "add", "encoder": "kw_args",
                   "cases": [{"truth": 7, "inputs": {"x": 3, "y": 4}}]}
        check("keyword_encoder_preserved", test_generic(keyword, scratch)[0]["ok"])
        absolute = {**generic, "error_fn": "abs", "abs_tolerance": 2}
        abs_result = test_generic(absolute, scratch)[0]
        check("absolute_error_has_separate_unit", abs_result["ok"] and abs_result["err_pct"] is None and abs_result["error_unit"] == "absolute")
        exceptional = {**generic, "algo": "explode"}
        check("algorithm_exception_recorded", "RuntimeError" in test_generic(exceptional, scratch)[0]["note"])
        nonfinite = {"generic_check": {**generic, "algo": "invalid"}, "output_dir": "reports"}
        proc = cli("synthetic_check.py", nonfinite)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("nonfinite_output_is_serializable_fail", proc.returncode == 1 and saved["generic_check"][0]["estimate"] is None)
        for section in ("order_alignment", "fft"):
            check(section + "_empty_cases_rejected", cli("synthetic_check.py", {section: {"d_true_list": []}, "output_dir": "reports"}).returncode == 2)
        model_cfg = {"model_check": {"model": str(example / "order_model.json")}, "output_dir": "reports"}
        proc = cli("synthetic_check.py", model_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("model_cli_pass_and_hash", proc.returncode == 0 and saved["verdict"] == "PASS" and len(saved["model_check"]["model_sha256"]) == 64)
        check("unconfigured_checks_not_reported_as_pass", saved["summary"]["a_alignment_ok"] is None and saved["sections_checked"]["order_alignment"] is False)
        check("unconfigured_trace_not_reported_as_pass", saved["summary"]["t_trace_ok"] is None
              and saved["sections_checked"]["trace_check"] is False)
        model_cfg["model_check"]["max_states"] = 2
        check("model_inconclusive_blocks_cli", cli("synthetic_check.py", model_cfg).returncode == 1)
        model_cfg["model_check"] = {"model": str(example / "order_model_buggy.json")}
        proc = cli("synthetic_check.py", model_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("negative_control_cli_blocks", proc.returncode == 1 and saved["model_check"]["requirement"] == "REQ-ORDER-001")

        for scenario in ("normal", "unpaid_shipping"):
            trace_path = scratch / f"{scenario}.json"
            proc = subprocess.run([sys.executable, "-X", "utf8", str(example / "order_program.py"),
                                   "--scenario", scenario, "--out", str(trace_path)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
            actual = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else None
            check(f"program_cli_{scenario}_records_actual_state", proc.returncode == 0 and actual == run_order(scenario))
        trace_path = scratch / "normal.json"
        trace_cfg = {"model_check": {"model": str(example / "order_model.json")},
                     "trace_check": {"trace": "normal.json"}, "output_dir": "reports"}
        proc = cli("synthetic_check.py", trace_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("trace_cli_pass_and_hashes", proc.returncode == 0 and saved["verdict"] == "PASS"
              and saved["summary"]["t_trace_ok"] is True and saved["sections_checked"]["trace_check"] is True
              and saved["trace_check"]["trace_sha256"] == hashlib.sha256(trace_path.read_bytes()).hexdigest()
              and saved["trace_check"]["model_sha256"] == saved["model_check"]["model_sha256"])
        trace_cfg["trace_check"]["trace"] = "unpaid_shipping.json"
        proc = cli("synthetic_check.py", trace_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("trace_cli_bug_blocks_with_correct_model", proc.returncode == 1 and saved["model_check"]["ok"]
              and not saved["trace_check"]["ok"] and saved["trace_check"]["requirement"] == "REQ-ORDER-001")
        (scratch / "prefix.json").write_text(json.dumps(prefix), encoding="utf-8")
        trace_cfg["trace_check"]["trace"] = "prefix.json"
        proc = cli("synthetic_check.py", trace_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("trace_cli_incomplete_blocks", proc.returncode == 1 and saved["verdict"] == "FAIL"
              and saved["trace_check"]["verdict"] == "INCONCLUSIVE")
        trace_cfg["trace_check"]["trace"] = "normal.json"
        trace_cfg["model_check"]["model"] = str(example / "order_model_buggy.json")
        proc = cli("synthetic_check.py", trace_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("trace_pass_does_not_override_model_fail", proc.returncode == 1 and saved["trace_check"]["ok"]
              and not saved["model_check"]["ok"])
        trace_cfg["model_check"] = {"model": str(example / "order_model.json"), "max_states": 2}
        proc = cli("synthetic_check.py", trace_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("trace_pass_does_not_override_model_limit", proc.returncode == 1 and saved["trace_check"]["ok"]
              and saved["model_check"]["verdict"] == "INCONCLUSIVE")
        check("trace_cli_requires_model", cli("synthetic_check.py", {"trace_check": {"trace": "normal.json"}}).returncode == 2)
        for invalid_config in ({}, None):
            check("trace_cli_rejects_empty_config_" + str(invalid_config),
                  cli("synthetic_check.py", {"trace_check": invalid_config}).returncode == 2)
        trace_cfg["trace_check"]["trace"] = "missing.json"
        check("trace_cli_missing_file_error", cli("synthetic_check.py", trace_cfg).returncode == 2)
        (scratch / "malformed.json").write_text("not JSON", encoding="utf-8")
        trace_cfg["trace_check"]["trace"] = "malformed.json"
        check("trace_cli_invalid_json_error", cli("synthetic_check.py", trace_cfg).returncode == 2)
        for name, invalid_input in (("empty", {"steps": []}), ("fields", {"steps": [{}]}),
                                    ("types", {"steps": [{"action": "pay", "before": {"paid": 0, "shipped": False},
                                                          "after": {"paid": True, "shipped": False}}]})):
            (scratch / "malformed.json").write_text(json.dumps(invalid_input), encoding="utf-8")
            check("trace_cli_invalid_" + name + "_error", cli("synthetic_check.py", trace_cfg).returncode == 2)
        (scratch / "no_terminal_model.json").write_text(json.dumps(deadlock), encoding="utf-8")
        trace_cfg["model_check"] = {"model": "no_terminal_model.json"}
        trace_cfg["trace_check"]["trace"] = "normal.json"
        check("trace_cli_requires_terminals", cli("synthetic_check.py", trace_cfg).returncode == 2)
    finally:
        assert scratch.parent == ROOT and scratch.name.startswith(".gate-check-")
        shutil.rmtree(scratch)
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks = run_checks()
    report = {"timestamp": datetime.now().isoformat(), "verdict": "PASS", "checks": len(checks),
              "python": sys.version, "results": checks}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: {len(checks)} regression checks")
