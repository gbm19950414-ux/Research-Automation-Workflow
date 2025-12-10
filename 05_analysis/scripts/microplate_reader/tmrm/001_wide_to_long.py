#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# 说明：本脚本不限制输入文件名称，但要求输入为 Excel 文件 (.xlsx)
# 输入文件格式要求：
#   - 前 7 列必须为参数列（例如：Sample, Condition, Time, 等）
#   - 第 8 列之后所有列将被视为需要熔融的检测值列
#
# 如何使用（有两种方式）：
#   1）直接使用默认路径（不带任何参数）：
#       python 001_wide_to_long.py
#      将会自动读取：
#       04_data/raw/microplate_reader/ros染色间接检测线粒体损伤/线粒体完整性检测_数据汇总.xlsx
#      并写出到：
#       04_data/interim/microplate_reader/线粒体完整性检测/线粒体完整性检测_数据汇总_long.xlsx
#
#   2）手动指定输入/输出：
#       python 001_wide_to_long.py 输入文件.xlsx [输出文件.xlsx]
#
#   若不提供输出文件路径（方式 2 中），则会自动在同目录生成：
#       输入文件名_long.xlsx
#
# 输出文件内容：
#   - gene  ：原列名（H 列以后所有列）
#   - value ：对应的检测值
#   - 参数列保持不变
# ------------------------------------------------------------
# 用法示例：python wide_to_long.py data.xlsx /Users/你/路径/out.xlsx 
# 输出文件就会直接写到 /Users/你/路径/out.xlsx
import sys
import pandas as pd
from pathlib import Path

def wide_to_long(input_path: str, output_path: str = None):
    in_path = Path(input_path)
    df = pd.read_excel(in_path)

    if df.shape[1] <= 7:
        raise ValueError("列数不足：至少需要8列（A-G为参数列，H及以后为检测值列）。")

    id_vars = list(df.columns[:7])
    value_vars = list(df.columns[7:])

    # 熔融为长表
    df_long = df.melt(
        id_vars=id_vars,
        value_vars=value_vars,
        var_name="gene",   # 改成 gene
        value_name="value" # 改成 value
    )

    if output_path is None:
        out_path = in_path.with_name(in_path.stem + "_long.xlsx")
    else:
        out_path = Path(output_path)

    df_long.to_excel(out_path, index=False)
    return df_long, out_path

def main():
    # 默认路径（用户未提供参数时使用）
    default_input = "04_data/raw/microplate_reader/ros染色间接检测线粒体损伤/线粒体完整性检测_数据汇总.xlsx"
    default_output = "04_data/interim/microplate_reader/线粒体完整性检测/线粒体完整性检测_数据汇总_long.xlsx"

    if len(sys.argv) == 1:
        # 无参数 → 使用默认路径
        input_xlsx = default_input
        output_xlsx = default_output
        print(f"未提供输入参数，使用默认文件：\n  输入: {input_xlsx}\n  输出: {output_xlsx}")
    else:
        # 有参数 → 使用用户输入（保留原有用法）
        if len(sys.argv) < 2:
            print("用法: python wide_to_long.py 输入文件.xlsx [输出文件.xlsx]")
            sys.exit(1)
        input_xlsx = sys.argv[1]
        output_xlsx = sys.argv[2] if len(sys.argv) >= 3 else None

    df_long, out_path = wide_to_long(input_xlsx, output_xlsx)
    print(f"已写出: {out_path}，行数: {len(df_long)}")

if __name__ == "__main__":
    main()