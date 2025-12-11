#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
003.2_AUC_stat.py

功能：
1. 读取一个或多个由 003.1_statistic_AUC.py 生成的 AUC Excel 文件：
   例如：
     04_data/interim/microplate_reader/线粒体完整性检测/
       线粒体完整性检测_blank_corrected_t0_corrected_batch-E53_dye-mitosox_auc.xlsx
2. 按 gene 中的 WT / HO 分组，在每个
   Dye_concentration * Dye_time * drug * dye * group 组合内，
   对 auc 做：
     - mean, sd, n
     - WT vs HO Welch t-test (双尾 p 值)
3. 每个输入文件输出一个对应的 *_auc_stats.xlsx，放在同一目录。

用法：
  # 自动扫描目录中所有 *_auc.xlsx
  python3 003.2_AUC_stat.py

  # 或手动指定部分文件
  python3 003.2_AUC_stat.py file1_auc.xlsx file2_auc.xlsx
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

# 固定目录
INPUT_DIR = Path("04_data/interim/microplate_reader/线粒体完整性检测")
OUTPUT_DIR = INPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 列名
GENE_COL = "gene"
DYE_CONC_COL = "Dye_concentration"
DYE_TIME_COL = "Dye_time"
DRUG_COL = "drug"
DYE_COL = "dye"
GROUP_COL = "group"
AUC_COL = "auc"

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
    return pd.Series(labels, index=df.index, name="geno")


def welch_p(a: pd.Series, b: pd.Series) -> float:
    """Welch t-test 双尾 p 值"""
    a = pd.to_numeric(a, errors="coerce").dropna()
    b = pd.to_numeric(b, errors="coerce").dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    if not _has_scipy:
        return np.nan
    return float(ttest_ind(a, b, equal_var=False, nan_policy="omit").pvalue)


def _mad_z_group(x: pd.Series) -> pd.Series:
    """在一个 group 内计算 robust z-score（基于 MAD）"""
    x = pd.to_numeric(x, errors="coerce")
    med = x.median()
    mad = (x - med).abs().median()
    if pd.isna(mad) or mad == 0:
        # MAD 为 0（全部一样或样本太少）时不判为离群
        return pd.Series(np.zeros(len(x)), index=x.index)
    return 0.6745 * (x - med) / mad


def process_file(in_file: Path) -> None:
    """对单个 *_auc.xlsx 文件做 WT/HO 统计"""
    print(f"[信息] 处理 AUC 文件: {in_file}")
    try:
        df = pd.read_excel(in_file)
    except Exception as e:
        print(f"[WARN] 无法读取文件 {in_file}: {e}")
        return

    required_cols = [
        "sample_batch",
        DYE_CONC_COL,
        DYE_TIME_COL,
        DRUG_COL,
        DYE_COL,
        GROUP_COL,
        GENE_COL,
        AUC_COL,
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[WARN] 文件 {in_file.name} 缺少必要列: {missing}，跳过。")
        return

    # 基因型标签
    df["geno"] = label_group(df)
    df = df[df["geno"].isin(["WT", "HO"])].copy()
    if df.empty:
        print(f"[WARN] 文件 {in_file.name} 中未识别到 WT/HO，跳过。")
        return

    # 数值化 AUC
    df[AUC_COL] = pd.to_numeric(df[AUC_COL], errors="coerce")

    # === 异常值剔除（对 AUC 做 MAD-z） ===
    # 分组维度：同一 genotype + 条件组合
    z_group_keys = ["geno", DYE_CONC_COL, DYE_TIME_COL, DRUG_COL, DYE_COL, GROUP_COL]

    df[f"robust_z_{AUC_COL}"] = (
        df.groupby(z_group_keys, dropna=False)[AUC_COL]
        .transform(_mad_z_group)
    )
    df[f"is_outlier_{AUC_COL}"] = df[f"robust_z_{AUC_COL}"].abs() > MAD_Z_THRESHOLD
    n_outliers = int(df[f"is_outlier_{AUC_COL}"].sum())
    if n_outliers > 0:
        print(f"[信息] 文件 {in_file.name} 中 AUC 剔除异常值 {n_outliers} 个（|z| > {MAD_Z_THRESHOLD}）")
    df = df.loc[~df[f"is_outlier_{AUC_COL}"]].copy()

    # === 按条件组合做 WT vs HO 统计 ===
    group_cols = [DYE_CONC_COL, DYE_TIME_COL, DRUG_COL, DYE_COL, GROUP_COL]
    out_rows = []

    for gvals, sub in df.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, gvals))

        a = sub.loc[sub["geno"] == "WT", AUC_COL]
        b = sub.loc[sub["geno"] == "HO", AUC_COL]

        row.update(
            {
                f"{AUC_COL}_WT_mean": np.nanmean(a) if len(a) else np.nan,
                f"{AUC_COL}_WT_sd": np.nanstd(a, ddof=1) if len(a) > 1 else np.nan,
                f"{AUC_COL}_WT_n": int(a.notna().sum()),
                f"{AUC_COL}_HO_mean": np.nanmean(b) if len(b) else np.nan,
                f"{AUC_COL}_HO_sd": np.nanstd(b, ddof=1) if len(b) > 1 else np.nan,
                f"{AUC_COL}_HO_n": int(b.notna().sum()),
                f"{AUC_COL}_p": welch_p(a, b),
            }
        )
        out_rows.append(row)

    if not out_rows:
        print(f"[WARN] 文件 {in_file.name} 未生成任何统计结果，跳过。")
        return

    res = pd.DataFrame(out_rows).sort_values(by=group_cols, ignore_index=True)

    out_file = OUTPUT_DIR / f"{in_file.stem}_stats.xlsx"  # -> *_auc_stats.xlsx
    res.to_excel(out_file, index=False)
    print(f"[完成] 写出 AUC 统计结果: {out_file}")


def auto_find_auc_files() -> list[Path]:
    """自动扫描目录中的 *_auc.xlsx 文件，排除临时和 *_stats.xlsx"""
    if not INPUT_DIR.exists():
        print(f"[WARN] 目录不存在: {INPUT_DIR.resolve()}")
        return []

    files: list[Path] = []
    for p in INPUT_DIR.iterdir():
        name = p.name.lower()
        if not name.endswith(".xlsx"):
            continue
        if name.startswith("~$"):
            continue
        if not name.endswith("_auc.xlsx"):
            continue
        if name.endswith("_auc_stats.xlsx"):
            # 已经统计过的结果，跳过
            continue
        files.append(p)

    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="对 AUC 做 WT vs HO 统计（mean / sd / n / p）")
    parser.add_argument(
        "inputs",
        nargs="*",
        help="可选：一个或多个 *_auc.xlsx 文件；若不提供则自动扫描默认目录。",
    )
    args = parser.parse_args()

    if args.inputs:
        files = [Path(p) for p in args.inputs]
    else:
        files = auto_find_auc_files()
        print(f"[信息] 未提供输入参数，自动找到 {len(files)} 个 *_auc.xlsx 文件:")
        for p in files:
            print("   -", p)

    if not files:
        print("[WARN] 未找到任何 *_auc.xlsx 文件。")
        return

    for f in files:
        process_file(f)


if __name__ == "__main__":
    main()