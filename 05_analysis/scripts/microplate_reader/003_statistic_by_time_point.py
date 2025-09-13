#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
003_statistic_by_time_point.py

功能：
1. 读取一个或多个 Excel 文件。
2. 按 gene 中的 WT / HO 分组，在每个 time_point 计算 mean、sd、n，并做 Welch t-test 得到 p。
3. 输出结果到固定目录，每个输入文件对应一个 *_stats.xlsx。

用法：
  python3 003_statistic_by_time_point.py file1.xlsx file2.xlsx ...
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from scipy.stats import ttest_ind
    _has_scipy = True
except ImportError:
    _has_scipy = False
    print("[警告] 未安装 scipy，p 值将输出为 NaN。安装方法：pip install scipy")

# 固定输出目录
OUTPUT_DIR = Path(
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/"
    "博士课题/EphB1/04_data/interim/microplate_reader/线粒体完整性检测"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 固定列名
TIME_COL = "time_point"
VALUE_COL = "value"
GENE_COL = "gene"


def label_group(df: pd.DataFrame) -> pd.Series:
    """根据 gene 列生成 WT/HO 标签"""
    if GENE_COL not in df.columns:
        raise KeyError(f"缺少列: {GENE_COL}")

    s = df[GENE_COL].astype(str).str.lower()
    labels = []
    for v in s:
        if "wt" in v:
            labels.append("WT")
        elif "ho" in v:
            labels.append("HO")
        else:
            labels.append(None)
    return pd.Series(labels, index=df.index, name="group")


def welch_p(a: pd.Series, b: pd.Series) -> float:
    """Welch t-test 双尾 p 值"""
    a = pd.to_numeric(a, errors="coerce").dropna()
    b = pd.to_numeric(b, errors="coerce").dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    if not _has_scipy:
        return np.nan
    return float(ttest_ind(a, b, equal_var=False, nan_policy="omit").pvalue)


def process_file(in_file: Path):
    print(f"[信息] 处理文件: {in_file}")
    df = pd.read_excel(in_file)
    # === 背景矫正（仅用 group=blank） ===
    # 1) 找到 blank 行
    lower_group = df["group"].astype(str).str.strip().str.lower()
    blank_mask = lower_group.eq("blank")  # 只认 blank

    # 新：按 (gene, time_point) 求背景值
    bg = (df.loc[blank_mask]
            .groupby([GENE_COL, TIME_COL])[VALUE_COL]
            .mean()
            .rename("__bg__")
            .reset_index())

    # 按 (gene, time_point) 合并回原表
    df = df.merge(bg, on=[GENE_COL, TIME_COL], how="left")
    df["__bg__"] = df["__bg__"].fillna(0)
    # 4) 用背景做矫正（覆盖 value）
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors="coerce") - df["__bg__"]

    # 5) 背景行不参与后续统计（仅剔除 blank；其它如 negative 保留）
    df = df.loc[~blank_mask].copy()    
    for col in [TIME_COL, VALUE_COL, GENE_COL]:
        if col not in df.columns:
            raise KeyError(f"缺少列: {col}")

    df["geno"] = label_group(df)           # 新列：geno
    df = df[df["geno"].isin(["WT", "HO"])] # 只保留 WT/HO
    out_rows = []
    for tval, sub in df.groupby(TIME_COL, dropna=False):
        a = sub.loc[sub["geno"] == "WT", VALUE_COL]
        b = sub.loc[sub["geno"] == "HO", VALUE_COL]

        row = {
            TIME_COL: tval,
            "WT_mean": np.nanmean(a) if len(a) else np.nan,
            "WT_sd": np.nanstd(a, ddof=1) if len(a) > 1 else np.nan,
            "WT_n": int(a.notna().sum()),
            "HO_mean": np.nanmean(b) if len(b) else np.nan,
            "HO_sd": np.nanstd(b, ddof=1) if len(b) > 1 else np.nan,
            "HO_n": int(b.notna().sum()),
            "p_value": welch_p(a, b)
        }
        out_rows.append(row)

    res = pd.DataFrame(out_rows).sort_values(by=TIME_COL, ignore_index=True)

    out_file = OUTPUT_DIR / f"{in_file.stem}_stats.xlsx"
    res.to_excel(out_file, index=False)
    print(f"[完成] 写出结果: {out_file}")


def main():
    parser = argparse.ArgumentParser(description="WT vs HO 按 time_point 统计")
    parser.add_argument("inputs", nargs="+", help="输入 Excel 文件路径，可多个")
    args = parser.parse_args()

    for f in args.inputs:
        process_file(Path(f))


if __name__ == "__main__":
    main()