"""实际执行编程工作流，以同批轨迹体检三套规则；不调用在线 Agent。"""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

EXAMPLE = Path(__file__).resolve().parent
sys.path.insert(0, str(EXAMPLE.parents[1] / "scripts"))
from check_rule_quality import run_check


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def fingerprints(work):
    return {name: hashlib.sha256((work / name).read_bytes()).hexdigest()
            for name in ("subject.py", "test_subject.py")}


def run_tests(work):
    proc = subprocess.run([sys.executable, "-B", "-X", "utf8", "test_subject.py"], cwd=work,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    # 退出 0 但没有执行测试也属于运行错误，不能伪装为通过或业务负例。
    summary = json.loads(proc.stdout)
    fields = {"tests_run", "failures", "errors", "skipped"}
    if (not isinstance(summary, dict) or set(summary) != fields
            or any(type(v) is not int or v < 0 for v in summary.values())
            or summary["tests_run"] != 1 or summary["errors"] or summary["skipped"]
            or summary["failures"] not in (0, 1)
            or proc.returncode != (1 if summary["failures"] else 0)):
        raise ValueError("测试未执行、运行异常或退出码与结构化测试结果不符")
    return summary["failures"] == 0, {"command": [sys.executable, "-B", "-X", "utf8", "test_subject.py"],
                                           "returncode": proc.returncode, "summary": summary,
                                           "stdout": proc.stdout, "stderr": proc.stderr}


def collect_case(spec, case_dir):
    """根据真实文件和测试结果采集；不读取任何待测模型。"""
    work = case_dir / "workspace"
    shutil.copytree(EXAMPLE / "fixture", work, ignore=shutil.ignore_patterns("__pycache__"))
    fixed_test = (work / "test_subject.py").read_bytes()
    baseline = (work / "subject.py").read_text(encoding="utf-8")
    tested = None
    last_passed = ever_passed = last_test = delivered = False

    def state():
        current = fingerprints(work)
        return {"validation": "untested" if tested != current else "passed" if last_passed else "failed",
                "ever_passed": ever_passed, "last_test": last_test, "delivered": delivered}

    steps, evidence = [], []
    for index, requested in enumerate(spec["actions"], 1):
        if delivered:
            raise ValueError("演示场景不能在交付后继续执行")
        before = state()
        before_hashes = fingerprints(work)
        action, details = requested, {}
        if requested in ("edit_good", "edit_bad"):
            value = 2 if requested == "edit_good" else 3
            (work / "subject.py").write_text(f"# edit {index}\ndef answer():\n    return {value}\n", encoding="utf-8")
            last_test = False
        elif requested == "test":
            if (work / "test_subject.py").read_bytes() != fixed_test:
                raise ValueError("固定测试文件被修改")
            tested = fingerprints(work)
            last_passed, details = run_tests(work)
            if tested != fingerprints(work):
                raise ValueError("测试期间受测文件发生变化")
            action = "test_pass" if last_passed else "test_fail"
            ever_passed = ever_passed or last_passed
            last_test = True
        elif requested == "read":
            diff = "".join(difflib.unified_diff(baseline.splitlines(True),
                          (work / "subject.py").read_text(encoding="utf-8").splitlines(True),
                          fromfile="baseline/subject.py", tofile="current/subject.py"))
            (case_dir / f"step-{index}-diff.txt").write_text(diff, encoding="utf-8")
            details = {"diff_file": f"step-{index}-diff.txt"}
            if fingerprints(work) != before_hashes:
                raise ValueError("只读操作修改了受测文件")
            last_test = False
        elif requested == "deliver":
            target = case_dir / "delivery"
            target.mkdir()
            for name in before_hashes:
                shutil.copyfile(work / name, target / name)
            if fingerprints(target) != before_hashes:
                raise ValueError("交付副本与受测文件不一致")
            delivered = True
            details = {"delivery_hashes": fingerprints(target)}
        else:
            raise ValueError(f"未知演示动作: {requested}")
        after_hashes = fingerprints(work)
        steps.append({"action": action, "before": before, "after": state()})
        # 保留每步的实际文件快照，便于离线复查历史摘要。
        snapshot = case_dir / f"step-{index}"
        snapshot.mkdir()
        for name in after_hashes:
            shutil.copyfile(work / name, snapshot / name)
        evidence.append({"step": index, "action": action, "before_hashes": before_hashes,
                         "after_hashes": after_hashes, **details})
    write_json(case_dir / "evidence.json", evidence)
    trace = {"steps": steps}
    write_json(case_dir / "trace.json", trace)
    return {**{key: spec[key] for key in ("id", "requirement", "rationale", "expected")}, "trace": trace}


def run_demo(outdir):
    specs_bytes = (EXAMPLE / "cases.json").read_bytes()
    specs = json.loads(specs_bytes)["cases"]
    ids = [s["id"] for s in specs]
    if not specs or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i.isascii()
            or not i.replace("_", "").isalnum() for i in ids):
        raise ValueError("演示案例 id 须为唯一的 ASCII 字母/数字/下划线")
    run_dir = Path(outdir).resolve() / ("run-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True)
    print(f"本次演示目录: {run_dir}")
    (run_dir / "cases.json").write_bytes(specs_bytes)
    cases = [collect_case(spec, run_dir / spec["id"]) for spec in specs]
    suite_path = run_dir / "suite.json"
    write_json(suite_path, {"schema_version": 1, "cases": cases})
    expected_findings = {"reasonable": {}, "permissive": {"stale_test": "false_acceptance", "latest_failure": "false_acceptance"},
                         "restrictive": {"read_after_test": "false_rejection"}}
    all_expected, outcomes = True, {}
    for name, findings in expected_findings.items():
        model_path = run_dir / f"model_{name}.json"
        model_path.write_bytes((EXAMPLE / model_path.name).read_bytes())
        report, report_dir = run_check(model_path, suite_path, run_dir / name)
        actual_findings = {c["id"]: c["classification"] for c in report["cases"] if c["classification"] != "matched"}
        expected = (len(cases) == 9 and report["model_check"]["verdict"] == "PASS"
                    and report["verdict"] == ("FAIL" if findings else "PASS") and actual_findings == findings)
        all_expected = all_expected and expected
        summary = report["summary"]
        outcomes[name] = {"report": str((report_dir / "report.json").relative_to(run_dir)),
                          "verdict": report["verdict"], "findings": actual_findings, "expected": expected}
        print(f"{name}: 模型 {report['model_check']['verdict']} / 体检 {report['verdict']} / "
              f"误拦 {summary['false_rejection']} / 漏检 {summary['false_acceptance']} / "
              f"{'符合预期' if expected else '不符合预期'}")
        print(f"  报告: {report_dir / 'report.md'}")
    write_json(run_dir / "demo_result.json", {"verdict": "PASS" if all_expected else "FAIL", "models": outcomes})
    print("演示成功：三套规则的差异符合预期。" if all_expected else "演示失败：诊断结果不符合预期。")
    print("这是脚本控制的真实本地执行；缺陷为故意注入，未测试自主 Agent 或整套交付门禁。")
    return 0 if all_expected else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=EXAMPLE / "reports" / "demo",
                        help="相对当前工作目录的输出根目录；每次新建独立子目录")
    args = parser.parse_args(argv)
    try:
        return run_demo(args.outdir)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(f"[ERROR 演示输入/运行错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
