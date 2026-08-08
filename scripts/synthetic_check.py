"""验证门禁②：合成数据自检 — 证明算法无系统偏差（配置驱动通用框架）

用"已知答案"的合成数据跑被测算法，验证还原误差 < pass_threshold_pct ——
证明算法无系统偏差（不只测噪声鲁棒）。

【通用框架】本脚本是自检框架，不绑定任何具体领域：
  用户在 gate_config.json 中声明要验证的算法类型和参数
  （字段说明见 references/gate_config.example.json）：
  - pass_threshold_pct : 还原误差阈值（%），默认 0.5
  - 各算法段（示例见下）：声明真值列表、参数范围、合成数据构造方式

【内置示例】本脚本内置一组光学厚度测量参考实现（级次对齐 / 修正轴 FFT /
kurtosis 判据）作为示例插件，配置段为：
  - order_alignment : 级次对齐还原 → 直接构造"整数级次谷"
  - fft             : 修正轴 FFT 还原 → 生成强多光束 Airy 光谱
  - kurtosis        : kurtosis 判据自洽 → 纯正弦 vs 强多光束
内置示例保留用于展示"如何为自己的算法写合成数据自检"。若被测算法与示例
参考实现的签名/假设不同，请按算法自身假设改写对应实现后再跑。

══════ 通用陷阱（必须遵守）═════════════════════════════════════
合成数据必须按被测算法自身假设构造，不能喂与算法假设错位的理想输入——
否则必然还原失败，那是生成器的问题不是算法的问题。
（示例：级次对齐算法隐含"谷在整数级次"的相位约定，验证必须直接构造谷位置
σ_j = m / (2·n·d_true·ncos)，m=整数；FFT 只依赖周期故可生成 Airy 光谱。）

输出：门禁报告_合成自检.json（落盘到 output_dir，默认=配置文件目录）
运行：python synthetic_check.py --config <path/to/gate_config.json>
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
from scipy.signal import savgol_filter
from scipy.optimize import minimize_scalar


# ═══════════════════════════════════════════════════════════════
# 参考实现（光学厚度测量示例插件：级次对齐 / 修正轴 FFT / kurtosis 判据）
# ═══════════════════════════════════════════════════════════════
def snell_cos(theta1_deg, n2):
    """Snell 定律 cos(θ₂)。"""
    t1 = np.radians(theta1_deg)
    sin_t2 = np.sin(t1) / np.asarray(n2)
    return np.cos(np.arcsin(np.clip(sin_t2, -1, 1)))


def coarse_to_fine(f, d_range, n_coarse=4000, refine_halfwidth=0.2, n_candidates=3):
    """粗网格全局扫描 + 局部精化（多峰目标函数最小化）。"""
    dmin, dmax = d_range
    grid = np.linspace(dmin, dmax, n_coarse)
    vals = np.array([f(float(d)) for d in grid])
    order = np.argsort(vals)
    cands = []
    for idx in order:
        d0 = grid[idx]
        if any(abs(d0 - c[0]) < refine_halfwidth for c in cands):
            continue
        cands.append((d0, vals[idx]))
        if len(cands) >= n_candidates:
            break
    refined = []
    for d0, _v0 in cands:
        lo = max(dmin, d0 - refine_halfwidth)
        hi = min(dmax, d0 + refine_halfwidth)
        res = minimize_scalar(f, bounds=(lo, hi), method="bounded")
        refined.append((float(res.x), float(res.fun)))
    refined.sort(key=lambda t: t[1])
    return refined


def alignment_single(valleys, theta1_deg, n=2.55, d_range=(5.0, 18.0)):
    """单角度级次对齐：E(d)=mean((j'-round j')²) 最小化。返回 (d_um, E_min)。"""
    if len(valleys) < 3:
        return None, None
    v = np.asarray(valleys, dtype=float)
    ncos = np.sqrt(n ** 2 - np.sin(np.radians(theta1_deg)) ** 2)

    def E(d):
        j = 2.0 * n * (float(d) * 1e-4) * ncos * v
        return float(np.mean((j - np.round(j)) ** 2))

    cands = coarse_to_fine(E, d_range, n_coarse=4000, refine_halfwidth=0.2)
    return cands[0][0], cands[0][1]


def order_alignment_shared(valleys_10, valleys_15, theta1_list, n=2.55, d_range=(5.0, 18.0)):
    """双角度联合级次对齐：两个角度共享同一厚度 d，联合 E(d) 最小化。"""
    def E(d):
        total, npts = 0.0, 0
        for valleys, theta1 in zip([valleys_10, valleys_15], theta1_list):
            if len(valleys) == 0:
                continue
            ncos = np.sqrt(max(n ** 2 - np.sin(np.radians(theta1)) ** 2, 1e-12))
            j = 2.0 * n * (float(d) * 1e-4) * ncos * np.asarray(valleys, dtype=float)
            total += float(np.sum((j - np.round(j)) ** 2))
            npts += len(valleys)
        return total / max(npts, 1)

    cands = coarse_to_fine(E, d_range, n_coarse=4000, refine_halfwidth=0.2)
    return {"d_um": float(cands[0][0]), "E": float(cands[0][1]),
            "rmse": float(np.sqrt(cands[0][1])), "candidates": cands[:3]}


def robust_baseline(signal, window=101):
    """宽窗滑动平均基线（保留干涉条纹）。"""
    window = max(5, int(window) | 1)
    if window >= len(signal):
        window = (len(signal) // 2) * 2 + 1
    pad = window // 2
    yp = np.pad(np.asarray(signal, dtype=float), (pad, pad), mode="edge")
    return np.convolve(yp, np.ones(window) / window, mode="valid")


def fft_axis(n_fft, dsigma):
    """修正光程差轴 OPD_k = k/(n_fft·dsigma)（cm）。"""
    return np.arange(n_fft // 2 + 1) / (n_fft * dsigma)


def parabolic_peak(y, k):
    """对数域抛物线亚像素峰值。"""
    k = int(k)
    if k <= 0 or k >= len(y) - 1:
        return float(k)
    a, b, c = np.log(np.maximum(y[k - 1:k + 2], 1e-12))
    den = a - 2.0 * b + c
    if abs(den) < 1e-12:
        return float(k)
    return k + 0.5 * (a - c) / den


def si_fft_thickness(sigma, R, theta1_deg, band=(400, 2000), n=3.42,
                     d_range=(3.0, 5.0), win=101):
    """修正轴 FFT 求厚度：去基线 + 去线性项 + rfft + 亚像素峰值。"""
    mask = (sigma >= band[0]) & (sigma <= band[1])
    s, r = sigma[mask], R[mask]
    if len(s) < 128:
        return None
    dsigma = s[1] - s[0]
    osc = r - robust_baseline(r, win)
    osc = osc - np.polyval(np.polyfit(s, osc, 1), s)
    nfft = 2 ** int(np.ceil(np.log2(len(osc))) + 2)
    amp = np.abs(np.fft.rfft(osc * np.hanning(len(osc)), n=nfft))
    ncos = np.sqrt(max(n ** 2 - np.sin(np.radians(theta1_deg)) ** 2, 1e-12))
    d_um = fft_axis(nfft, dsigma) / (2 * ncos) * 1e4
    allowed = (d_um >= d_range[0]) & (d_um <= d_range[1])
    if not np.any(allowed):
        return None
    idx = np.flatnonzero(allowed)[np.argmax(amp[allowed])]
    kf = parabolic_peak(amp, idx)
    return float(kf / (nfft * dsigma) / (2 * ncos) * 1e4)


def compute_kurtosis(signal):
    """峰度（非超额）。纯正弦=1.5。"""
    y = np.asarray(signal, dtype=float)
    y = y - np.mean(y)
    m4 = np.mean(y ** 4)
    m2 = np.mean(y ** 2)
    if m2 < 1e-20:
        return 1.5
    return m4 / (m2 ** 2)


def sg_detrend(sigma, R, window=301):
    """大窗 SG 去基线（保留振荡特征）。"""
    w = min(window, len(R) // 4 * 2 + 1)
    if w < 5:
        return R - np.mean(R), np.full_like(R, np.mean(R))
    baseline = savgol_filter(R, w, 3)
    return R - baseline, baseline


def kurtosis_metric(sigma, R, band=(500, 2000), sg_window=301):
    """SG 去基线后峰度（示例口径）。多光束 >> 1.5。"""
    mask = (np.asarray(sigma) >= band[0]) & (np.asarray(sigma) <= band[1])
    s, r = np.asarray(sigma)[mask], np.asarray(R)[mask]
    if len(s) < 50:
        return 1.5
    rs = savgol_filter(r, min(51, len(r) // 2 * 2 + 1), 3)
    osc, _ = sg_detrend(s, rs, window=sg_window)
    return compute_kurtosis(osc)


# ═══════════════════════════════════════════════════════════════
# 合成数据构造（按算法自身假设构造，见文件头物理陷阱说明）
# ═══════════════════════════════════════════════════════════════
def ncos(theta, n):
    return float(np.sqrt(n ** 2 - np.sin(np.radians(theta)) ** 2))


def integer_order_valleys(d_true, theta, n, m_range, jitter_cm1=0.0, seed=0):
    """直接构造谷位置：j'(σ_j)=2·n·d·ncos·σ_j = 整数 m → σ_j = m/(2·n·d·ncos)。
    可选加谷位置扰动（模拟检测噪声）。"""
    d_cm = d_true * 1e-4
    nc = ncos(theta, n)
    sigma_j = np.array([m / (2.0 * n * d_cm * nc) for m in m_range], dtype=float)
    if jitter_cm1 > 0:
        rng = np.random.default_rng(seed)
        sigma_j = sigma_j + rng.normal(0, jitter_cm1, len(sigma_j))
    return sigma_j


def auto_m_range(d_true, n, thetas, band, n_valleys_min=7):
    """选整数 m，使谷位置对所有角度都落在 band 内（留边距），且谷数≥下限。"""
    d_cm = d_true * 1e-4
    ncos_list = [ncos(th, n) for th in thetas]
    ncos_max, ncos_min = max(ncos_list), min(ncos_list)
    lo = band[0] * 1.05
    hi = band[1] * 0.95
    m_min = int(np.ceil(lo * 2.0 * n * d_cm * ncos_max))
    m_max = int(np.floor(hi * 2.0 * n * d_cm * ncos_min))
    m_max = max(m_max, m_min + n_valleys_min - 1)
    return range(m_min, m_max + 1)


def gen_airy_spectrum(sigma, d_true, theta, n, r2=0.3, noise=0.001):
    """强多光束 Airy 光谱（常数 n）—— FFT 应免疫条纹形状失真。"""
    n_arr = np.full_like(sigma, n, dtype=float)
    cos_t = snell_cos(theta, n_arr)
    dc = d_true * 1e-4
    delta = 4 * np.pi * n_arr * dc * cos_t * sigma
    r1 = (1 - n) / (1 + n)
    r1s, r2s, r12 = r1 ** 2, r2 ** 2, r1 * r2
    cosd = np.cos(delta)
    R = (r1s + r2s + 2 * r12 * cosd) / (1 + r1s * r2s + 2 * r12 * cosd)
    R = np.clip(R, 0, 1)
    R = R + np.random.default_rng(0).normal(0, noise, len(sigma))
    return np.clip(R, 0.001, 1)


# ═══════════════════════════════════════════════════════════════
# 三组验证
# ═══════════════════════════════════════════════════════════════
def test_order_alignment(cfg):
    """【A】级次对齐还原：直接构造整数级次谷（±jitter 扰动模拟噪声）。"""
    out = []
    n = cfg.get("n", 2.55)
    d_range = tuple(cfg.get("d_range", [5.0, 18.0]))
    thetas = cfg.get("ncos_theta_list", cfg.get("thetas", [10, 15]))
    band = tuple(cfg.get("band", [1100, 2000]))
    jitter_list = [0.0] if cfg.get("jitter_cm1", 0.0) == 0 else [0.0, cfg["jitter_cm1"]]
    for d_true in cfg["d_true_list"]:
        mr = auto_m_range(d_true, n, thetas, band)
        if len(mr) < 4:
            out.append({"ok": False, "d_true": d_true, "err": "谷数不足", "n_valleys": len(mr)})
            continue
        for jitter in jitter_list:
            v10 = integer_order_valleys(d_true, thetas[0], n, mr, jitter_cm1=jitter)
            v15 = integer_order_valleys(d_true, thetas[1], n, mr, jitter_cm1=jitter)
            d10, E10 = alignment_single(v10, thetas[0], n=n, d_range=d_range)
            d15, E15 = alignment_single(v15, thetas[1], n=n, d_range=d_range)
            joint = order_alignment_shared(v10, v15, thetas, n=n, d_range=d_range)
            rel_joint = abs(joint["d_um"] - d_true) / d_true * 100
            ok = (rel_joint < cfg["pass_threshold_pct"] and d10 is not None and d15 is not None)
            out.append({
                "ok": bool(ok), "d_true": d_true, "jitter_cm1": jitter,
                "d10": d10, "d15": d15,
                "d_joint": round(float(joint["d_um"]), 4),
                "rel_err_pct": round(float(rel_joint), 3),
                "n_valleys": len(v10),
            })
    return out


def test_fft(cfg):
    """【B】修正轴 FFT 还原：强多光束 Airy 光谱 → 应还原 d_true。"""
    out = []
    n = cfg.get("n", 3.42)
    d_range = tuple(cfg.get("d_range", [3.0, 5.0]))
    thetas = cfg.get("thetas", cfg.get("thetas_deg", [10, 15]))
    band = tuple(cfg.get("band", [400, 2000]))
    r2 = cfg.get("r2", 0.3)
    step = cfg.get("sigma_step_cm1", 0.5)
    sigma = np.arange(band[0], band[1] + step, step)
    for d_true in cfg["d_true_list"]:
        d10 = si_fft_thickness(sigma, gen_airy_spectrum(sigma, d_true, thetas[0], n, r2),
                               thetas[0], band=band, n=n, d_range=d_range)
        d15 = si_fft_thickness(sigma, gen_airy_spectrum(sigma, d_true, thetas[1], n, r2),
                               thetas[1], band=band, n=n, d_range=d_range)
        ok = (d10 is not None and d15 is not None)
        rel = abs((d10 + d15) / 2 - d_true) / d_true * 100 if ok else float("inf")
        out.append({
            "ok": bool(ok and rel < cfg["pass_threshold_pct"]), "d_true": d_true,
            "d10": d10, "d15": d15,
            "d_mean": round((d10 + d15) / 2, 4) if ok else None,
            "rel_err_pct": round(float(rel), 3) if ok else None,
        })
    return out


def test_kurtosis(cfg):
    """【C】kurtosis 判据自洽：纯正弦 vs 强多光束（同 n 同 d，单调可区分）。"""
    n = cfg.get("n", 2.55)
    band = tuple(cfg.get("band", [1100, 2000]))
    r2 = cfg.get("r2", 0.3)
    d_true = cfg.get("d_true", 8.0)
    theta = cfg.get("theta", cfg.get("theta_deg", 10))
    two_beam_max = cfg.get("two_beam_max", 2.5)
    strong_min = cfg.get("strong_min", 3.0)
    step = cfg.get("sigma_step_cm1", 0.5)

    sigma = np.arange(band[0], band[1] + step, step)
    # 纯正弦（两光束极限）
    n_arr = np.full_like(sigma, n, dtype=float)
    cos_t = snell_cos(theta, n_arr)
    dc = d_true * 1e-4
    delta = 4 * np.pi * n_arr * dc * cos_t * sigma
    R_sin = np.clip(0.19 + 0.05 * np.cos(delta), 0.001, 1)
    k_sin = float(kurtosis_metric(sigma, R_sin, band=band))
    # 强多光束 Airy
    R_air = gen_airy_spectrum(sigma, d_true, theta, n, r2)
    k_air = float(kurtosis_metric(sigma, R_air, band=band))
    ok = (k_sin < two_beam_max) and (k_air > strong_min) and (k_air > k_sin + 0.5)
    return {"k_two_beam": round(k_sin, 2), "k_strong_multibeam": round(k_air, 2),
            "two_beam_max": two_beam_max, "strong_min": strong_min,
            "criterion_ok": bool(ok)}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="验证门禁②：合成数据自检（算法无系统偏差证明）")
    ap.add_argument("--config", default="gate_config.json",
                    help="gate_config.json 路径（默认当前目录 gate_config.json）")
    ap.add_argument("--outdir", default=None, help="报告落盘目录（覆盖配置里的 output_dir）")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"[配置缺失] 找不到配置文件: {cfg_path}")
        sys.exit(2)
    cfg_dir = cfg_path.resolve().parent
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out_dir = Path(args.outdir) if args.outdir else Path(cfg.get("output_dir", cfg_dir))
    if not out_dir.is_absolute():
        out_dir = cfg_dir / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    threshold = float(cfg.get("pass_threshold_pct", 0.5))

    print("=" * 68)
    print("验证门禁②：合成数据自检（算法无系统偏差证明）")
    print(f"配置: {cfg_path.resolve()}")
    print("=" * 68)
    print("口径说明：级次对齐按 j'=整数级次谷直接构造（与算法相位约定一致）；\n"
          "         FFT 用强多光束 Airy 光谱（免疫条纹形状失真）；kurtosis 判据验证单调区分。")

    results = {}
    verdict_ok = True
    detail_lines = []

    # 【A】级次对齐
    oa_cfg = cfg.get("order_alignment")
    if oa_cfg:
        oa_cfg = dict(oa_cfg)
        oa_cfg["pass_threshold_pct"] = threshold
        print(f"\n【A】级次对齐还原（直接构造整数级次谷，n={oa_cfg.get('n',2.55)}, "
              f"jitter={oa_cfg.get('jitter_cm1',0.0)} cm⁻¹）")
        sic = test_order_alignment(oa_cfg)
        results["order_alignment"] = sic
        for r in sic:
            mark = "✓" if r["ok"] else "✗"
            if "err" in r:
                print(f"  {mark} d_true={r['d_true']} µm [{r['err']}]")
            else:
                jit = f"扰动±{r['jitter_cm1']}" if r["jitter_cm1"] else "无扰动"
                print(f"  {mark} d_true={r['d_true']} µm [{jit}] → joint={r['d_joint']} "
                      f"(误差 {r['rel_err_pct']:.3f}%)")
            verdict_ok = verdict_ok and r["ok"]
    else:
        detail_lines.append("未配置 order_alignment，跳过")

    # 【B】FFT
    fft_cfg = cfg.get("fft")
    if fft_cfg:
        fft_cfg = dict(fft_cfg)
        fft_cfg["pass_threshold_pct"] = threshold
        print(f"\n【B】修正轴 FFT 还原（强多光束 Airy r2={fft_cfg.get('r2',0.3)}, "
              f"band {fft_cfg.get('band',[400,2000])}, n={fft_cfg.get('n',3.42)}）")
        si = test_fft(fft_cfg)
        results["fft"] = si
        for r in si:
            mark = "✓" if r["ok"] else "✗"
            if r["d_mean"] is not None:
                print(f"  {mark} d_true={r['d_true']} µm → d_mean={r['d_mean']} "
                      f"(误差 {r['rel_err_pct']:.3f}%, 10°={r['d10']:.4f} 15°={r['d15']:.4f})")
            else:
                print(f"  ✗ d_true={r['d_true']} µm → FFT 无主峰")
            verdict_ok = verdict_ok and r["ok"]
    else:
        detail_lines.append("未配置 fft，跳过")

    # 【C】kurtosis 判据
    kur_cfg = cfg.get("kurtosis")
    if kur_cfg:
        print(f"\n【C】kurtosis 判据自洽（纯正弦 vs 强多光束）")
        kc = test_kurtosis(dict(kur_cfg))
        results["kurtosis_criterion"] = kc
        print(f"  纯正弦 kurtosis={kc['k_two_beam']} (理论 1.5)，"
              f"强多光束 kurtosis={kc['k_strong_multibeam']} → "
              f"{'✓ 判据单调区分' if kc['criterion_ok'] else '✗ 判据异常'}")
        verdict_ok = verdict_ok and kc["criterion_ok"]
    else:
        detail_lines.append("未配置 kurtosis，跳过")

    if not (cfg.get("order_alignment") or cfg.get("fft") or cfg.get("kurtosis")):
        print("[配置错误] order_alignment / fft / kurtosis 至少配置一个。")
        sys.exit(2)

    # 汇总
    a_ok = all(r["ok"] for r in results.get("order_alignment", [])) if "order_alignment" in results else True
    b_ok = all(r["ok"] for r in results.get("fft", [])) if "fft" in results else True
    c_ok = results.get("kurtosis_criterion", {}).get("criterion_ok", True)
    n_pass = sum(1 for sec in ("order_alignment", "fft") for r in results.get(sec, []) if r["ok"])
    n_total = sum(len(results.get(sec, [])) for sec in ("order_alignment", "fft"))
    all_ok = a_ok and b_ok and c_ok
    print("\n" + "=" * 68)
    print(f"判定: {'PASS — 算法无系统偏差' if all_ok else 'FAIL — 存在还原偏差'}")
    print(f"  级次对齐: {'通过' if a_ok else '存在失败'}   FFT: {'通过' if b_ok else '存在失败'}")
    print(f"  kurtosis 判据: {'通过' if c_ok else '未通过'}")
    print(f"  还原测试通过 {n_pass}/{n_total}（阈值 {threshold}%）")
    print("=" * 68)

    out = {
        "timestamp": datetime.now().isoformat(),
        "config_path": str(cfg_path.resolve()),
        "pass_threshold_pct": threshold,
        "verdict": "PASS" if all_ok else "FAIL",
        "sections_checked": {
            "order_alignment": "order_alignment" in results,
            "fft": "fft" in results,
            "kurtosis": "kurtosis_criterion" in results,
        },
        "summary": {"a_alignment_ok": a_ok, "b_fft_ok": b_ok, "c_kurtosis_ok": c_ok,
                    "passed": n_pass, "total": n_total},
        **results,
    }
    out_path = out_dir / "门禁报告_合成自检.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已落盘: {out_path}")


if __name__ == "__main__":
    main()
