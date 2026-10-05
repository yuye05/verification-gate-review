"""验证门禁①：数值口径自动一致性校验（机器门禁，非人眼核对）— 配置驱动通用版

从 gate_config.json 读取配置（字段说明见 references/gate_config.example.json）：

  - authoritative_json : 权威数字来源 JSON 列表（递归展平提取全部数值作为"真值"）
  - scan_dirs          : 要扫描的文档/代码/图注目录（相对配置文件所在目录）
  - scan_globs         : 扫描的文件扩展名（默认 .md/.txt/.json/.drawio）
  - forbidden_numbers  : 已废除的旧口径数字（出现即 FAIL，HARD）→ [{value, label}]
  - forbidden_texts    : 已废除的旧口径文本片段（出现即 FAIL）
  - whitelist          : 合法但非结果的数字（物理常数/参数/波段/DOI 等），孤儿检测跳过
  - skip_dirs          : 不扫描的目录（备份、图、__pycache__ 等，按路径片段匹配）
  - skip_files         : 不扫描的文件（会话备份、权威来源自身等，按文件名精确匹配）
  - core_docs          : 核心结果必须出现的关键文档名片段（缺失即 WARN）
  - core_key_fragments : 标记"核心"权威数字的 JSON key 片段（缺省=全部核心）
  - skip_key_fragments : 不提取为权威数字的 JSON key 片段（如诊断数组、谷列表）
  - rel_tolerance      : 数值容差（默认 0.002，即 0.2%）
  - output_dir         : 报告落盘目录（默认=配置文件所在目录）

报告三类问题：
  A. 权威关键数字缺失 —— 核心结果数字没有出现在应该出现的文档里（WARN）
  B. 禁用旧口径残留   —— 已被废除的旧数字/旧口径仍出现在某处（HARD FAIL）
  C. 孤儿数字候选     —— 结果域数字出现在文档中，但既不在权威集也不在白名单（人工复核）

判定：B 出现任一 → FAIL；A 核心缺失 → WARN（人工判断）；C → 列出候选。
输出：stdout 报告 + 落盘 门禁报告_一致性.md

运行：python check_consistency.py --config <path/to/gate_config.json>
"""
import sys
import json
import re
import math
import argparse
from pathlib import Path
from datetime import datetime

# ── 默认值（与已验证通过的 B 项目口径一致）──────────────────────
DEFAULT_GLOBS = {".md", ".txt", ".json", ".drawio"}
DEFAULT_SKIP_DIRS = {"__pycache__", ".git", ".claude"}
DEFAULT_REL_TOL = 0.002          # 权威数字匹配容差：相对 0.2% 或绝对 0.002
FORBIDDEN_REL_TOL = 0.0005       # 禁用数字匹配收紧到 0.05%，避免误伤合法相邻值
REPORT_NAME = "门禁报告_一致性.md"
GATE_DIR = Path(__file__).resolve().parent


# ── 配置加载 ───────────────────────────────────────────────────
def load_config(config_path):
    """读取 JSON 配置；相对路径一律以配置文件所在目录为基准。"""
    if not config_path.exists():
        print(f"[配置缺失] 找不到配置文件: {config_path}")
        print(f"请按 references/gate_config.example.json 创建 gate_config.json 后再运行。")
        sys.exit(2)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return config_path.resolve().parent, cfg


def resolve(base_dir, p):
    """把配置里的路径解析为绝对路径：相对路径以 base_dir（配置文件目录）为基准。"""
    path = Path(p)
    return path if path.is_absolute() else (base_dir / path)


def norm_globs(globs):
    """规范化扩展名列表：".MD"→".md"，"md"→".md"。"""
    out = set()
    for g in globs or []:
        g = g.strip().lower()
        if not g.startswith("."):
            g = "." + g
        out.add(g)
    return out or set(DEFAULT_GLOBS)


# ── 权威数字提取（递归展平 JSON）───────────────────────────────
def flatten_json(obj, prefix=""):
    """递归展平 JSON 为 (value, keypath) 对。只提取 int/float，bool 不算数字。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{prefix}.{k}" if prefix else str(k)
            out.extend(flatten_json(v, kp))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(flatten_json(v, f"{prefix}[{i}]"))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.append((float(obj), prefix))
    return out


# ── 数值工具 ───────────────────────────────────────────────────
def num_close(a, b, rel=DEFAULT_REL_TOL, abs_tol=DEFAULT_REL_TOL):
    """数值容差比较：相对 0.2% 或绝对 0.002（等价口径）。"""
    return abs(a - b) <= abs_tol + rel * max(abs(a), abs(b))


TOKEN_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
TAG_RE = re.compile(r"\\tag\{[^}]*\}")          # LaTeX 方程编号 \tag{3.15}


def extract_tokens(text):
    """提取含符号/科学计数法的数字；只剔除明确的 LaTeX 方程编号。"""
    text = TAG_RE.sub(" ", text)
    return [float(t) for t in TOKEN_RE.findall(text)]


# ── 文件扫描 ───────────────────────────────────────────────────
def scan_text_files(cfg, cfg_dir, config_path=None):
    """收集待扫描文本文件（排除权威来源、配置/报告自身、skip 目录与文件）。"""
    scan_dirs = [resolve(cfg_dir, d) for d in cfg.get("scan_dirs", ["."])]
    globs = norm_globs(cfg.get("scan_globs"))
    skip_dirs = set(cfg.get("skip_dirs", [])) | DEFAULT_SKIP_DIRS
    skip_files = set(cfg.get("skip_files", [])) | {
        "gate_config.json", REPORT_NAME, "门禁报告_合成自检.json"
    }
    # 权威来源 JSON 自动排除（它们是源头，不是交付文档；否则 A 类会误报"已出现"）
    auth_srcs = {resolve(cfg_dir, jp).resolve() for jp in cfg.get("authoritative_json", [])}
    if config_path is not None:
        auth_srcs.add(config_path.resolve())

    files = set()
    for d in scan_dirs:
        if not d.is_dir():
            raise ValueError(f"扫描目录不存在或不是目录: {d}")
        for f in sorted(d.rglob("*")):
            if f.is_dir() or f.suffix.lower() not in globs:
                continue
            if f.resolve() in auth_srcs:
                continue
            if any(part in skip_dirs for part in f.parts):
                continue
            if f.name in skip_files:
                continue
            if GATE_DIR in f.parents:       # 本 skill 的脚本目录，不扫
                continue
            files.add(f.resolve())
    return sorted(files)


# ── 主校验 ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="验证门禁①：数值口径自动一致性校验")
    ap.add_argument("--config", default="gate_config.json",
                    help="gate_config.json 路径（默认当前目录 gate_config.json）")
    ap.add_argument("--outdir", default=None, help="报告落盘目录（覆盖配置里的 output_dir）")
    args = ap.parse_args()

    cfg_dir, cfg = load_config(Path(args.config))
    out_dir = resolve(cfg_dir, args.outdir or cfg.get("output_dir", "."))
    out_dir.mkdir(parents=True, exist_ok=True)

    rel_tol = float(cfg.get("rel_tolerance", DEFAULT_REL_TOL))
    if not math.isfinite(rel_tol) or rel_tol < 0:
        raise ValueError("rel_tolerance 必须是非负有限数")

    print("=" * 68)
    print("验证门禁①：数值口径自动一致性校验（配置驱动通用版）")
    print(f"配置: {Path(args.config).resolve()}")
    print("=" * 68)

    files = scan_text_files(cfg, cfg_dir, Path(args.config))
    if not files:
        raise ValueError("没有可扫描的目标文件，不能判定 PASS")
    print(f"\n[扫描] {len(files)} 个文本文件\n")

    # 读取全部文本 + token（同时保留原始 token 字符串，孤儿检测用格式判断）
    file_texts, file_tokens, file_rawtokens = {}, {}, {}
    for f in files:
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:
            txt = f.read_text(encoding="utf-8", errors="replace")
        file_texts[f] = txt
        cleaned = TAG_RE.sub(" ", txt)
        file_tokens[f] = [float(t) for t in TOKEN_RE.findall(cleaned)]
        file_rawtokens[f] = TOKEN_RE.findall(cleaned)
        if not all(math.isfinite(t) for t in file_tokens[f]):
            raise ValueError(f"目标文件包含溢出的数值: {f}")

    # ── 权威数字（从 JSON 自动提取）──
    skip_key_frags = cfg.get("skip_key_fragments", [])
    core_key_frags = cfg.get("core_key_fragments", [])
    authoritative = []
    for jp in cfg.get("authoritative_json", []):
        p = resolve(cfg_dir, jp)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [配置错误] 权威 JSON 读取失败: {p} → {e}")
            sys.exit(2)
        for value, kp in flatten_json(data):
            if any(frag in kp for frag in skip_key_frags):
                continue
            if not math.isfinite(value):
                raise ValueError(f"权威数字非有限值: {p}: {kp}")
            authoritative.append((value, kp))
    if not authoritative:
        print("  [配置错误] 权威数字为空。请检查 authoritative_json 是否指向含数值的 JSON。")
        sys.exit(2)

    report = []
    fails, warns, candidates = [], [], []

    # ── B. 禁用旧口径（HARD FAIL）──
    print("【B】禁用旧口径残留检测")
    forbidden_nums = [(float(fb["value"]), fb.get("label", str(fb["value"])))
                      for fb in cfg.get("forbidden_numbers", [])]
    if not all(math.isfinite(n) for n, _ in forbidden_nums):
        raise ValueError("forbidden_numbers 必须是有限数值")
    forbidden_texts = cfg.get("forbidden_texts", [])
    for f in files:
        txt = file_texts[f]
        rel_path = str(f.relative_to(cfg_dir)) if cfg_dir in f.parents else str(f)
        for num, label in forbidden_nums:
            hit = any(num_close(num, t, rel=FORBIDDEN_REL_TOL, abs_tol=FORBIDDEN_REL_TOL)
                      for t in file_tokens[f])
            if hit:
                fails.append((rel_path, f"禁用数字 {num}（{label}）"))
        for text in forbidden_texts:
            if text in txt:
                fails.append((rel_path, f"禁用文本「{text}」"))
    if fails:
        for p, msg in fails:
            print(f"  [FAIL] {p}: {msg}")
    else:
        print("  ✓ 无旧口径残留")

    # ── A. 权威数字出现情况 ──
    print("\n【A】权威数字出现矩阵")
    core_docs = cfg.get("core_docs", [])
    core_missing = []
    for value, kp in authoritative:
        found_in = [str(f.relative_to(cfg_dir)) if cfg_dir in f.parents else str(f)
                    for f in files if any(num_close(value, t, rel=rel_tol) for t in file_tokens[f])]
        # core 判定：配置了 core_key_fragments 才区分核心/辅助，否则全部核心
        is_core = (not core_key_frags) or any(frag in kp for frag in core_key_frags)
        if is_core:
            if core_docs:
                in_core = [p for p in found_in if any(d in p for d in core_docs)]
                if not in_core:
                    core_missing.append((value, kp))
            elif not found_in:
                core_missing.append((value, kp))
        mark = "✓" if found_in else ("⚠核心缺失" if is_core else "○未出现")
        print(f"  [{mark}] {value:<10} {kp}")
        report.append((value, kp, found_in))

    if core_missing:
        print("\n  [WARN] 核心数字未出现在核心文档中：")
        for value, kp in core_missing:
            print(f"    - {value} ({kp})")
            warns.append((str(value), f"核心数字 {value} ({kp}) 未出现在核心文档"))
    else:
        print("  ✓ 全部核心数字已在核心文档出现")

    # ── C. 孤儿数字候选 ──
    print("\n【C】孤儿数字候选（结果样式数字，不在权威集/白名单）")
    auth_vals = [v for v, _ in authoritative]
    whitelist = [float(w) for w in cfg.get("whitelist", [])]
    if not all(math.isfinite(w) for w in whitelist):
        raise ValueError("whitelist 必须是有限数值")
    white_vals = set(auth_vals) | set(whitelist)
    seen = set()
    for f in files:
        rel_path = str(f.relative_to(cfg_dir)) if cfg_dir in f.parents else str(f)
        for raw in file_rawtokens[f]:
            t = float(raw)
            dec = len(raw.split(".")[1]) if "." in raw else 0
            # 结果样式判定：小数位≥3 且值域像厚度/RMSE/Δd，或 2 位小数且在结果域
            looks_result = (dec >= 3 and (3.0 <= t <= 20.0 or 0.0 <= t <= 1.0)) \
                or (dec >= 2 and 1.0 <= t <= 10.0)
            if not looks_result:
                continue
            if any(num_close(t, w, rel=rel_tol) for w in white_vals):
                continue
            key = (round(t, 4), rel_path)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((t, rel_path))
    if candidates:
        for t, p in sorted(candidates, key=lambda x: -x[0])[:40]:
            print(f"  [候选] {t:<10} {p}")
        if len(candidates) > 40:
            print(f"  ... 另有 {len(candidates)-40} 个候选，详见落盘报告")
    else:
        print("  ✓ 无孤儿数字候选")

    # ── 汇总 ──
    print("\n" + "=" * 68)
    status = "FAIL" if fails else ("PASS（含 WARN）" if warns or candidates else "PASS")
    print(f"判定: {status}")
    print(f"  HARD FAIL 项: {len(fails)}")
    print(f"  WARN 项:     {len(warns)}")
    print(f"  孤儿候选:    {len(candidates)}（需人工复核）")
    print("=" * 68)

    # ── 落盘报告 ──
    lines = ["# 门禁报告①：数值口径一致性校验",
             f"\n> 运行时间：{datetime.now().isoformat()}",
             f"\n> 配置：{Path(args.config).resolve()}",
             f"\n## 判定：{status}",
             f"- HARD FAIL: {len(fails)}", f"- WARN: {len(warns)}",
             f"- 孤儿候选: {len(candidates)}",
             f"- 扫描文件数: {len(files)}", ""]
    if fails:
        lines += ["## 禁用旧口径残留（FAIL）", ""]
        lines += [f"- {p}: {msg}" for p, msg in fails]
    if warns:
        lines += ["", "## 核心数字缺失（WARN）", ""]
        lines += [f"- {num}: {label}" for num, label in core_missing]
    lines += ["", "## 权威数字出现情况", ""]
    lines += ["| 数字 | 含义(JSON路径) | 出现位置 |", "|------|--------------|----------|"]
    for value, kp, found in report:
        lines += [f"| {value} | {kp} | {('、'.join(found))[:120] if found else '—'} |"]
    lines += ["", "## 孤儿数字候选（人工复核）", ""]
    lines += [f"- {t} @ {p}" for t, p in sorted(candidates, key=lambda x: -x[0])]
    out_path = out_dir / REPORT_NAME
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已落盘: {out_path}")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"[配置/输入错误] {exc}")
        sys.exit(2)
