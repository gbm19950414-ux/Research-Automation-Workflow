#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
003.1_statistic_AUC.py

功能：
1. 在 04_data/interim/microplate_reader/线粒体完整性检测/ 目录下，寻找所有
   “线粒体完整性检测_blank_corrected_t0_corrected_batch-*_dye-*.xlsx”
   形式的文件（或由命令行显式提供的文件）。
2. 对每个文件中、每一条时间曲线（同一 sample_batch + Dye_concentration +
   Dye_time + drug + dye + group + gene）计算 AUC：
   - x 轴：time_point
   - y 轴：value_t0_ratio
   使用梯形积分 (trapezoidal rule)。
3. 将每个文件的 AUC 结果输出为一个新的 Excel 文件：
   原文件名后加后缀 "_auc"，例如：
   线粒体完整性检测_blank_corrected_t0_corrected_batch-E99-2_dye-tmrm.xlsx
   -> 线粒体完整性检测_blank_corrected_t0_corrected_batch-E99-2_dye-tmrm_auc.xlsx

用法：
  # 在项目根目录下运行，自动扫描默认目录的所有 *_t0_corrected_*.xlsx
  python3 003.1_statistic_AUC.py

  # 或者手动指定部分文件
  python3 003.1_statistic_AUC.py \
      04_data/interim/microplate_reader/线粒体完整性检测/线粒体完整性检测_blank_corrected_t0_corrected_batch-E99-2_dye-tmrm.xlsx
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# 默认输入目录
INPUT_DIR = Path("04_data/interim/microplate_reader/线粒体完整性检测")

# 识别一条“曲线”的字段（与源文件列保持一致）
CURVE_KEYS = [
    "sample_batch",
    "Dye_concentration",
    "Dye_time",
    "drug",
    "dye",
    "group",
    "gene",
]

TIME_COL = "time_point"
VALUE_COL = "value_t0_ratio"


def compute_auc_for_curve(df_curve: pd.DataFrame) -> float:
    """
    对单条曲线（同一 sample_batch + ... + gene）计算 AUC。
    使用 time_point vs value_t0_ratio 的梯形积分。
    """
    # 按时间排序
    df_curve = df_curve.sort_values(TIME_COL)

    x = df_curve[TIME_COL].to_numpy(dtype=float)
    y = df_curve[VALUE_COL].to_numpy(dtype=float)

    # 仅使用 x、y 都非 NaN 的点
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]

    # 至少需要 2 个点才能做梯形积分
    if x.size < 2:
        return np.nan

    return float(np.trapz(y, x))


def process_file(in_file: Path) -> None:
    """
    对单个 *_t0_corrected_*.xlsx 文件计算所有曲线的 AUC，并写出 *_auc.xlsx。
    """
    print(f"[信息] 读取文件: {in_file}")
    try:
        df = pd.read_excel(in_file)
    except Exception as e:
        print(f"[WARN] 无法读取文件 {in_file}: {e}")
        return

    # 检查必要列
    required_cols = CURVE_KEYS + [TIME_COL, VALUE_COL]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[WARN] 文件 {in_file.name} 缺少必要列: {missing}，跳过。")
        return

    # 按曲线分组（dropna=False 确保 Dye_concentration / Dye_time 为 NA 的曲线也保留）
    groups = df.groupby(CURVE_KEYS, dropna=False)

    rows = []
    for keys, sub in groups:
        auc = compute_auc_for_curve(sub)
        n_points = sub[VALUE_COL].notna().sum()

        # keys 是一个 tuple，对应 CURVE_KEYS 顺序
        row = dict(zip(CURVE_KEYS, keys))

        # 从 gene 推断 WT / HO，用于后续箱线图的 hue 映射
        gene_val = str(row.get("gene", "")).lower()
        if "wt" in gene_val:
            geno = "WT"
        elif "ho" in gene_val:
            geno = "HO"
        else:
            geno = None

        row.update(
            {
                "geno": geno,
                "n_points": int(n_points),
                "auc": auc,
            }
        )
        rows.append(row)
    if not rows:
        print(f"[WARN] 文件 {in_file.name} 未找到任何曲线，跳过。")
        return

    res = pd.DataFrame(rows)

    # 输出文件名：原文件名加 "_auc"
    out_file = in_file.with_name(in_file.stem + "_auc.xlsx")
    res.to_excel(out_file, index=False)
    print(f"[DONE] 写出 AUC 结果: {out_file}")


def auto_find_input_files() -> list[Path]:
    """
    在默认目录中自动查找所有 *_blank_corrected_t0_corrected_batch-*_dye-*.xlsx 文件，
    排除 ~ 开头的临时文件、_stats.xlsx、_auc.xlsx。
    """
    if not INPUT_DIR.exists():
        print(f"[WARN] 默认目录不存在: {INPUT_DIR.resolve()}")
        return []

    files = []
    for p in INPUT_DIR.glob("线粒体完整性检测_blank_corrected_t0_corrected_batch-*_dye-*.xlsx"):
        name = p.name
        # 排除临时文件和已经统计过的文件
        if name.startswith("~$"):
            continue
        if name.endswith("_stats.xlsx") or name.endswith("_auc.xlsx"):
            continue
        files.append(p)

    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="为每个样品的每条时间曲线计算 AUC（time_point vs value_t0_ratio）"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="可选：一个或多个输入 Excel 文件；若不提供则自动扫描默认目录。",
    )
    args = parser.parse_args()

    if args.inputs:
        files = [Path(p) for p in args.inputs]
    else:
        files = auto_find_input_files()
        if files:
            print("[信息] 未提供输入参数，自动找到以下文件：")
            for p in files:
                print("  -", p)
        else:
            print("[WARN] 未在默认目录中找到任何匹配的 *_t0_corrected_*.xlsx 文件。")
            return

    for f in files:
        process_file(f)


if __name__ == "__main__":
    main()