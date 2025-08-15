# -*- coding: utf-8 -*-
from pathlib import Path
import pandas as pd

# ==== 配置（相对项目根目录）====
# 脚本位于 05_analysis/scripts/ 下时，项目根目录是上上级
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_XLSX = PROJECT_ROOT / "04_data" / "raw" / "qpcr" / "qpcr_original_data.xlsx"
OUTPUT_CSV = PROJECT_ROOT / "04_data" / "raw" / "qpcr" / "gene_names_with_rows.csv"

# H–AK: 3列×10块 = 30 列；每块高 13 行
START_COL = 7    # H 列的 0-based 索引
END_COL   = 36   # AK 列的 0-based 索引
BLOCK_W   = 3
BLOCK_H   = 13
BLOCKS_PER_ROW = 10
# ==============================

def main():
    # 不把第一行当表头，避免列名干扰；用整数索引
    df = pd.read_excel(INPUT_XLSX, header=None, engine="openpyxl")

    rows_out = []
    n_rows = df.shape[0]

    # 纵向按 13 行一块扫描
    for r0 in range(0, n_rows, BLOCK_H):
        # 横向 10 个块（3列为一块）
        for b in range(BLOCKS_PER_ROW):
            c0 = START_COL + b * BLOCK_W
            if c0 + 2 > END_COL or r0 >= n_rows:
                continue
            # 取该块第一行的三个单元格（重复），容错地优先取非空值
            candidates = [df.iat[r0, c0], df.iat[r0, c0 + 1], df.iat[r0, c0 + 2]]
            val = next((v for v in candidates if pd.notna(v)), None)
            # Excel 行号（header=None 时，0-based 行索引 + 1）
            excel_row = r0 + 1
            rows_out.append({"gene_name": (str(val).strip() if val is not None else None),
                             "excel_row": excel_row})

    out = pd.DataFrame(rows_out)

    # 按基因名排序（不区分大小写；空值放最后）
    if not out.empty:
        key = out["gene_name"].fillna("")
        out = out.sort_values(by="gene_name", key=lambda s: key.str.upper()).reset_index(drop=True)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ 提取完成：共 {len(out)} 个块，已保存到 {OUTPUT_CSV}")

if __name__ == "__main__":
    main()