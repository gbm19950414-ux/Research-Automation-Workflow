"""
本脚本用于将 qPCR 原始汇总 Excel（宽格式、多基因成组排列）转换为规范的长格式文本（CSV），以便后续进行统计分析、清洗、ΔCt/ΔΔCt 计算和绘图。

【脚本工作流程说明】
1. **读取输入 Excel 文件（宽格式）**：
   - Excel 文件按板子逐块存储，每一块固定高度为 13 行（BLOCK_ROWS）。
   - 每块中前 7 列（META_COLS）为元信息，包括 plate_id、sample_id 等。
   - 后续的列按基因为单位，每个基因占 3 列（plate_position / mean_cp / std_cp）。

2. **按板块（block）遍历 Excel**：
   - 以 13 行为步长，从上到下切分整个表格。
   - 若遇到不足 13 行的残块（不完整板子），跳过。

3. **提取基因名称**：
   - 在每块的第 1 行（block.iloc[0]）解析基因名称。
   - 每 3 列组成一组（plate_position / mean_cp / std_cp），在组的中间列读取基因名。
   - 若基因名缺失，则自动设为 Unknown_xx。

4. **逐行转换为长格式记录**：
   - 从第 2 行开始（真实样本行），逐行读取元信息：
     plate_id、experiment_id、experimental_objective、batch_id、sample_id、treatment、component。
   - 为该行的每个基因创建一条记录，包含：
     gene、plate_position、mean_cp、std_cp。

5. **汇总所有记录并导出 CSV**：
   - 所有板块全部展开为记录字典列表。
   - 最终生成规范的长格式 DataFrame 并写出 CSV 文件（UTF‑8‑SIG 编码）。

【适用场景】
- 与脚本 001 配合使用，将宽格式的 qPCR 原始排版表自动转成长格式用于后续统计。
- 方便在 R/Python 中进行 ΔCt、ΔΔCt、2^-ΔΔCt、显著性检验、绘图等分析。

"""
import pandas as pd

def convert_plate_excel_to_long(input_file, output_file):
    df = pd.read_excel(input_file, header=None)
    records = []

    BLOCK_ROWS = 13
    META_COLS = 7               # ⚠️ 增加到 7 列（包括 plate_id）
    GENE_GROUP = 3
    TOTAL_COLS = df.shape[1]
    num_rows = df.shape[0]

    for start_row in range(0, num_rows, BLOCK_ROWS):
        block = df.iloc[start_row:start_row + BLOCK_ROWS, :]
        if block.shape[0] < BLOCK_ROWS:
            continue  # 不完整的板块跳过

        # 获取 gene 名称
        gene_names = []
        for col in range(META_COLS, TOTAL_COLS, GENE_GROUP):
            gene = block.iloc[0, col + 1]  # mean_cp 所在列为中心
            if pd.isna(gene):
                gene = f"Unknown_{col}"
            gene_names.append((gene, col))

        # 逐行提取样本
        for i in range(1, BLOCK_ROWS):  # 跳过第1行标题
            row = block.iloc[i]
            plate_id = row[0]
            experiment_id = row[1]
            experimental_objective = row[2]
            batch_id = row[3]
            sample_id = row[4]
            treatment = row[5]
            component = row[6]

            for gene, col in gene_names:
                plate_pos = row[col]
                mean_cp   = row[col + 1]
                std_cp    = row[col + 2]

                records.append({
                    "plate_id": plate_id,
                    "experiment_id": experiment_id,
                    "experimental_objective": experimental_objective,
                    "batch_id": batch_id,
                    "sample_id": sample_id,
                    "treatment": treatment,
                    "component": component,
                    "gene": gene,
                    "plate_position": plate_pos,
                    "mean_cp": mean_cp,
                    "std_cp": std_cp
                })

    df_long = pd.DataFrame(records)
    df_long.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"✅ 导出成功：{output_file}")

if __name__ == "__main__":
    input_file = "04_data/raw/qpcr/qpcr_original_data.xlsx"          # 替换为你的文件名
    output_file = '04_data/interim/qpcr/qpcr_original_data_long_format.csv'    # 输出文件名
    convert_plate_excel_to_long(input_file, output_file)
