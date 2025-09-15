#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
004_plot_time_series.py

- 外观完全由《外观指南.yaml》控制；
- figure 左上角标题（不与图像重叠）：使用 suptitle + constrained_layout；
- 从 *_stats.xlsx 读取 p 值（多种列名），按阈值绘制 * / **；
- 点大小、星标大小均可在 YAML 中配置。
"""
import argparse
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import yaml

# ==== 常量 ====
TIME_COL = "time_point"
VALUE_COL = "value"

# ==== 路径 ====
OUTPUT_DIR = Path(
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/"
    "博士课题/EphB1/04_data/processed/microplate_reader/线粒体完整性检测"
)
STYLE_PATH = Path("/Users/gongbaoming/Library/Mobile Documents/com~apple~CloudDocs/phd_thesis/方法/外观指南.yaml")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def _mm_to_in(mm: float) -> Optional[float]:
    return float(mm) / 25.4 if mm is not None else None

def load_style():
    """读取 YAML；逐项安全更新 rcParams；返回配置及 constrained_layout 开关。"""
    cfg = yaml.safe_load(STYLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("外观指南.yaml 内容不是字典结构")

    # 1) rcParams：清空后逐项设置；对未知键静默跳过（避免 KeyError）
    mpl.rcParams.clear()
    rc = cfg.get("rcparams", {})

    # 一些稳妥的默认值（若 YAML 未给出）
    rc.setdefault("font.family", "sans-serif")
    rc.setdefault("font.sans-serif",
                  ["Arial", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", "DejaVu Sans"])
    rc.setdefault("pdf.fonttype", 42)
    rc.setdefault("ps.fonttype", 42)
    rc.setdefault("axes.unicode_minus", False)
    rc.setdefault("savefig.format", "pdf")
    rc.setdefault("savefig.dpi", 450)
    rc.setdefault("axes.grid", False)
    rc.setdefault("axes.spines.right", False)
    rc.setdefault("axes.spines.top", False)
    rc.setdefault("lines.markersize", 2.8)
    rc.setdefault("lines.markeredgewidth", 0.5)
    rc.setdefault("errorbar.capsize", 2.0)

    for k, v in rc.items():
        try:
            mpl.rcParams[k] = v
        except Exception:
            # 忽略未知或旧版本不存在的 rc 参数（如误写 constrained_layout.use）
            pass

    # 2) 其它配置块
    axes_cfg   = cfg.get("axes", {})
    export_cfg = cfg.get("export", {})
    panel_cfg  = cfg.get("panel_layout", cfg.get("layout", {}))
    fig_cfg    = cfg.get("figure_layout", cfg.get("layout", {}))
    stat_cfg   = cfg.get("statistics", {})
    ptitle_cfg = cfg.get("panel_title", {})

    # 3) constrained_layout 开关（不要放进 rcParams）
    # 优先读 figure.constrained_layout.use（若用户在 YAML rcparams 中写了正确键名）
    use_cl = False
    try:
        use_cl = bool(mpl.rcParams.get("figure.constrained_layout.use", False))
    except Exception:
        pass
    # 也允许在 YAML 顶层提供显式开关（可选）
    use_cl = bool(cfg.get("constrained_layout", use_cl))
    # 如果使用 suptitle，一般推荐打开
    if ptitle_cfg.get("method", "suptitle") == "suptitle":
        use_cl = True

    # 4) v1 兼容：panel_layout 缺失则给出安全默认
    if "width_mm_range" not in panel_cfg:
        panel_cfg = {
            "width_mm_range": [40, 85],
            "default_width_mm": 55,
            "aspect_ratio": 0.75,
            "margins_mm": {"left": 3, "right": 3, "top": 3, "bottom": 3},
        }

    return cfg, axes_cfg, export_cfg, panel_cfg, fig_cfg, stat_cfg, ptitle_cfg, use_cl

CFG, AXES_CFG, EXPORT_CFG, PANEL_CFG, FIG_CFG, STAT_CFG, PTITLE_CFG, USE_CL = load_style()

def compute_panel_figsize() -> Tuple[float, float]:
    wmin, wmax = PANEL_CFG.get("width_mm_range", [40, 85])
    w = PANEL_CFG.get("default_width_mm", 55)
    w = min(max(w, wmin), wmax)
    ar = float(PANEL_CFG.get("aspect_ratio", 0.75))
    h = w * ar
    return _mm_to_in(w), _mm_to_in(h)

def apply_axes_style(ax: plt.Axes):
    ax.grid(False)
    for s in AXES_CFG.get("hide_spines", ["right", "top"]):
        if s in ax.spines:
            ax.spines[s].set_visible(False)
    for s in AXES_CFG.get("show_spines", ["left", "bottom"]):
        if s in ax.spines:
            ax.spines[s].set_visible(True)
    ax.tick_params(
        axis="both", which="major",
        direction=AXES_CFG.get("tick_direction", "out"),
        length=AXES_CFG.get("tick_major_length_pt", 2.5),
        width=AXES_CFG.get("tick_major_width_pt", 0.5),
    )
    if AXES_CFG.get("minor_ticks", False):
        ax.minorticks_on()
    else:
        ax.minorticks_off()

def xlabel(ax: plt.Axes, name: str, unit: str):
    tpl = AXES_CFG.get("axis_title_template", "{name}（{unit}）")
    ax.set_xlabel(tpl.format(name=name, unit=unit))

def ylabel(ax: plt.Axes, name: str, unit: str):
    tpl = AXES_CFG.get("axis_title_template", "{name}（{unit}）")
    ax.set_ylabel(tpl.format(name=name, unit=unit))

def _find_p_col(df: pd.DataFrame) -> Optional[str]:
    # 宽松兼容多种命名
    for name in ["p_value", "p-value", "pvalue", "p", "P"]:
        if name in df.columns:
            return name
    for c in df.columns:
        key = str(c).strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if key in {"p", "pvalue", "pval"}:
            return c
    return None

def _draw_panel_title(ax: plt.Axes, text: str):
    """在 figure 左上角或 axes 内部绘制标题，由 YAML panel_title 控制。"""
    method = PTITLE_CFG.get("method", "suptitle")   # suptitle / axes-title
    if method == "suptitle":
        fig = ax.figure
        dx_mm, dy_mm = PTITLE_CFG.get("offset_mm", [2.0, 4.0])
        W, H = fig.get_size_inches()
        x = (dx_mm / 25.4) / W      # figure 左缘为 0
        y = 1.0 - (dy_mm / 25.4) / H  # figure 上缘为 1
        fig.suptitle(
            text,
            x=x, y=y,
            ha="left", va="top",
            fontsize=PTITLE_CFG.get("fontsize_pt", 8),
            fontweight=PTITLE_CFG.get("weight", "bold"),
        )
    else:
        ax.set_title(
            text,
            loc="left",
            pad=PTITLE_CFG.get("pad_pt", 2.0),
            fontsize=PTITLE_CFG.get("fontsize_pt", 8),
            fontweight=PTITLE_CFG.get("weight", "bold"),
        )

def _plot_significance_if_any(ax: plt.Axes, x, wt_y, ho_y, df: pd.DataFrame):
    pcol = "p_value" if "p_value" in df.columns else _find_p_col(df)
    if not pcol or pcol not in df.columns or not STAT_CFG.get("enabled", True):
        return
    ps = df[pcol].values
    ymin = float(np.nanmin([np.nanmin(wt_y), np.nanmin(ho_y)]))
    ymax = float(np.nanmax([np.nanmax(wt_y), np.nanmax(ho_y)]))
    pad = STAT_CFG.get("pad_frac", 0.06) * (ymax - ymin if ymax > ymin else 1.0)
    fontsize = STAT_CFG.get("star_fontsize_pt", 6)

    def stars(p):
        if p < STAT_CFG.get("p_thr1", 0.01): return "**"
        if p < STAT_CFG.get("p_thr2", 0.05): return "*"
        return "ns"

    for xi, w, h, p in zip(x, wt_y, ho_y, ps):
        lab = stars(p)
        if lab == "ns" and not STAT_CFG.get("show_ns", False):
            continue
        y = max(w, h) + pad
        ax.text(xi, y, lab, ha="center", va="bottom", fontsize=fontsize)

def process_file(in_path: Path, x_name: str, x_unit: str, y_name: str, y_unit: str):
    print(f"[信息] 作图文件: {in_path}")
    df = pd.read_excel(in_path)
    required = {TIME_COL, "WT_mean", "WT_sd", "HO_mean", "HO_sd"}
    if not required.issubset(df.columns):
        raise KeyError("输入文件缺少必需列")

    pcol = _find_p_col(df)
    cols = [TIME_COL, "WT_mean", "WT_sd", "HO_mean", "HO_sd"]
    if pcol: cols.append(pcol)
    stats_df = df[cols].copy()
    if pcol and pcol != "p_value":
        stats_df.rename(columns={pcol: "p_value"}, inplace=True)

    x = stats_df[TIME_COL].values
    wt_y = stats_df["WT_mean"].values
    wt_e = stats_df["WT_sd"].values
    ho_y = stats_df["HO_mean"].values
    ho_e = stats_df["HO_sd"].values

    # —— 建图：通过 USE_CL 开启 constrained_layout（不要放进 rcParams）——
    fig, ax = plt.subplots(figsize=compute_panel_figsize(), constrained_layout=USE_CL)
    apply_axes_style(ax)

    caplen = mpl.rcParams.get("errorbar.capsize", None)
    ax.errorbar(x, wt_y, yerr=wt_e, fmt="o-", label="WT", capsize=caplen)
    ax.errorbar(x, ho_y, yerr=ho_e, fmt="s--", label="HO", capsize=caplen)

    xlabel(ax, x_name, x_unit)
    ylabel(ax, y_name, y_unit)

    _draw_panel_title(ax, in_path.stem)
    _plot_significance_if_any(ax, x, wt_y, ho_y, stats_df)

    out_pdf = OUTPUT_DIR / f"{in_path.stem}_line_sd.pdf"
    # 若未启用 constrained_layout，再回退到 tight_layout
    if not USE_CL:
        plt.tight_layout()
    plt.savefig(out_pdf, bbox_inches="tight", transparent=EXPORT_CFG.get("transparent", False))
    plt.close(fig)
    print(f"[完成] 输出：\n  {out_pdf}")

def main():
    ap = argparse.ArgumentParser(description="绘制时间序列点线图 (WT vs HO, mean ± SD)，支持 figure 顶左标题与显著性标注。")
    ap.add_argument("inputs", nargs="+", help="输入 *_stats.xlsx 文件路径（可多个）")
    ap.add_argument("--x-name", default="时间", help="横轴名称")
    ap.add_argument("--x-unit", default="min", help="横轴单位")
    ap.add_argument("--y-name", default="信号", help="纵轴名称")
    ap.add_argument("--y-unit", default="a.u.", help="纵轴单位")
    args = ap.parse_args()

    for f in args.inputs:
        process_file(Path(f), args.x_name, args.x_unit, args.y_name, args.y_unit)

if __name__ == "__main__":
    main()