#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import norm
import matplotlib
import matplotlib.font_manager as fm

# ---------------- 字体设置（中文 + Arial 数学/英文） ----------------
CJK_CANDIDATES = [
    "PingFang SC", "Heiti SC", "Songti SC", "STHeiti",
    "SimHei", "Microsoft YaHei", "Noto Sans CJK SC",
    "Source Han Sans SC", "WenQuanYi Zen Hei", "Arial Unicode MS"
]
LATIN_FONT = "Arial"

installed = {f.name for f in fm.fontManager.ttflist}
cjk = next((name for name in CJK_CANDIDATES if name in installed), None)
if cjk is None:
    print("⚠️ 未找到可用中文字体，建议安装 'Noto Sans CJK SC' 或 'PingFang SC'。临时用 Arial Unicode MS 兜底。")
    cjk = "Arial Unicode MS"

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [cjk, LATIN_FONT]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["mathtext.fontset"] = "custom"
matplotlib.rcParams["mathtext.rm"] = LATIN_FONT
matplotlib.rcParams["mathtext.it"] = f"{LATIN_FONT}:italic"
matplotlib.rcParams["mathtext.bf"] = f"{LATIN_FONT}:bold"

# ---------------- 路径配置 ----------------
BASE_DIR = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/qpcr"
PER_UNIT = f"{BASE_DIR}/per_unit_effects.csv"
META_SUM = f"{BASE_DIR}/meta_gene_summary.csv"
OUT_DIR  = Path(BASE_DIR)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- 影响度与离群判定阈值（可调）----
RESID_Z_TH  = 2.0     # 标准化残差阈值（|z|>2 标红）
DELTA_E_TH  = 0.20    # leave-one-out 后合并效应变化阈值（log2FC）
ALPHA       = 0.05    # 用于描述文本中的显著性阈值

# ---- “严格逻辑”判定阈值（新增）----
ALPHA_P = 0.05        # 统计显著：p 阈值
ALPHA_Q = 0.05        # 统计显著：q 阈值（若有 q）
TREND_Q = 0.25        # 趋势：宽松 q
TREND_P = 0.10        # 趋势：宽松 p
EFFECT_MIN = 0.50     # 趋势/生物学意义的 |log2FC| 阈值（≈1.41x）
I2_HIGH   = 0.60      # I² 高异质性提示阈值

# ------------ 元分析函数（固定效应 + 随机效应 DL）------------
def meta_fe(e, v):
    w = 1.0 / v
    mu = np.sum(w*e) / np.sum(w)
    se = np.sqrt(1.0 / np.sum(w))
    z  = mu / se
    p  = 2*(1 - norm.cdf(abs(z)))
    ci = (mu - 1.96*se, mu + 1.96*se)
    return mu, se, z, p, ci

def meta_re_dl(e, v):
    w  = 1.0 / v
    mu_fe = np.sum(w*e) / np.sum(w)
    Q  = np.sum(w * (e - mu_fe)**2)
    k  = len(e)
    if k <= 1:
        tau2 = 0.0
    else:
        C = np.sum(w) - (np.sum(w**2) / np.sum(w))
        tau2 = max(0.0, (Q - (k-1)) / C)
    w_re = 1.0 / (v + tau2)
    mu = np.sum(w_re*e) / np.sum(w_re)
    se = np.sqrt(1.0 / np.sum(w_re))
    z  = mu / se if se>0 else np.nan
    p  = 2*(1 - norm.cdf(abs(z))) if np.isfinite(z) else np.nan
    ci = (mu - 1.96*se, mu + 1.96*se)
    I2 = max(0.0, (Q - (k-1)) / Q) if (k>1 and Q>0) else 0.0
    return mu, se, z, p, ci, tau2, I2, Q

def standardized_residuals(e, v, mu, tau2):
    return (e - mu) / np.sqrt(v + tau2)

# ------------ 打标签（严格逻辑） ------------
def label_and_rationale(re_effect, re_ci, re_p, q, fe_effect, max_delta_loo, i2):
    """
    返回 label（显著/趋势/不显著 + 修饰）与判定过程 rationale 文本
    严格逻辑：
      1) 先判统计显著： (CI不跨0 或 p<0.05) 且 (如有q则 q<0.05)
      2) 再判趋势：[(q<0.25 或 p<0.1) 且 |effect|>=阈值]
      3) 稳健性和异质性仅作为“修饰语”，不作为显著性的硬门槛
    """
    ci_low, ci_high = re_ci
    has_ci = (ci_low is not None) and (ci_high is not None) and np.isfinite(ci_low) and np.isfinite(ci_high)
    ci_ok  = (has_ci and (ci_low * ci_high > 0))
    p_ok   = (re_p is not None) and np.isfinite(re_p) and (re_p < ALPHA_P)
    q_ok   = (q is not None) and np.isfinite(q) and (q < ALPHA_Q)

    # 显著：必须满足 CI/p 之一 + （若有 q 则 q<0.05）
    sig_stat = (ci_ok or p_ok) and (q_ok or (q is None or not np.isfinite(q)))

    # 趋势：更宽松的阈值 + 生物学意义的最小效应
    trend_stat = (((q is not None and np.isfinite(q) and q < TREND_Q) or
                   (re_p is not None and np.isfinite(re_p) and re_p < TREND_P))
                  and (abs(re_effect) >= EFFECT_MIN))

    # 方向一致（RE vs FE）
    same_dir = (np.sign(re_effect) == np.sign(fe_effect)) if (np.isfinite(re_effect) and np.isfinite(fe_effect)) else True

    # 稳健性（LOO）
    robust = (max_delta_loo is not None) and np.isfinite(max_delta_loo) and (max_delta_loo < DELTA_E_TH)

    # 异质性
    high_het = (i2 is not None) and np.isfinite(i2) and (i2 > I2_HIGH)

    # 主标签
    if sig_stat and same_dir:
        label = "显著"
    elif trend_stat and same_dir:
        label = "趋势"
    else:
        label = "不显著"

    # 修饰语
    mods = []
    if high_het: mods.append("高异质性，谨慎")
    mods.append("稳健" if robust else "受单元影响")
    if not same_dir: mods.append("FE/RE 方向不一致")
    label_full = label + (f"（{'；'.join(mods)}）" if mods else "")

    # 判定过程
    parts = []
    parts.append(f"CI跨0={'否' if ci_ok else '是'}")
    parts.append(f"p={re_p:.3g}" if (re_p is not None and np.isfinite(re_p)) else "p=NA")
    parts.append(f"q={q:.3g}" if (q is not None and np.isfinite(q)) else "q=NA")
    parts.append(f"FE_dir={'同向' if same_dir else '反向'}")
    parts.append(f"LOOmax={max_delta_loo:.2f}" if (max_delta_loo is not None and np.isfinite(max_delta_loo)) else "LOOmax=NA")
    parts.append(f"I2={i2:.2f}" if (i2 is not None and np.isfinite(i2)) else "I2=NA")
    rationale = " | ".join(parts)

    return label_full, rationale

# ------------ forest 图函数 ------------
def forest_plot_for_gene(unit_df, gene, outpath, model="RE", q_lookup=None):
    """
    unit_df: 包含 gene 的多行 DataFrame，至少列：experiment_id, batch_id, effect, se, var
    model: "RE" (默认) 或 "FE"
    q_lookup: 可选 dict，gene -> q 值（来自 meta_gene_summary.csv）
    """
    d = unit_df.copy().sort_values(["experiment_id","batch_id"])
    e = d["effect"].values
    v = d["var"].values

    # FE & RE
    mu_fe, se_fe, z_fe, p_fe, ci_fe = meta_fe(e, v)
    mu_re, se_re, z_re, p_re, ci_re, tau2, I2, Q = meta_re_dl(e, v)

    if model.upper() == "FE":
        mu, se, z, p, ci = mu_fe, se_fe, z_fe, p_fe, ci_fe
        tau2_use, I2_use = 0.0, 0.0
    else:
        mu, se, z, p, ci = mu_re, se_re, z_re, p_re, ci_re
        tau2_use, I2_use = tau2, I2

    # 影响诊断：标准化残差 + 留一
    r = standardized_residuals(e, v, mu, tau2_use)
    d["std_resid"] = r
    d["suspect"] = (np.abs(r) > RESID_Z_TH)

    delta_effect = []
    for i in range(len(d)):
        e_loo = np.delete(e, i)
        v_loo = np.delete(v, i)
        mu_loo, _, _, _, _ = meta_re_dl(e_loo, v_loo)[:5]
        delta_effect.append(mu - mu_loo)
    d["delta_mu_loo"] = np.array(delta_effect)
    d["suspect"] |= (np.abs(d["delta_mu_loo"]) > DELTA_E_TH)
    max_delta = float(np.abs(d["delta_mu_loo"]).max()) if len(d) else 0.0

    # 权重（RE 权重）
    w = 1.0 / (v + tau2_use)
    w = w / w.sum()
    d["weight"] = w

    # ---- 画图 ----
    fig, ax = plt.subplots(figsize=(5.6, 0.46*len(d) + 2.4))
    y = np.arange(len(d))[::-1]
    ci_low = e - 1.96*np.sqrt(v)
    ci_high = e + 1.96*np.sqrt(v)
    colors = np.where(d["suspect"], "tab:red", "tab:blue")
    sizes = 34 + 170*w

    ax.hlines(y, ci_low, ci_high, color=colors, alpha=0.9, linewidth=1.9)
    ax.scatter(e, y, s=sizes, c=colors, alpha=0.9, zorder=3)

    ax.axvline(0, color="gray", lw=1, ls="--")
    ax.hlines(-1, ci[0], ci[1], color="black", linewidth=3.6)
    ax.scatter([mu], [-1], s=120, c="black", zorder=4)

    labels = [
        f"exp {row.experiment_id}, batch {row.batch_id}  (w={row.weight:.2f}{'; !' if row.suspect else ''})"
        for _, row in d.iterrows()
    ]
    ax.set_yticks(np.append(y, -1))
    ax.set_yticklabels(labels + [f"Pooled ({model.upper()})"])
    ax.set_xlabel("HO − WT (log2FC)")

    # —— 标题与统计信息（防截断）——
    fig.suptitle(gene, x=0.02, y=0.99, ha="left", fontsize=13, fontweight="bold")
    stats_str = f"I²={I2_use*100:.0f}%   τ²={tau2_use:.3f}   pooled={mu:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]   p={p:.3g}"
    fig.text(0.99, 0.99, stats_str, transform=fig.transFigure, ha="right", va="top", fontsize=10)

    # —— 图下方“描述性话语” + 严格逻辑的标签与判定过程 —— 
    fc_ratio = 2**mu
    direction = "上调" if mu > 0 else "下调"
    i2_level = ("低" if I2_use < 0.25 else "中等" if I2_use < 0.50 else "较高" if I2_use < 0.75 else "很高")
    q_val = (q_lookup.get(gene) if isinstance(q_lookup, dict) else None)
    q_text = f"q={q_val:.3g}" if (q_val is not None and np.isfinite(q_val)) else f"p={p:.3g}"
    ci_text = f"95% CI {ci[0]:.2f}, {ci[1]:.2f}"

    # 严格逻辑打标签
    label, rationale = label_and_rationale(
        re_effect=mu, re_ci=ci, re_p=p, q=q_val,
        fe_effect=mu_fe, max_delta_loo=max_delta, i2=I2_use
    )

    desc = (
        f"将基因 {gene} 在各 experiment×batch 的 HO−WT log2FC 用随机效应模型合并，"
        f"得到总体效应 μ={mu:.2f}（{ci_text}，{q_text}），I²={I2_use*100:.0f}%。"
        f"该基因整体呈{direction}，幅度约 {fc_ratio:.2f}×（2^{mu:.2f}≈{fc_ratio:.2f}），"
        f"异质性{i2_level}；结论稳健（leave-one-out 最大变化 {max_delta:.2f} log2FC"
        f"{' < ' + str(DELTA_E_TH) if max_delta < DELTA_E_TH else ' ≥ ' + str(DELTA_E_TH)}）。\n"
        f"【严格判定】标签：{label}；判定过程：{rationale}"
    )

    fig.text(0.01, 0.02, desc, ha="left", va="bottom", fontsize=9, wrap=True)

    ax.grid(axis="x", alpha=0.2)
    plt.tight_layout(rect=[0, 0.16, 1, 0.92])   # 底部多留一点空间
    fig.savefig(outpath, dpi=300)
    plt.close(fig)

    return d.assign(gene=gene), {
        "mu":mu, "se":se, "p":p, "ci_low":ci[0], "ci_high":ci[1],
        "I2":I2_use, "tau2":tau2_use, "Q":Q, "q": q_val, "max_delta_loo": max_delta,
        "mu_fe": mu_fe
    }

# ------------ 运行：对一批基因出图并生成诊断表 ------------
def main(genes=None, model="RE"):
    unit = pd.read_csv(PER_UNIT)
    unit.columns = unit.columns.str.lower()

    q_lookup = {}
    meta_path = Path(META_SUM)
    if meta_path.exists():
        meta = pd.read_csv(meta_path)
        meta.columns = meta.columns.str.lower()
        if "gene" in meta.columns and "q" in meta.columns:
            q_lookup = dict(zip(meta["gene"], meta["q"]))

    if genes is None:
        genes = sorted(unit["gene"].unique())

    all_diag = []
    for g in genes:
        sub = unit[unit["gene"]==g].copy()
        if sub.empty or sub.shape[0] < 2:
            continue
        out = OUT_DIR / f"forest_{g}_{model}.png"
        diag, summary = forest_plot_for_gene(sub, g, out, model=model, q_lookup=q_lookup)
        for k, v in summary.items():
            diag[k] = v
        all_diag.append(diag)

    if all_diag:
        diag_df = pd.concat(all_diag, ignore_index=True)
        diag_csv = OUT_DIR / f"forest_diagnostics_{model}.csv"
        diag_df.to_csv(diag_csv, index=False)
        print(f"✅ 诊断表保存：{diag_csv}")
    print(f"✅ forest 图输出目录：{OUT_DIR}")

if __name__ == "__main__":
    main(model="RE")