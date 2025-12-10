#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
003.5_heatmap_time_lines.py

功能：
1. 自动扫描目录：
       04_data/interim/microplate_reader/线粒体完整性检测/
   中所有文件名包含 "blank_corrected_t0_corrected" 且以 "stats.xlsx" 结尾的 Excel 文件，
   例如：
       线粒体完整性检测_blank_corrected_t0_corrected_batch-E99-2_dye-tmrm_stats.xlsx

2. 读取这些 *_stats.xlsx 文件，合并为一个长表。
   每一行对应一个 (时间线属性 + time_point) 的统计结果。

3. 将 WT / HO 都绘制在同一张热图中：
   - 每条“时间线名称”定义为：
       sample_batch | Dye_concentration | Dye_time | drug | dye | group
     例如：
       E51|nan|nan|lps+nigericin|h2dcha|experiment
   - 同一条时间线名称下，生成两行：
       E51|nan|nan|lps+nigericin|h2dcha|experiment|WT
       E51|nan|nan|lps+nigericin|h2dcha|experiment|HO
     并保证 WT / HO 相邻。

4. 根据 time_point 的间隔，将曲线分成两类并分别绘图：
   - 间隔约为 1 的一类（例如 0, 1, 2, 3, ...）
   - 间隔约为 2.5 的一类（例如 0, 2.5, 5, 7.5, ...）
   即：
     - step_group = "1"   表示最小间隔在 [0.75, 1.25] 之间
     - step_group = "2.5" 表示最小间隔在 [2.0, 3.0] 之间
   对每一类分别绘制一张热图，X 轴都是 time_point。

5. Y 轴排序规则：
   - 首先按基因型聚合：所有 WT 在前，所有 HO 在后；
   - 在每个基因型内部，先按 dye 聚类（分组排序）；
   - 在每个 dye 内，按 drug 排序；
   - 在每个 drug 内，按 Dye_concentration 排序；
   - 在每个 (基因型, dye, drug, Dye_concentration) 内，按时间线名称排序。

6. 颜色值：
   - WT 行使用 value_t0_ratio_WT_mean
   - HO 行使用 value_t0_ratio_HO_mean
   - 使用 5% 和 95% 分位数作为 vmin / vmax 以收窄颜色范围，减少极端值影响。

7. 输出：
   在同一目录下写出两张图（如果该 step_group 有数据）：
       线粒体完整性检测_heatmap_value_t0_ratio_WT_HO_mean_step-1.pdf
       线粒体完整性检测_heatmap_value_t0_ratio_WT_HO_mean_step-2.5.pdf

用法：
  # 直接使用默认行为（推荐）
  python 003.5_heatmap_time_lines.py

  # 或显式指定一个或多个 *_stats.xlsx 文件
  python 003.5_heatmap_time_lines.py file1_stats.xlsx file2_stats.xlsx ...

注意：
- 如果某些列不存在（例如 sample_batch 或 gene），脚本会自动跳过该列，
  用剩余的列来构建时间线名称。
- 如果 stats 文件中不存在所需的 WT / HO 数值列，会报错提醒。
"""

import argparse
from pathlib import Path
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    import seaborn as sns
    _has_seaborn = True
except ImportError:
    _has_seaborn = False
    print("[警告] 未安装 seaborn，将使用 matplotlib.imshow 绘制热图（无颜色条标签等增强功能）。")
    import matplotlib  # noqa: F401

# 固定目录
BASE_DIR = Path("04_data/interim/microplate_reader/线粒体完整性检测")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# 时间点列名
TIME_COL = "time_point"

# 用于 WT / HO 的数值列
WT_COL = "value_t0_ratio_WT_mean"
HO_COL = "value_t0_ratio_HO_mean"
VALUE_COLS = [WT_COL, HO_COL]

# 构成“时间线名称”的列（不包含 gene，以便 WT/HO 成对）
TIMELINE_BASE_COLS = [
    "sample_batch",
    "Dye_concentration",
    "Dye_time",
    "drug",
    "dye",
    "group",
]


def find_default_files() -> list[Path]:
    """扫描 BASE_DIR，找到所有 *_stats.xlsx 文件作为输入"""
    files: list[Path] = []
    for p in BASE_DIR.iterdir():
        name = p.name
        lname = name.lower()

        # 跳过 Excel 的临时锁文件
        if lname.startswith("~$"):
            continue

        # 只要包含 blank_corrected_t0_corrected 且以 stats.xlsx 结尾
        if ("blank_corrected_t0_corrected" in lname) and lname.endswith("stats.xlsx"):
            files.append(p)

    print(f"[信息] 自动找到 {len(files)} 个 *_stats.xlsx 文件作为输入：")
    for p in files:
        print("   -", p)
    return files


def parse_sample_batch_from_filename(path: Path) -> str | None:
    """
    从文件名中解析 batch 信息，例如：
    线粒体完整性检测_blank_corrected_t0_corrected_batch-E99-2_dye-tmrm_stats.xlsx
    提取出：E99-2
    """
    m = re.search(r"batch-([^_]+)", path.name)
    if m:
        return m.group(1)
    return None


def load_and_concat(files: list[Path]) -> pd.DataFrame:
    """读取所有 stats 文件并合并为一个 DataFrame"""
    dfs = []
    for f in files:
        print(f"[读取] {f}")
        df = pd.read_excel(f)

        # 若 stats 中没有 sample_batch，尝试从文件名推断
        if "sample_batch" not in df.columns:
            sb = parse_sample_batch_from_filename(f)
            if sb is not None:
                df["sample_batch"] = sb

        # 记录来源文件名（调试用）
        df["__source_file__"] = f.name
        dfs.append(df)

    if not dfs:
        raise RuntimeError("未找到任何待处理的 *_stats.xlsx 文件。")

    all_df = pd.concat(dfs, ignore_index=True)
    return all_df


def build_long_table(all_df: pd.DataFrame) -> pd.DataFrame:
    """
    将合并后的 stats 表转换为“长表”：
    每一行表示一条时间线在一个 time_point 下的一个基因型 (WT/HO) 的值。

    输出列：
        - row_id         : 时间线名称 + "|WT" 或 "|HO"
        - timeline_base  : 时间线名称（不含 WT/HO）
        - geno_label     : "WT" 或 "HO"
        - dye, drug, Dye_concentration
        - time_point
        - value          : 对应 WT_COL / HO_COL 的值
    """
    for col in VALUE_COLS:
        if col not in all_df.columns:
            raise KeyError(f"在合并后的数据中未找到列: {col}")

    df = all_df.copy()

    # 构建时间线基础名称（不包含 gene）
    existing_base_cols = [c for c in TIMELINE_BASE_COLS if c in df.columns]
    if not existing_base_cols:
        # 如果一个都没有，就退而求其次，用来源文件名
        existing_base_cols = ["__source_file__"]
        print("[警告] 未发现任何时间线属性列，将使用 __source_file__ 作为时间线名称。")
    else:
        print("[信息] 用于构建时间线名称的列：", ", ".join(existing_base_cols))

    def make_base_label(row) -> str:
        parts = [str(row.get(c, "nan")) for c in existing_base_cols]
        return "|".join(parts)

    df["timeline_base"] = df.apply(make_base_label, axis=1)

    records = []
    for _, row in df.iterrows():
        base = row["timeline_base"]
        dye = row.get("dye", None)
        drug = row.get("drug", None)
        conc = row.get("Dye_concentration", None)
        t = row.get(TIME_COL, None)

        # WT 行
        wt_val = row.get(WT_COL, np.nan)
        if not (wt_val is None or (isinstance(wt_val, float) and np.isnan(wt_val))):
            records.append(
                {
                    "row_id": f"{base}|WT",
                    "timeline_base": base,
                    "geno_label": "WT",
                    "dye": dye,
                    "drug": drug,
                    "Dye_concentration": conc,
                    TIME_COL: t,
                    "value": wt_val,
                }
            )

        # HO 行
        ho_val = row.get(HO_COL, np.nan)
        if not (ho_val is None or (isinstance(ho_val, float) and np.isnan(ho_val))):
            records.append(
                {
                    "row_id": f"{base}|HO",
                    "timeline_base": base,
                    "geno_label": "HO",
                    "dye": dye,
                    "drug": drug,
                    "Dye_concentration": conc,
                    TIME_COL: t,
                    "value": ho_val,
                }
            )

    long_df = pd.DataFrame.from_records(records)
    if long_df.empty:
        raise RuntimeError("长表为空，可能所有 WT / HO 数值列均为 NaN。")

    return long_df


def assign_step_group(long_df: pd.DataFrame) -> pd.DataFrame:
    """
    根据每条时间线（timeline_base）的 time_point 间隔，分配 step_group：
      - "1"   : 最小间隔在 [0.75, 1.25] 之间
      - "2.5" : 最小间隔在 [2.0, 3.0] 之间
      - 其他   : 记为 "other"
    并在 long_df 中添加列 "step" 和 "step_group"。
    """
    step_by_base: dict[str, float] = {}

    for base, sub in long_df.groupby("timeline_base"):
        tvals = sorted(
            [float(x) for x in sub[TIME_COL].dropna().unique()]
        )
        if len(tvals) < 2:
            step = np.nan
        else:
            diffs = np.diff(tvals)
            # 只考虑正间隔
            diffs = diffs[diffs > 0]
            if diffs.size == 0:
                step = np.nan
            else:
                step = float(np.min(diffs))
        step_by_base[base] = step

    long_df = long_df.copy()
    long_df["step"] = long_df["timeline_base"].map(step_by_base)

    def _group_step(x: float) -> str:
        if isinstance(x, float) and not np.isnan(x):
            if 0.75 <= x <= 1.25:
                return "1"
            if 2.0 <= x <= 3.0:
                return "2.5"
        return "other"

    long_df["step_group"] = long_df["step"].apply(_group_step)
    return long_df


def build_heat_matrix_for_step(long_df_step: pd.DataFrame) -> pd.DataFrame:
    """
    为某一个 step_group 构建热图矩阵：
      index  = row_id（E51|...|WT / E51|...|HO）
      columns= time_point
      values = value
    并按照 dye、drug、Dye_concentration、timeline_base、WT/HO 顺序排序行。
    """
    if long_df_step.empty:
        return pd.DataFrame()

    # 准备行顺序
    geno_order_map = {"WT": 0, "HO": 1}
    meta_cols = [
        "row_id",
        "timeline_base",
        "dye",
        "drug",
        "Dye_concentration",
        "geno_label",
    ]
    row_meta = (
        long_df_step[meta_cols]
        .drop_duplicates()
        .copy()
    )
    row_meta["geno_order"] = row_meta["geno_label"].map(geno_order_map).fillna(99)

    # 排序：先按基因型聚合（WT 在前，HO 在后），再按 dye -> drug -> Dye_concentration -> timeline_base
    row_meta = row_meta.sort_values(
        by=["dye", "geno_order", "drug", "Dye_concentration", "timeline_base"],
        kind="mergesort",
    )
    row_order = row_meta["row_id"].tolist()

    # 构建矩阵
    mat = long_df_step.pivot_table(
        index="row_id",
        columns=TIME_COL,
        values="value",
        aggfunc="mean",  # 若有重复则取均值
    )

    # 按 time_point 排序列（尝试按数值排序）
    def _sort_key(x):
        s = str(x)
        try:
            return float(s)
        except Exception:
            return float("inf")

    mat = mat.reindex(sorted(mat.columns, key=_sort_key), axis=1)

    # 纵轴按 row_order 排序
    mat = mat.reindex(row_order, axis=0)

    return mat


def compute_color_range(mat: pd.DataFrame) -> tuple[float, float]:
    """
    根据单个矩阵的整体分布，计算一个“收窄”的颜色范围。
    使用 5% 和 95% 分位数，减少极端值对色条的拉伸。
    """
    if mat.empty:
        return None, None

    arr = mat.values.ravel()
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return None, None

    vmin = float(np.nanpercentile(arr, 5))
    vmax = float(np.nanpercentile(arr, 95))
    if vmax <= vmin:
        vmin = float(np.nanmin(arr))
        vmax = float(np.nanmax(arr))
    return vmin, vmax


def plot_heatmap_single(mat: pd.DataFrame, out_path: Path, title_suffix: str):
    """
    绘制单个 step_group 的热图，并保存为 PDF。
    """
    if mat.empty:
        raise RuntimeError("热图矩阵为空，无法绘图。请检查输入数据。")

    n_rows, n_cols = mat.shape
    print(f"[信息] 热图矩阵尺寸: {n_rows} 条时间线 × {n_cols} 个时间点")

    # 动态调整画布大小
    width = max(8, 0.5 * n_cols)
    height = max(6, 0.18 * n_rows)

    vmin, vmax = compute_color_range(mat)

    fig, ax = plt.subplots(figsize=(width, height))

    if _has_seaborn:
        sns.heatmap(
            mat,
            ax=ax,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            cbar_kws={"label": "value_t0_ratio (WT/HO)"},
            linewidths=0.1,
            linecolor="white",
            yticklabels=mat.index,  # 显式指定每一行的标签，避免自动抽稀
        )
    else:
        im = ax.imshow(mat.values, aspect="auto", vmin=vmin, vmax=vmax)
        fig.colorbar(im, ax=ax, label="value_t0_ratio (WT/HO)")
        ax.set_yticks(np.arange(n_rows))
        ax.set_yticklabels(mat.index)

    # 确保每一行都有一个 y 轴刻度和标签（避免 seaborn / matplotlib 自动抽稀）
    ax.set_yticks(np.arange(n_rows) + 0.5)
    ax.set_yticklabels(mat.index)

    ax.set_xlabel("time_point")
    ax.set_ylabel("时间线名称 + 基因型（...|WT / ...|HO）")
    ax.set_title(f"Heatmap of value_t0_ratio (WT & HO) - step {title_suffix}")

    # 美化 X 轴刻度
    ax.set_xticks(np.arange(n_cols) + 0.5)
    ax.set_xticklabels(mat.columns, rotation=45, ha="right")

    plt.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[完成] 写出热图: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="按 time_point 绘制 WT/HO 时间线热图，并按时间间隔分两张图展示。")
    parser.add_argument(
        "inputs",
        nargs="*",
        help="可选：显式指定一个或多个 *_stats.xlsx 文件；若不指定则自动扫描目录。",
    )
    args = parser.parse_args()

    # 确定输入文件列表
    if not args.inputs:
        files = find_default_files()
    else:
        files = [Path(p) for p in args.inputs]

    if not files:
        print("[错误] 未找到任何输入文件。")
        return

    # 读取并合并
    all_df = load_and_concat(files)

    # 构建长表（包含 WT / HO）
    long_df = build_long_table(all_df)

    # 分配 step_group
    long_df = assign_step_group(long_df)

    # 针对 step_group = "1" 和 "2.5" 分别绘图
    for step_label in ["1", "2.5"]:
        sub = long_df[long_df["step_group"] == step_label]
        if sub.empty:
            print(f"[信息] step_group = {step_label} 没有数据，跳过绘图。")
            continue

        mat = build_heat_matrix_for_step(sub)
        if mat.empty:
            print(f"[信息] step_group = {step_label} 生成的热图矩阵为空，跳过绘图。")
            continue

        out_name = f"线粒体完整性检测_heatmap_value_t0_ratio_WT_HO_mean_step-{step_label}.pdf"
        out_path = BASE_DIR / out_name

        plot_heatmap_single(mat, out_path, step_label)


if __name__ == "__main__":
    main()