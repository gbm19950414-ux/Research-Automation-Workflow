#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ELISA 数据统计流程：
1. 背景矫正
   - 在相同 matrix_index 中：
       * 找 cell为空 且 group 不包含 'sc' 的行，求 450 平均 → 450 背景
       * 450 - 450背景 → 450_bg_correct
       * 求 570 平均 → 570 背景
       * 570 - 570背景 → 570_bg_correct
       * 450_bg_correct - 570_bg_correct → absorbance_correct
2. 标准曲线矫正
   - 提取 group 包含 'sc' 的行。
   - 按 group 名升序、antibody 分组，计算 absorbance_correct 的平均。
   - 8 个检测值对应浓度 [1000,500,250,125,62.5,31.25,15.625,7.8125] ng/ml。
   - 每个 matrix_index & antibody 拟合线性标准曲线 (浓度 vs absorbance_correct)。
   - 将 cell='pm' 的 absorbance_correct 代入曲线公式 → std_curve_correct。
3. MTT 背景矫正
   - 在相同 matrix_index 中：
       * 找 cell为空 的行求 580 平均 → 580 背景
       * 580 - 580背景 → 580_bg_correct
       * cell='pm' 的 580_bg_correct 求中位数 → mtt_median
       * 580_bg_correct / mtt_median → mtt_factor
4. 最终值
   - 对 cell='pm' 的行：std_curve_correct / mtt_factor → final_value
输出：增加所有中间矫正列和最终结果列。
"""

import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.linear_model import LinearRegression
from scipy.optimize import curve_fit

# 输入/输出路径
INPUT_PATH  = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA原始数据_long.xlsx"
OUTPUT_PATH = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA_statistic.xlsx"

def four_pl(x, A, B, C, D):
    return D + (A - D) / (1 + (x / C)**B)

def main():
    df = pd.read_excel(INPUT_PATH)

    # 确保需要的列存在
    required = {"matrix_index","cell","group","antibody","450","570","580"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"缺少必要列: {missing}")

    # -------- 1. 背景矫正 --------
    def bg_correct(group_df):
        # 背景条件：cell 为空 & group 不含 sc
        bg_mask = group_df['cell'].isna() & ~group_df['group'].str.contains('sc', case=False, na=False)
        bg_450 = group_df.loc[bg_mask, '450'].mean()
        bg_570 = group_df.loc[bg_mask, '570'].mean()
        group_df['450_bg_correct'] = group_df['450'] - bg_450
        group_df['570_bg_correct'] = group_df['570'] - bg_570
        group_df['absorbance_correct'] = group_df['450_bg_correct'] - group_df['570_bg_correct']
        return group_df

    df = df.groupby('matrix_index', group_keys=False).apply(bg_correct)

    # -------- 2. 标准曲线矫正 --------
    std_conc = np.array([1000,500,250,125,62.5,31.25,15.625,7.8125])

    def std_curve_correct(group_df):
        std_rows = group_df[group_df['group'].str.contains('sc', case=False, na=False)]
        if std_rows.empty:
            group_df['std_curve_correct'] = np.nan
            return group_df
        std_means = (std_rows.groupby(['antibody','group'])['absorbance_correct']
                               .mean().reset_index())
        std_means = std_means.sort_values(['antibody','group'])

        pred = []
        for ab, gdf in group_df.groupby('antibody'):
            std_sub = std_means[std_means['antibody'] == ab]
            if len(std_sub) < 4:  # 至少4个点更稳
                pred.append(pd.Series(np.nan, index=gdf.index))
                continue
            x = np.array([1000,500,250,125,62.5,31.25,15.625,7.8125][:len(std_sub)])
            y = std_sub['absorbance_correct'].values
            # 初始值
            A0, D0 = y.max(), y.min()
            B0, C0 = 1.0, np.median(x)
            p0 = [A0, B0, C0, D0]
            try:
                popt, _ = curve_fit(four_pl, x, y, p0=p0, maxfev=20000)
            except RuntimeError:
                pred.append(pd.Series(np.nan, index=gdf.index))
                continue
            A, B, C, D = popt
            # 反解浓度
            def invert_4pl(yq):
                with np.errstate(divide='ignore', invalid='ignore'):
                    return C * np.power(( (A - D) / (yq - D) - 1 ), 1.0 / B)
            pred.append(pd.Series(invert_4pl(gdf['absorbance_correct'].values),
                                  index=gdf.index))
        group_df['std_curve_correct'] = pd.concat(pred).sort_index()
        return group_df

    df = df.groupby('matrix_index', group_keys=False).apply(std_curve_correct)

    # -------- 3. MTT 背景矫正 --------
    def mtt_correct(group_df):
        bg_mask = group_df['cell'].isna()
        bg_580 = group_df.loc[bg_mask, '580'].mean()
        group_df['580_bg_correct'] = group_df['580'] - bg_580
        # cell='pm' 的 580 背景矫正中位数
        pm_mask = group_df['cell'].eq('pm')
        mtt_median = group_df.loc[pm_mask, '580_bg_correct'].median()
        group_df['mtt_factor'] = group_df['580_bg_correct'] / mtt_median if mtt_median and not np.isnan(mtt_median) else np.nan
        return group_df

    df = df.groupby('matrix_index', group_keys=False).apply(mtt_correct)

    # -------- 4. 最终值 --------
    df['final_value'] = df['std_curve_correct'] / df['mtt_factor']

    # 保存结果
    out_path = Path(OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    print(f"处理完成，结果已保存到 {out_path}")

if __name__ == "__main__":
    main()