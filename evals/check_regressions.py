"""一个可运行的回归入口；不需要测试框架。所有临时数据只写项目内。"""

import argparse
import copy
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
        model_cfg["model_check"]["max_states"] = 2
        check("model_inconclusive_blocks_cli", cli("synthetic_check.py", model_cfg).returncode == 1)
        model_cfg["model_check"] = {"model": str(example / "order_model_buggy.json")}
        proc = cli("synthetic_check.py", model_cfg)
        saved = json.loads(synthetic_report.read_text(encoding="utf-8"))
        check("negative_control_cli_blocks", proc.returncode == 1 and saved["model_check"]["requirement"] == "REQ-ORDER-001")
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
