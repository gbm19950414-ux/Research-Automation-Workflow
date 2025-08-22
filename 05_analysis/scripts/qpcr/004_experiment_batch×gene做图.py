#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按 gene 输出分面矩阵图（experiment × batch × gene）
- 每个 gene 一张图
- 图内按 experiment 做分面（small multiples）
- 分面中横轴=batch，WT/HO 并排箱线 + 散点
- 仅保留最少必要过滤：每组 n>=MIN_SAMPLES_PER_GROUP 且成对（WT & HO）
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from pathlib import Path

# ============== 用户可调参数 =========================
INPUT_CSV             = '/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/ddct_analysis.csv'
MIN_SAMPLES_PER_GROUP = 2
OUT_DIR = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/qpcr")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 图版式（大量 experiment 时可调）
COL_WRAP   = 4      # 每行最多放几个 experiment 分面
PLOT_H     = 2.8    # 每个分面的高度（inch）
PLOT_ASPECT= 1.2    # 每个分面的宽高比
Y_LIMIT    = None   # 例如设为 (-2, 2) 可统一 y 轴；None 表示自动
# ====================================================

# ---------- 0. 读取 & 预处理 ----------
df = pd.read_csv(INPUT_CSV)
df.columns = df.columns.str.strip().str.lower()

if "fold_change" not in df.columns:
    raise ValueError("❌ 输入文件缺少 'fold_change' 列。")

# 如存在 is_outlier，则先过滤离群
if "is_outlier" in df.columns:
    df = df[~df["is_outlier"].fillna(False)]

df = df[df["fold_change"] > 0].copy()
df["log2fc"] = np.log2(df["fold_change"])

def infer_group(sid: str) -> str:
    sid = str(sid).upper()
    if "WT" in sid: return "WT"
    if "HO" in sid or "KO" in sid: return "HO"
    return "Unknown"
df["group"] = df["sample_id"].apply(infer_group)
df = df[df["group"].isin(["WT", "HO"])]

# ---------- 1. 最少必要过滤 ----------
# 1) 组内样本数阈值：按 gene × experiment × batch × group
valid = (df.groupby(["gene", "experiment_id", "batch_id", "group"])
           .size().reset_index(name="n")
           .query("n >= @MIN_SAMPLES_PER_GROUP"))
df = df.merge(valid[["gene", "experiment_id", "batch_id", "group"]],
              on=["gene","experiment_id","batch_id","group"])

# 2) 要求同一 gene × experiment × batch 内 WT/HO 成对存在
pair = (df.groupby(["gene", "experiment_id", "batch_id"])["group"]
          .nunique().reset_index()
          .query("group >= 2"))
df = df.merge(pair[["gene", "experiment_id", "batch_id"]],
              on=["gene","experiment_id","batch_id"])

# 统一顺序（x 轴批次全局一致；分面只放当前基因出现过的 experiment）
batches_all = sorted(df["batch_id"].dropna().unique())
sns.set(style="whitegrid")

# ---------- 2. 每个基因：experiment 分面 × batch 横轴 ----------
for gene in sorted(df["gene"].dropna().unique()):
    sub = df[df["gene"] == gene].copy()
    if sub.empty:
        continue

    # 该基因出现过的 experiment 顺序
    exp_order = sorted(sub["experiment_id"].dropna().unique())

    g = sns.catplot(
        data=sub,
        x="batch_id", y="log2fc", hue="group",
        col="experiment_id", col_order=exp_order, col_wrap=COL_WRAP,
        order=batches_all, hue_order=["WT","HO"],
        kind="box", dodge=True, showfliers=False,
        height=PLOT_H, aspect=PLOT_ASPECT, sharey=True, palette={"WT":"#66c2a5","HO":"#fc8d62"}
    )

    # 叠加散点（抖动）
    # stripplot 需要逐轴绘制，避免重复图例
    for ax, exp in zip(g.axes.flat, exp_order):
        ax_data = sub[sub["experiment_id"] == exp]
        if ax_data.empty: 
            continue
        sns.stripplot(
            data=ax_data,
            x="batch_id", y="log2fc", hue="group",
            order=batches_all, hue_order=["WT","HO"],
            dodge=True, alpha=0.6, size=3, ax=ax, legend=False
        )
        ax.set_xlabel("Batch")
        if Y_LIMIT is not None:
            ax.set_ylim(*Y_LIMIT)
        ax.tick_params(axis='x', rotation=45)

    g.set_ylabels(r"$\log_2(\mathrm{Fold\ Change})$")
    g.set_titles(col_template="exp = {col_name}")
    g.fig.suptitle(f"{gene}", x=0.02, y=1.03, ha="left", fontsize=14, fontweight="bold")
    g.fig.tight_layout()

    out_path = OUT_DIR / f"{gene}_experiment×batch_matrix.png"
    g.savefig(out_path, dpi=300)
    plt.close(g.fig)
    print(f"✅ Saved: {out_path}") 
