#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from statannotations.Annotator import Annotator

from pathlib import Path
# === 路径 ===
INPUT_DIR = Path("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子")
OUT_DIR = Path("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/04_data/processed/microplate_reader/ELISA检测细胞因子/figures")
OUT_DIR.mkdir(exist_ok=True)

def main():
    # 遍历所有匹配的输入文件
    for input_file in INPUT_DIR.glob("ELISA_statistic_*_summary.xlsx"):
        # 提取批次名
        fname = input_file.name
        # 例如 ELISA_statistic_E18_summary.xlsx -> E18
        if fname.startswith("ELISA_statistic_") and fname.endswith("_summary.xlsx"):
            batch = fname[len("ELISA_statistic_"):-len("_summary.xlsx")]
        else:
            batch = fname
        print(f"处理批次: {batch}, 文件: {input_file}")

        # === 读入数据 ===
        df = pd.read_excel(input_file, sheet_name="final_values")
        pairs_df = pd.read_excel(input_file, sheet_name="pair_stats")
        # 只保留未剔除的值
        clean = df[df["outlier"] == False].copy()

        # === 绘制每个antibody在不同drug下的WT与HO对比的boxplot ===
        for antibody, sub in clean.groupby("antibody"):
            plt.figure(figsize=(8,5))
            drugs = sorted(sub["drug"].unique())
            sns.boxplot(
                data=sub,
                x="drug",
                y="final_value",
                hue="genotype",         # 按 WT / HO 分色
                palette="Set2",
                linewidth=1.0,
                width=0.6,
                fliersize=0,
                order=drugs
            )
            sns.stripplot(
                data=sub,
                x="drug",
                y="final_value",
                hue="genotype",
                dodge=True,
                palette="dark:0.4",
                linewidth=0.6,
                size=3,
                alpha=0.7,
                legend=False,
                order=drugs
            )
            plt.title(f"{batch}: {antibody}")
            plt.xlabel("Drug")
            plt.ylabel("Final value (a.u.)")
            plt.xticks(rotation=30, ha='right')
            plt.legend(title="Genotype", frameon=False)

            # 从 pair_stats 读取已计算好的 p 值进行显著性标注
            pairs_use, pvals_use = [], []
            for drug in drugs:
                match = pairs_df[(pairs_df["antibody"] == antibody) & (pairs_df["drug"] == drug)]
                if not match.empty and pd.notna(match.iloc[0]["p_value"]):
                    pairs_use.append(((drug, "WT"), (drug, "HO")))
                    pvals_use.append(float(match.iloc[0]["p_value"]))

            if pairs_use:  # 只有在有可用的 p 值时才进行标注
                ax = plt.gca()
                annotator = Annotator(
                    ax, pairs_use,
                    data=sub, x="drug", y="final_value",
                    hue="genotype", order=drugs
                )
                # 使用外部 p 值，不在脚本内做统计检验
                annotator.configure(test=None, text_format="star", loc="inside", verbose=0)
                annotator.set_pvalues_and_annotate(pvalues=pvals_use)

            plt.tight_layout()

            out_file = OUT_DIR / f"{batch}_{antibody}_boxplot.pdf"
            plt.savefig(out_file, dpi=300)
            plt.close()
            print(f"已保存（批次 {batch}）: {out_file}")

        # === 可选：绘制所有 antibody 合并的图 ===
        plt.figure(figsize=(8,5))
        sns.boxplot(
            data=clean,
            x="antibody",
            y="final_value",
            hue="genotype",
            palette="Set2",
            linewidth=1.0,
            width=0.6,
            fliersize=0
        )
        plt.xlabel("Antibody")
        plt.ylabel("Final value (a.u.)")
        plt.legend(title="Genotype", frameon=False)
        plt.tight_layout()
        merged = OUT_DIR / f"{batch}_all_antibodies_boxplot.pdf"
        plt.savefig(merged, dpi=300)
        plt.close()
        print(f"已保存（批次 {batch}）: {merged}")

if __name__ == "__main__":
    main()