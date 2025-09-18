#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版：仅按 genetype 统计
-------------------------
功能：
1. 自动从 sample_id 提取 genetype (WT/HO)
2. 按 genetype 统计 n、mean、sd
3. 计算 WT vs HO t 检验
4. 输出 <文件名>_stats.xlsx ：
   - data       : 原始数据 + genetype + 统计列
   - pair_stats : WT vs HO 统计
   - meta       : 运行时间
"""

import sys, os
import numpy as np
import pandas as pd
from scipy.stats import ttest_ind
from datetime import datetime

# 必需列
SAMPLE_COL  = "sample_id"   # 用于解析 genetype
VALUE_COL   = "fold_change"       # 需要求平均值/SD/p 的数值列

def process_one(path: str):
    print(f"处理 {path} ...")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(path)
    else:
        print(f"跳过不支持的文件类型: {path}")
        return

    # 检查必要列
    for c in [SAMPLE_COL, VALUE_COL]:
        if c not in df.columns:
            raise ValueError(f"{path} 缺少必要列：{c}")

    # 自动解析 genetype
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors="coerce")
    df["genetype"] = df[SAMPLE_COL].astype(str).str.split("_").str[0].str.upper()

    # 1. 组内统计：按 genetype
    group_stats = (
        df.groupby("genetype", dropna=False)[VALUE_COL]
          .agg(cell_n="count",
               cell_mean="mean",
               cell_sd=lambda s: s.std(ddof=1) if len(s) > 1 else (0.0 if len(s) == 1 else np.nan))
          .reset_index()
    )
    df = df.merge(group_stats, on="genetype", how="left")

    # 2. WT vs HO 两组比较
    wt = pd.to_numeric(df.loc[df["genetype"] == "WT", VALUE_COL], errors="coerce").dropna()
    ho = pd.to_numeric(df.loc[df["genetype"] == "HO", VALUE_COL], errors="coerce").dropna()
    if len(wt) >= 2 and len(ho) >= 2:
        t_stat, p_val = ttest_ind(wt, ho, equal_var=False)
    else:
        t_stat, p_val = np.nan, np.nan

    # 提取唯一的 gene 名称（假定只有一个唯一值）
    gene_name = df["gene"].dropna().unique()[0] if "gene" in df.columns else "WT_vs_HO"

    pair_stats = pd.DataFrame([{
        "gene": gene_name,    # 使用原始 gene 列的唯一值
        "wt_n": len(wt), "wt_mean": wt.mean() if len(wt) else np.nan,
        "wt_sd": wt.std(ddof=1) if len(wt) > 1 else (0.0 if len(wt) == 1 else np.nan),
        "ho_n": len(ho), "ho_mean": ho.mean() if len(ho) else np.nan,
        "ho_sd": ho.std(ddof=1) if len(ho) > 1 else (0.0 if len(ho) == 1 else np.nan),
        "delta(ho-wt)": (ho.mean() - wt.mean()) if len(wt) and len(ho) else np.nan,
        "t_stat": t_stat, "p_value": p_val
    }])

    # 把两组比较结果添加到每行
    for col in pair_stats.columns:
        df[col] = pair_stats[col].iloc[0]

    # 3. 输出 Excel
    out_dir  = os.path.dirname(path)
    base     = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{base}_stats.xlsx")

    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="data")
        pair_stats.to_excel(w, index=False, sheet_name="pair_stats")
        pd.DataFrame({
            "key": ["run_time"],
            "value": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        }).to_excel(w, index=False, sheet_name="meta")

    print(f"完成：{out_path}")

def main():
    input_paths = sys.argv[1:]
    if not input_paths:
        print("用法: python3 003_group_stats_genetype_only.py file_or_folder [...]")
        sys.exit(1)

    files = []
    for path in input_paths:
        if os.path.isdir(path):
            for fname in os.listdir(path):
                full_path = os.path.join(path, fname)
                if os.path.isfile(full_path) and fname.lower().endswith((".csv", ".xls", ".xlsx")):
                    files.append(full_path)
        elif os.path.isfile(path) and path.lower().endswith((".csv", ".xls", ".xlsx")):
            files.append(path)

    if not files:
        print("未找到可处理的 .csv/.xls/.xlsx 文件")
        sys.exit(1)

    for f in files:
        process_one(f)

if __name__ == "__main__":
    main()