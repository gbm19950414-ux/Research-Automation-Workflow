#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗脚本
=========================
功能：
    1. 读取长格式 Excel 数据。
    2. 按用户指定条件筛选（默认 drug=null, dye=tmrm）。
    3. 按 sample_batch + drug + dye + Dye_concentration + Dye_time 分组拆分，并输出 Excel 文件。
       文件名仅保留这几个值，用下划线连接，不含参数名称，以避免过长路径问题。

用法示例：
    python clean_data.py /path/to/线粒体完整性检测_数据汇总_long.xlsx
    python clean_data.py /path/to/线粒体完整性检测_数据汇总_long.xlsx --output_dir /Users/gongbaoming/Desktop/test_output
"""

import argparse
import re
import traceback
from pathlib import Path
import pandas as pd


def safe_filename(name: str) -> str:
    """替换文件名中不被系统支持的字符，并控制长度"""
    safe = re.sub(r'[\\/:"*?<>|]+', '_', str(name))
    return safe[:150]


def clean_data(input_file: str,
               output_dir: str = None,
               drug: str = "null",
               dye: str = "tmrm"):
    # 你原先的默认输出路径（保留不变）
    default_output = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/"
                          "发育生物所/博士课题/EphB1/04_data/interim/"
                          "microplate_reader/线粒体完整性检测")
    # 若更通用：也可用输入文件同目录 → in_path.parent / f"{in_path.stem}_split"

    in_path = Path(input_file)
    if not in_path.exists():
        raise FileNotFoundError(f"未找到输入文件: {in_path}")

    out_dir = Path(output_dir) if output_dir else default_output
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {out_dir}")

    df = pd.read_excel(in_path)

    # （可选但推荐）列存在性检查
    required_cols = ["sample_batch", "drug", "dye", "Dye_concentration", "Dye_time"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise KeyError(f"缺少列: {missing}")

    # 构造筛选条件：drug=null 视为空值 或 文本 'null'
    if (drug is None) or (str(drug).strip().lower() in {"null", "none", "nan", ""}):
        drug_mask = df["drug"].isna() | (df["drug"].astype(str).str.lower() == "null")
    else:
        drug_mask = df["drug"].astype(str).str.lower() == str(drug).strip().lower()

    dye_mask = df["dye"].astype(str).str.lower() == str(dye).strip().lower()
    df_filtered = df[drug_mask & dye_mask].copy()
    print(f"匹配行数: {len(df_filtered)}")

    if df_filtered.empty:
        print("没有匹配到数据，请检查筛选条件。")
        return

    group_cols = ["sample_batch", "drug", "dye", "Dye_concentration", "Dye_time"]

    # 关键：保留含 NaN 的分组（否则 groupby 会丢掉 drug=NaN 的组）
    for keys, group in df_filtered.groupby(group_cols, dropna=False):
        # keys 顺序与 group_cols 对齐
        sb, dr, dy, conc, tm = keys
        # === 新增：把原始 df 中“相同 sample_batch 且 group=blank”的行追加进来 ===
        blank_rows = df[(df["sample_batch"] == sb) & (df["group"].astype(str).str.strip().str.lower() == "blank")].copy()
        out_df = pd.concat([group, blank_rows], ignore_index=True).drop_duplicates()
        # === 新增结束 ===
        # 文件名为值本身，给 NaN 指定占位符：drug 空→'null'，其余空→'NA'
        parts = [
            str(sb)   if pd.notna(sb)   else "NA",
            str(dr)   if pd.notna(dr)   else "null",
            str(dy)   if pd.notna(dy)   else "NA",
            str(conc) if pd.notna(conc) else "NA",
            str(tm)   if pd.notna(tm)   else "NA",
        ]
        fname = safe_filename("_".join(parts) + ".xlsx")
        out_path = out_dir / fname

        try:
            print(f"开始写文件: {out_path}")   # 调试输出
            out_df.to_excel(out_path, index=False)
            print(f"写文件结束: {out_path}, 行数: {len(out_df)}")
        except Exception as e:
            print(f"写文件失败: {out_path}\n错误信息: {e}\n{traceback.format_exc()}")


def main():
    parser = argparse.ArgumentParser(description="按条件清洗并拆分数据")
    parser.add_argument("input", help="输入 Excel 文件路径")
    parser.add_argument("--output_dir", default=None, help="输出目录（默认写入脚本中设定的路径）")
    parser.add_argument("--drug", default="null", help="筛选 drug，默认 null")
    parser.add_argument("--dye", default="tmrm", help="筛选 dye，默认 tmrm")
    args = parser.parse_args()

    clean_data(input_file=args.input,
               output_dir=args.output_dir,
               drug=args.drug,
               dye=args.dye)


if __name__ == "__main__":
    main()