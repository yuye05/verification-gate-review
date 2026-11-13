"""演示入口的端到端检查；只在项目内的独立副本中注入缺陷。"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = Path("examples/microservice_order")
REPORT = "门禁报告_合成自检.json"


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.scratch = ROOT / (".gate-check-" + uuid.uuid4().hex)
        self.repo = self.scratch / "中文 project"
        (self.repo / EXAMPLE).mkdir(parents=True)
        shutil.copytree(ROOT / "scripts", self.repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("run_demo.py", "order_program.py", "order_model.json"):
            shutil.copyfile(ROOT / EXAMPLE / name, self.repo / EXAMPLE / name)
        self.out = self.scratch / "输出 reports"

    def tearDown(self):
        self.assertEqual(self.scratch.parent, ROOT)
        self.assertTrue(self.scratch.name.startswith(".gate-check-"))
        shutil.rmtree(self.scratch)

    def run_demo(self, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(self.repo / EXAMPLE / "run_demo.py"), *args],
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )

    def test_positive_negative_repeat_and_paths(self):
        model_path = self.repo / EXAMPLE / "order_model.json"
        original = model_path.read_bytes()
        for _ in range(2):
            result = self.run_demo("--outdir", self.out.name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("REQ-ORDER-001", result.stdout)
        runs = list(self.out.glob("run-*"))
        self.assertEqual(len(runs), 2)
        for run in runs:
            for scenario, verdict in (("normal", "PASS"), ("unpaid_shipping", "FAIL")):
                case = run / scenario
                report = json.loads((case / REPORT).read_text(encoding="utf-8"))
                self.assertEqual(report["model_check"]["verdict"], "PASS")
                self.assertEqual(report["trace_check"]["verdict"], verdict)
                self.assertEqual(report["config_path"], str((case / "gate_config.json").resolve()))
                self.assertEqual(report["trace_check"]["trace_sha256"],
                                 hashlib.sha256((case / "trace.json").read_bytes()).hexdigest())
            self.assertEqual(report["trace_check"]["step"], 1)
            self.assertEqual(report["trace_check"]["action"], "ship")
            self.assertEqual(report["trace_check"]["requirement"], "REQ-ORDER-001")
        self.assertEqual(model_path.read_bytes(), original)
        # 已存在的成功报告不能掩盖本次子进程异常（退出码同为 1）。
        (self.repo / "scripts/synthetic_check.py").write_text(
            "raise ModuleNotFoundError('injected missing dependency')\n", encoding="utf-8")
        result = self.run_demo("--outdir", self.out.name)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("injected missing dependency", result.stderr)
        self.assertNotIn("演示成功", result.stdout)
        self.assertEqual(len(list(self.out.glob("run-*"))), 3)

    def test_default_output_independent_of_cwd(self):
        result = self.run_demo()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list((self.repo / EXAMPLE / "reports/demo").glob("run-*"))), 1)

    def test_wrong_negative_result_is_failure(self):
        program = self.repo / EXAMPLE / "order_program.py"
        source = program.read_text(encoding="utf-8")
        old = 'order, actions = BuggyOrder(), ("ship",)'
        self.assertIn(old, source)
        program.write_text(source.replace(old, 'order, actions = Order(), ("pay", "ship")'), encoding="utf-8")
        result = self.run_demo("--outdir", str(self.out))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("不符合预期", result.stdout)
        self.assertNotIn("演示成功", result.stdout)

    def test_invalid_model_is_input_error(self):
        (self.repo / EXAMPLE / "order_model.json").write_text("not JSON", encoding="utf-8")
        result = self.run_demo("--outdir", str(self.out))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("检查器运行失败 (2)", result.stderr)

    def test_output_file_is_error_and_preserved(self):
        self.out.write_text("keep me", encoding="utf-8")
        result = self.run_demo("--outdir", str(self.out))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "keep me")

    def test_report_hash_mismatch_is_error(self):
        checker = self.repo / "scripts/synthetic_check.py"
        source = checker.read_text(encoding="utf-8")
        old = 'hashlib.sha256(cfg_path.read_bytes()).hexdigest()'
        self.assertIn(old, source)
        checker.write_text(source.replace(old, '"wrong hash"'), encoding="utf-8")
        result = self.run_demo("--outdir", str(self.out))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("报告与本次配置、模型或轨迹不匹配", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
