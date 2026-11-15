"""将有限模型的判定与独立标注案例比较；只评价提供的案例。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

from model_check import check_model, validate_model, validate_state
from trace_check import check_trace

VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")


def validate_suite(model, suite):
    validate_model(model)
    if not model.get("terminals"):
        raise ValueError("规则体检要求非空 terminals")
    if not isinstance(suite, dict) or set(suite) != {"schema_version", "cases"}:
        raise ValueError("案例集必须且只能包含 schema_version/cases")
    if type(suite["schema_version"]) is not int or suite["schema_version"] != 1:
        raise ValueError("仅支持 schema_version=1")
    if not isinstance(suite["cases"], list) or not suite["cases"]:
        raise ValueError("cases 必须为非空列表")
    ids, labels = set(), {}
    for case in suite["cases"]:
        if not isinstance(case, dict) or set(case) != {"id", "requirement", "rationale", "expected", "trace"}:
            raise ValueError("案例必须且只能包含 id/requirement/rationale/expected/trace")
        for field in ("id", "requirement", "rationale"):
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError(f"案例 {field} 必须为非空字符串")
        if case["id"] in ids:
            raise ValueError(f"案例 id 重复: {case['id']}")
        ids.add(case["id"])
        if case["expected"] not in VERDICTS:
            raise ValueError(f"{case['id']}: expected 必须为 PASS/FAIL/INCONCLUSIVE")
        trace = case["trace"]
        if not isinstance(trace, dict) or set(trace) != {"steps"}:
            raise ValueError(f"{case['id']}: trace 必须且只能包含 steps")
        if not isinstance(trace["steps"], list) or not trace["steps"]:
            raise ValueError(f"{case['id']}: steps 必须为非空列表")
        previous = model["initial"]
        for index, step in enumerate(trace["steps"], 1):
            if not isinstance(step, dict) or set(step) != {"action", "before", "after"}:
                raise ValueError(f"{case['id']} step {index}: 必须且只能包含 action/before/after")
            if not isinstance(step["action"], str) or not step["action"]:
                raise ValueError(f"{case['id']} step {index}: action 必须为非空字符串")
            for phase in ("before", "after"):
                validate_state(model["variables"], step[phase], f"{case['id']} step {index}.{phase}")
            # 损坏的采集不能当作成功检出的业务负例；守卫/动作匹配仍由被测规则决定。
            if step["before"] != previous:
                raise ValueError(f"{case['id']} step {index}: 初始状态不符或轨迹不连续")
            previous = step["after"]
        key = json.dumps(trace, sort_keys=True, ensure_ascii=False)
        if key in labels and labels[key] != case["expected"]:
            raise ValueError(f"{case['id']}: 相同轨迹的预期标签冲突")
        labels[key] = case["expected"]


def check_rule_quality(model, suite, max_states=10000):
    """纯函数；输入错误抛 ValueError，不修改输入，不执行外部代码。"""
    validate_suite(model, suite)
    model_result = check_model(model, max_states)
    matrix = {expected: {actual: 0 for actual in VERDICTS} for expected in VERDICTS}
    counts = {"matched": 0, "false_rejection": 0, "false_acceptance": 0, "other_mismatch": 0}
    cases = []
    for case in suite["cases"]:
        result = check_trace(model, case["trace"])
        expected, actual = case["expected"], result["verdict"]
        classification = ("matched" if actual == expected else
                          "false_rejection" if (expected, actual) == ("PASS", "FAIL") else
                          "false_acceptance" if (expected, actual) == ("FAIL", "PASS") else
                          "other_mismatch")
        matrix[expected][actual] += 1
        counts[classification] += 1
        cases.append({"id": case["id"], "case_requirement": case["requirement"],
                      "rationale": case["rationale"], "expected": expected, "actual": actual,
                      "classification": classification, "trace_check": result})
    missing = [label for label in ("PASS", "FAIL") if not any(c["expected"] == label for c in cases)]
    mismatches = len(cases) - counts["matched"]
    verdict = ("FAIL" if model_result["verdict"] == "FAIL" or mismatches else
               "INCONCLUSIVE" if model_result["verdict"] != "PASS" or missing else "PASS")
    warnings = []
    if missing:
        warnings.append("缺少预期类别: " + ", ".join(missing))
    if model_result["complete"]:
        if model_result["unreachable_actions"]:
            warnings.append("需复核不可达动作: " + ", ".join(model_result["unreachable_actions"]))
        inactive = [p["id"] for p in model_result["properties"] if not p["activated"]]
        if inactive:
            warnings.append("需复核未触发属性: " + ", ".join(inactive))
    else:
        warnings.append("模型搜索未穷尽，不作不可达或永不触发结论")
    return {"schema_version": 1, "scope": "provided_labeled_cases", "verdict": verdict,
            "model_check": model_result, "case_verdict": "FAIL" if mismatches else "PASS",
            "summary": {"total": len(cases), **counts, "missing_expected": missing},
            "confusion_matrix": matrix, "warnings": warnings, "cases": cases}


def markdown_report(report):
    def cell(value):
        return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("|", "&#124;").replace("\n", "<br>").replace("\r", ""))

    labels = {"matched": "符合预期", "false_rejection": "误拦", "false_acceptance": "漏检",
              "other_mismatch": "其他判定不一致"}
    lines = ["# 规则体检报告", "", f"总体：**{report['verdict']}**", "",
             f"模型检查：{report['model_check']['verdict']}；案例一致性：{report['case_verdict']}", "",
             "通过仅表示提供的案例符合预期，不证明规则完整、标签正确或真实 Agent 可靠。", "",
             f"运行：{report['run_id']}", f"模型 SHA-256：{report['model_sha256']}",
             f"案例集 SHA-256：{report['suite_sha256']}", ""]
    summary = report["summary"]
    lines.extend([f"共 {summary['total']} 例；匹配 {summary['matched']}；误拦 {summary['false_rejection']}；"
                  f"漏检 {summary['false_acceptance']}；其他不一致 {summary['other_mismatch']}。", "",
                  "## 判定计数", "", "行是案例预期，列是检查器实际判定。", "",
                  "| 预期 \\ 实际 | PASS | FAIL | INCONCLUSIVE |", "|---|---|---|---|"])
    for expected in VERDICTS:
        lines.append("| " + " | ".join([expected, *[str(report["confusion_matrix"][expected][actual])
                                                  for actual in VERDICTS]]) + " |")
    lines.extend(["", "## 案例结果", "", "| 案例 | 需求 | 预期 | 实际 | 分类 |", "|---|---|---|---|---|"])
    for case in report["cases"]:
        lines.append("| " + " | ".join(cell(v) for v in (case["id"], case["case_requirement"],
                     case["expected"], case["actual"], labels[case["classification"]])) + " |")
    for case in report["cases"]:
        result = case["trace_check"]
        lines.extend(["", f"## {cell(case['id'])}", "", f"预期依据：{cell(case['rationale'])}", "",
                      f"判定：{case['expected']} → {case['actual']}（{labels[case['classification']]}）"])
        if "reason" in result:
            lines.append(f"检查器原因：{cell(result['reason'])}；步骤：{result.get('step', '结束位置')}；动作：{cell(result.get('action', '无'))}")
        if "requirement" in result:
            lines.append(f"检查器需求编号：{cell(result['requirement'])}（与案例需求分别记录）")
        if case["classification"] == "false_acceptance":
            lines.append("检查器未产生违规证据；漏检判断来自独立案例标签。")
        if "execution_prefix" in result:
            payload = json.dumps(result["execution_prefix"], ensure_ascii=False, indent=2)
            fence = "```"
            while fence in payload:
                fence += "`"
            lines.extend(["", "首次违规执行前缀（未经最小化）：", "", fence + "json", payload, fence])
    if report["warnings"]:
        lines.extend(["", "## 复核提示", "", *["- " + cell(w) for w in report["warnings"]]])
    return "\n".join(lines) + "\n"


def run_check(model_path, suite_path, outdir=None, max_states=10000):
    model_path, suite_path = Path(model_path).resolve(), Path(suite_path).resolve()
    model_bytes, suite_bytes = model_path.read_bytes(), suite_path.read_bytes()
    report = check_rule_quality(json.loads(model_bytes), json.loads(suite_bytes), max_states)
    root = Path(outdir).resolve() if outdir is not None else suite_path.parent / "reports" / "rule-quality"
    run_dir = root / ("run-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True)
    report.update({"run_id": run_dir.name, "timestamp": datetime.now(timezone.utc).isoformat(),
                   "model_path": str(model_path), "suite_path": str(suite_path),
                   "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
                   "suite_sha256": hashlib.sha256(suite_bytes).hexdigest()})
    (run_dir / "model.json").write_bytes(model_bytes)
    (run_dir / "suite.json").write_bytes(suite_bytes)
    (run_dir / "report.md").write_text(markdown_report(report), encoding="utf-8")
    # JSON 最后落盘；本次目录中的完整报告才是运行结果。
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report, run_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--max-states", type=int, default=10000)
    args = parser.parse_args(argv)
    try:
        report, run_dir = run_check(args.model, args.suite, args.outdir, args.max_states)
        summary = report["summary"]
        print(f"规则体检 {report['verdict']}；模型 {report['model_check']['verdict']}；"
              f"匹配 {summary['matched']}/{summary['total']}；误拦 {summary['false_rejection']}；"
              f"漏检 {summary['false_acceptance']}；其他不一致 {summary['other_mismatch']}")
        print(f"报告: {run_dir / 'report.json'}")
        print(f"阅读版: {run_dir / 'report.md'}")
        return 0 if report["verdict"] == "PASS" else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"[ERROR 输入/运行错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
