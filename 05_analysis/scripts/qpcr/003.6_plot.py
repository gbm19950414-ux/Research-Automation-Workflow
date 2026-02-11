#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
3.6_plot.py
从指定文件夹读取所有 *_stats.xlsx（qPCR ddCT 统计文件），
对每个基因画：treatment 为 x，WT/HO 为 hue 的箱线图 + 散点，并标注显著性（来自 pair_stats.p_value）。
输出到 04_data/processed/qpcr

用法：
  python 3.6_plot.py 04_data/interim/qpcr/ddct_analysis_001a+003a_split
"""

import sys
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# seaborn 可选但建议装（更好看）
try:
    import seaborn as sns
    HAS_SNS = True
except Exception:
    HAS_SNS = False


# ----------------- 可调参数 -----------------
OUT_DIR = Path("04_data/processed/qpcr")
DPI = 300

Y_SCALE = "linear"   # "linear" 画 fold_change；如想画 log2，可改成 "log2"
SHOW_NS = True       # p>=0.05 是否也标注 "ns"
POINT_SIZE = 4
POINT_ALPHA = 0.75
# -------------------------------------------


def p_to_star(p):
    """把 p 值转成显著性星号"""
    if pd.isna(p):
        return "NA"
    try:
        p = float(p)
    except Exception:
        return "NA"
    if p < 0.0001:
        return "****"
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def sanitize_filename(s):
    s = str(s)
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s


def read_stats_xlsx(xlsx_path):
    """读取 stats xlsx 的 data / pair_stats / meta 三个表"""
    data = pd.read_excel(xlsx_path, sheet_name="data")
    pair = pd.read_excel(xlsx_path, sheet_name="pair_stats")
    try:
        meta = pd.read_excel(xlsx_path, sheet_name="meta")
    except Exception:
        meta = None
    # 统一列名
    data.columns = [str(c).strip().lower() for c in data.columns]
    pair.columns = [str(c).strip().lower() for c in pair.columns]
    if meta is not None:
        meta.columns = [str(c).strip().lower() for c in meta.columns]
    return data, pair, meta


def prepare_plot_data(data_df):
    """从 data sheet 提取样本级 fold_change，并做必要过滤"""
    required = ["sample_id", "genetype", "treatment", "fold_change"]
    for c in required:
        if c not in data_df.columns:
            raise ValueError("data sheet 缺少必要列: {}".format(c))

    df = data_df.copy()

    # 去掉汇总行（sample_id == '-'）
    df["sample_id"] = df["sample_id"].astype(str)
    df = df[df["sample_id"] != "-"].copy()

    # 过滤离群（如果存在）
    if "is_outlier" in df.columns:
        df["is_outlier"] = df["is_outlier"].fillna(0)
        df = df[df["is_outlier"] != 1].copy()

    # fold_change 必须是数且 > 0
    df["fold_change"] = pd.to_numeric(df["fold_change"], errors="coerce")
    df = df.dropna(subset=["fold_change"]).copy()
    df = df[df["fold_change"] > 0].copy()

    # 只保留 WT/HO
    df["genetype"] = df["genetype"].astype(str).str.upper().str.strip()
    df = df[df["genetype"].isin(["WT", "HO"])].copy()

    # 处理 y
    if Y_SCALE == "log2":
        df["y"] = np.log2(df["fold_change"])
        y_label = r"$\log_2(\mathrm{Fold\ Change})$"
    else:
        df["y"] = df["fold_change"]
        y_label = "Fold Change"

    # treatment 排序：保持原始出现顺序（更贴近你的实验）
    # 如果你想固定顺序，可在这里改成自定义列表
    treat_order = list(pd.unique(df["treatment"].astype(str)))

    return df, treat_order, y_label


def get_context_title(data_df, xlsx_path):
    """从 data 表中拿 gene / experiment_id / batch_id 作为标题信息（尽量稳）"""
    cols = [c.lower() for c in data_df.columns]
    gene = None
    exp = None
    batch = None
    if "gene" in cols:
        gene_vals = data_df["gene"].dropna().astype(str)
        gene = gene_vals.iloc[0] if len(gene_vals) else None
    if "experiment_id" in cols:
        exp_vals = data_df["experiment_id"].dropna().astype(str)
        exp = exp_vals.iloc[0] if len(exp_vals) else None
    if "batch_id" in cols:
        batch_vals = data_df["batch_id"].dropna().astype(str)
        batch = batch_vals.iloc[0] if len(batch_vals) else None

    # 兜底：从文件名猜 gene
    if not gene:
        stem = xlsx_path.stem
        # ..._Acaca_stats -> Acaca
        m = re.search(r"_([^_]+)_stats$", stem)
        gene = m.group(1) if m else stem

    parts = [gene]
    if exp:
        parts.append(str(exp))
    if batch:
        parts.append("batch {}".format(batch))
    title = " | ".join(parts)
    return title, gene, exp, batch


def annotate_pvalues(ax, df, pair_df, treat_order):
    """
    在每个 treatment 上方画 WT vs HO 的括号 + 星号
    p 值来自 pair_stats（按 treatment）
    """
    if "treatment" not in pair_df.columns or "p_value" not in pair_df.columns:
        return

    # pair_stats 可能含一行 treatment='-' 的空行，过滤掉
    pair = pair_df.copy()
    pair["treatment"] = pair["treatment"].astype(str)
    pair = pair[pair["treatment"] != "-"].copy()

    # 构建映射：treatment -> p_value
    p_map = {}
    for _, r in pair.iterrows():
        t = str(r.get("treatment"))
        p_map[t] = r.get("p_value")

    # 计算每个 treatment 的最高点，用于放括号
    y_max_by_t = df.groupby("treatment")["y"].max().to_dict()
    y_min = float(df["y"].min()) if len(df) else 0.0
    y_rng = float(df["y"].max() - df["y"].min()) if len(df) else 1.0
    if y_rng <= 0:
        y_rng = 1.0

    # x 坐标：treat_order 中的 index
    # 这里用近似的 WT/HO 偏移（适用于两组并排）
    wt_off = -0.20
    ho_off = +0.20

    for i, t in enumerate(treat_order):
        if t not in y_max_by_t:
            continue
        p = p_map.get(str(t), np.nan)
        star = p_to_star(p)
        if (star == "ns") and (not SHOW_NS):
            continue

        y0 = y_max_by_t[t]
        # 括号高度/间距
        h = 0.06 * y_rng
        pad = 0.08 * y_rng
        y = y0 + pad

        x1 = i + wt_off
        x2 = i + ho_off

        # 画括号
        ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=1.2, c="black")

        # 写星号（可把 p 值也写上：star + "\n" + "p=..."
        label = star
        ax.text((x1 + x2) / 2.0, y + h + 0.02 * y_rng, label,
                ha="center", va="bottom", fontsize=11, color="black")


def plot_one(xlsx_path):
    data, pair, meta = read_stats_xlsx(xlsx_path)
    df, treat_order, y_label = prepare_plot_data(data)

    if df.empty:
        print("⚠️ Skip (no valid rows after filtering): {}".format(xlsx_path))
        return None

    title, gene, exp, batch = get_context_title(data, xlsx_path)

    # 画布
    n_treat = max(1, len(treat_order))
    fig_w = max(5.2, 1.2 * n_treat)
    fig_h = 4.2
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    if HAS_SNS:
        sns.set(style="whitegrid")
        # 箱线
        sns.boxplot(
            data=df, x="treatment", y="y", hue="genetype",
            order=treat_order, hue_order=["WT", "HO"],
            showfliers=False, width=0.6, ax=ax
        )
        # 散点
        sns.stripplot(
            data=df, x="treatment", y="y", hue="genetype",
            order=treat_order, hue_order=["WT", "HO"],
            dodge=True, jitter=0.18,
            size=POINT_SIZE, alpha=POINT_ALPHA,
            ax=ax
        )
        # 只保留一个图例（stripplot 会重复）
        handles, labels = ax.get_legend_handles_labels()
        # 期望 labels 里会重复 WT/HO 两轮，取前两项
        if len(handles) >= 2:
            ax.legend(handles[:2], labels[:2], title="Genotype", frameon=True)
    else:
        # 没 seaborn 就用 matplotlib 简易版：只画散点 + 中位数线（不推荐，但可用）
        # x: treatment index, hue: WT/HO offset
        ax.grid(True, axis="y", alpha=0.3)
        offsets = {"WT": -0.2, "HO": 0.2}
        for i, t in enumerate(treat_order):
            sub = df[df["treatment"].astype(str) == str(t)]
            for g in ["WT", "HO"]:
                s = sub[sub["genetype"] == g]["y"].values
                if len(s) == 0:
                    continue
                x = np.random.normal(i + offsets[g], 0.03, size=len(s))
                ax.scatter(x, s, s=18, alpha=POINT_ALPHA, label=g)
                # 中位数线
                med = np.median(s)
                ax.plot([i + offsets[g] - 0.08, i + offsets[g] + 0.08], [med, med], lw=2)
        # 去重图例
        handles, labels = ax.get_legend_handles_labels()
        uniq = {}
        for h, l in zip(handles, labels):
            if l not in uniq:
                uniq[l] = h
        ax.legend(list(uniq.values()), list(uniq.keys()), title="Genotype", frameon=True)
        ax.set_xticks(range(len(treat_order)))
        ax.set_xticklabels(treat_order, rotation=30, ha="right")

    # 标注显著性（来自 pair_stats）
    annotate_pvalues(ax, df, pair, treat_order)

    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel("Treatment")
    ax.set_ylabel(y_label)
    ax.tick_params(axis="x", rotation=30)

    fig.tight_layout()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    batch_tag = "NA" if (batch is None or str(batch).strip() == "") else str(batch).strip()
    exp_tag = "NA" if (exp is None or str(exp).strip() == "") else str(exp).strip()

    # 文件名加入 batch（必要）以及 experiment（可选）以避免不同批次/实验覆盖
    out_name = sanitize_filename("{}__{}__{}_boxplot.png".format(gene, batch_tag, exp_tag))
    out_path = OUT_DIR / out_name
    fig.savefig(str(out_path), dpi=DPI)
    plt.close(fig)

    print("✅ Saved:", out_path)
    return {
        "gene": str(gene),
        "batch": batch_tag,
        "experiment": exp_tag,
        "image_path": str(out_path),
    }


# 拼图函数
def make_montage(records, out_dir):
    """把所有已生成的单基因图像拼成一张（或多张）大图。

    逻辑：按 experiment 分开输出；每张大图的列=batch，行=gene。
    （注意：单图里已同时包含 WT/HO 两组，因此此拼图是“汇总展示全部图像”。）
    """
    if not records:
        return

    # 过滤掉 None
    records = [r for r in records if r]
    if not records:
        return

    # 按 experiment 分组
    exp_groups = {}
    for r in records:
        exp = r.get("experiment", "NA")
        exp_groups.setdefault(exp, []).append(r)

    for exp_tag, recs in exp_groups.items():
        genes = sorted({r["gene"] for r in recs})
        batches = sorted({r["batch"] for r in recs})

        if not genes or not batches:
            continue

        # gene x batch -> image_path
        grid = {}
        for r in recs:
            key = (r["gene"], r["batch"])
            # 若同一个 (gene,batch) 出现多次（极少见），保留第一次并打印提示
            if key not in grid:
                grid[key] = r["image_path"]

        n_rows = len(genes)
        n_cols = len(batches)

        # 画布尺寸：每个小图约 3.2 x 2.6 inch
        fig_w = max(6.0, 3.2 * n_cols)
        fig_h = max(4.5, 2.6 * n_rows)

        fig, axes = plt.subplots(n_rows, n_cols, figsize=(fig_w, fig_h))

        # axes 兼容 n_rows/n_cols 为 1 的情况
        if n_rows == 1 and n_cols == 1:
            axes = np.array([[axes]])
        elif n_rows == 1:
            axes = np.array([axes])
        elif n_cols == 1:
            axes = np.array([[ax] for ax in axes])

        for i, g in enumerate(genes):
            for j, b in enumerate(batches):
                ax = axes[i, j]
                ax.axis("off")
                p = grid.get((g, b))
                if p and Path(p).exists():
                    try:
                        img = plt.imread(p)
                        ax.imshow(img)
                    except Exception:
                        # 读图失败就留空
                        pass

                # 第一行：标 batch
                if i == 0:
                    ax.set_title(str(b), fontsize=10)
                # 第一列：标 gene
                if j == 0:
                    ax.text(-0.02, 0.5, str(g), transform=ax.transAxes,
                            ha="right", va="center", rotation=90, fontsize=10)

        fig.suptitle("All genes montage | experiment={}".format(exp_tag), fontsize=14, fontweight="bold")
        fig.tight_layout(rect=[0, 0.02, 1, 0.95])

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = sanitize_filename("ALL_GENES__{}__montage.png".format(exp_tag))
        out_path = out_dir / out_name
        fig.savefig(str(out_path), dpi=DPI)
        plt.close(fig)

        print("🧩 Montage saved:", out_path)


def main():
    if len(sys.argv) < 2:
        print("用法：python 3.6_plot.py <stats_folder>")
        sys.exit(1)

    folder = Path(sys.argv[1]).expanduser().resolve()
    if not folder.exists():
        print("❌ Folder not found:", folder)
        sys.exit(1)

    files = sorted(folder.glob("*_stats.xlsx"))
    if not files:
        print("❌ No *_stats.xlsx found in:", folder)
        sys.exit(1)

    print("Found {} stats files.".format(len(files)))
    records = []
    for f in files:
        try:
            rec = plot_one(f)
            if rec:
                records.append(rec)
        except Exception as e:
            print("❌ Failed:", f)
            print("   Error:", e)

    # 额外输出一张（或多张）大拼图：列=batch，行=gene；按 experiment 分开
    make_montage(records, OUT_DIR)


if __name__ == "__main__":
    main()