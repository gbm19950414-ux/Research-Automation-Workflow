# boxplot plotting placeholder
# engine/figlib/boxplot.py
import os
import seaborn as sns
from statannotations.Annotator import Annotator
import pandas as pd
from ..registry import register
from ..io import load_table

def _combine_string_expr(df: pd.DataFrame, expr: str, colname: str = "_combo_x") -> str:
    """
    安全地把表达式（如 "antibody + '|' + drug"）转成字符串列。
    - 支持常量（用单引号包裹的字符串）
    - 支持列名相加
    - 对缺失值当作空串处理
    返回生成的列名（默认 "_combo_x"）
    """
    parts = [p.strip() for p in expr.split("+")]
    out = pd.Series([""] * len(df), index=df.index, dtype=object)
    for p in parts:
        if len(p) >= 2 and p[0] == p[-1] == "'":  # 常量
            out = out + p[1:-1]
        else:  # 列名
            if p not in df.columns:
                # 列不存在时也不报错，按空串处理，避免 KeyError
                continue
            out = out + df[p].astype(str).fillna("")
    df[colname] = out
    return colname

@register("box")
def plot_box(ax, panel, style=None):
    df = load_table(panel["data"], sheet_name=panel.get("sheet"))
    y_key = panel["mapping"]["y"]
    x_expr = panel["mapping"]["x"]               # 原始 YAML 中的 x 表达式/列名（字符串）
    x_key = x_expr
    # 支持在 mapping.x 中写表达式（如 "antibody + '|' + drug"）
    is_expr = isinstance(x_expr, str) and ("+" in x_expr or "|" in x_expr)
    if is_expr:
        _combine_string_expr(df, x_expr, "_combo_x")
        x_key = "_combo_x"                       # 只在本地变量中切换到临时列

    if y_key not in df.columns:
        if "final_value" in df.columns:
            panel["mapping"]["y"] = "final_value"
        else:
            raise ValueError(f"Column '{y_key}' not found in {panel['data']}. Check mapping.y in YAML and the sheet name.")

    # 如果 panel 中指定了 order，则强制 df 的 x 列按照 order 排序
    if panel.get("order"):
        df[x_key] = pd.Categorical(
            df[x_key],
            categories=panel["order"],
            ordered=True
        )
    # 优先使用面板级调色板，其次是全局样式中的 palette
    palette = panel.get("palette")
    if palette is None and style:
        palette = style.get("color", {}).get("palette")
    sns.boxplot(
        data=df,
        x=x_key,
        y=panel["mapping"]["y"],
        hue=panel["mapping"].get("hue"),
        order=panel.get("order"),
        hue_order=panel.get("hue_order"),
        palette=palette,
        ax=ax,
        linewidth=0.5,
        width=panel.get("box_width", 0.6),
        fliersize=0,
        dodge=True
    )
    sns.stripplot(
        data=df,
        x=x_key,
        y=panel["mapping"]["y"],
        hue=panel["mapping"].get("hue"),
        order=panel.get("order"),
        hue_order=panel.get("hue_order"),
        palette=palette,
        ax=ax,
        dodge=True,
        color=None,
        size=2,
        legend=False   # 避免生成重复图例
    )
        # === 显著性标注 ===
    stats_cfg = panel.get("stats", {})
    if stats_cfg.get("enabled", False):
        sheet_name = stats_cfg.get("sheet")
        try:
            pvals_df = pd.read_excel(stats_cfg["source"], sheet_name=sheet_name or "pair_stats")
        except ValueError:
            pvals_df = pd.read_excel(stats_cfg["source"], sheet_name=0)

        # 与主表一致地构造 x 列（若为表达式）
        if is_expr:
            _combine_string_expr(pvals_df, x_expr, "_combo_x")

        # 若指定了顺序，保持一致
        display_order = panel.get("order", [])
        if display_order:
            pvals_df[x_key] = pd.Categorical(pvals_df[x_key], categories=display_order, ordered=True)
            pvals_df = pvals_df.sort_values(x_key)

        pairs, pvals = [], []
        for _, row in pvals_df.iterrows():
            cat = row.get(x_key)
            if pd.isna(cat):
                continue
            pairs.append(((cat, "WT"), (cat, "HO")))
            pvals.append(row[stats_cfg.get("column", "p_value")])

        if pairs:
            annot = Annotator(
                ax, pairs, data=df,
                x=x_key,
                y=panel["mapping"]["y"],
                hue=panel["mapping"].get("hue")
            )
            stat_style = style.get("stat", {}) if style else {}
            annot.configure(
                test=None,
                text_format="star",
                loc="inside",
                fontsize=stat_style.get("star_fontsize", 6),
                line_width=stat_style.get("line_width", 0.5),
                line_height=stat_style.get("line_height", 0.03)
            )
            annot.set_pvalues(pvals)
            annot.annotate()
    # 设置坐标轴范围
    if "ylim" in panel:
        ax.set_ylim(panel["ylim"])
    # 设置坐标轴标题，并确保留有足够的内边距
    ax.set_xlabel(panel.get("x_label", ""), labelpad=panel.get("x_labelpad", 4))
    ax.set_ylabel(panel.get("y_label", ""), labelpad=panel.get("y_labelpad", 10))
    
    # 如果在 panel 中指定了 x_tick_rotation，则旋转 x 轴刻度标签
    if "x_tick_rotation" in panel:
        for tick in ax.get_xticklabels():
            tick.set_rotation(panel["x_tick_rotation"])
            tick.set_ha("right")
    # 如果在 panel 中指定了 x_rename，则替换 x 轴刻度标签
    if "x_rename" in panel:
        x_rename = panel["x_rename"]
        order = panel.get("order")
        if order:
            label_map = {str(k): x_rename.get(k, k) for k in order}
            new_labels = [label_map.get(str(label.get_text()), label.get_text()) for label in ax.get_xticklabels()]
        else:
            new_labels = [x_rename.get(label.get_text(), label.get_text()) for label in ax.get_xticklabels()]
        ax.set_xticklabels(new_labels)
    # 图例：仅使用 boxplot 生成的图例，保持顺序去重
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    uniq_handles, uniq_labels = [], []
    for h, lb in zip(handles, labels):
        if lb not in seen and lb != "":
            seen.add(lb)
            uniq_handles.append(h)
            uniq_labels.append(lb)
    if uniq_handles:
        ax.legend(uniq_handles, uniq_labels, title=None, frameon=False)
    else:
        ax.legend().remove()