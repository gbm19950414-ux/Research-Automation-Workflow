#!/usr/bin/env python3
# ============================
# Script A: define gel_boxes in shot.yaml
# ============================
# 用途：
#   只负责交互式画框，并把 gel_boxes 写回：
#   EphB1/04_data/raw/wb/shots/<shot_name>/shot.yaml
#   最小单位原则：同一批样品、同一个抗体的一张图
#
# 运行示例：
#   python 00_define_gel_boxes.py --shot E26_SHOT1 --expect 3
#
# 参数：
#   --shot         必填，shots 下的 shot 目录名
#   --expect       预期胶块数量，用来提示（默认 5）
#   --reset-boxes  若已存在 gel_boxes，清空后重画
#
# 后续：
#   画完框并保存后，再运行 01_split_shot.py 进行裁剪。
# ============================

import matplotlib
matplotlib.use("MacOSX")

from pathlib import Path
import yaml
import numpy as np
from PIL import Image


def load_arr(p: Path):
    return np.array(Image.open(p))


def main(shot_name: str, expect: int = 5, reset_boxes: bool = False):
    if shot_name is None:
        raise ValueError("shot_name cannot be None")

    root = Path(__file__).resolve().parents[2]  # EphB1/
    raw_shot = root / "04_data" / "raw" / "wb" / "shots" / shot_name
    meta_path = raw_shot / "shot.yaml"

    assert raw_shot.exists(), f"raw shot not found: {raw_shot}"
    assert meta_path.exists(), f"shot.yaml not found: {meta_path}"

    with open(meta_path, "r") as f:
        meta = yaml.safe_load(f)

    if reset_boxes:
        meta["gel_boxes"] = []
        print("[INFO] --reset-boxes: cleared existing gel_boxes in shot.yaml")

    boxes_existing = meta.get("gel_boxes") or []
    if boxes_existing and not reset_boxes:
        print(f"[INFO] Existing gel_boxes found in shot.yaml (n={len(boxes_existing)}).")
        print("       如果你想重画，请加 --reset-boxes 参数。")
        return

    # 读取白光图像
    white_key = meta.get("white")
    assert white_key, "shot.yaml must contain 'white' key pointing to TIFF file"
    white_path = raw_shot / white_key
    assert white_path.exists(), f"white image not found: {white_path}"
    white = load_arr(white_path)

    # 进入交互式画框
    import matplotlib.pyplot as plt
    from matplotlib.widgets import RectangleSelector

    fig, ax = plt.subplots()
    ax.imshow(white, cmap="gray")
    ax.set_title(
        f"{shot_name}: Draw up to {expect} boxes\n"
        "click-drag to add; 'r' reset; 'enter' finish"
    )

    rects = []
    artists = []

    def onselect(eclick, erelease):
        x0, y0 = eclick.xdata, eclick.ydata
        x1, y1 = erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x1 - x0))
        h = int(abs(y1 - y0))
        rects.append([x, y, w, h])
        r_artist = plt.Rectangle((x, y), w, h, fill=False, linewidth=1.0)
        artists.append(r_artist)
        ax.add_patch(r_artist)
        fig.canvas.draw_idle()

    def on_key(event):
        if event.key == "r":
            rects.clear()
            for art in artists:
                art.remove()
            artists.clear()
            fig.canvas.draw_idle()
        elif event.key == "enter":
            plt.close(fig)

    # Keep a reference to the selector; otherwise it may be garbage-collected
    selector = RectangleSelector(ax, onselect, useblit=False, interactive=True)
    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()

    if len(rects) > expect:
        rects[:] = rects[:expect]

    if not rects:
        raise SystemExit("No boxes were drawn. Aborting without modifying shot.yaml.")

    boxes = []
    print("[INFO] Now enter target and sample_batch for each gel box.")
    print("       直接回车可沿用上一框（第一次使用默认 UNKNOWN / BATCH）.")

    last_target = None
    last_batch = None

    for i, rect in enumerate(rects):
        print(f"\n[BOX {i+1}] rect = {rect}")
        default_target = last_target or "UNKNOWN"
        default_batch = last_batch or "BATCH"

        try:
            target_in = input(f"  target [{default_target}]: ").strip()
        except EOFError:
            target_in = ""
        try:
            batch_in = input(f"  sample_batch [{default_batch}]: ").strip()
        except EOFError:
            batch_in = ""

        target = target_in or default_target
        sample_batch = batch_in or default_batch

        last_target = target
        last_batch = sample_batch

        boxes.append(
            {
                "gel_id": f"G{i+1}",
                "rect": rect,
                "target": target,
                "sample_batch": sample_batch,
            }
        )

    meta["gel_boxes"] = boxes
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False)

    print(f"[OK] Saved {len(boxes)} gel_boxes to {meta_path}")
    for b in boxes:
        print("   ", b)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", help="shots 下的 shot 目录名")
    ap.add_argument(
        "--expect", type=int, default=5, help="number of gels expected (for UI hint only)"
    )
    ap.add_argument(
        "--reset-boxes",
        action="store_true",
        help="clear existing gel_boxes in shot.yaml before drawing",
    )
    args = ap.parse_args()

    if args.shot is None:
        root = Path(__file__).resolve().parents[2]
        shots_dir = root / "04_data" / "raw" / "wb" / "shots"
        inferred = None
        for folder in sorted(shots_dir.iterdir()):
            meta_path = folder / "shot.yaml"
            if not meta_path.exists():
                continue
            with open(meta_path, "r") as f:
                meta = yaml.safe_load(f)
            if not meta.get("gel_boxes"):
                inferred = folder.name
                break
        if inferred is None:
            print("[INFO] No shot with empty gel_boxes found. Exiting.")
            raise SystemExit
        args.shot = inferred
        print(f"[INFO] Auto-selected shot: {args.shot}")

    main(args.shot, args.expect, args.reset_boxes)