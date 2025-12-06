#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
003.4_split.py
----------------
用法:
    python 05_analysis/scripts/qpcr/003.4_split.py /path/to/source_file.(csv|xls|xlsx)

功能:
    读取一个包含 qPCR 结果的“整合大表”，
    按 (plate_id, experiment_id, experimental_objective, batch_id, gene) 分组，
    为每个组合导出一个 Excel 文件：

    输出目录:
        <源文件所在目录>/<源文件名>_split/

    输出文件名:
        <plate_id>_<experiment_id>_<experimental_objective>_<batch_id>_<gene>.xlsx

    源文件需要至少包含以下列:
        plate_id, experiment_id, experimental_objective, batch_id,
        sample_id, treatment, component, gene,
        plate_position, mean_cp, std_cp,
        ref_ct, delta_ct, baseline_ct, deltadelta_ct, fold_change, is_outlier
"""

import sys
import os
import re
import pandas as pd


REQUIRED_COLS = [
    "plate_id",
    "experiment_id",
    "experimental_objective",
    "batch_id",
    "sample_id",
    "treatment",
    "component",
    "gene",
    "plate_position",
    "mean_cp",
    "std_cp",
    "ref_ct",
    "delta_ct",
    "baseline_ct",
    "deltadelta_ct",
    "fold_change",
    "is_outlier",
]

GROUP_COLS = [
    "plate_id",
    "experiment_id",
    "experimental_objective",
    "batch_id",
    "gene",
]


def sanitize_for_filename(s: str) -> str:
    """
    将任意字符串转为适合文件名的形式:
    - 去掉首尾空格
    - 将空白字符变成单个下划线
    - 将容易出问题的字符（/ \\ : * ? \" < > |）替换为 _
    """
    if s is None:
        return "NA"
    s = str(s).strip()
    if not s:
        return "NA"
    # 合并空白为单个下划线
    s = re.sub(r"\s+", "_", s)
    # 替换非法字符
    s = re.sub(r"[\\/:\*\?\"<>\|]", "_", s)
    return s


def read_source(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"不支持的文件类型: {ext} (只支持 .csv/.xls/.xlsx)")
    return df


def check_required_cols(df: pd.DataFrame, path: str) -> None:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"文件缺少必要列: {missing}\n文件: {path}")


def split_file(src_path: str) -> None:
    print(f"[INFO] 读取源文件: {src_path}")
    df = read_source(src_path)
    check_required_cols(df, src_path)

    # 输出目录: <src_dir>/<src_basename>_split/
    src_dir = os.path.dirname(os.path.abspath(src_path))
    base_name = os.path.splitext(os.path.basename(src_path))[0]
    out_dir = os.path.join(src_dir, base_name + "_split")
    os.makedirs(out_dir, exist_ok=True)

    if df.empty:
        print("[WARN] 源文件为空，不进行拆分。")
        return

    # 按组拆分
    grouped = df.groupby(GROUP_COLS, dropna=False)

    n_groups = 0
    n_rows_total = len(df)
    print(f"[INFO] 总行数: {n_rows_total}")
    print(f"[INFO] 按 {GROUP_COLS} 分组输出到: {out_dir}")

    for key, subdf in grouped:
        # key 是一个元组，对应 GROUP_COLS 的顺序
        key_dict = dict(zip(GROUP_COLS, key))

        # 构造文件名
        name_parts = [
            sanitize_for_filename(key_dict.get("plate_id", "NA")),
            sanitize_for_filename(key_dict.get("experiment_id", "NA")),
            sanitize_for_filename(key_dict.get("experimental_objective", "NA")),
            sanitize_for_filename(key_dict.get("batch_id", "NA")),
            sanitize_for_filename(key_dict.get("gene", "NA")),
        ]
        fname = "_".join(name_parts) + ".xlsx"
        out_path = os.path.join(out_dir, fname)

        # 写出 Excel
        subdf_sorted = subdf.sort_values(
            by=["sample_id", "treatment", "component", "plate_position"],
            kind="mergesort",
        )
        subdf_sorted.to_excel(out_path, index=False)

        n_groups += 1
        print(f"  [OK] {fname}  (rows={len(subdf_sorted)})")

    print(f"[DONE] 共输出 {n_groups} 个文件，目录: {out_dir}")


def main():
    if len(sys.argv) != 2:
        print("用法: python 05_analysis/scripts/qpcr/003.4_split.py /path/to/source_file.(csv|xls|xlsx)")
        sys.exit(1)

    src_path = sys.argv[1]
    if not os.path.isfile(src_path):
        print(f"错误: 找不到源文件: {src_path}")
        sys.exit(1)

    try:
        split_file(src_path)
    except Exception as e:
        print(f"[ERROR] 处理失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()