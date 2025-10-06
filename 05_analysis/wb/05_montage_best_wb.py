#!/usr/bin/env python3
"""
05_montage_best_wb.py
将每个 shot 的最佳曝光 WB 条带自动拼接成面板图。

输入：
- 04_data/interim/wb/gel_crops/<shot_id>/<gel_id>_<target>_<sample_batch>/
  └── <best_exposure>.tif
- 04_data/interim/wb/exposure_selected/exposure_selected.yaml

输出：
- 04_data/processed/wb/montage/<shot_id>_montage.tif
"""

import yaml
import numpy as np
from PIL import Image
from pathlib import Path
import warnings
import argparse

def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def montage_vert(images, spacing=30):
    """纵向拼接图像（从上到下）"""
    w = max(im.shape[1] for im in images)
    h_total = sum(im.shape[0] for im in images) + spacing * (len(images) - 1)
    canvas = np.ones((h_total, w), dtype=images[0].dtype) * 255
    y = 0
    for im in images:
        h, w_im = im.shape
        canvas[y:y+h, :w_im] = im
        y += h + spacing
    return canvas


def read_roi_yaml(roi_path):
    """读取roi.yaml，返回多边形点的列表（每个ROI条带为一个多边形点列表）
    支持的格式：
      - [ [x1,y1], [x2,y2], [x3,y3], [x4,y4] ]                     # 纯多边形列表
      - [ {"points": [[x1,y1],...], "sample": "S1"}, {...} ]       # 新版：列表里是字典，含points
      - {"roi": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]}              # 旧版：dict里嵌套一个列表
      - [ {"rect": [x,y,w,h]}, ... ]                               # 兼容矩形：自动转为四点
    返回：list[ list[[x,y], ...] ]
    """
    try:
        data = load_yaml(roi_path)
        polys = []

        if isinstance(data, list):
            for item in data:
                # 列表项本身就是点列表
                if isinstance(item, list) and len(item) >= 4 and isinstance(item[0], (list, tuple)):
                    polys.append([[float(x), float(y)] for x, y in item[:4]])
                # 列表项是字典，含 points
                elif isinstance(item, dict) and "points" in item and isinstance(item["points"], list):
                    pts = item["points"]
                    if len(pts) >= 4:
                        polys.append([[float(x), float(y)] for x, y in pts[:4]])
                # 列表项是字典，含 rect -> 转四点
                elif isinstance(item, dict) and "rect" in item and isinstance(item["rect"], (list, tuple)) and len(item["rect"]) == 4:
                    x, y, w, h = item["rect"]
                    polys.append([[float(x), float(y)], [float(x+w), float(y)], [float(x+w), float(y+h)], [float(x), float(y+h)]])
        elif isinstance(data, dict):
            # 旧格式：dict里含一个列表或直接含points
            if "points" in data and isinstance(data["points"], list) and len(data["points"]) >= 4:
                pts = data["points"]
                polys.append([[float(x), float(y)] for x, y in pts[:4]])
            else:
                for v in data.values():
                    if isinstance(v, list):
                        if v and isinstance(v[0], (list, tuple)):
                            if len(v) >= 4:
                                polys.append([[float(x), float(y)] for x, y in v[:4]])
                        elif len(v) == 4 and all(isinstance(n, (int, float)) for n in v):
                            # rect as [x,y,w,h]
                            x, y, w, h = v
                            polys.append([[float(x), float(y)], [float(x+w), float(y)], [float(x+w), float(y+h)], [float(x), float(y+h)]])
        return polys
    except Exception as e:
        warnings.warn(f"Failed to read ROI yaml: {roi_path} ({e})")
        return []


def bounding_rect_from_polygon(poly, img_shape, expand_ratio=0.1):
    """从多边形点计算外接矩形, 并适当扩展（以保证band居中）"""
    xs = [pt[0] for pt in poly]
    ys = [pt[1] for pt in poly]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y
    # 扩展10%
    expand_x = int(w * expand_ratio / 2)
    expand_y = int(h * expand_ratio / 2)
    min_x = max(0, min_x - expand_x)
    min_y = max(0, min_y - expand_y)
    max_x = min(img_shape[1], max_x + expand_x)
    max_y = min(img_shape[0], max_y + expand_y)
    return int(min_x), int(min_y), int(max_x), int(max_y)

def percentile_stretch(im, pmin=1, pmax=99):
    """简单的百分位数拉伸，返回float64数组"""
    lower = np.percentile(im, pmin)
    upper = np.percentile(im, pmax)
    if upper == lower:
        return im.astype(np.float64)
    stretched = (im.astype(np.float64) - lower) / (upper - lower)
    stretched = np.clip(stretched, 0, 1)
    stretched = stretched * 255
    return stretched

def main():
    parser = argparse.ArgumentParser(description="Generate montage of best exposure WB bands.")
    parser.add_argument("--preserve-raw", action="store_true", help="Preserve raw pixel values without percentile adjustment.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    gel_crops_root = root / "04_data/interim/wb/gel_crops"
    exposure_path = root / "04_data/interim/wb/exposure_selected/exposure_selected.yaml"
    output_root = root / "04_data/processed/wb/montage"
    output_root.mkdir(parents=True, exist_ok=True)

    exposure = load_yaml(exposure_path)

    for shot_id, gels in exposure.items():
        print(f"[INFO] Building montage for {shot_id} ...")

        shot_dir = gel_crops_root / shot_id
        imgs, labels = [], []

        for gel_name, info in gels.items():
            gel_dir = shot_dir / gel_name
            best_file = info.get("best_file")
            if not best_file:
                print(f"[WARN] {gel_name} has no best_file, skipping.")
                continue

            img_path = gel_dir / best_file
            if not img_path.exists():
                print(f"[WARN] Missing {img_path}, skipping.")
                continue

            # Load image preserving original dtype and pixel values
            img = np.array(Image.open(img_path))
            roi_path = gel_dir / "roi.yaml"
            use_full_img = False
            if roi_path.exists():
                rois = read_roi_yaml(roi_path)
                if rois and isinstance(rois[0], list) and len(rois[0]) >= 4:
                    # 只用第一个ROI（每个gel只有一个条带）
                    poly = rois[0]
                    min_x, min_y, max_x, max_y = bounding_rect_from_polygon(poly, img.shape)
                    cropped = img[min_y:max_y, min_x:max_x]
                else:
                    warnings.warn(f"No valid ROI found in {roi_path}, using full image.")
                    cropped = img
                    use_full_img = True
            else:
                warnings.warn(f"ROI file missing: {roi_path}, using full image.")
                cropped = img
                use_full_img = True

            if not args.preserve_raw:
                # Apply minimal percentile-based stretch to improve faint bands visibility
                cropped = percentile_stretch(cropped, pmin=1, pmax=99)
            else:
                # Keep raw pixel values as is (may be any dtype)
                cropped = cropped.astype(np.float64)

            imgs.append(cropped)
            labels.append(gel_name)

        if not imgs:
            print(f"[WARN] No valid images for {shot_id}.")
            continue

        panel = montage_vert(imgs, spacing=30)

        # Clip values to 0-255 and convert to uint8 before saving
        panel_uint8 = np.clip(panel, 0, 255).astype(np.uint8)

        # 保存面板
        out_path = output_root / f"{shot_id}_montage.tif"
        Image.fromarray(panel_uint8).save(out_path)
        print(f"[OK] Montage saved → {out_path}")

    print("[ALL DONE] Montage generation complete.")

if __name__ == "__main__":
    main()