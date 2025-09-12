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
    df = stats_df.copy()
    df["_t"] = pd.to_numeric(df[TIME_COL], errors="coerce")
    df = df.sort_values(["_t", TIME_COL], kind="mergesort")

    x = df[TIME_COL].values
    wt_y = df["WT_mean"].values
    wt_e = df["WT_sd"].values
    ho_y = df["HO_mean"].values
    ho_e = df["HO_sd"].values

    plt.figure(figsize=(7, 4.5))  # 单图，简洁风格
    # 误差棒点线图（不设颜色，使用默认色）
    plt.errorbar(x, wt_y, yerr=wt_e, fmt='o-', capsize=3, label="WT")
    plt.errorbar(x, ho_y, yerr=ho_e, fmt='s--', capsize=3, label="HO")

    plt.title(title)
    plt.xlabel(TIME_COL)
    plt.ylabel(f"{VALUE_COL} (mean ± SD)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    plt.savefig(out_png, dpi=300)
    plt.savefig(out_pdf)
    plt.close()


def process_file(in_path: Path):
    print(f"[信息] 作图文件: {in_path}")
    df = pd.read_excel(in_path)

    if _has_stats_columns(df):
        stats_df = df[[TIME_COL, "WT_mean", "WT_sd", "WT_n", "HO_mean", "HO_sd", "HO_n"]].copy()
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