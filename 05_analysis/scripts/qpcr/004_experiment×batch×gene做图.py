#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按 experiment × batch × gene 单独出图
- 每个组合单独一张 PNG
- 图内横轴=group (WT vs HO)，纵轴=log2FC
- 自动加显著性标注 (t-test)
"""

import warnings
warnings.filterwarnings("ignore")
import sys
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from pathlib import Path
from statannotations.Annotator import Annotator
import matplotlib as mpl

# —— Nature 单图规范：字体/字号/线宽/可编辑文字（TrueType）——
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "pdf.fonttype": 42,            # TrueType，AI 中可编辑；避免 Type 3
    "ps.fonttype": 42,
    "mathtext.fontset": "dejavusans",  # 数学文本无衬线，风格一致
    "text.usetex": False,          # 避免因 LaTeX 导致文字转曲或缺字
    # 字号：标题≈面板字母 8 pt；轴标签 7 pt；刻度 6 pt；图例 6 pt
    "axes.titlesize": 8,
    "axes.labelsize": 7,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,
    # 线宽：保持 0.8–1.0 pt 区间（最终尺寸可见）
    "axes.linewidth": 0.8,
    "lines.linewidth": 1.0,
})

# seaborn 风格但不覆盖上面的 rc（如需更细可在 sns.set 里传 rc=...）
# ============== 用户可调参数 =========================

if len(sys.argv) < 2:
    sys.exit("❌ 请指定输入文件路径：python draw_ddct.py <ddct_analysis.csv>")
INPUT_CSV = Path(sys.argv[1])
MIN_SAMPLES_PER_GROUP = 2
OUT_DIR = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/qpcr")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 统一 y 轴范围；常用 (-2, 2)≈0.25×~4×；如需更宽可改 (-3, 3)。设为 None 表示自动。
Y_LIMIT = (-2, 2)   # 或 None

# 标题与显著性标注的间距（点数越大，标题越高）
TITLE_PAD = 14

# 给显著性标注预留的顶部空间（单位：log2FC）
TOP_HEAD = 0.18
# ====================================================

# ---------- 0. 读取 & 预处理 ----------
df = pd.read_csv(INPUT_CSV)
df.columns = df.columns.str.strip().str.lower()

if "fold_change" not in df.columns:
    raise ValueError("❌ 输入文件缺少 'fold_change' 列。")

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
valid = (df.groupby(["gene", "experiment_id", "batch_id", "group"])
           .size().reset_index(name="n")
           .query("n >= @MIN_SAMPLES_PER_GROUP"))
df = df.merge(valid[["gene", "experiment_id", "batch_id", "group"]],
              on=["gene","experiment_id","batch_id","group"])

pair = (df.groupby(["gene", "experiment_id", "batch_id"])["group"]
          .nunique().reset_index()
          .query("group >= 2"))
df = df.merge(pair[["gene", "experiment_id", "batch_id"]],
              on=["gene","experiment_id","batch_id"])

sns.set(style="whitegrid", rc={"grid.linewidth": 0.6})

# ---------- 2. 每个 gene × experiment × batch 单独出图 ----------
for gene in sorted(df["gene"].unique()):
    for exp_id in sorted(df.loc[df["gene"]==gene, "experiment_id"].unique()):
        for batch_id in sorted(df.loc[(df["gene"]==gene)&(df["experiment_id"]==exp_id), "batch_id"].unique()):
            sub = df.query("gene == @gene and experiment_id == @exp_id and batch_id == @batch_id")
            if sub.empty: 
                continue

            FIG_W = 3.54  # 90 mm 单栏宽（Nature 常用）
            fig, ax = plt.subplots(figsize=(FIG_W, 4))
            
            sns.boxplot(
                data=sub,
                x="group", y="log2fc",
                order=["WT","HO"], palette={"WT":"#66c2a5","HO":"#fc8d62"},
                width=0.6, showfliers=False, ax=ax,
                linewidth=1.0
            )
            sns.stripplot(
                data=sub,
                x="group", y="log2fc",
                order=["WT","HO"], color="k", size=3, alpha=0.6,
                ax=ax, jitter=True, dodge=False
            )

            # -------- 显著性标注 --------
            pairs = [("WT","HO")]
            annotator = Annotator(ax, pairs, data=sub, x="group", y="log2fc", order=["WT","HO"])
            annotator.configure(test='t-test_ind', text_format='star', loc='outside', verbose=0)
            annotator.apply_and_annotate()

            # 标题和坐标轴设置
            ax.set_title(f"{gene} | exp={exp_id} | batch={batch_id}", fontsize=8, pad=TITLE_PAD)
            ax.set_ylabel(r"$\log_2(\mathrm{Fold\ Change})$")
            ax.set_xlabel("")

            # —— 统一 y 轴，并在顶部为显著性标注留出空间 ——
            if Y_LIMIT is not None:
                # 固定范围，再额外加一点顶部余量给星标
                ax.set_ylim(Y_LIMIT[0], Y_LIMIT[1] + TOP_HEAD)
            else:
                # 自动范围：根据当前数据留出头部空间
                ymin = float(sub["log2fc"].min())
                ymax = float(sub["log2fc"].max())
                head = max(TOP_HEAD, 0.10 * (ymax - ymin))  # 至少 TOP_HEAD，或相对 10%
                ax.set_ylim(ymin - 0.05, ymax + head)

            out_path = OUT_DIR / f"{gene}_exp{exp_id}_batch{batch_id}.pdf"
            plt.tight_layout()
            plt.savefig(out_path, bbox_inches="tight")  # PDF 矢量不需要 dpi
            plt.close(fig)
            print(f"✅ Saved: {out_path}")
            