#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
002a_blank_correction.py
=====================================
功能：对线粒体完整性检测的微孔板数据进行「blank 背景矫正」。

工作流角色：
- 输入：001_wide_to_long.py 输出的长表文件
    04_data/interim/microplate_reader/线粒体完整性检测/线粒体完整性检测_数据汇总_long.xlsx

- 按「同 sample_batch + 同 dye」作为一个模块进行矫正和输出：

    1）在该模块中，找到 group == "blank" 的行，
       在「同一时间点 + （可选）同一基因型 + 同一 gene」的粒度上，计算 value 的平均值 → 作为该批次的通用 blank_mean；
    2）然后在该批次下、具体某个染料模块 (batch + dye) 内，对 group == "experiment" 的行，
       找到相应时间点 +（可选）基因型 + gene 的 blank_mean，计算
       value_corrected = value - blank_mean；
    3）把结果按「批次 × 染料」拆分为多个文件写出。

- 输出目录（默认）：
    04_data/interim/microplate_reader/线粒体完整性检测/

列名假定（如与你的表不一致，可在脚本中修改默认列名常量）：
    batch_col   = "sample_batch"   # 批次
    dye_col     = "dye"            # 染料
    group_col   = "group"          # blank / experiment
    geno_col    = None             # 基因型列名（如 "genotype"，若没有基因型维度，可设为 None）
    time_col    = "time_point"     # 时间点
    gene_col    = "gene"           # 从 001 脚本 melt 后的指标名列
    value_col   = "value"          # 数值列

使用方法：
    1）使用默认输入/输出（推荐）：
        python 002a_blank_correction.py

    2）手动指定输入文件（输出目录仍使用默认）：
        python 002a_blank_correction.py 输入文件.xlsx

    3）手动指定输入文件和输出目录：
        python 002a_blank_correction.py 输入文件.xlsx 输出目录

输出文件命名示例：
    线粒体完整性检测_blank_corrected_batch-<批次>_dye-<染料>.xlsx
"""

import sys
from pathlib import Path
import pandas as pd

# ========================
# 路径 & 列名默认设置
# ========================

DEFAULT_INPUT = Path(
    "04_data/interim/microplate_reader/线粒体完整性检测/线粒体完整性检测_数据汇总_long.xlsx"
)
DEFAULT_OUTPUT_DIR = Path(
    "04_data/interim/microplate_reader/线粒体完整性检测"
)

# 根据你实际表头需要，修改下面这些列名
BATCH_COL = "sample_batch"
DYE_COL = "dye"
GROUP_COL = "group"
GENO_COL = None  # 若有基因型列，例如 "genotype"，在此填写列名；当前数据无基因型维度，设为 None
TIME_COL = "time_point"
GENE_COL = "gene"
VALUE_COL = "value"

GROUP_BLANK = "blank"
GROUP_EXPERIMENT = "experiment"


def ensure_dir(path: Path):
    """若目录不存在则创建"""
    path.mkdir(parents=True, exist_ok=True)


def blank_correction(
    input_path: Path,
    output_dir: Path,
    batch_col: str = BATCH_COL,
    dye_col: str = DYE_COL,
    group_col: str = GROUP_COL,
    geno_col = GENO_COL,
    time_col: str = TIME_COL,
    gene_col: str = GENE_COL,
    value_col: str = VALUE_COL,
    group_blank: str = GROUP_BLANK,
    group_exp: str = GROUP_EXPERIMENT,
):
    """对一个长表文件进行 blank 背景矫正，并按批次×染料输出。"""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    ensure_dir(output_dir)

    print(f"[INFO] 读取输入文件: {input_path}")
    df = pd.read_excel(input_path)

    # 检查必需列
    required_cols = [
        batch_col, dye_col, group_col,
        time_col, gene_col, value_col
    ]
    if geno_col is not None:
        required_cols.append(geno_col)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"下列必需列在输入表中缺失：{missing}")

    # 找到所有 (batch, dye) 组合
    modules = df[[batch_col, dye_col]].drop_duplicates()

    if modules.empty:
        print("[WARN] 未找到任何 batch × dye 组合，检查输入数据是否为空。")
        return

    print(f"[INFO] 共检测到 {len(modules)} 个 batch × dye 组合，将分别输出。")

    for _, row in modules.iterrows():
        batch_val = row[batch_col]
        dye_val = row[dye_col]

        print(f"\n[INFO] 处理模块：batch = {batch_val}, dye = {dye_val}")

        # 当前模块内所有行（含 blank 和 experiment），按 batch + dye 取子集
        mask_bd = (df[batch_col] == batch_val) & (df[dye_col] == dye_val)
        df_bd = df.loc[mask_bd].copy()

        # 1) 计算 blank_mean：在当前模块内，仅使用 group == blank 的行
        df_blank = df_bd[df_bd[group_col] == group_blank].copy()
        if df_blank.empty:
            print("  [WARN] 该模块中没有 group=blank 的行，无法进行背景矫正，只导出原始数据。")
            out_df = df_bd.copy()
            # 输出原始数据
            _write_module_output(
                out_df, output_dir, batch_val, dye_val, suffix="raw_no_blank"
            )
            continue

        # 按 time +（可选）genotype + gene 求 mean(value)
        group_keys = [time_col, gene_col]
        if geno_col is not None:
            group_keys.insert(1, geno_col)

        blank_mean = (
            df_blank
            .groupby(group_keys, dropna=False)[value_col]
            .mean()
            .reset_index()
            .rename(columns={value_col: "blank_mean"})
        )

        # 2) 对非 blank 行（experiment / negative / positive 等）做矫正
        df_exp = df_bd[df_bd[group_col] != group_blank].copy()
        if df_exp.empty:
            print("  [WARN] 该模块中只有 blank 行，无需矫正，直接导出。")
            out_df = df_bd.copy()
            _write_module_output(
                out_df, output_dir, batch_val, dye_val, suffix="only_blank"
            )
            continue

        merge_keys = [time_col, gene_col]
        if geno_col is not None:
            merge_keys.insert(1, geno_col)

        df_exp = df_exp.merge(
            blank_mean,
            on=merge_keys,
            how="left"
        )

        # 计算背景矫正值
        df_exp["value_corrected"] = df_exp[value_col] - df_exp["blank_mean"]

        # 3) 组合输出：
        #    - 保留 experiment 行（含 corrected）
        #    - 也可以选择是否同时保留 blank 行，这里一起导出，方便检查
        df_out = pd.concat(
            [df_exp, df_blank],
            ignore_index=True,
            sort=False
        )

        # 输出
        _write_module_output(df_out, output_dir, batch_val, dye_val, suffix="blank_corrected")


def _sanitize_for_filename(x) -> str:
    """把 batch / dye 里的特殊字符替换掉，避免文件名非法。"""
    s = str(x)
    for ch in ["/", "\\", " ", ":", "*", "?", "\"", "<", ">", "|"]:
        s = s.replace(ch, "_")
    return s


def _write_module_output(df_out: pd.DataFrame, output_dir: Path, batch_val, dye_val, suffix: str):
    """按 batch × dye 写出一个 Excel 文件。"""
    batch_str = _sanitize_for_filename(batch_val)
    dye_str = _sanitize_for_filename(dye_val)

    fname = f"线粒体完整性检测_{suffix}_batch-{batch_str}_dye-{dye_str}.xlsx"
    out_path = output_dir / fname

    print(f"  [INFO] 写出文件: {out_path} (共 {len(df_out)} 行)")
    df_out.to_excel(out_path, index=False)


def main():
    # 解析命令行参数
    if len(sys.argv) == 1:
        # 使用默认路径
        input_path = DEFAULT_INPUT
        output_dir = DEFAULT_OUTPUT_DIR
        print("[INFO] 未提供参数，使用默认输入/输出路径：")
        print(f"       输入: {input_path}")
        print(f"       输出目录: {output_dir}")
    elif len(sys.argv) == 2:
        input_path = Path(sys.argv[1])
        output_dir = DEFAULT_OUTPUT_DIR
        print("[INFO] 使用自定义输入文件 + 默认输出目录：")
        print(f"       输入: {input_path}")
        print(f"       输出目录: {output_dir}")
    else:
        input_path = Path(sys.argv[1])
        output_dir = Path(sys.argv[2])
        print("[INFO] 使用自定义输入文件 + 自定义输出目录：")
        print(f"       输入: {input_path}")
        print(f"       输出目录: {output_dir}")

    blank_correction(input_path, output_dir)


if __name__ == "__main__":
    main()