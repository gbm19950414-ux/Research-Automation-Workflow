#!/usr/bin/env python3
"""
03_select_exposure_from_crops.py
对每个 gel_crops 下的分割结果自动挑选最佳曝光图像。

逻辑：
- 每个 shot 文件夹包含多个 gel_id_target_sample_batch 子文件夹；
- 每个子文件夹内有多个曝光时间点（多张 .tif）；
- 逐个读取计算曝光指标（平均灰度、对比度、信噪比）；
- 排除过曝或过暗，选出最佳曝光；
- 结果写入 exposure_selected.yaml。
"""

import yaml
import numpy as np
from PIL import Image
from pathlib import Path
from skimage import img_as_float

def compute_metrics(arr: np.ndarray):
    """计算曝光质量指标"""
    img = img_as_float(arr)
    mean_intensity = np.mean(img)
    sat_ratio = np.mean(img > 0.98)  # 过曝比例
    dark_ratio = np.mean(img < 0.02)
    contrast = np.percentile(img, 99) - np.percentile(img, 1)
    snr = contrast / (0.01 + np.std(img))
    return dict(
        mean=mean_intensity,
        sat_ratio=sat_ratio,
        dark_ratio=dark_ratio,
        contrast=contrast,
        snr=snr,
    )

def to_native(o):
    """递归将 numpy 类型转换为原生 Python 类型"""
    if isinstance(o, dict):
        return {k: to_native(v) for k, v in o.items()}
    elif isinstance(o, list):
        return [to_native(v) for v in o]
    elif isinstance(o, (np.generic, np.ndarray)):
        return o.item() if np.ndim(o) == 0 else [to_native(v) for v in o.tolist()]
    else:
        return o

def choose_best(metrics_list):
    """根据指标挑选最佳曝光页"""
    valid = [m for m in metrics_list if m["sat_ratio"] < 0.02 and m["mean"] > 0.05]
    if not valid:
        valid = metrics_list
    best = sorted(valid, key=lambda x: (x["snr"], x["contrast"]), reverse=True)[0]
    return best

def main():
    root = Path(__file__).resolve().parents[2]
    gel_crops_root = root / "04_data/interim/wb/gel_crops"
    output_root = root / "04_data/interim/wb/exposure_selected"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for shot_dir in sorted(gel_crops_root.glob("*")):
        if not shot_dir.is_dir():
            continue
        print(f"[INFO] Processing {shot_dir.name} ...")

        shot_result = {}

        for gel_dir in sorted(shot_dir.glob("*")):
            if not gel_dir.is_dir():
                continue
            tifs = sorted(gel_dir.glob("*.tif"))
            if not tifs:
                print(f"[WARN] No .tif files found in {gel_dir}")
                continue

            metrics_list = []
            for tif in tifs:
                arr = np.array(Image.open(tif))
                m = compute_metrics(arr)
                m["file"] = tif.name
                metrics_list.append(m)

            best = choose_best(metrics_list)
            shot_result[gel_dir.name] = {
                "best_file": best["file"],
                "metrics": best,
                "all_files": metrics_list,
            }
            print(f"  - {gel_dir.name}: selected {best['file']} "
                  f"(SNR={best['snr']:.2f}, contrast={best['contrast']:.3f})")

        all_results[shot_dir.name] = shot_result

    out_path = output_root / "exposure_selected.yaml"
    all_results_native = to_native(all_results)
    with open(out_path, "w") as f:
        yaml.safe_dump(all_results_native, f, sort_keys=False, allow_unicode=True)

    print(f"[OK] Exposure selection complete → {out_path}")

if __name__ == "__main__":
    main()