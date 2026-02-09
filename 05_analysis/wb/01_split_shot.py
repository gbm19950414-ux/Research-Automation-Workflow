#!/usr/bin/env python3
# ============================
# Script B: crop gels into gel_crops using existing gel_boxes
# ============================
# 用途：
#   读取 shot.yaml 里的 gel_boxes / file / seconds 信息，
#   把原始 TIFF 裁剪到：
#   EphB1/04_data/interim/wb/gel_crops/<shot_name>/<gel_id>_<target>_<sample_batch>/
#
# 要求：
#   已经用 00_define_gel_boxes.py 写好了 gel_boxes。
#
# 运行示例：
#   python 01_split_shot.py 会自动扫描没有被切割的shot，自动切割到gel_crops 文件夹
#
# 参数：
#   --shot        必填，shot 目录名
#   --force       默认会“跳过已裁剪目录”；加 --force 则重新覆盖裁剪
#
# “跳过已处理”逻辑：
#   - 每个 dst_dir（G1_target_batch 这种）如果已经存在任何 .tif 文件，
#     且未加 --force，则直接跳过该 box，并打印 [SKIP]。
# ============================

from pathlib import Path
import yaml
import numpy as np
from PIL import Image
import glob
import shutil


def load_arr(p: Path):
    return np.array(Image.open(p))


def save_arr(path: Path, arr):
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


def crop(arr, rect):
    x, y, w, h = rect
    return arr[y : y + h, x : x + w]


def expected_dirs_from_gel_boxes(gel_boxes):
    valid_dirs = set()
    for entry in gel_boxes:
        target = str(entry.get("target", "UNKNOWN")).strip()
        gel_id = entry.get("gel_id", "G?")
        sample_batch = entry.get("sample_batch", "BATCH")
        valid_dirs.add(f"{gel_id}_{target}_{sample_batch}")
    return valid_dirs


def main(shot_name: str, force: bool = False):
    root = Path(__file__).resolve().parents[2]  # EphB1/
    raw_shot = root / "04_data" / "raw" / "wb" / "shots" / shot_name
    meta_path = raw_shot / "shot.yaml"

    assert raw_shot.exists(), f"raw shot not found: {raw_shot}"
    assert meta_path.exists(), f"shot.yaml not found: {meta_path}"

    with open(meta_path, "r") as f:
        meta = yaml.safe_load(f)

    gel_boxes = meta.get("gel_boxes") or []
    if not gel_boxes:
        raise SystemExit(
            "No gel_boxes found in shot.yaml.\n"
            "请先运行：python 00_define_gel_boxes.py --shot "
            + shot_name
        )

    # file / seconds 信息
    file_entry = meta.get("file")
    if not file_entry:
        raise KeyError("No 'file' specified in shot.yaml")

    seconds_entry = meta.get("seconds", "s1")

    if isinstance(file_entry, str):
        file_list = [file_entry]
    elif isinstance(file_entry, list):
        if not file_entry:
            raise ValueError("'file' list in shot.yaml is empty")
        file_list = file_entry
    else:
        raise TypeError("'file' in shot.yaml must be a string or a list of strings")

    if isinstance(seconds_entry, list):
        seconds_list = [str(s) for s in seconds_entry]
        seconds_base = None
    else:
        seconds_list = None
        seconds_base = str(seconds_entry)

    gel_root = root / "04_data" / "interim" / "wb" / "gel_crops" / shot_name
    shot_id = meta.get("shot_id", "UNKNOWN_SHOT")
    print(f"[INFO] Shot: {shot_name} (shot_id={shot_id})")
    print(f"[INFO] Using {len(gel_boxes)} gel_boxes, cropping into: {gel_root}")

    for file_idx, file_name in enumerate(file_list):
        file_path = raw_shot / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # 决定这个文件对应的 seconds 标签
        if seconds_list is not None:
            if file_idx < len(seconds_list):
                seconds_for_file = seconds_list[file_idx]
            else:
                seconds_for_file = f"s{file_idx+1}"
        else:
            if len(file_list) > 1:
                seconds_for_file = f"{seconds_base}_f{file_idx+1}"
            else:
                seconds_for_file = seconds_base

        print(f"[INFO] Cropping file[{file_idx}]={file_name}, seconds={seconds_for_file}")

        for entry in gel_boxes:
            target = str(entry.get("target", "UNKNOWN")).strip()
            gel_id = entry.get("gel_id", "G?")
            rect = entry.get("rect")
            sample_batch = entry.get("sample_batch", "BATCH")

            if not rect or len(rect) != 4:
                print(f"[WARN] Skip {gel_id} (invalid rect: {rect})")
                continue

            dst_dir = gel_root / f"{gel_id}_{target}_{sample_batch}"
            dst_dir.mkdir(parents=True, exist_ok=True)

            # --- 跳过已处理逻辑 ---
            existing_tifs = glob.glob(str(dst_dir / "*.tif"))
            if existing_tifs and not force:
                print(
                    f"[SKIP] {dst_dir} already has {len(existing_tifs)} .tif files. "
                    "Use --force to overwrite."
                )
                continue

            for i, arr, suffix in iter_pages(file_path):
                out_name = f"{target}_{seconds_for_file}{suffix}.tif"
                sub = crop(arr, rect)
                save_arr(dst_dir / out_name, sub)

            print(f"[OK] Cropped to {dst_dir}")

    # --- 清理不属于 gel_boxes 的旧文件夹 ---
    valid_dirs = expected_dirs_from_gel_boxes(gel_boxes)

    for sub in gel_root.iterdir():
        if not sub.is_dir():
            continue
        if sub.name not in valid_dirs:
            print(f"[CLEAN] Removing stale folder not in gel_boxes: {sub}")
            shutil.rmtree(sub)

    print(f"[DONE] All gels cropped into {gel_root}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--shot",
        help="shot 目录名；若不提供则遍历所有 shots 自动检查并按 gel_boxes 重新裁剪"
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="do not skip existing dst_dir; overwrite crops",
    )
    args = ap.parse_args()

    if args.shot:
        # 手动指定单个 shot：保持原有行为
        main(args.shot, args.force)
    else:
        # 自动模式：遍历全部 shots
        root = Path(__file__).resolve().parents[2]
        shots_dir = root / "04_data" / "raw" / "wb" / "shots"
        if not shots_dir.exists():
            print(f"[INFO] shots dir not found: {shots_dir}")
            raise SystemExit

        print(f"[INFO] Auto mode: scanning all shots in {shots_dir}")

        for folder in sorted(shots_dir.iterdir()):
            if not folder.is_dir():
                continue
            meta_path = folder / "shot.yaml"
            if not meta_path.exists():
                continue

            shot_name = folder.name
            with open(meta_path, "r") as f:
                meta = yaml.safe_load(f)

            gel_boxes = meta.get("gel_boxes") or []
            if not gel_boxes:
                print(f"[SKIP] {shot_name}: no gel_boxes in shot.yaml")
                continue

            expected = expected_dirs_from_gel_boxes(gel_boxes)
            gel_root = root / "04_data" / "interim" / "wb" / "gel_crops" / shot_name

            existing = set()
            if gel_root.exists():
                for sub in gel_root.iterdir():
                    if sub.is_dir():
                        existing.add(sub.name)

            if gel_root.exists() and existing == expected:
                print(f"[OK] {shot_name}: gel_crops fully matches gel_boxes, skip.")
                continue

            print(f"[REBUILD] {shot_name}: mismatch or missing crops, recropping with cleanup.")
            main(shot_name, force=True)