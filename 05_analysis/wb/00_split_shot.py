#!/usr/bin/env python3
import matplotlib
matplotlib.use('MacOSX')
from pathlib import Path
import yaml, numpy as np
from PIL import Image
from skimage.filters import threshold_otsu
from skimage.measure import label, regionprops

def load_arr(p): return np.array(Image.open(p))

def save_arr(path, arr):
    Image.fromarray(arr).save(path)

def iter_pages(path: Path):
    """
    Yield tuples of (page_index, np.ndarray, out_name_suffix) for each page in a TIFF.
    If single-page, yields once with suffix "".
    """
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    for i in range(n):
        if n > 1:
            try:
                im.seek(i)
            except EOFError:
                break
        arr = np.array(im)
        suffix = f"_p{i+1:03d}" if n > 1 else ""
        yield i, arr, suffix

def detect_boxes(white_arr, expect=5):
    a = white_arr.astype(np.float32)
    t = threshold_otsu(a)
    mask = a > t
    lab = label(mask)
    regs = sorted(regionprops(lab), key=lambda r: -r.area)[:expect]
    boxes = []
    for r in regs:
        minr, minc, maxr, maxc = r.bbox
        boxes.append([int(minc), int(minr), int(maxc-minc), int(maxr-minr)])
    boxes.sort(key=lambda b: b[0])  # 从左到右 → G1..G5
    return boxes

def crop(arr, rect):
    x,y,w,h = rect
    return arr[y:y+h, x:x+w]

def main(shot_name, expect=5, interactive=False, reset_boxes=False):
    root = Path(__file__).resolve().parents[2]  # EphB1/
    raw_shot = root / "04_data" / "raw" / "wb" / "shots" / shot_name
    meta_path = root / "04_data" / "interim" / "wb" / "shots" / shot_name / "shot.yaml"
    assert raw_shot.exists(), f"raw shot not found: {raw_shot}"
    assert meta_path.exists(), f"shot.yaml not found: {meta_path}"

    with open(meta_path, "r") as f:
        meta = yaml.safe_load(f)
    # Load white image early so it is available for both interactive and auto-detect branches
    white = load_arr(raw_shot / meta["white"])

    if reset_boxes:
        meta["gel_boxes"] = []
        print("[INFO] --reset-boxes: cleared existing gel_boxes in shot.yaml")

    boxes_existing = meta.get("gel_boxes") or []
    if not boxes_existing:
        if interactive:
            print("[INFO] Interactive mode: launching rectangle selector UI...")
            import matplotlib.pyplot as plt
            from matplotlib.widgets import RectangleSelector
            fig, ax = plt.subplots()
            ax.imshow(white, cmap="gray")
            ax.set_title(f"Draw {expect} boxes: click-drag to add; 'r' reset; 'enter' to finish.")
            rects, artists = [], []
            def onselect(eclick, erelease):
                x0, y0 = eclick.xdata, eclick.ydata
                x1, y1 = erelease.xdata, erelease.ydata
                if None in (x0, y0, x1, y1):
                    return
                x, y = int(min(x0, x1)), int(min(y0, y1))
                w, h = int(abs(x1 - x0)), int(abs(y1 - y0))
                rects.append([x, y, w, h])
                r_artist = plt.Rectangle((x, y), w, h, fill=False, linewidth=1.0)
                artists.append(r_artist)
                ax.add_patch(r_artist)
                fig.canvas.draw_idle()
            def on_key(event):
                if event.key == "r":
                    rects.clear()
                    for art in artists: art.remove()
                    artists.clear()
                    fig.canvas.draw_idle()
                elif event.key == "enter":
                    plt.close(fig)
            rs = RectangleSelector(ax, onselect, useblit=False, interactive=True)
            fig.canvas.mpl_connect("key_press_event", on_key)
            plt.show()
            if len(rects) > expect:
                rects = rects[:expect]
            boxes = rects
            if not boxes:
                raise SystemExit("No boxes were drawn. If no window appeared, try: "
                                 "MPLBACKEND=MacOSX or MPLBACKEND=Qt5Agg and rerun with --interactive.")
        else:
            boxes = detect_boxes(white, expect=expect)
        meta["gel_boxes"] = [{"gel_id": f"G{i+1}", "rect": boxes[i]} for i in range(len(boxes))]
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f: yaml.safe_dump(meta, f, sort_keys=False)
        print("[INFO] gel_boxes set and saved to shot.yaml")
    else:
        print(f"[INFO] Using existing gel_boxes from shot.yaml (n={len(boxes_existing)}). "
              f"Pass --reset-boxes to redraw them.")

    gel_root = root / "04_data" / "interim" / "wb" / "gel_crops"
    for run in meta["runs"]:
        src = raw_shot / run["file"]
        if not src.exists():
            raise FileNotFoundError(f"Run image not found: {src}")
        target = str(run.get("target", "UNKNOWN")).strip()

        # Iterate each page (single or multi-page TIFF)
        for i, arr, suffix in iter_pages(src):
            out_base = src.stem + suffix + src.suffix.lower()
            for gb in meta["gel_boxes"]:
                sub = crop(arr, gb["rect"])
                dst_dir = gel_root / gb["gel_id"] / target
                dst_dir.mkdir(parents=True, exist_ok=True)
                save_arr(dst_dir / out_base, sub)
    # Done
    print("[OK] Cropped all runs into gel_crops/<Gk>/<target>/")
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--expect", type=int, default=5, help="number of gels expected")
    ap.add_argument("--interactive", action="store_true", help="draw gel boxes manually instead of auto-detecting")
    ap.add_argument("--reset-boxes", action="store_true", help="ignore and clear existing gel_boxes, then prompt for manual selection (with --interactive) or auto-detect")
    args = ap.parse_args()
    main(args.shot, args.expect, args.interactive, args.reset_boxes)