#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
绘制 qPCR 各基因箱线图 + 显著性括号（单位：experiment_id-batch_id；横轴：gene）
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.stats import ttest_ind
from pathlib import Path
import random

# ============== 用户可调参数 =========================
INPUT_CSV             = '/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/ddct_analysis.csv'
MIN_SAMPLES_PER_GROUP = 2                                        # 每组最少样本数
OUT_DIR = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/qpcr/experiment&batch_group")
OUT_DIR.mkdir(parents=True, exist_ok=True)
# ====================================================

# ---------- 0. 读取 & 预处理 ----------
df = pd.read_csv(INPUT_CSV)
df.columns = df.columns.str.strip().str.lower()
if "fold_change" not in df.columns:
    raise ValueError("❌ 输入文件缺少 'fold_change' 列。")

df = df[df["fold_change"] > 0].copy()
df["log2fc"] = np.log2(df["fold_change"])

def infer_group(sid: str) -> str:
    sid = str(sid).upper()
    if "WT" in sid: return "WT"
    if "HO" in sid: return "HO"
    return "Unknown"
df["group"] = df["sample_id"].apply(infer_group)

# 新增：组合 experiment_id-batch_id 作为绘图单位
if "experiment_id" not in df.columns or "batch_id" not in df.columns:
    raise ValueError("❌ 数据缺少 experiment_id 或 batch_id 列。")
df["exp_batch"] = df["experiment_id"].astype(str) + "-" + df["batch_id"].astype(str)

# ---------- 1. 基础过滤（按 gene / exp_batch / group） ----------
valid = (df.groupby(["gene", "exp_batch", "group"])
           .size().reset_index(name="n")
           .query("n >= @MIN_SAMPLES_PER_GROUP"))
df = df.merge(valid[["gene", "exp_batch", "group"]])

valid_pair = (df.groupby(["gene", "exp_batch"])["group"]
                .nunique().reset_index()
                .query("group >= 2"))
df = df.merge(valid_pair[["gene", "exp_batch"]])

# ---------- 2. 绘图风格 ----------
sns.set(style="whitegrid")
random.seed(0); np.random.seed(0)
hue_order = ["WT", "HO"]
colors    = {"WT": "#66c2a5", "HO": "#fc8d62"}
delta     = 0.20                # WT / HO 相对类别中心的水平偏移
jitter_max = 0.12               # 散点水平抖动

# 横轴全局基因顺序（保证各图一致）
genes_all = sorted(df["gene"].unique())

# ---------- 3. 按 exp_batch 单独出图，横轴为 gene ----------
for exp_batch in sorted(df["exp_batch"].unique()):
    data = df[df["exp_batch"] == exp_batch].copy()
    if data.empty:
        continue

    fig, ax = plt.subplots(figsize=(max(8, 0.5*len(genes_all) + 4), 4))

    # 3.1 箱线图
    sns.boxplot(
        x="gene", y="log2fc", hue="group",
        data=data, ax=ax,
        palette=colors, width=0.6, showfliers=False,
        dodge=True, order=genes_all, hue_order=hue_order
    )

    # 3.2 散点 (jitter)
    for idx, gene_name in enumerate(genes_all):
        for grp, sign in zip(hue_order, (-1, +1)):      # WT 左，HO 右
            pts = data.query("gene == @gene_name and group == @grp")["log2fc"]
            if len(pts) == 0:
                continue
            x_center = idx + sign * delta
            jitter   = (np.random.rand(len(pts)) - 0.5) * 2 * jitter_max
            ax.scatter(x_center + jitter, pts,
                       color="k", alpha=0.6, s=28, zorder=3)

    # 3.3 显著性比较 (只比 WT vs HO)
    if data["log2fc"].notna().any():
        full_range = (data["log2fc"].max() - data["log2fc"].min())
    else:
        full_range = 0.0
    offset_frac = 0.05                  # 括号离箱顶的相对偏移
    for idx, gene_name in enumerate(genes_all):
        wt = data.query("gene == @gene_name and group == 'WT'")["log2fc"]
        ho = data.query("gene == @gene_name and group == 'HO'")["log2fc"]

        if len(wt) < MIN_SAMPLES_PER_GROUP or len(ho) < MIN_SAMPLES_PER_GROUP:
            continue

        # Welch t-test（稳妥取 p 值并转换为星号）
        res = ttest_ind(wt, ho, equal_var=False, nan_policy="omit")
        p = float(res.pvalue)
        sig = ("ns", "*", "**", "***", "****")[ int(p < 0.05) + int(p < 0.01) + int(p < 0.001) + int(p < 0.0001) ] if not np.isnan(p) else "ns"

        x1, x2 = idx - delta, idx + delta
        group_max = np.nanmax([wt.max() if len(wt)>0 else np.nan,
                               ho.max() if len(ho)>0 else np.nan])
        v_offset  = (full_range if full_range > 0 else 1.0) * offset_frac + 0.05
        y_bracket = group_max + v_offset

        ax.plot([x1, x1, x2, x2],
                [y_bracket, y_bracket + v_offset*0.4,
                 y_bracket + v_offset*0.4, y_bracket],
                lw=1.3, c='k')
        ax.text((x1 + x2) / 2, y_bracket + v_offset*0.45, sig,
                ha='center', va='bottom', fontsize=10)

    # 3.4 轴 & 标题
    ax.set_title(exp_batch, loc="left", fontsize=14, fontweight="bold", pad=10)
    ax.set_ylabel(r"$\log_2(\mathrm{Fold\ Change})$")
    ax.set_xlabel("Gene")
    ax.set_xticks(range(len(genes_all)))
    ax.set_xticklabels(genes_all, rotation=45, ha='right')
    ax.set_xlim(-0.5, len(genes_all) - 0.5)
    if ax.get_legend(): ax.get_legend().remove()

    # 3.5 保存
    safe_name = str(exp_batch).replace("/", "-").replace(" ", "_")
    out_path = OUT_DIR / f"{safe_name}_boxplot.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"✅ Saved: {out_path}")