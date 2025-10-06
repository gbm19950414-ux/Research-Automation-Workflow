#!/usr/bin/env python3
"""
04_roi_annotation.py
对每个 gel_crops 下的最佳曝光 WB 图像进行 ROI 标注。

输入：
- exposure_selected.yaml（由 03_select_exposure_from_crops.py 生成）
- gel_crops/<shot_id>/<gel_id>_<target>_<sample_batch>/best_exposure.tif

输出：
- 每个文件夹生成 roi.yaml，记录多边形坐标与对应样本名称

本版本支持通过点击四个点定义倾斜矩形的 ROI。
"""

import yaml
import numpy as np
from PIL import Image
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.widgets import PolygonSelector

def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def save_yaml(data, path):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def annotate_roi(image_path, save_path):
    """交互式绘制倾斜矩形 ROI（四点多边形）并保存坐标"""
    img = np.array(Image.open(image_path))
    fig, ax = plt.subplots()
    ax.imshow(img, cmap="gray")
    plt.title(f"ROI annotation (click 4 points): {image_path.name}")
    rois = []
    current_points = []

    def onselect(verts):
        if len(verts) == 4:
            polygon = np.array(verts)
            rois.append({"points": polygon.tolist(), "sample": f"S{len(rois)+1}"})
            ax.plot(*zip(*(list(polygon) + [polygon[0]])), color='r', linewidth=1.5)
            fig.canvas.draw()
            print(f"[ROI] Added polygon with points: {polygon.tolist()}")
            polygon_selector.disconnect_events()
            plt.close(fig)

    polygon_selector = PolygonSelector(ax, onselect, useblit=False, props=dict(color='r', linewidth=1.5))
    plt.show()

    save_yaml(rois, save_path)
    print(f"[OK] ROI saved → {save_path}")

def main():
    root = Path(__file__).resolve().parents[2]
    gel_crops_root = root / "04_data/interim/wb/gel_crops"
    exposure_path = root / "04_data/interim/wb/exposure_selected/exposure_selected.yaml"

    if not exposure_path.exists():
        raise FileNotFoundError("Exposure selection YAML not found. Please run 03_select_exposure_from_crops.py first.")
    exposure = load_yaml(exposure_path)

    for shot_id, gels in exposure.items():
        print(f"[INFO] Processing {shot_id} ...")
        shot_dir = gel_crops_root / shot_id
        if not shot_dir.exists():
            print(f"[WARN] Missing folder: {shot_dir}")
            continue

        for gel_name, info in gels.items():
            gel_dir = shot_dir / gel_name
            best_file = info.get("best_file")
            if not best_file:
                print(f"[WARN] No best exposure found for {gel_name}")
                continue
            img_path = gel_dir / best_file
            if not img_path.exists():
                print(f"[WARN] Missing image: {img_path}")
                continue

            roi_path = gel_dir / "roi.yaml"
            print(f"[INFO] Launching ROI annotation for {gel_name}")
            annotate_roi(img_path, roi_path)

    print("[ALL DONE] ROI annotation complete for all gels.")

if __name__ == "__main__":
    main()