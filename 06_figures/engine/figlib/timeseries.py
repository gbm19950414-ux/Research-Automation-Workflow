import matplotlib.pyplot as plt
from ..registry import register
from ..io import load_table
import seaborn as sns
import pandas as pd

@register("timeseries")
def plot_timeseries(ax, panel, style=None):
    df = load_table(panel["data"])
    # 提取均值和标准差列
    mean_cols = ["WT_mean", "HO_mean"]
    sd_cols = ["WT_sd", "HO_sd"]

    mean_long = df.melt(
        id_vars=["time_point", "p_value"],
        value_vars=mean_cols,
        var_name="group",
        value_name="value"
    )
    sd_long = df.melt(
        id_vars=["time_point"],
        value_vars=sd_cols,
        var_name="group",
        value_name="sd"
    )

    mean_long["group"] = mean_long["group"].str.replace("_mean", "")
    sd_long["group"] = sd_long["group"].str.replace("_sd", "")

    df_long = pd.merge(mean_long, sd_long, on=["time_point", "group"])

    palette = panel.get("palette") or style.get("color", {}).get("palette")
    # 从 style 的外层 errorbar 配置读取
    err_cfg = style.get("errorbar", {}) if style else {}
    elinewidth = err_cfg.get("linewidth", 1.2)
    capsize = err_cfg.get("capsize", 3)
    capthick = err_cfg.get("capthick", 1.2)

    for g, gdata in df_long.groupby("group"):
        ax.errorbar(
            gdata["time_point"],
            gdata["value"],
            yerr=gdata["sd"],
            label=g,
            fmt='-o',
            color=palette.get(g) if palette else None,
            capsize=capsize,
            elinewidth=elinewidth,
            capthick=capthick
        )
    ax.legend(title=None, frameon=False)

    # 读取显著性统计
    stats_cfg = panel.get("stats", {})
    if stats_cfg.get("enabled", False):
        pvals_df = pd.read_excel(stats_cfg["source"], sheet_name=stats_cfg.get("sheet", 0))
        # 根据需要绘制星号，可以在这里循环调用 ax.text(...)
        for _, row in pvals_df.iterrows():
            if row["p_value"] < 0.05:
                ax.text(row["time_point"], max(df_long.loc[df_long["time_point"]==row["time_point"], "value"]) * 1.05,
                        "*" if row["p_value"] >= 0.01 else "**", ha="center", va="bottom", fontsize=style.get("stat", {}).get("star_fontsize", 6))

    ax.set_xlabel(panel.get("x_label", ""))
    ax.set_ylabel(panel.get("y_label", ""))

    # 如果在 YAML 面板配置中设置了 y 轴范围，则应用
    if "ylim" in panel:
        ax.set_ylim(panel["ylim"])

    # 单图单面板刻度控制
    if "ticks" in panel and "x" in panel["ticks"]:
        xticks_cfg = panel["ticks"]["x"]
        if "major_locator" in xticks_cfg:
            ax.xaxis.set_major_locator(plt.MultipleLocator(xticks_cfg["major_locator"]))
        if "major_formatter" in xticks_cfg:
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, _: xticks_cfg["major_formatter"].format(val)))