#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ELISA 数据统计流程：
1. 背景矫正
   - 在相同 matrix_index 中：
       * 找 genotype 为空 且 group 不包含 'sc' 的行，求 450 平均 → 450 背景
       * 450 - 450背景 → 450_bg_correct
       * 求 570 平均 → 570 背景
       * 570 - 570背景 → 570_bg_correct
       * 450_bg_correct - 570_bg_correct → absorbance_correct
2. 标准曲线矫正（**二次多项式**）
   - 提取 group 包含 'sc' 的行。
   - 按 group 名升序、antibody 分组，计算 absorbance_correct 的平均。
   - 8 个检测点对应浓度 [1000,500,250,125,62.5,31.25,15.625,7.8125] ng/ml。
   - 每个 batch & antibody 用 **二次多项式**拟合：
     浓度 = a*(吸光度)^2 + b*(吸光度) + c（使用 `np.polyfit(y=吸光度, x=浓度, deg=2)`）。
   - 将同一 batch 内该 antibody 的所有 **非 sc** 行的 absorbance_correct 直接代入该多项式，得到 std_curve_correct（不做范围裁剪）。
3. MTT 背景矫正
   - 在相同 matrix_index 中：
       * 找 genotype 为空 的行求 580 平均 → 580 背景
       * 580 - 580背景 → 580_bg_correct
       * 有细胞的孔（genotype∈{wt,ho}）的 580_bg_correct 求中位数 → mtt_median
       * 580_bg_correct / mtt_median → mtt_factor
4. 最终值
   - 对有细胞的行（genotype∈{wt,ho}）：std_curve_correct / mtt_factor → final_value
输出：增加所有中间矫正列和最终结果列。
"""

import pandas as pd
import numpy as np
from pathlib import Path

# 配置项：是否让所有批次的 IL-1β 使用 batch1 的标准曲线
USE_BATCH1_STD_FOR_IL1B = True  # 需要启用时改为 True
IL1B_STD_BATCH_NAME = "E1"   # 作为“标准曲线来源”的 batch 名称
IL1B_ANTIBODY_NAME = "il1b"      # il1b 对应的 antibody 名称（区分大小写与否在后面处理）

def four_pl(x, A, B, C, D):
    return D + (A - D) / (1 + (x / C)**B)

def bg_correct(group_df):
    # 背景条件：genotype 为空 & group 不含 sc
    bg_mask = group_df['genotype'].isna() & ~group_df['group'].str.contains('sc', case=False, na=False)
    bg_450 = group_df.loc[bg_mask, '450'].mean()
    bg_570 = group_df.loc[bg_mask, '570'].mean()
    group_df['450_bg_correct'] = group_df['450'] - bg_450
    group_df['570_bg_correct'] = group_df['570'] - bg_570
    group_df['absorbance_correct'] = group_df['450_bg_correct'] - group_df['570_bg_correct']
    return group_df

def std_curve_correct(batch_df, full_df):
    """Within a batch, fit one 4PL curve per antibody using sc_* points found
    anywhere in the same batch, and apply it to all non-sc rows of that antibody.
    """
    batch_val = batch_df['batch'].iloc[0]
    # 输出容器：先全 NaN，按抗体逐一填充
    result = pd.Series(np.nan, index=batch_df.index, dtype=float)

    # 当前 batch 内的抗体集合（去除 NaN）
    antibodies = batch_df['antibody'].dropna().unique()
    std_conc = np.array([1000,500,250,125,62.5,31.25,15.625,7.8125])
    for ab in antibodies:
        # 根据配置决定本抗体标准曲线的来源 batch：
        # - 默认：使用当前 batch 的标准点
        # - 如果启用 USE_BATCH1_STD_FOR_IL1B 且抗体为 IL1B_ANTIBODY_NAME：统一使用 IL1B_STD_BATCH_NAME 的标准点
        ab_str = str(ab)
        if USE_BATCH1_STD_FOR_IL1B and ab_str.lower() == IL1B_ANTIBODY_NAME.lower():
            std_source_batch = IL1B_STD_BATCH_NAME
        else:
            std_source_batch = batch_val

        # 在指定标准来源 batch + antibody 内收集标准点（sc_*）
        std_rows = full_df[(full_df['batch'] == std_source_batch)
                      & (full_df['antibody'] == ab)
                      & (full_df['group'].str.contains('sc', case=False, na=False))]
        if std_rows.empty:
            continue

        # 计算每个 sc 组的平均吸光度（与 Excel 做法一致）
        std_means = (std_rows.groupby('group')['absorbance_correct']
                              .mean()
                              .reset_index())
        if len(std_means) < 3:
            # 二次多项式至少需要 3 个点
            continue

        # sc_1 → 1000, sc_2 → 500, ..., sc_8 → 7.8125
        def _sc_order(s):
            import re
            m = re.search(r"(\d+)", s)
            return int(m.group(1)) if m else 999
        std_means = std_means.sort_values('group', key=lambda s: s.map(_sc_order))

        # 已知浓度（x）与对应的平均吸光度（y）
        x_conc = std_conc[:len(std_means)]
        y_abs  = std_means['absorbance_correct'].values

        # 拟合：浓度 = a*(吸光度)^2 + b*(吸光度) + c
        # 用 polyfit(自变量=y_abs, 因变量=x_conc, 次数=2)
        try:
            coeffs = np.polyfit(y_abs, x_conc, deg=2)
        except Exception:
            continue
        a, b, c = coeffs

        # 只对当前 batch、当前抗体、且非 sc 的行进行预测
        mask_ab = (batch_df['antibody'] == ab) & (~batch_df['group'].str.contains('sc', case=False, na=False))
        if mask_ab.any():
            yq = batch_df.loc[mask_ab, 'absorbance_correct'].astype(float).to_numpy()
            conc_pred = a * (yq ** 2) + b * yq + c
            result.loc[mask_ab] = conc_pred

    batch_df['std_curve_correct'] = result
    return batch_df

def mtt_correct(group_df):
    # 背景孔：无细胞（genotype 为空）
    bg_mask = group_df['genotype'].isna()
    bg_580 = group_df.loc[bg_mask, '580'].mean()
    group_df['580_bg_correct'] = group_df['580'] - bg_580

    # 有细胞的孔（genotype in {wt, ho}）
    vals = group_df['genotype'].astype(str).str.lower()
    has_cells_mask = vals.isin({'wt', 'ho'})
    mtt_median = group_df.loc[has_cells_mask, '580_bg_correct'].median()
    group_df['mtt_factor'] = (
        group_df['580_bg_correct'] / mtt_median if mtt_median and not np.isnan(mtt_median) else np.nan
    )
    return group_df

def process_file(file_path, output_dir):
    df = pd.read_excel(file_path)

    # 确保需要的列存在（只考虑 genotype）
    required = {"matrix_index","group","antibody","450","570","580","genotype","batch"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"缺少必要列: {missing} in file {file_path}")

    # 先在当前文件内按 matrix_index 做背景矫正
    df = df.groupby('matrix_index', group_keys=False).apply(bg_correct)

    # 默认情况下，标准曲线只基于当前文件数据
    full_df_for_std = df

    # 如果启用“所有批次 il1b 共用某个 batch 的标准曲线”模式，
    # 且当前文件不是该标准来源 batch，则额外加载标准来源 batch 的 il1b 标准孔行
    if USE_BATCH1_STD_FOR_IL1B:
        # 当前文件对应的 batch 名称（从文件名中提取，例如 ELISA原始数据_long_batch_E1.xlsx → E1）
        batchname = file_path.stem.replace("ELISA原始数据_long_batch_", "")
        # 只有当当前文件的 batch 与标准来源 batch 不同的时候才需要额外加载
        if batchname != IL1B_STD_BATCH_NAME:
            std_file = file_path.with_name(f"ELISA原始数据_long_batch_{IL1B_STD_BATCH_NAME}.xlsx")
            if std_file.exists():
                std_df = pd.read_excel(std_file)
                # 做最基本的列检查，防止格式错误
                missing_std = required - set(std_df.columns)
                if not missing_std:
                    # 对标准来源文件也先做背景矫正
                    std_df = std_df.groupby("matrix_index", group_keys=False).apply(bg_correct)
                    # 只保留 il1b 且 group 中包含 sc 的标准孔行
                    il1b_mask = std_df["antibody"].astype(str).str.strip().str.lower().eq(IL1B_ANTIBODY_NAME.lower())
                    sc_mask = std_df["group"].astype(str).str.contains("sc", case=False, na=False)
                    std_il1b_rows = std_df[il1b_mask & sc_mask].copy()
                    # 仅在确实存在标准孔时才拼接到 full_df_for_std
                    if not std_il1b_rows.empty:
                        full_df_for_std = pd.concat([df, std_il1b_rows], ignore_index=True)
            # 如果 std_file 不存在或缺列，保持 full_df_for_std=当前 df，不做额外处理

    # 在当前文件内按 batch 分组，使用 full_df_for_std 作为查找标准点的全集
    df = df.groupby('batch', group_keys=False).apply(lambda x: std_curve_correct(x, full_df_for_std))

    # 再按 matrix_index 做 MTT 矫正
    df = df.groupby('matrix_index', group_keys=False).apply(mtt_correct)

    # 最终值
    df['final_value'] = df['std_curve_correct'] / df['mtt_factor']

    batchname = file_path.stem.replace("ELISA原始数据_long_batch_", "")
    out_path = output_dir / f"ELISA_statistic_{batchname}.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    print(f"处理完成，结果已保存到 {out_path}")

def main():
    input_dir = Path("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/")
    output_dir = Path("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/")

    files = sorted(input_dir.glob("ELISA原始数据_long_batch_*.xlsx"))
    if not files:
        raise SystemExit(f"未找到匹配的输入文件于 {input_dir}")

    for file_path in files:
        process_file(file_path, output_dir)

if __name__ == "__main__":
    main()