#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
002a.1_T0_correction.py

工作流角色：
- 在 002a_blank_correction.py 之后，对每个 well / 条件 / 样本的时间序列做「基线 T0 归一化」。
- 基于列 `value_corrected` 计算：
    1) ΔF = F(t) - F(T0)   → 列名：value_t0_delta
    2) F/F0 = F(t) / F(T0) → 列名：value_t0_ratio
- T0 定义为：同一条曲线中最早的 time_point（不强制必须是 0，只取最小值）。

默认输入/输出：
- 若运行时未提供参数，脚本会自动扫描目录：
    04_data/interim/microplate_reader/线粒体完整性检测/
  选择所有文件名中：
    * 含有 "blank_corrected"
    * 不含有 "stats"
    * 不含有 "t0_corrected"
    * 扩展名为 .xlsx
  的文件作为输入。
- 输出文件与输入文件在同一目录下，文件名规则：
    * 若原名包含 "blank_corrected"，则在其后插入 "t0_corrected"：
        例如：foo_blank_corrected_batch-E52.xlsx
        →    foo_blank_corrected_t0_corrected_batch-E52.xlsx
    * 否则，在扩展名前加后缀 "_t0_corrected"。

T0 归一化的分组逻辑（非常重要）：
- 在本脚本中，一条时间曲线由以下元信息唯一标识：
    * sample_batch * Dye_concentration * Dye_time * drug * dye * group * gene
    * 即同一块板（sample_batch）上，同一染料、同一浓度、同一孵育时间、同一处理、同一 group、同一 gene 视作一条独立的时间曲线。
- 对每一条时间曲线（上述组合）：
    1) 找到该曲线内最小的 time_point 作为 T0；
    2) 在该曲线内所有 time_point == T0 的行上取 value_corrected 的平均值，作为该曲线的 T0 值；
    3) 对该曲线内的所有行计算：
        value_t0_delta = value_corrected - T0_value
        value_t0_ratio = value_corrected / T0_value  （若 T0_value 为 0 或 NaN，则记为 NaN）。

注意：
- 脚本不修改原始文件，只生成新的 *_t0_corrected*.xlsx。
- 请确保输入文件中至少包含列：
    - "time_point"
    - "value_corrected"
- 其它所有列会原样保留。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


# 默认扫描目录
DEFAULT_DIR = Path("04_data/interim/microplate_reader/线粒体完整性检测")

TIME_COL = "time_point"
VALUE_COL = "value_corrected"

# ---------------------------------------------------------------------------


def find_input_files(scan_dir: Path) -> List[Path]:
    """在默认目录中查找符合条件的 blank_corrected Excel 文件。"""
    if not scan_dir.exists():
        print(f"[WARN] 默认目录不存在: {scan_dir}")
        return []

    files: List[Path] = []
    for p in scan_dir.iterdir():
        name = p.name
        lname = name.lower()
        if (
            p.is_file()
            and lname.endswith(".xlsx")
            and "blank_corrected" in lname
            and "stats" not in lname
            and "t0_corrected" not in lname
        ):
            files.append(p)

    print(
        f"[INFO] 在 {scan_dir} 中找到 {len(files)} 个待处理文件 "
        f"(包含 'blank_corrected'，不包含 'stats' / 't0_corrected')。"
    )
    for p in files:
        print("   -", p)
    return files


def build_output_path(path: Path) -> Path:
    """根据命名规则生成输出路径。"""
    name = path.name
    if "blank_corrected" in name:
        new_name = name.replace("blank_corrected", "blank_corrected_t0_corrected")
    else:
        new_name = path.stem + "_t0_corrected" + path.suffix
    return path.with_name(new_name)


def t0_normalize_file(path: Path) -> None:
    """对单个 blank_corrected 文件执行 T0 归一化，并写出新文件。"""
    print(f"\n[INFO] 读取文件: {path}")
    try:
        df = pd.read_excel(path)
    except Exception as e:
        print(f"[ERROR] 读取失败，跳过: {e}")
        return

    # 检查必需列
    for col in (TIME_COL, VALUE_COL):
        if col not in df.columns:
            print(f"[ERROR] 缺少必需列 '{col}'，无法处理此文件，跳过。")
            return

    # 若 value_corrected 全为空，则不做处理
    if df[VALUE_COL].notna().sum() == 0:
        print("[WARN] 列 'value_corrected' 全为 NaN，跳过 T0 归一化，只复制原始内容。")
        out_path = build_output_path(path)
        df.to_excel(out_path, index=False)
        print(f"[DONE] 写出文件（未做归一化）: {out_path}")
        return

    # 分组列定义：同一条时间曲线由 sample_batch * Dye_concentration * Dye_time * drug * dye * group * gene 唯一确定
    group_cols = [
        "sample_batch",
        "Dye_concentration",
        "Dye_time",
        "drug",
        "dye",
        "group",
        "gene",
    ]
    missing = [c for c in group_cols if c not in df.columns]
    if missing:
        print(f"[ERROR] 缺少用于分组的列: {missing}，无法进行 T0 归一化，跳过。")
        return

    # 若表中已经包含旧的 T0 归一化列，先删除，避免参与分组或干扰后续判断
    for col in ("value_t0_delta", "value_t0_ratio"):
        if col in df.columns:
            print(f"[INFO] 检测到已有列 '{col}'，将在本次计算前删除并重新生成。")
            df = df.drop(columns=[col])

    # 为了 T0 逻辑更清晰，先按 group_cols + time 排序
    sort_cols = group_cols + [TIME_COL] if group_cols else [TIME_COL]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    # 1) 每个 group 内找到最早的 time_point（T0）
    if group_cols:
        t0_time = df.groupby(group_cols, dropna=False)[TIME_COL].transform("min")
    else:
        t0_time = pd.Series(df[TIME_COL].min(), index=df.index)

    df["__t0_time_point"] = t0_time

    # 2) 在每个 group 中，time_point == T0 的行上求 value_corrected 的平均：T0_value
    if group_cols:
        t0_rows = df[df[TIME_COL] == df["__t0_time_point"]].copy()
        t0_mean = (
            t0_rows.groupby(group_cols, dropna=False)[VALUE_COL]
            .mean()
            .reset_index()
            .rename(columns={VALUE_COL: "__t0_value"})
        )
        df = df.merge(t0_mean, on=group_cols, how="left")
    else:
        t0_value = df.loc[df[TIME_COL] == df["__t0_time_point"], VALUE_COL].mean()
        df["__t0_value"] = t0_value

    # 3) 计算 ΔF 和 F/F0
    t0_vals = df["__t0_value"].astype(float)
    val = df[VALUE_COL].astype(float)

    # ΔF = F(t) - F0
    df["value_t0_delta"] = val - t0_vals

    # F/F0（若 T0 为 0 或 NaN，则结果记为 NaN）
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = val / t0_vals
    ratio[~np.isfinite(ratio)] = np.nan
    df["value_t0_ratio"] = ratio

    # 一些简单的日志
    n_groups = df[group_cols].drop_duplicates().shape[0] if group_cols else 1
    n_bad_t0 = df["__t0_value"].isna().sum()
    print(f"[INFO] 共处理 {n_groups} 条曲线（按 {group_cols or '全表'} 分组）。")
    if n_bad_t0 > 0:
        print(f"[WARN] 有 {n_bad_t0} 行缺失 T0 值，相关 ΔF / F/F0 为 NaN。")

    # 清理中间列
    df = df.drop(columns=["__t0_time_point", "__t0_value"], errors="ignore")

    # 写出结果
    out_path = build_output_path(path)
    try:
        df.to_excel(out_path, index=False)
    except Exception as e:
        print(f"[ERROR] 写出文件失败: {e}")
        return

    print(f"[DONE] 写出 T0 归一化文件: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="对 blank_corrected 的 value_corrected 做基线 T0 归一化 "
        "(ΔF 和 F/F0，新增列 value_t0_delta / value_t0_ratio)。"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="可选：指定一个或多个 blank_corrected Excel 文件；若不提供则自动扫描默认目录。",
    )
    args = parser.parse_args()

    if args.inputs:
        files = [Path(p) for p in args.inputs]
        print("[INFO] 使用命令行指定的输入文件：")
        for p in files:
            print("   -", p)
    else:
        files = find_input_files(DEFAULT_DIR)

    if not files:
        print("[WARN] 没有找到任何可处理的输入文件，脚本结束。")
        return

    for f in files:
        t0_normalize_file(f)


if __name__ == "__main__":
    main()