#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
003_statistic_by_time_point.py

功能：
1. 读取一个或多个 Excel 文件。
2. 按 gene 中的 WT / HO 分组，在每个 Dye_concentration * Dye_time * drug * time_point * dye * group 组合内计算 mean、sd、n，并做 Welch t-test 得到 p。
3. 输出结果到固定目录，每个输入文件对应一个 *_stats.xlsx。

用法：
  python3 003_statistic_by_time_point.py file1.xlsx file2.xlsx ...

默认输入行为：
- 若运行时未提供参数，则脚本会自动扫描目录：
    04_data/interim/microplate_reader/线粒体完整性检测/
  挑选所有文件名中包含“blank_corrected”且不包含“stats”或“long”的 Excel 文件作为输入。
- 统计使用 value_corrected 列，而不是 value 列。
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
OUTPUT_DIR = Path("04_data/interim/microplate_reader/线粒体完整性检测")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 固定列名
TIME_COL = "time_point"
VALUE_COLS = ["value_corrected", "value_t0_delta", "value_t0_ratio"]
GENE_COL = "gene"
DYE_CONC_COL = "Dye_concentration"
DYE_TIME_COL = "Dye_time"
DRUG_COL = "drug"
DYE_COL = "dye"
group_COL = "group"
MAD_Z_THRESHOLD = 2.5

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
            .groupby([GENE_COL, TIME_COL])[VALUE_COLS[0]]
            .mean()
            .rename("__bg__")
            .reset_index())

    # 按 (gene, time_point) 合并回原表
    df = df.merge(bg, on=[GENE_COL, TIME_COL], how="left")
    df["__bg__"] = df["__bg__"].fillna(0)
    # 4) 用背景做矫正（覆盖 value_corrected）
    df[VALUE_COLS[0]] = pd.to_numeric(df[VALUE_COLS[0]], errors="coerce") - df["__bg__"]

    # 对三个指标都进行数值转换
    for vcol in VALUE_COLS:
        if vcol in df.columns:
            df[vcol] = pd.to_numeric(df[vcol], errors="coerce")

    # 5) 背景行不参与后续统计（仅剔除 blank；其它如 negative 保留）
    df = df.loc[~blank_mask].copy()    
    required_cols = [
        TIME_COL,
        VALUE_COLS[0],  # 只强制要求 value_corrected 存在；value_t0_* 可选
        GENE_COL,
        DYE_CONC_COL,
        DYE_TIME_COL,
        DRUG_COL,
        DYE_COL,
        group_COL,
    ]
    for col in required_cols:
        if col not in df.columns:
            raise KeyError(f"缺少列: {col}")

    df["geno"] = label_group(df)           # 新列：geno
    df = df[df["geno"].isin(["WT", "HO"])] # 只保留 WT/HO
    # === 异常值剔除（MAD-z，按每个 time_point 和 geno 分组） ===

    def _mad_z_group(x: pd.Series) -> pd.Series:
        x = pd.to_numeric(x, errors="coerce")
        med = x.median()
        mad = (x - med).abs().median()
        if pd.isna(mad) or mad == 0:
            # MAD 为 0（全部一样或样本太少）时不判为离群
            return pd.Series(np.zeros(len(x)), index=x.index)
        return 0.6745 * (x - med) / mad

    # 对每个 (geno, Dye_concentration, Dye_time, drug, time_point, dye, group) 组合计算 robust z
    z_group_keys = ["geno", DYE_CONC_COL, DYE_TIME_COL, DRUG_COL, TIME_COL, DYE_COL, group_COL]

    # 对三个指标分别进行离群值检测与剔除
    for vcol in VALUE_COLS:
        if vcol not in df.columns:
            continue
        df[f"robust_z_{vcol}"] = df.groupby(z_group_keys)[vcol].transform(_mad_z_group)
        df[f"is_outlier_{vcol}"] = df[f"robust_z_{vcol}"].abs() > MAD_Z_THRESHOLD
        df = df.loc[~df[f"is_outlier_{vcol}"]].copy()

    # 若不想保留辅助列，可再：df.drop(columns=["robust_z","is_outlier"], inplace=True)

    group_cols = [DYE_CONC_COL, DYE_TIME_COL, DRUG_COL, TIME_COL, DYE_COL, group_COL]
    out_rows = []
    for gvals, sub in df.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, gvals))
        for vcol in VALUE_COLS:
            if vcol not in df.columns:
                continue
            a = sub.loc[sub["geno"] == "WT", vcol]
            b = sub.loc[sub["geno"] == "HO", vcol]

            row.update({
                f"{vcol}_WT_mean": np.nanmean(a) if len(a) else np.nan,
                f"{vcol}_WT_sd": np.nanstd(a, ddof=1) if len(a) > 1 else np.nan,
                f"{vcol}_WT_n": int(a.notna().sum()),
                f"{vcol}_HO_mean": np.nanmean(b) if len(b) else np.nan,
                f"{vcol}_HO_sd": np.nanstd(b, ddof=1) if len(b) > 1 else np.nan,
                f"{vcol}_HO_n": int(b.notna().sum()),
                f"{vcol}_p": welch_p(a, b),
            })
        out_rows.append(row)

    res = pd.DataFrame(out_rows).sort_values(by=group_cols, ignore_index=True)

    out_file = OUTPUT_DIR / f"{in_file.stem}_stats.xlsx"
    res.to_excel(out_file, index=False)
    print(f"[完成] 写出结果: {out_file}")


def main():
    parser = argparse.ArgumentParser(description="WT vs HO 按 time_point 统计")
    parser.add_argument("inputs", nargs="*", help="输入 Excel 文件路径，可为 0 个或多个")
    args = parser.parse_args()

    # 若用户未提供任何输入文件 → 自动扫描默认目录
    if len(args.inputs) == 1 and args.inputs[0] == "":
        pass  # not used
    if args.inputs == [""] or len(args.inputs) == 0:
        scan_dir = Path("04_data/interim/microplate_reader/线粒体完整性检测")
        files = []
        for p in scan_dir.iterdir():
            name = p.name.lower()
            if name.endswith(".xlsx") and ("blank_corrected" in name) and ("stats" not in name) and ("long" not in name):
                files.append(p)
        print(f"[信息] 未提供输入参数，自动找到 {len(files)} 个 blank_corrected 文件:")
        for p in files:
            print("   -", p)
        for p in files:
            process_file(p)
    else:
        for f in args.inputs:
            process_file(Path(f))


if __name__ == "__main__":
    main()