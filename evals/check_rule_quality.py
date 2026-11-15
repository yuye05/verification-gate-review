"""规则体检的单元与端到端测试；故障注入仅操作独立副本。"""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_rule_quality import check_rule_quality, run_check

EXAMPLE = ROOT / "examples" / "agent_rule_quality"
sys.path.insert(0, str(EXAMPLE))
import run_demo as agent_demo


class RuleQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / (".gate-check-" + uuid.uuid4().hex)
        cls.scratch.mkdir()
        cls.demo_root = cls.scratch / "真实演示 reports"
        proc = subprocess.run([sys.executable, "-X", "utf8", str(EXAMPLE / "run_demo.py"),
                               "--outdir", str(cls.demo_root)], cwd=cls.scratch,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stdout + proc.stderr)
        cls.demo_run = next(cls.demo_root.glob("run-*"))
        cls.suite = json.loads((cls.demo_run / "suite.json").read_bytes())
        cls.models = {name: json.loads((EXAMPLE / f"model_{name}.json").read_bytes())
                      for name in ("reasonable", "permissive", "restrictive")}

    @classmethod
    def tearDownClass(cls):
        assert cls.scratch.parent == ROOT and cls.scratch.name.startswith(".gate-check-")
        shutil.rmtree(cls.scratch)

    def setUp(self):
        self.model = copy.deepcopy(self.models["reasonable"])
        self.cases = copy.deepcopy(self.suite)

    def cli(self, model_path, suite_path, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/check_rule_quality.py"),
                               "--model", str(model_path), "--suite", str(suite_path), *map(str, args)],
                              cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_three_models_same_cases_and_no_input_mutation(self):
        before = copy.deepcopy((self.model, self.cases))
        expected = {"reasonable": ("PASS", 0, 0), "permissive": ("FAIL", 0, 2),
                    "restrictive": ("FAIL", 1, 0)}
        for name, (verdict, rejected, accepted) in expected.items():
            with self.subTest(name=name):
                result = check_rule_quality(self.models[name], self.cases)
                self.assertEqual(result["model_check"]["verdict"], "PASS")
                self.assertEqual(result["verdict"], verdict)
                self.assertEqual(result["summary"]["false_rejection"], rejected)
                self.assertEqual(result["summary"]["false_acceptance"], accepted)
                self.assertEqual(result["summary"]["other_mismatch"], 0)
                self.assertEqual(result["confusion_matrix"]["INCONCLUSIVE"]["INCONCLUSIVE"], 1)
        self.assertEqual((self.model, self.cases), before)

    def test_new_case_names_and_labels_drive_results(self):
        self.cases["cases"][0]["id"] = "user_custom_case"
        extra = copy.deepcopy(self.cases["cases"][1])
        extra["id"] = "another_legal_read"
        self.cases["cases"].append(extra)
        result = check_rule_quality(self.models["restrictive"], self.cases)
        self.assertEqual(result["summary"]["total"], 10)
        self.assertEqual(result["summary"]["false_rejection"], 2)
        self.assertEqual(result["cases"][-1]["id"], "another_legal_read")

    def test_requirement_and_failure_prefix_not_invented(self):
        result = check_rule_quality(self.models["restrictive"], self.cases)
        case = result["cases"][1]
        self.assertEqual(case["case_requirement"], "REQ-DELIVERY-002")
        self.assertNotIn("requirement", case["trace_check"])
        self.assertEqual(case["trace_check"]["reason"], "guard_not_satisfied")
        self.assertEqual(case["trace_check"]["step"], 4)
        self.assertEqual(case["trace_check"]["execution_prefix"], self.cases["cases"][1]["trace"]["steps"])
        missed = check_rule_quality(self.models["permissive"], self.cases)["cases"][6]
        self.assertNotIn("reason", missed["trace_check"])
        self.assertEqual(missed["classification"], "false_acceptance")

    def test_inconclusive_is_not_binary_failure_or_false_acceptance(self):
        self.cases["cases"][-1]["expected"] = "FAIL"
        result = check_rule_quality(self.model, self.cases)
        self.assertEqual(result["cases"][-1]["classification"], "other_mismatch")
        self.assertEqual(result["summary"]["false_acceptance"], 0)
        self.assertEqual(result["verdict"], "FAIL")

    def test_missing_positive_or_negative_coverage(self):
        for expected in ("PASS", "FAIL", "INCONCLUSIVE"):
            with self.subTest(expected=expected):
                suite = {"schema_version": 1, "cases": [c for c in self.cases["cases"] if c["expected"] == expected]}
                result = check_rule_quality(self.model, suite)
                self.assertEqual(result["verdict"], "INCONCLUSIVE")
                self.assertEqual(result["case_verdict"], "PASS")
                self.assertTrue(result["summary"]["missing_expected"])

    def test_model_failure_and_state_limit_do_not_override_cases(self):
        limited = check_rule_quality(self.model, self.cases, 1)
        self.assertEqual(limited["verdict"], "INCONCLUSIVE")
        self.assertEqual(limited["case_verdict"], "PASS")
        self.assertEqual(limited["model_check"]["unreachable_actions"], [])
        self.assertIn("未穷尽", limited["warnings"][0])
        self.model["invariants"].append({"id": "initial_bad", "assert": {"ever_passed": True}})
        failed = check_rule_quality(self.model, self.cases)
        self.assertEqual(failed["model_check"]["verdict"], "FAIL")
        self.assertEqual(failed["verdict"], "FAIL")
        self.assertEqual(len(failed["cases"]), 9)

    def test_inactive_and_unreachable_are_review_warnings(self):
        self.model["transitions"].append({"id": "never", "guard": {"validation": "passed", "ever_passed": False},
                                          "set": {"last_test": False}})
        self.model["invariants"].append({"id": "never_when", "when": {"validation": "passed", "ever_passed": False},
                                        "assert": {"last_test": False}})
        result = check_rule_quality(self.model, self.cases)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["warnings"]), 2)

    def test_invalid_suites_and_conflicting_labels(self):
        variants = []
        for value in (None, [], {}, {"schema_version": True, "cases": self.cases["cases"]},
                      {"schema_version": 2, "cases": self.cases["cases"]}, {"schema_version": 1, "cases": []}):
            variants.append(value)
        for field, value in (("id", ""), ("rationale", " "), ("requirement", None), ("expected", "ERROR"),
                             ("trace", {"steps": []}), ("extra", True)):
            suite = copy.deepcopy(self.cases)
            suite["cases"][0][field] = value
            variants.append(suite)
        duplicate = copy.deepcopy(self.cases)
        duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
        variants.append(duplicate)
        conflict = copy.deepcopy(self.cases)
        other = copy.deepcopy(conflict["cases"][0])
        other.update(id="conflicting", expected="FAIL")
        conflict["cases"].append(other)
        variants.append(conflict)
        for index, suite in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                check_rule_quality(self.model, suite)

    def test_corrupt_negative_trace_is_error_even_after_earlier_mismatch(self):
        for mutation in ("domain", "type", "initial", "discontinuity", "extra", "missing", "empty_action"):
            suite = copy.deepcopy(self.cases)
            steps = suite["cases"][-1]["trace"]["steps"]
            if mutation == "domain":
                steps[-1]["after"]["validation"] = "other"
            elif mutation == "type":
                steps[-1]["after"]["delivered"] = 0
            elif mutation == "initial":
                steps[0]["before"]["ever_passed"] = True
            elif mutation == "discontinuity":
                steps[-1]["before"]["last_test"] = True
            elif mutation == "extra":
                steps[-1]["extra"] = True
            elif mutation == "missing":
                del steps[-1]["after"]
            else:
                steps[-1]["action"] = ""
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check_rule_quality(self.models["restrictive"], suite)

    def test_independent_real_execution_and_artifact_fingerprints(self):
        self.assertEqual(len(self.suite["cases"]), 9)
        for case in self.suite["cases"]:
            evidence = json.loads((self.demo_run / case["id"] / "evidence.json").read_bytes())
            for step in evidence:
                snapshot = self.demo_run / case["id"] / f"step-{step['step']}"
                self.assertEqual(agent_demo.fingerprints(snapshot), step["after_hashes"])
                if step["action"].startswith("test_"):
                    self.assertEqual(step["summary"]["tests_run"], 1)
                    self.assertEqual(step["returncode"], 0 if step["action"] == "test_pass" else 1)
                if step["action"] == "read":
                    self.assertEqual(step["before_hashes"], step["after_hashes"])
        stale = self.suite["cases"][6]["trace"]["steps"]
        self.assertEqual(stale[1]["after"]["validation"], "passed")
        self.assertEqual(stale[2]["after"]["validation"], "untested")
        self.assertTrue(stale[2]["after"]["ever_passed"])

    def test_test_runner_rejects_zero_tests_crashes_and_inconsistent_exit(self):
        summaries = [(0, {"tests_run": 0, "failures": 0, "errors": 0, "skipped": 0}),
                     (0, {"tests_run": 1, "failures": 1, "errors": 0, "skipped": 0}),
                     (1, {"tests_run": 1, "failures": 0, "errors": 1, "skipped": 0})]
        for code, summary in summaries:
            with self.subTest(summary=summary), patch.object(agent_demo.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], code, json.dumps(summary), "")), self.assertRaises(ValueError):
                agent_demo.run_tests(self.scratch)
        with patch.object(agent_demo.subprocess, "run", return_value=
                subprocess.CompletedProcess([], 0, "", "")), self.assertRaises(ValueError):
            agent_demo.run_tests(self.scratch)
        with patch.object(agent_demo.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 30)), self.assertRaises(subprocess.TimeoutExpired):
            agent_demo.run_tests(self.scratch)

    def test_cli_reports_paths_hashes_repeat_and_old_report_isolation(self):
        work = self.scratch / "中文 CLI project"
        work.mkdir()
        model_path, suite_path = work / "model.json", work / "suite.json"
        model_path.write_text(json.dumps(self.model), encoding="utf-8")
        suite_path.write_text(json.dumps(self.cases), encoding="utf-8")
        output = "CLI 输出 reports"
        for _ in range(2):
            proc = self.cli(model_path.relative_to(self.scratch), suite_path.relative_to(self.scratch), "--outdir", output)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        runs = list((self.scratch / output).glob("run-*"))
        self.assertEqual(len(runs), 2)
        for run in runs:
            report = json.loads((run / "report.json").read_bytes())
            self.assertEqual(report["suite_sha256"], hashlib.sha256(suite_path.read_bytes()).hexdigest())
            self.assertEqual(report["model_sha256"], hashlib.sha256((run / "model.json").read_bytes()).hexdigest())
            self.assertEqual((run / "suite.json").read_bytes(), suite_path.read_bytes())
            self.assertIn("首次违规执行前缀", (run / "report.md").read_text(encoding="utf-8"))
        suite_path.write_text("broken", encoding="utf-8")
        proc = self.cli(model_path, suite_path, "--outdir", output)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("规则体检 PASS", proc.stdout)
        self.assertEqual(len(list((self.scratch / output).glob("run-*"))), 2)

    def test_cli_default_output_and_exit_codes(self):
        work = self.scratch / "default-output"
        work.mkdir()
        suite_path = work / "suite.json"
        suite_path.write_text(json.dumps(self.cases), encoding="utf-8")
        good_model = EXAMPLE / "model_reasonable.json"
        for args, code in (([], 0), (["--max-states", "1"], 1), (["--max-states", "0"], 2)):
            self.assertEqual(self.cli(good_model, suite_path, *args).returncode, code)
        self.assertEqual(self.cli(EXAMPLE / "model_permissive.json", suite_path).returncode, 1)
        self.assertEqual(self.cli(work / "missing.json", suite_path).returncode, 2)
        blocker = work / "file-not-directory"
        blocker.write_text("keep", encoding="utf-8")
        self.assertEqual(self.cli(good_model, suite_path, "--outdir", blocker).returncode, 2)
        self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")
        with patch("check_rule_quality.Path.mkdir", side_effect=PermissionError("unwritable")), self.assertRaises(PermissionError):
            run_check(good_model, suite_path)
        self.assertEqual(len(list((work / "reports/rule-quality").glob("run-*"))), 3)

    def test_demo_repeat_default_output_failure_and_exception(self):
        repo = self.scratch / "isolated 中文 repo"
        shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        example = repo / "examples/agent_rule_quality"
        shutil.copytree(EXAMPLE, example, ignore=shutil.ignore_patterns("reports", "__pycache__"))
        originals = {p.relative_to(example): p.read_bytes() for p in example.rglob("*") if p.is_file()}

        def demo(*args):
            return subprocess.run([sys.executable, "-X", "utf8", str(example / "run_demo.py"), *map(str, args)],
                                  cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=60)

        for _ in range(2):
            proc = demo()
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        runs = list((example / "reports/demo").glob("run-*"))
        self.assertEqual(len(runs), 2)
        self.assertTrue(all(p.read_bytes() == originals[p.relative_to(example)]
                            for p in example.rglob("*") if p.is_file() and p.relative_to(example) in originals))
        model_path = example / "model_permissive.json"
        model_path.write_bytes((example / "model_reasonable.json").read_bytes())
        proc = demo()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("不符合预期", proc.stdout)
        # 同一输出根已有成功报告，当前测试子进程未执行任何测试仍须返回 ERROR。
        (example / "fixture/test_subject.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        proc = demo()
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("演示成功", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
