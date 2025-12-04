# ============================
# How to Run This Script
# ============================
# Example:
#   python 04_roi_annotation.py
#
# Description:
#   This script loads:
#       EphB1/04_data/interim/wb/exposure_selected/exposure_selected.yaml
#   and performs interactive ROI annotation on each best-exposure image:
#       EphB1/04_data/interim/wb/gel_crops/<shot_id>/<gel_id>_<target>_<sample_batch>/best_exposure.tif
#
# Steps:
#   1. Run 00_split_shot.py to generate gel_crops/
#   2. Run 02_select_exposure.py to produce exposure_selected.yaml
#   3. Then run this script:
#         python 04_roi_annotation.py
#
# Output:
#   Each gel directory will receive a roi.yaml file containing polygon ROI points.
#
# Requirements:
#   - No arguments required
#   - Requires matplotlib GUI (MacOSX/Qt/Tk)
#
# ============================
#!/usr/bin/env python3
"""
04_roi_annotation.py
对每个 gel_crops 下的最佳曝光 WB 图像进行 ROI 标注。

输入：
- exposure_selected.yaml（由 03_select_exposure_from_crops.py 生成）
- gel_crops/<shot_id>/<gel_id>_<target>_<sample_batch>/best_exposure.tif

输出：
- 每个文件夹生成 roi.yaml，记录多边形坐标与对应样本名称

本版本支持通过点击四个点定义倾斜矩形的 ROI，且支持在同一张图像上标注多个 ROI。
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
    """交互式绘制一个或多个倾斜矩形 ROI（四点多边形）并保存坐标

    使用方式：
    - 每次弹出一张图像窗口，使用 PolygonSelector 依次点击 4 个点定义一个 ROI；
    - 关闭窗口后，终端会询问是否继续在同一张图上添加新的 ROI：
        * 输入 y 回车：继续添加下一个 ROI（重新弹出同一张图）
        * 直接回车或输入其他字符：结束本图的标注并保存所有 ROI
    """
    img = np.array(Image.open(image_path))
    rois = []
    roi_index = 1

    while True:
        fig, ax = plt.subplots()
        ax.imshow(img, cmap="gray")
        plt.title(f"ROI #{roi_index} (click 4 points): {image_path.name}")

        holder = {"verts": None}

        def onselect(verts):
            if len(verts) == 4:
                holder["verts"] = verts
                polygon = np.array(verts)
                ax.plot(
                    *zip(*(list(polygon) + [polygon[0]])),
                    color="r",
                    linewidth=1.5,
                )
                fig.canvas.draw()
                print(f"[ROI] Candidate polygon with points: {polygon.tolist()}")

        polygon_selector = PolygonSelector(
            ax,
            onselect,
            useblit=False,
            props=dict(color="r", linewidth=1.5),
        )

        plt.show()

        verts = holder["verts"]
        if verts is None:
            print("[INFO] No polygon drawn in this round, stop adding ROIs.")
            break

        polygon = np.array(verts)

        # ---- auto-detect target prefix from folder name ----
        gel_name = image_path.parent.name
        parts = gel_name.split("_")
        if len(parts) >= 2:
            target_prefix = parts[1]
        else:
            target_prefix = "band"

        # ---- ask user for band label ----
        user_band = input(
            "Band name for this ROI (e.g., full, p19, p17): "
        ).strip()
        if not user_band:
            user_band = f"band{len(rois)+1}"

        full_band = f"{target_prefix}_{user_band}"

        rois.append(
            {
                "points": polygon.tolist(),
                "band": full_band,
            }
        )

        print(f"[ROI] Added ROI #{len(rois)} with band: {full_band}")
        print(f"[ROI] Points: {polygon.tolist()}")

        cont = input(
            "Add another ROI on this image? (y/[n]): "
        ).strip().lower()
        if cont != "y":
            break

        roi_index += 1

    if not rois:
        print(f"[WARN] No ROI saved for {image_path.name}")
        return

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
            if roi_path.exists():
                print(f"[SKIP] roi.yaml already exists for {gel_name} → skipping annotation.")
                continue

            print(f"[INFO] Launching ROI annotation for {gel_name}")
            annotate_roi(img_path, roi_path)

    print("[ALL DONE] ROI annotation complete for all gels.")

if __name__ == "__main__":
    main()