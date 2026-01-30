#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MVP: Run sheet timeline table generator

Usage:
  python visualize_run_sheet_timeline.py /path/to/run_sheet_temp.yaml

Behavior:
- Each step has a base 'day' (int).
- If a step contains 'offset days: N', then for each run in that step:
    shift[run] += N
  and the current + all subsequent steps for that run are shifted by N days.
- 'run' field is supported as list[str]; also supports 'applies_to'.
Outputs:
- <yaml_basename>_timeline.tsv
- <yaml_basename>_timeline_by_run.tsv
"""

import os
import sys
import yaml
import csv
from collections import defaultdict
import matplotlib.pyplot as plt
import textwrap
from matplotlib import font_manager

def _pick_cjk_font():
    """
    Pick an available CJK-capable font on the current system.
    Works on macOS/Windows/Linux depending on installed fonts.
    """
    preferred = [
        "PingFang SC", "Heiti SC", "STHeiti", "Songti SC",
        "Microsoft YaHei", "SimHei",
        "Noto Sans CJK SC", "Noto Sans SC",
        "Arial Unicode MS",
        "WenQuanYi Zen Hei",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            return name
    return "DejaVu Sans"

def _wrap_cjk(s: str, width: int = 18) -> str:
    """
    Wrap text by character count (CJK-friendly).
    """
    s = "" if s is None else str(s)
    s = s.strip()
    if not s:
        return s
    return "\n".join([s[i:i+width] for i in range(0, len(s), width)])

def _get_runs(step: dict):
    # support both run: and applies_to:
    runs = step.get("run", step.get("applies_to", []))
    if runs is None:
        return []
    if isinstance(runs, str):
        return [runs]
    if isinstance(runs, list):
        return [str(x) for x in runs]
    return []

def main(yaml_path: str):
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "run_sheet" not in data:
        raise ValueError("YAML missing top-level key: run_sheet")

    rs = data["run_sheet"]
    steps = rs.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("run_sheet.steps must be a list")

    # Matplotlib font setup for Chinese text
    cjk_font = _pick_cjk_font()
    plt.rcParams["font.sans-serif"] = [cjk_font]
    plt.rcParams["axes.unicode_minus"] = False

    # cumulative shift per run
    shift = defaultdict(int)

    records = []
    for idx, step in enumerate(steps, start=1):
        action = step.get("action", "")
        base_day = step.get("day", None)
        if base_day is None:
            raise ValueError(f"Step #{idx} missing 'day': action={action}")
        try:
            base_day = int(base_day)
        except Exception:
            raise ValueError(f"Step #{idx} 'day' must be int: got {base_day}")

        runs = _get_runs(step)
        if not runs:
            # allow step with no runs; still output a row with run="(none)"
            runs = ["(none)"]

        # If offset days exists, it should shift THIS action and all subsequent actions for these runs.
        offset = step.get("offset days", 0)
        try:
            offset = int(offset)
        except Exception:
            raise ValueError(f"Step #{idx} 'offset days' must be int if provided: got {offset}")

        # Build annotation note from all fields after `action:` (i.e., other keys in this step)
        exclude_keys = {"action", "day", "run", "applies_to"}
        note_items = []
        for k in sorted(step.keys()):
            if k in exclude_keys:
                continue
            v = step.get(k)
            # skip empty
            if v is None or v == "" or v == [] or v == {}:
                continue
            note_items.append(f"{k}={v}")
        note = "; ".join(note_items) if note_items else f"seq={idx}"

        # Optional duration (days) for block width
        duration = step.get("duration_days", 1)
        try:
            duration = float(duration)
        except Exception:
            duration = 1.0
        if duration <= 0:
            duration = 1.0

        if offset != 0:
            for r in runs:
                if r != "(none)":
                    shift[r] += offset

        for r in runs:
            eff_day = base_day + (shift[r] if r != "(none)" else 0)
            records.append({
                "seq": idx,
                "run": r,
                "base_day": base_day,
                "shift_applied": (shift[r] if r != "(none)" else 0),
                "day": eff_day,
                "action": str(action),
                "offset days_here": offset,
                "note": note,
                "duration_days": duration
            })

    # output paths
    base = os.path.splitext(os.path.basename(yaml_path))[0]
    out_dir = os.path.dirname(os.path.abspath(yaml_path))
    out1 = os.path.join(out_dir, f"{base}_timeline.tsv")
    out2 = os.path.join(out_dir, f"{base}_timeline_by_run.tsv")

    # write out1 (sorted by effective day then seq)
    records_sorted = sorted(records, key=lambda x: (x["day"], x["seq"], x["run"]))
    with open(out1, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records_sorted[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(records_sorted)

    # write out2 (sorted by run then effective day)
    records_by_run = sorted(records, key=lambda x: (x["run"], x["day"], x["seq"]))
    with open(out2, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records_by_run[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(records_by_run)

    # -------------------------
    # 3) PNG timeline (MVP) - action blocks
    # -------------------------
    # Prepare run order: alphabetical, "(none)" last if present
    runs_all = sorted({r["run"] for r in records if r["run"] != "(none)"})
    if any(r["run"] == "(none)" for r in records):
        runs_all.append("(none)")

    run_to_y = {r: i for i, r in enumerate(runs_all)}

    # Figure sizing
    xs_all = [r["day"] for r in records]
    xmin, xmax = (min(xs_all), max(xs_all)) if xs_all else (0, 1)
    fig_w = max(10, 0.8 * (xmax - xmin + 2))
    fig_h = max(4, 0.7 * len(runs_all) + 1)

    plt.figure(figsize=(fig_w, fig_h))

    # Spread actions within the same (run, day) horizontally in seq order
    # Compute maximum number of actions on the same day for any run
    counts = defaultdict(int)
    for rec in records:
        counts[(rec["run"], rec["day"])] += 1
    max_actions_per_run_day = max(counts.values()) if counts else 1
    day_stride = max_actions_per_run_day + 1

    # Pre-compute within-day indices by (run, day) in seq order
    within_idx_map = {}
    grouped = defaultdict(list)
    for rec in records:
        grouped[(rec["run"], rec["day"])].append(rec)
    for key, recs in grouped.items():
        recs_sorted = sorted(recs, key=lambda x: x["seq"])
        for i, rec in enumerate(recs_sorted):
            within_idx_map[(rec["seq"], rec["run"])] = i

    lane_height = 0.8
    for rec in sorted(records, key=lambda x: (x["run"], x["day"], x["seq"])):
        r = rec["run"]
        y0 = run_to_y[r]
        day0 = float(rec["day"])
        within_idx = within_idx_map.get((rec["seq"], rec["run"]), 0)

        # Stretch x axis so multiple actions on the same day can be ordered left->right
        start = day0 * day_stride + within_idx

        dur = float(rec.get("duration_days", 1.0))
        if dur > 1:
            width = dur * day_stride - 0.2
        else:
            width = 0.8

        bar_y = y0 - lane_height / 2
        bar_h = lane_height

        plt.broken_barh([(start, width)], (bar_y, bar_h))
        # annotate with wrapped action text (Chinese-friendly)
        action_txt = _wrap_cjk(rec.get("action", ""), width=18)
        plt.annotate(
            action_txt,
            (start, y0),
            textcoords="offset points",
            xytext=(4, 2),
            fontsize=9,
            va="bottom",
            ha="left",
            clip_on=False,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.7),
        )


    # X ticks at day boundaries (stretched axis)
    days_all = sorted({float(r["day"]) for r in records})
    xticks = [d * day_stride for d in days_all]
    xlabels = [str(int(d)) if float(d).is_integer() else str(d) for d in days_all]
    plt.xticks(xticks, xlabels)

    plt.yticks(range(len(runs_all)), runs_all)
    plt.xlabel("Day (after per-run offsets; stretched within-day ordering)")
    plt.ylabel("Run")
    plt.title(f"Run sheet timeline: {base}")
    plt.grid(True, axis="x", linestyle="--", alpha=0.4)

    png_path = os.path.join(out_dir, f"{base}_timeline.png")
    plt.tight_layout()
    plt.savefig(png_path, dpi=200)
    plt.close()

    print("[OK] Wrote:")
    print(" -", out1)
    print(" -", out2)
    print(" -", png_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python visualize_run_sheet_timeline.py /path/to/run_sheet_temp.yaml")
        sys.exit(1)
    main(sys.argv[1])