#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
004_plot_time_series.py

功能：
- 读取一个或多个 Excel 源文件；
  * 若包含统计列（WT_mean, WT_sd, HO_mean, HO_sd），直接作图；
  * 否则假定包含 raw 列（gene, time_point, value），先计算 WT/HO 在各 time_point 的 mean/sd，再作图。
- 横轴：time_point；纵轴：mean（误差棒为 SD），点线图（WT 与 HO 各一条）。
- 每个输入文件单独生成 PNG 和 PDF。

用法：
  python3 004_plot_time_series.py file1.xlsx file2.xlsx ...

固定输出目录：
  /Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/microplate_reader/线粒体完整性检测
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yaml, math

# 用你的绝对路径（注意：整段替换你现在的 _STYLE_PATH/_CFG/_PS/_STAT 代码）
import yaml
from pathlib import Path

STYLE_PATH = Path("/Users/gongbaoming/Library/Mobile Documents/com~apple~CloudDocs/phd_thesis/方法/nature_bio_figure_requirements.yaml")

if not STYLE_PATH.exists():
    raise FileNotFoundError(f"找不到样式文件：{STYLE_PATH}")

_CFG  = yaml.safe_load(STYLE_PATH.read_text(encoding="utf-8")).get("Nature_Figure_Requirements", {})
_PS   = _CFG.get("plot_style", {})
_STAT = _CFG.get("statistics", {})

def _mm_to_in(mm):
    return float(mm) / 25.4 if mm is not None else None
# 固定列名（用于原始数据路径）
TIME_COL  = "time_point"
VALUE_COL = "value"
GENE_COL  = "gene"

# 固定输出目录
OUTPUT_DIR = Path(
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/"
    "博士课题/EphB1/04_data/processed/microplate_reader/线粒体完整性检测"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# 全局 rcParams（字体/字号/线宽 等）
plt.rcParams.update({
    "font.family": _PS.get("font", {}).get("family", "Arial"),
    "axes.labelsize": _PS.get("font", {}).get("axis_pt", 7),
    "xtick.labelsize": _PS.get("font", {}).get("tick_pt", 6),
    "ytick.labelsize": _PS.get("font", {}).get("tick_pt", 6),
    "legend.fontsize": _PS.get("font", {}).get("legend_pt", 6),
    "axes.linewidth": _PS.get("axes", {}).get("axis_w", 0.8),
    "lines.linewidth": _PS.get("lines", {}).get("lw", 1.0),
    "pdf.fonttype": 42,   # Illustrator 可编辑文字
    "ps.fonttype": 42,
})

# —— 工具函数：自适应尺寸 & 横坐标标签管理 ——
def _figure_size_inches(n_xlabels: int):
    size = _PS.get("size", {})
    width_mm  = size.get("width_mm", 89)
    height_mm = size.get("height_mm")  # None/Null → 用比例
    wr, hr = map(int, str(size.get("aspect_ratio", "4:3")).split(":"))
    if height_mm is None:
        height_mm = width_mm * hr / wr

    # 自适应加宽
    dyn = _PS.get("dynamic", {}).get("size_adaptive", {})
    if dyn.get("enable", True):
        th = dyn.get("threshold_labels", 10)
        if n_xlabels > th:
            extra = (n_xlabels - th) * dyn.get("mm_per_extra_label", 3)
            width_mm = min(width_mm + extra, size.get("max_width_mm", 183))
            if size.get("height_mm") is None:
                height_mm = width_mm * hr / wr

    return (_mm_to_in(width_mm), _mm_to_in(height_mm))

def _manage_xticks(ax):
    xt = _PS.get("dynamic", {}).get("x_ticks", {})
    labels = ax.get_xticklabels()
    N = len(labels)
    max_labels = xt.get("max_labels", 10)
    step = math.ceil(N / max_labels) if xt.get("step_auto", True) else max(1, int(xt.get("step", 1)))
    for i, lab in enumerate(labels):
        lab.set_visible(i % step == 0)

    rot = xt.get("rotate_deg", 0)
    if rot:
        for lab in ax.get_xticklabels():
            lab.set_rotation(rot)
            lab.set_horizontalalignment("right")

    wrap = xt.get("wrap_chars")  # None 表示不换行
    if wrap:
        new_texts = []
        for lab in ax.get_xticklabels():
            s = lab.get_text()
            new_texts.append("\n".join([s[i:i+wrap] for i in range(0, len(s), wrap)]))
        ax.set_xticklabels(new_texts)

def _has_stats_columns(df: pd.DataFrame) -> bool:
    need = {"WT_mean", "WT_sd", "HO_mean", "HO_sd", TIME_COL}
    return need.issubset(set(df.columns))


def _label_group_from_gene(df: pd.DataFrame) -> pd.Series:
    if GENE_COL not in df.columns:
        raise KeyError(f"缺少列: {GENE_COL}")
    s = df[GENE_COL].astype(str).str.lower()
    out = []
    for v in s:
        if "wt" in v:
            out.append("WT")
        elif "ho" in v:
            out.append("HO")
        else:
            out.append(None)
    return pd.Series(out, index=df.index, name="group")


def _compute_stats_from_raw(df: pd.DataFrame) -> pd.DataFrame:
    """从原始表（含 gene/time_point/value）计算到 stats 结构"""
    for col in [TIME_COL, VALUE_COL, GENE_COL]:
        if col not in df.columns:
            raise KeyError(f"缺少列: {col}")

    df = df.copy()
    df["group"] = _label_group_from_gene(df)
    df = df[df["group"].isin(["WT", "HO"])]
    if df.empty:
        raise ValueError("未筛到 WT/HO 数据，请检查 gene 列是否包含 wt/ho 关键字。")

    # 按 time_point 与 group 计算 mean/sd/n（样本 SD：ddof=1）
    agg = df.groupby(["group", TIME_COL])[VALUE_COL].agg(
        mean=lambda x: float(np.nanmean(pd.to_numeric(x, errors="coerce"))),
        sd=lambda x: float(np.nanstd(pd.to_numeric(x, errors="coerce"), ddof=1)) if x.notna().sum() > 1 else np.nan,
        n=lambda x: int(pd.to_numeric(x, errors="coerce").notna().sum())
    ).reset_index()

    # 透视为列：WT_mean, WT_sd, WT_n, HO_mean, HO_sd, HO_n
    mean_p = agg.pivot(index=TIME_COL, columns="group", values="mean")
    sd_p   = agg.pivot(index=TIME_COL, columns="group", values="sd")
    n_p    = agg.pivot(index=TIME_COL, columns="group", values="n")

    stats = pd.DataFrame({
        TIME_COL: mean_p.index,
        "WT_mean": mean_p.get("WT"),
        "HO_mean": mean_p.get("HO"),
        "WT_sd":   sd_p.get("WT"),
        "HO_sd":   sd_p.get("HO"),
        "WT_n":    n_p.get("WT"),
        "HO_n":    n_p.get("HO"),
    })

    # 排序 time_point（尽量按数值排序）
    stats["_t"] = pd.to_numeric(stats[TIME_COL], errors="coerce")
    stats = stats.sort_values(["_t", TIME_COL], kind="mergesort").drop(columns=["_t"]).reset_index(drop=True)
    return stats


def _plot_one(stats_df: pd.DataFrame, title: str, out_png: Path, out_pdf: Path):
    # 统一数据类型并排序
    def _p_to_star(p: float) -> str:
        if p is None or (isinstance(p, float) and (np.isnan(p) or np.isinf(p))):
            return "ns"
        return "**" if p < 0.01 else ("*" if p < 0.05 else "ns")
    df = stats_df.copy()
    df["_t"] = pd.to_numeric(df[TIME_COL], errors="coerce")
    df = df.sort_values(["_t", TIME_COL], kind="mergesort")

    x = df[TIME_COL].values
    wt_y = df["WT_mean"].values
    wt_e = df["WT_sd"].values
    ho_y = df["HO_mean"].values
    ho_e = df["HO_sd"].values

    fig_w, fig_h = _figure_size_inches(n_xlabels=len(x))
    plt.figure(figsize=(fig_w, fig_h))
    # 误差棒点线图（不设颜色，使用默认色）
    palette = {"WT": _PS.get("palette", {}).get("wt", "#1f77b4"),
            "HO": _PS.get("palette", {}).get("ho", "#ff7f0e")}
    capsz = _PS.get("errorbar", {}).get("capsize", 2.0)
    lw    = _PS.get("lines", {}).get("lw", 1.0)
    ms    = _PS.get("lines", {}).get("ms", 3.0)
    plt.errorbar(x, wt_y, yerr=wt_e, fmt='o-', capsize=capsz, label="WT",
                color=palette["WT"], linewidth=lw, markersize=ms)
    plt.errorbar(x, ho_y, yerr=ho_e, fmt='s--', capsize=capsz, label="HO",
                color=palette["HO"], linewidth=lw, markersize=ms)
    # —— 显著性标记（仅当 stats_df 有 p_value 列时）——
    if "p_value" in df.columns:
        # 为了不遮挡，给上方多留一点空间
        cur_ylim = plt.ylim()
        ymin = np.nanmin([wt_y, ho_y])
        ymax = np.nanmax([wt_y, ho_y])
        pad = 0.05 * (ymax - ymin if np.isfinite(ymax - ymin) and (ymax - ymin) > 0 else 1.0)
        plt.ylim(cur_ylim[0], max(cur_ylim[1], ymax + 2 * pad))

        # 每个 time_point 的 y 位置：两组均值的更高者再加一点 padding
        # df 已经按 time 排序，和 x、wt_y、ho_y 对齐
        pvals = df["p_value"].values
        for xi, w, h, p in zip(x, wt_y, ho_y, pvals):
            star = _p_to_star(p)
            if star == "ns":
                continue  # 不标记不显著
            y = np.nanmax([w, h]) + pad
            plt.text(xi, y, star, ha="center", va="bottom")
    plt.title(title)
    plt.xlabel(TIME_COL)
    plt.ylabel(f"{VALUE_COL} (mean ± SD)")
    plt.grid(True, alpha=0.3)
    ax = plt.gca()
    # 去上/右脊
    if not _PS.get("axes", {}).get("spine_top", False):
        ax.spines["top"].set_visible(False)
    if not _PS.get("axes", {}).get("spine_right", False):
        ax.spines["right"].set_visible(False)
    # 刻度样式
    ax.tick_params(direction=_PS.get("axes", {}).get("tick_dir", "out"),
                length=_PS.get("axes", {}).get("tick_len", 2),
                width=_PS.get("axes", {}).get("tick_w", 0.6))
    # 横坐标很多时自动降采样/旋转/换行
    _manage_xticks(ax)
    plt.legend()
    # —— 显著性标注（若有 p_value 且允许标注）——
    if _STAT.get("annotate_on_plot", True) and ("p_value" in df.columns):
        thresholds = [(s["p_lt"], s["label"]) for s in _STAT.get("stars", [])]  # 例如 [(0.01,"**"), (0.05,"*")]
        show_ns = _STAT.get("show_ns", False)

        y_min = float(np.nanmin([np.nanmin(wt_y), np.nanmin(ho_y)]))
        y_max = float(np.nanmax([np.nanmax(wt_y), np.nanmax(ho_y)]))
        pad = 0.05 * (y_max - y_min if y_max > y_min else 1.0)

        cur_y0, cur_y1 = ax.get_ylim()
        ax.set_ylim(cur_y0, max(cur_y1, y_max + 2*pad))

        for xi, w, h, p in zip(x, wt_y, ho_y, df["p_value"].values):
            lab = None
            if p is not None and not np.isnan(p):
                for thr, sym in thresholds:
                    if p < thr:
                        lab = sym
                        break
            if lab is None and not show_ns:
                continue
            if lab is None:
                lab = "ns"
            y = np.nanmax([w, h]) + pad
            ax.text(xi, y, lab, ha="center", va="bottom")
    plt.tight_layout()

    # 先 PDF（矢量），再 PNG（600 dpi）
    plt.savefig(out_pdf, bbox_inches="tight")
    exp = _PS.get("export", {})
    plt.savefig(out_png, dpi=exp.get("dpi", 600),
                bbox_inches="tight", transparent=exp.get("transparent", False))
    plt.savefig(out_png, dpi=300)
    plt.savefig(out_pdf)
    plt.close()


def process_file(in_path: Path):
    print(f"[信息] 作图文件: {in_path}")
    df = pd.read_excel(in_path)

    if _has_stats_columns(df):
        cols = [TIME_COL, "WT_mean", "WT_sd", "WT_n", "HO_mean", "HO_sd", "HO_n"]
        if "p_value" in df.columns:
            cols.append("p_value")
        stats_df = df[cols].copy()
    else:
        stats_df = _compute_stats_from_raw(df)

    # 输出文件名
    stem = in_path.stem
    out_png = OUTPUT_DIR / f"{stem}_line_sd.png"
    out_pdf = OUTPUT_DIR / f"{stem}_line_sd.pdf"

    # 标题尽量简短：用源文件名
    _plot_one(stats_df, title=stem, out_png=out_png, out_pdf=out_pdf)
    print(f"[完成] 输出：\n  {out_png}\n  {out_pdf}")


def main():
    ap = argparse.ArgumentParser(description="按 time_point 绘制 WT/HO (mean ± SD) 点线图")
    ap.add_argument("inputs", nargs="+", help="输入 Excel 文件路径（可多个）。可为 *_stats.xlsx 或原始数据表。")
    args = ap.parse_args()

    for f in args.inputs:
        process_file(Path(f))


if __name__ == "__main__":
    main()