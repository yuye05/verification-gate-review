"""运行订单正反例；演示成功不代表缺陷程序通过验证。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

EXAMPLE = Path(__file__).resolve().parent
CHECKER = EXAMPLE.parents[1] / "scripts" / "synthetic_check.py"
REPORT = "门禁报告_合成自检.json"


def run_script(script, *args):
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    return proc


def run_demo(outdir):
    run_dir = outdir.resolve() / ("run-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True)
    print(f"本次演示目录: {run_dir}")
    model_path = run_dir / "order_model.json"
    model_path.write_bytes((EXAMPLE / "order_model.json").read_bytes())
    all_expected = True
    for scenario, expected_exit in (("normal", 0), ("unpaid_shipping", 1)):
        case_dir = run_dir / scenario
        case_dir.mkdir()
        trace_path = case_dir / "trace.json"
        proc = run_script(EXAMPLE / "order_program.py", "--scenario", scenario, "--out", trace_path)
        if proc.returncode != 0:
            raise RuntimeError(f"轨迹生成失败 ({proc.returncode}): {proc.stderr or proc.stdout}")
        config_path = case_dir / "gate_config.json"
        config = {"model_check": {"model": "../order_model.json", "max_states": 100},
                  "trace_check": {"trace": "trace.json"}, "output_dir": "."}
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        proc = run_script(CHECKER, "--config", config_path)
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"检查器运行失败 ({proc.returncode}): {proc.stderr or proc.stdout}")
        report_path = case_dir / REPORT
        if not report_path.is_file():
            raise RuntimeError(f"检查器未生成本次报告: {proc.stderr or proc.stdout}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        model, trace = report["model_check"], report["trace_check"]
        model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if (report["config_sha256"] != hashlib.sha256(config_path.read_bytes()).hexdigest()
                or model["model_sha256"] != model_hash or trace["model_sha256"] != model_hash
                or trace["trace_sha256"] != hashlib.sha256(trace_path.read_bytes()).hexdigest()):
            raise ValueError("报告与本次配置、模型或轨迹不匹配")
        expected = (proc.returncode == expected_exit and model["verdict"] == "PASS"
                    and model["ok"] is True and model["complete"] is True)
        if scenario == "normal":
            expected = (expected and report["verdict"] == "PASS" and trace["verdict"] == "PASS"
                        and trace["ok"] is True and trace["complete"] is True
                        and trace["steps_checked"] == trace["total_steps"] == 2)
        else:
            expected = (expected and report["verdict"] == "FAIL" and trace["verdict"] == "FAIL"
                        and trace["ok"] is False and trace.get("step") == 1
                        and trace.get("action") == "ship"
                        and trace.get("reason") == "guard_not_satisfied"
                        and trace.get("requirement") == "REQ-ORDER-001"
                        and trace.get("before") == {"paid": False, "shipped": False}
                        and trace.get("after") == {"paid": False, "shipped": True})
        all_expected = all_expected and expected
        print(f"{scenario}: 模型 {model['verdict']} / 轨迹 {trace['verdict']} / "
              f"{'符合预期' if expected else '不符合预期'}")
        if "reason" in trace:
            print(f"  原因: {trace['reason']}；步骤: {trace.get('step', '结束位置')}；"
                  f"动作: {trace.get('action', '无')}；需求: {trace.get('requirement', '无')}")
        print(f"  报告: {report_path}")
    if all_expected:
        print("演示成功：正常场景通过，缺陷场景被准确检出。")
    else:
        print("演示失败：检查结果与预期不符，请查看本次报告。")
    print("这不表示缺陷程序或整套交付门禁通过；本演示只检查模型与记录的轨迹。")
    return 0 if all_expected else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=EXAMPLE / "reports" / "demo",
                        help="输出根目录；相对路径以当前工作目录为准，每次新建独立子目录")
    args = parser.parse_args(argv)
    try:
        return run_demo(args.outdir)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[演示运行/输入错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
