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
    input_file = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/raw/qpcr/qpcr_original_data.xlsx"          # 替换为你的文件名
    output_file = '/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/qpcr_original_data_long_format.csv'    # 输出文件名
    convert_plate_excel_to_long(input_file, output_file)
