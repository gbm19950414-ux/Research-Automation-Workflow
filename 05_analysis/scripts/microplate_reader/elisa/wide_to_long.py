#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 8 个并排的 12x8 数据块（第一行为参数名）拆成 96 行 × 8 列的长表。
每个 super block（8行高）→ 96 行；每行包含 8 个参数列。
"""

import pandas as pd
import os

# 固定输入输出路径
INPUT_PATH  = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/EphB1/04_data/raw/microplate_reader/ELISA检测细胞因子/ELISA原始数据.xlsx"
OUTPUT_PATH = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA原始数据_long.xlsx"

# 单元结构
BLOCK_ROWS = 8     # 每个数据块的行数
BLOCK_COLS = 12    # 每个数据块的列数
BLOCKS_PER_UNIT = 8  # 每组实验的块数

def first_nonempty_name(series: pd.Series, default: str) -> str:
    """取一组列名中的第一个非空文本"""
    for x in series:
        if pd.notna(x) and str(x).strip():
            return str(x).strip()
    return default

def make_unique(names):
    """去重名称，重复的加后缀"""
    seen = {}
    out = []
    for n in names:
        k = seen.get(n, 0)
        if k:
            name = f"{n}_{k+1}"
        else:
            name = n
        while name in out:
            k += 1
            name = f"{n}_{k+1}"
        seen[n] = k + 1
        out.append(name)
    return out

def main():
    df = pd.read_excel(INPUT_PATH, sheet_name='Sheet1', header=None)

    # 删除空行空列
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        raise SystemExit("表格为空。")

    # 第1行为参数名
    top  = df.iloc[0, :].copy()
    body = df.iloc[1:, :].copy()

    total_cols = BLOCKS_PER_UNIT * BLOCK_COLS   # 8*12 = 96
    # 只要有至少 total_cols 列，就取前 total_cols 的整数倍，多余的忽略
    if body.shape[1] < total_cols:
        raise SystemExit(f"有效数据列只有 {body.shape[1]}，不足 {total_cols} 列。")

    usable_cols = (body.shape[1] // total_cols) * total_cols
    if body.shape[1] % total_cols != 0:
        print(f"提示：总列数 {body.shape[1]} 不是 {total_cols} 的整数倍，将只处理前 {usable_cols} 列。")

    top  = top.iloc[:usable_cols]
    body = body.iloc[:, :usable_cols]

    usable_rows = (body.shape[0] // BLOCK_ROWS) * BLOCK_ROWS
    if usable_rows == 0:
        raise SystemExit("行数不足 8 的整数倍。")
    if usable_rows != body.shape[0]:
        print(f"警告：仅处理前 {usable_rows} 行。")
    body = body.iloc[:usable_rows, :]

    # 每个实验单元的数量
    n_units = usable_rows // BLOCK_ROWS

    # 获取 8 个参数块的名称
    param_names = []
    for p in range(BLOCKS_PER_UNIT):
        c0, c1 = p * BLOCK_COLS, (p + 1) * BLOCK_COLS
        param_names.append(first_nonempty_name(top.iloc[c0:c1], f"param_{p+1}"))
    param_names = make_unique(param_names)

    # 构建 96 行骨架：row, col, cell_index
    rows = pd.Series(range(1, BLOCK_ROWS + 1), name="row")
    cols = pd.Series(range(1, BLOCK_COLS + 1), name="col")
    base96 = (
        rows.to_frame().assign(key=1)
            .merge(cols.to_frame().assign(key=1), on="key")
            .drop(columns="key")
            .sort_values(["row", "col"], ignore_index=True)
    )
    base96["cell_index"] = (base96["row"] - 1) * BLOCK_COLS + base96["col"]

    all_units = []

    for u in range(n_units):
        r0, r1 = u * BLOCK_ROWS, (u + 1) * BLOCK_ROWS
        band = body.iloc[r0:r1, :].copy()  # 8 x 96

        out_u = base96.copy()
        # 每个参数块取相同位置的值
        for p in range(BLOCKS_PER_UNIT):
            c0, c1 = p * BLOCK_COLS, (p + 1) * BLOCK_COLS
            block = band.iloc[:, c0:c1].copy()
            block.index = range(1, BLOCK_ROWS + 1)
            block.columns = range(1, BLOCK_COLS + 1)
            long_p = (
                block.stack(dropna=False)
                     .rename(param_names[p])
                     .reset_index()
                     .rename(columns={"level_0":"row", "level_1":"col"})
            )
            out_u = out_u.merge(long_p, on=["row", "col"], how="left")

        out_u.insert(0, "matrix_index", u + 1)
        all_units.append(out_u)

    result = pd.concat(all_units, ignore_index=True)
    result = result[["matrix_index", "cell_index", "row", "col"] + param_names]

    result.columns = [str(c).replace('.0','') for c in result.columns]

    # Group by 'batch' column and save each group to separate Excel files
    if 'batch' not in result.columns:
        raise SystemExit("数据中缺少 'batch' 列，无法按批次分组。")

    output_dir = os.path.dirname(OUTPUT_PATH)
    base_filename = os.path.splitext(os.path.basename(OUTPUT_PATH))[0]

    for batch_value, group_df in result.groupby('batch'):
        batch_str = str(batch_value)
        batch_filename = f"{base_filename}_batch_{batch_str}.xlsx"
        batch_path = os.path.join(output_dir, batch_filename)
        group_df.to_excel(batch_path, index=False)

if __name__ == "__main__":
    main()