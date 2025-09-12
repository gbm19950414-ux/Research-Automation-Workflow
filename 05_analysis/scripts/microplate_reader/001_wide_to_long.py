#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
    if len(sys.argv) < 2:
        print("用法: python wide_to_long.py 输入文件.xlsx [输出文件.xlsx]")
        sys.exit(1)
    input_xlsx = sys.argv[1]
    output_xlsx = sys.argv[2] if len(sys.argv) >= 3 else None
    df_long, out_path = wide_to_long(input_xlsx, output_xlsx)
    print(f"已写出: {out_path}，行数: {len(df_long)}")

if __name__ == "__main__":
    main()