#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版：按 gene + treatment 分组，比较 WT vs HO
-------------------------
功能：
1. 自动从 sample_id 提取 genetype (WT/HO)
2. 按 (gene, treatment, genetype) 统计 n、mean、sd
3. 在每个 (gene, treatment) 组合内做 WT vs HO t 检验
4. 输出 <文件名>_stats.xlsx ：
   - data       : 原始数据 + genetype + 统计列
   - pair_stats : 每个 (gene, treatment) 的 WT vs HO 统计
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

    # 检查必要列：sample_id, fold_change, gene, treatment
    required_cols = [SAMPLE_COL, VALUE_COL, "gene", "treatment"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"{path} 缺少必要列：{c}")

    # 自动解析 genetype
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors="coerce")
    df["genetype"] = df[SAMPLE_COL].astype(str).str.split("_").str[0].str.upper()

    # 1. 组内统计：按 (gene, treatment, genetype)
    group_stats = (
        df.groupby(["gene", "treatment", "genetype"], dropna=False)[VALUE_COL]
          .agg(
              cell_n="count",
              cell_mean="mean",
              cell_sd=lambda s: s.std(ddof=1) if len(s) > 1 else (0.0 if len(s) == 1 else np.nan),
          )
          .reset_index()
    )
    df = df.merge(group_stats, on=["gene", "treatment", "genetype"], how="left")

    # 2. 在每个 (gene, treatment) 组合内做 WT vs HO 两组比较
    pair_rows = []
    for (g, tr), sub in df.groupby(["gene", "treatment"], dropna=False):
        wt = pd.to_numeric(sub.loc[sub["genetype"] == "WT", VALUE_COL], errors="coerce").dropna()
        ho = pd.to_numeric(sub.loc[sub["genetype"] == "HO", VALUE_COL], errors="coerce").dropna()

        if len(wt) >= 2 and len(ho) >= 2:
            t_stat, p_val = ttest_ind(wt, ho, equal_var=False)
        else:
            t_stat, p_val = np.nan, np.nan

        pair_rows.append({
            "gene": g,
            "treatment": tr,
            "wt_n": len(wt),
            "wt_mean": wt.mean() if len(wt) else np.nan,
            "wt_sd": wt.std(ddof=1) if len(wt) > 1 else (0.0 if len(wt) == 1 else np.nan),
            "ho_n": len(ho),
            "ho_mean": ho.mean() if len(ho) else np.nan,
            "ho_sd": ho.std(ddof=1) if len(ho) > 1 else (0.0 if len(ho) == 1 else np.nan),
            "delta(ho-wt)": (ho.mean() - wt.mean()) if len(wt) and len(ho) else np.nan,
            "t_stat": t_stat,
            "p_value": p_val,
        })

    pair_stats = pd.DataFrame(pair_rows)

    # 把每个 (gene, treatment) 的比较结果合并回原始行
    df = df.merge(pair_stats, on=["gene", "treatment"], how="left")

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