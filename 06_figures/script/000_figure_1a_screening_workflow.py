#!/usr/bin/env python3
"""
Figure 1a — Genetic screening workflow (3-part schematic draft)

Layout:
  INPUT (left)  ->  WORKFLOW (middle)  ->  OUTPUT (right)

Outputs:
  06_figures/figure_1/000_figure_1a_workflow.pdf
  06_figures/figure_1/000_figure_1a_workflow.svg
"""

from __future__ import annotations

from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


def mm_to_in(mm: float) -> float:
    return mm / 25.4


def add_group_panel(ax, x, y, w, h, title):
    # light group background + title
    bg = Rectangle((x, y), w, h, facecolor="white", edgecolor="black", linewidth=1)
    ax.add_patch(bg)
    ax.text(
        x + 0.02 * w,
        y + h - 0.08 * h,
        title,
        ha="left",
        va="center",
        fontsize=10,
        fontweight="bold",
        color="black",
    )


def add_box(ax, x, y, w, h, text, *, lw=1, fontsize=9, bold=False):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=lw,
        edgecolor="black",
        facecolor="white",
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight="bold" if bold else "normal",
        color="black",
        wrap=True,
    )


def add_arrow(ax, x0, y0, x1, y1, *, lw=1):
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops=dict(arrowstyle="-|>", lw=lw, color="black", shrinkA=0, shrinkB=0),
    )


def main():
    outdir = Path("06_figures/figure_1")
    outdir.mkdir(parents=True, exist_ok=True)

    # Figure size close to your Nature-style single-row panel
    width_mm, height_mm = 173, 70
    fig = plt.figure(figsize=(mm_to_in(width_mm), mm_to_in(height_mm)), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Fonts (safe fallback)
    mpl.rcParams["pdf.fonttype"] = 42
    mpl.rcParams["ps.fonttype"] = 42
    mpl.rcParams["font.family"] = "sans-serif"
    mpl.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans"]

    # --- Three-part layout (group panels) ---
    top, bottom = 0.92, 0.12
    H = top - bottom
    gap = 0.02

    # group widths
    w_left, w_mid, w_right = 0.28, 0.48, 0.20
    x_left = 0.04
    x_mid = x_left + w_left + gap
    x_right = x_mid + w_mid + gap

    add_group_panel(ax, x_left, bottom, w_left, H, "INPUT")
    add_group_panel(ax, x_mid, bottom, w_mid, H, "WORKFLOW")
    add_group_panel(ax, x_right, bottom, w_right, H, "OUTPUT")

    # --- INPUT content ---
    # Big box: strains + genotypes
    bx = x_left + 0.06 * w_left
    by = bottom + 0.32 * H
    bw = w_left * 0.88
    bh = H * 0.42
    add_box(
        ax,
        bx,
        by,
        bw,
        bh,
        "Multiple pb genetic backgrounds\n(≈20 strains)\n\nWithin each strain:\nWT vs HO (Ephb1)",
        fontsize=9,
    )
    ax.text(
        bx + bw / 2,
        bottom + 0.18 * H,
        "Same experimental conditions\nacross strains",
        ha="center",
        va="center",
        fontsize=8.5,
    )

    # --- WORKFLOW content (stacked steps) ---
    mid_x = x_mid + 0.06 * w_mid
    mid_w = w_mid * 0.88
    step_h = H * 0.18
    step_gap = H * 0.05
    y1 = bottom + H * 0.66
    y2 = y1 - (step_h + step_gap)
    y3 = y2 - (step_h + step_gap)

    add_box(ax, mid_x, y1, mid_w, step_h, "1) Cell preparation\n(macrophages per strain)", fontsize=9)
    add_box(ax, mid_x, y2, mid_w, step_h, "2) Inflammasome activation\n(e.g. NLRP3 / NLRC4 / AIM2)", fontsize=9)
    add_box(ax, mid_x, y3, mid_w, step_h, "3) Readouts\nIL-1β release (ELISA)\n± LDH (pyroptosis)", fontsize=9)

    # arrows within workflow
    add_arrow(ax, mid_x + mid_w / 2, y1, mid_x + mid_w / 2, y2 + step_h, lw=1)
    add_arrow(ax, mid_x + mid_w / 2, y2, mid_x + mid_w / 2, y3 + step_h, lw=1)

    # --- OUTPUT content ---
    ox = x_right + 0.08 * w_right
    ow = w_right * 0.84

    # criteria box
    add_box(
        ax,
        ox,
        bottom + 0.58 * H,
        ow,
        H * 0.28,
        "Within-strain\nstatistics\n\nEffect size\n+ significance",
        fontsize=9,
    )
    # candidate box
    add_box(
        ax,
        ox,
        bottom + 0.22 * H,
        ow,
        H * 0.26,
        "Prioritized candidate:\nEphb1\n(081230020-HRB)",
        fontsize=9,
        bold=True,
    )

    # connecting arrows between groups
    # from INPUT main box to WORKFLOW step1
    add_arrow(ax, x_left + w_left, by + bh / 2, x_mid, y1 + step_h / 2, lw=1)
    # from WORKFLOW step3 to OUTPUT criteria
    add_arrow(ax, x_mid + w_mid, y3 + step_h / 2, x_right, bottom + 0.72 * H, lw=1)

    # Optional small caption (can delete later in AI)
    ax.text(
        0.04,
        0.97,
        "Figure 1a | Genetic screening workflow (schematic)",
        ha="left",
        va="center",
        fontsize=10,
        fontweight="bold",
    )

    pdf_path = outdir / "000_figure_1a_workflow.pdf"
    svg_path = outdir / "000_figure_1a_workflow.svg"
    fig.savefig(pdf_path, transparent=True)
    fig.savefig(svg_path, transparent=True)
    plt.close(fig)

    print(f"[OK] Wrote: {pdf_path}")
    print(f"[OK] Wrote: {svg_path}")


if __name__ == "__main__":
    main()