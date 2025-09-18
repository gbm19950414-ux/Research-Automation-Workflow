#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量统计分析
---------------------------------------
- 取 gene 前两字母为 genetype (WT/HO)
- 所有 group 都参与 z-score 计算
- 每组 (group, drug, genetype) 去异常后计算 cell_n/cell_mean/cell_sd 并写回每行
- 每组 (group, drug) 去异常后做 WT vs HO 显著性比较并写回每行
输出：
    <源文件名>_stats.xlsx
    - data : 原始每行 + 统计列
    - meta : 背景均值
"""
import sys, os
import numpy as np
import pandas as pd
from scipy.stats import ttest_ind

# === 默认列名/标签 ===
GROUP_COL      = "group"
DRUG_COL       = "drug"
GENE_COL       = "gene"
VALUE_COL      = "value"
BLANK_LABEL    = "blank"
POSITIVE_LABEL = "positive"
OUTLIER_Z      = 2
# =====================

def robust_z(series: pd.Series) -> pd.Series:
    """median/MAD 鲁棒 z 分数"""
    x = pd.to_numeric(series, errors="coerce")
    med = x.median(skipna=True)
    mad = (x - med).abs().median(skipna=True)
    if pd.isna(mad) or mad == 0:
        return pd.Series(np.nan, index=x.index)
    return (x - med) / (1.4826 * mad)

def process_one(path: str):
    print(f"处理 {path} ...")
    df = pd.read_excel(path)

    # 检查必要列
    for c in [GROUP_COL, DRUG_COL, GENE_COL, VALUE_COL]:
        if c not in df.columns:
            raise ValueError(f"{path} 缺少必要列：{c}")

    # 预处理
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors="coerce")
    df["genetype"] = df[GENE_COL].astype(str).str[:2].str.upper()
    g_lower = df[GROUP_COL].astype(str).str.lower()

    # 1. 背景均值
    if not g_lower.eq(BLANK_LABEL).any():
        raise ValueError(f"{path}: 未找到背景标签 '{BLANK_LABEL}'。")
    background_mean = df.loc[g_lower.eq(BLANK_LABEL), VALUE_COL].mean(skipna=True)

    # 2. 背景矫正
    df["bg_corrected"] = df[VALUE_COL] - background_mean

    # 3. 归一化：同 gene 且 group=positive 的背景矫正值
    if not g_lower.eq(POSITIVE_LABEL).any():
        raise ValueError(f"{path}: 未找到正控标签 '{POSITIVE_LABEL}'。")
    pos_map = (
        df.loc[g_lower.eq(POSITIVE_LABEL), [GENE_COL, "bg_corrected"]]
          .groupby(GENE_COL, dropna=False)["bg_corrected"].mean()
    )
    df["pos_bg"] = df[GENE_COL].map(pos_map)
    df["normalized"] = np.where(df["pos_bg"] > 0, df["bg_corrected"] / df["pos_bg"], np.nan)

    # 4. 鲁棒Z（所有 group 参与）
    df["zscore"] = (
        df.groupby([GROUP_COL, DRUG_COL, "genetype"], dropna=False)["normalized"]
          .transform(robust_z)
    )
    df["outlier"] = df["zscore"].abs() > OUTLIER_Z

    # 5. 去异常后的数据
    clean = df[df["normalized"].notna() & (~df["outlier"])].copy()

    # 6. 每组 (group, drug, genetype) 统计并写回每行
    cell_stats = (
        clean.groupby([GROUP_COL, DRUG_COL, "genetype"], dropna=False)["normalized"]
             .agg(cell_n="count",
                  cell_mean="mean",
                  cell_sd=lambda s: s.std(ddof=1) if len(s) > 1 else (0.0 if len(s) == 1 else np.nan))
             .reset_index()
    )
    df = df.merge(cell_stats, on=[GROUP_COL, DRUG_COL, "genetype"], how="left")

    # 7. 每组 (group, drug) 的 WT vs HO 显著性检验并写回每行
    def summarize_pair(sub):
        wt = pd.to_numeric(sub.loc[sub["genetype"] == "WT", "normalized"], errors="coerce").dropna()
        ho = pd.to_numeric(sub.loc[sub["genetype"] == "HO", "normalized"], errors="coerce").dropna()
        n_wt, n_ho = wt.size, ho.size
        mean_wt = wt.mean() if n_wt else np.nan
        mean_ho = ho.mean() if n_ho else np.nan
        sd_wt = wt.std(ddof=1) if n_wt > 1 else (0.0 if n_wt == 1 else np.nan)
        sd_ho = ho.std(ddof=1) if n_ho > 1 else (0.0 if n_ho == 1 else np.nan)
        if n_wt >= 2 and n_ho >= 2:
            t_stat, p_val = ttest_ind(wt, ho, equal_var=False)
        else:
            t_stat, p_val = np.nan, np.nan
        return pd.Series({
            "wt_n": n_wt, "wt_mean": mean_wt, "wt_sd": sd_wt,
            "ho_n": n_ho, "ho_mean": mean_ho, "ho_sd": sd_ho,
            "delta(ho-wt)": (mean_ho - mean_wt) if (pd.notna(mean_wt) and pd.notna(mean_ho)) else np.nan,
            "t_stat": t_stat, "p_value": p_val
        })

    pair_stats = (
        clean.groupby([GROUP_COL, DRUG_COL], dropna=False)
             .apply(summarize_pair)
             .reset_index()
    )
    df = df.merge(pair_stats, on=[GROUP_COL, DRUG_COL], how="left")

    # 8. 输出到同目录
    out_dir  = os.path.dirname(path)
    base     = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{base}_stats.xlsx")

    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        # 逐行数据：去掉 p_value 和 t_stat 列
        data_cols = [GROUP_COL, DRUG_COL, GENE_COL, "genetype", VALUE_COL,
                     "bg_corrected", "pos_bg", "normalized", "zscore", "outlier",
                     "cell_n", "cell_mean", "cell_sd",
                     "wt_n", "wt_mean", "wt_sd", "ho_n", "ho_mean", "ho_sd",
                     "delta(ho-wt)"]
        data_cols = [c for c in data_cols if c in df.columns]
        df.to_excel(w, index=False, sheet_name="data", columns=data_cols)

        # 单独输出组间比较的统计结果
        pair_stats.to_excel(w, index=False, sheet_name="pair_stats")

        # meta：背景均值
        pd.DataFrame({"key": ["background_mean"], "value": [background_mean]}).to_excel(
            w, index=False, sheet_name="meta"
        )
    print(f"完成：{out_path}")

def main():
    files = [f for f in sys.argv[1:] if f.lower().endswith(".xlsx")]
    if not files:
        print("用法: python analyze_batch.py file1.xlsx [file2.xlsx ...]")
        sys.exit(1)
    for f in files:
        process_one(f)

if __name__ == "__main__":
    main()