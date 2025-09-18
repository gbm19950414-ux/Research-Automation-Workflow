#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 *_stats.xlsx 生成 Nature 风格的带散点箱线图。

用法：
    python3 plot_box_normalized.py /path/to/E32_stats.xlsx /path/to/output_folder
输出：
    /path/to/output_folder/<文件名>_boxplot.pdf
"""

import sys, os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import yaml
from statannotations.Annotator import Annotator
# === 外观指南的绝对路径 ===
STYLE_FILE = "/Users/gongbaoming/Library/Mobile Documents/com~apple~CloudDocs/phd_thesis/方法/外观指南.yaml"

def main():
    # 解析命令行参数
    if len(sys.argv) < 3:
        print("用法: python3 plot_box_normalized.py /path/to/E32_stats1.xlsx [/path/to/E32_stats2.xlsx ...] /path/to/output_folder")
        sys.exit(1)

    # 最后一个参数是输出目录，其余都是输入文件
    *data_files, out_dir = sys.argv[1:]
    out_dir = os.path.abspath(out_dir)

    if not os.path.isdir(out_dir):
        print(f"输出文件夹不存在: {out_dir}")
        sys.exit(1)

    # 逐一处理每个输入文件
    for f in data_files:
        data_file = os.path.abspath(f)
        if not os.path.isfile(data_file):
            print(f"输入文件不存在: {data_file}")
            continue

        # === 读取数据与外观指南 ===
        df_data = pd.read_excel(data_file, sheet_name="data")
        df_stats = pd.read_excel(data_file, sheet_name="pair_stats")
        with open(STYLE_FILE, "r", encoding="utf-8") as y:
            guide = yaml.safe_load(y)

        # === 应用 Nature 风格 ===
        plt.rcParams.update(guide["rcparams"])

        # === 数据预处理 ===
        df_data["x_label"] = df_data.apply(
            lambda r: r["drug"] if str(r["group"]).lower() == "experiment" else r["group"],
            axis=1
        )
        # 如果 drug 整列为空，则直接用 group 作为 x_label
        if df_data["drug"].isna().all() or (df_data["drug"].astype(str).str.strip() == "").all():
            df_data["x_label"] = df_data["group"]
            use_group_only = True
        else:
            use_group_only = False

        # === 绘制箱线图 ===
        fig, ax = plt.subplots()
        sns.boxplot(
            data=df_data, x="x_label", y="normalized", hue="genetype",
            palette=guide["color"]["palette"], ax=ax, fliersize=0.5
        )
        sns.stripplot(
            data=df_data, x="x_label", y="normalized", hue="genetype",
            dodge=True, palette=guide["color"]["palette"], size=1.5, ax=ax
        )
        # === 基于 p_value 的显著性标注 ===
        pairs = []
        pvals = []
        # 如果 pair_stats 存在则使用它
        if not df_stats.empty:
            for _, row in df_stats.iterrows():
                label = row["drug"] if str(row["group"]).lower() == "experiment" else row["group"]
                pairs.append(((label, "WT"), (label, "HO")))
                pvals.append(row["p_value"])
        if pairs:
            annot = Annotator(ax, pairs, data=df_data,
                              x="x_label", y="normalized", hue="genetype")
            annot.configure(test=None, text_format="star",
                            loc="inside", line_height=0.02)
            annot.set_pvalues(pvals)
            annot.annotate()
        # 处理图例去重
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles[:2], labels[:2],
                  frameon=guide["legend"]["frameon"],
                  fontsize=guide["legend"]["fontsize_pt"])

        # 坐标轴标签
        ax.set_xlabel("Group / Drug")
        ax.set_ylabel("Normalized (a.u.)")

        # 解决横坐标标签重叠：旋转 45° 并右对齐
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

        plt.tight_layout()
        # === 保存 PDF ===
        base = os.path.splitext(os.path.basename(data_file))[0]
        out_path = os.path.join(out_dir, f"{base}_boxplot.pdf")
        plt.savefig(out_path, dpi=guide["export"]["dpi"])
        plt.close()
        print(f"图像已保存到：{out_path}")
if __name__ == "__main__":
    main()