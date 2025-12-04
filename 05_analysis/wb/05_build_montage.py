#!/usr/bin/env python3
"""
06_build_montage.py
读取 materials/<shot_id> 内的 *_patch.tif（与 exposure_selected.yaml 的顺序一致），
在每个条带上方添加泳道图注（来自 manifests/<date>.xlsx 的对应 shot 列），
并按纵向拼接生成最终 montage.tif。

输入：
- 04_data/interim/wb/materials/<shot_id>/<gel_name>_patch.tif
- 04_data/interim/wb/exposure_selected/exposure_selected.yaml
- 04_data/interim/wb/manifests/<date>.xlsx  （date 取自 shot_id 前缀，如 2025-09-22）

输出：
- 04_data/processed/wb/montage/<shot_id>_montage.tif
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import yaml
import re

# 尝试导入 pandas（用于读取 Excel 清单）；若失败则跳过图注
try:
    import pandas as pd
except Exception:
    pd = None


def load_yaml(p):
    with open(p, "r") as f:
        return yaml.safe_load(f)


def try_load_font(size=16):
    """尽量加载一个系统字体（支持中英文），失败则退回默认字体。"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB W3.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for fp in candidates:
        p = Path(fp)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


def montage_vert(images, spacing=30):
    """纵向拼接并『水平居中』每一张图。白底。"""
    W = max(im.shape[1] for im in images)
    H_total = sum(im.shape[0] for im in images) + spacing * (len(images) - 1)
    canvas = np.ones((H_total, W), dtype=images[0].dtype) * 255
    y = 0
    for im in images:
        h, w_im = im.shape
        x = (W - w_im) // 2  # 居中
        canvas[y:y+h, x:x+w_im] = im
        y += h + spacing
    return canvas


def read_lane_labels_from_manifest(manifest_path: Path, shot_id: str, gel_name: str):
    """
    从清单 Excel 里读取『该 gel 行』的泳道标签列表。
    规则：
      - 从 shot_id 提取日期和数字编号（SHOT2 → 2）；
      - 读取对应 Excel；
      - 过滤 shot == 2；
      - 再过滤 gel_id；
      - 按 lane 排序；
      - 返回多字段组合标签（sample_batch, treatment, target, genotype），每个泳道为 4 行文本组成的列表。
      - 若 sample_batch、treatment、target 与前一泳道相同，则该字段显示为空字符串。
    """
    if pd is None:
        print(f"[WARN] 未安装 pandas/openpyxl，跳过图注。可用 `pip install pandas openpyxl` 安装后重试。")
        return None
    if not manifest_path.exists():
        print(f"[WARN] Manifest not found: {manifest_path}")
        return None

    # 提取 shot 数字
    m = re.search(r"SHOT(\d+)", shot_id, flags=re.IGNORECASE)
    shot_num = m.group(1) if m else None

    # 解析 gel_name
    parts = str(gel_name).split("_")
    gel_id = parts[0] if len(parts) > 0 else None

    try:
        df = pd.read_excel(manifest_path, sheet_name=0)
    except Exception as e:
        print(f"[WARN] 读取清单失败: {manifest_path} ({e})")
        return None

    if shot_num is None:
        return None

    q = df.copy()

    # 过滤 shot == shot_num
    if 'shot' in q.columns:
        q = q[q['shot'].astype(str).str.strip() == str(shot_num)]
    else:
        # 如果没有 shot 列，则无法过滤，返回 None
        return None

    # 过滤 gel_id
    if gel_id is not None and 'gel_id' in q.columns:
        q = q[q['gel_id'].astype(str).str.strip() == str(gel_id)]

    if q.empty:
        return None

    # 需要 lane 列
    if 'lane' not in q.columns:
        print(f"[WARN] 清单缺少 'lane' 列: {manifest_path}")
        return None

    q = q.sort_values(by='lane', kind='mergesort')

    labels = []
    prev_sample_batch = None
    prev_treatment = None
    prev_target = None

    for _, row in q.iterrows():
        sample_batch = str(row['sample_batch']) if 'sample_batch' in row and pd.notna(row['sample_batch']) else None
        treatment = str(row['treatment']) if 'treatment' in row and pd.notna(row['treatment']) else None
        target = str(row['target']) if 'target' in row and pd.notna(row['target']) else None
        genotype = str(row['genotype']) if 'genotype' in row and pd.notna(row['genotype']) else None

        # 比较是否与前一泳道相同，若相同则显示空字符串
        if sample_batch == prev_sample_batch:
            sample_batch_disp = ""
        else:
            sample_batch_disp = sample_batch if sample_batch is not None else ""

        if treatment == prev_treatment:
            treatment_disp = ""
        else:
            treatment_disp = treatment if treatment is not None else ""

        if target == prev_target:
            target_disp = ""
        else:
            target_disp = target if target is not None else ""

        genotype_disp = genotype if genotype is not None else ""

        labels.append([sample_batch_disp, treatment_disp, target_disp, genotype_disp])

        prev_sample_batch = sample_batch
        prev_treatment = treatment
        prev_target = target

    return labels if labels else None


def compose_row_with_labels(patch_arr: np.ndarray, labels, top_h: int = 60):
    """
    在条带 patch 顶部加一条注释带（白底），将 labels 按等间距居中绘制。
    返回合成后的灰度图（uint8）。
    文字绘制在条带上方，不重叠条带区域。
    为每行文字分配固定行高，确保多行标签竖直间距一致。
    """
    # 增加top_h高度以容纳下划线，调整为4行文字 + 下划线空间
    top_h_adjusted = int(top_h * 4 / 3) + 20
    h, w = patch_arr.shape
    row_img = Image.new('L', (w, top_h_adjusted + h + 20), 255)
    # 把 patch 贴到底部，向下移动10像素
    row_img.paste(Image.fromarray(patch_arr), (0, top_h_adjusted + 10))

    # 画标签（如果有）
    if labels:
        draw = ImageDraw.Draw(row_img)
        font = try_load_font(size=14)
        n = len(labels)
        if n > 0:
            line_height = top_h_adjusted // 4  # 4 行分配
            xs = [int((i + 0.5) * w / n) for i in range(n)]  # 等分中心
            y_offset = -10
            x_left = 10  # 固定左边距

            # 对 sample_batch, treatment, target 三行，使用连续相同非空标签的区间绘制每个区间的标签一次
            for line_idx in range(3):
                # 提取该行所有标签
                line_labels = [lbl[line_idx] for lbl in labels]

                # 计算连续相同非空标签区间
                segments = []
                start = None
                prev_label = None
                for i, label_text in enumerate(line_labels):
                    if label_text == "":
                        # 空字符串，结束当前段
                        if start is not None:
                            segments.append((start, i - 1, prev_label))
                            start = None
                            prev_label = None
                    else:
                        if label_text != prev_label:
                            # 新段开始
                            if start is not None:
                                segments.append((start, i - 1, prev_label))
                            start = i
                            prev_label = label_text
                # 收尾
                if start is not None:
                    segments.append((start, len(line_labels) - 1, prev_label))

                # 绘制每个区间的标签，左对齐于固定左边距
                y = line_idx * line_height + (line_height // 2) + y_offset
                for seg_start, seg_end, text in segments:
                    # 获取文字尺寸（兼容 PIL >= 10）
                    if hasattr(draw, "textbbox"):
                        bbox = draw.textbbox((0, 0), text, font=font)
                        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    else:
                        tw, th = draw.textsize(text, font=font)
                    draw.text((x_left, y - th // 2), text, fill=0, font=font)

            # 画 genotype 标签下的下划线，并绘制每个连续段的 genotype 标签
            genotype_idx = 3
            genotype_list = [lbl[genotype_idx] for lbl in labels]

            # 计算连续相同非空 genotype 区间
            segments = []
            start = None
            prev_genotype = None
            for i, g in enumerate(genotype_list):
                if g == "":
                    # 空字符串，结束当前段
                    if start is not None:
                        segments.append((start, i - 1, prev_genotype))
                        start = None
                        prev_genotype = None
                else:
                    if g != prev_genotype:
                        # 新段开始
                        if start is not None:
                            segments.append((start, i - 1, prev_genotype))
                        start = i
                        prev_genotype = g
            # 收尾
            if start is not None:
                segments.append((start, len(genotype_list) - 1, prev_genotype))

            underline_y = 4 * line_height + line_height // 2 + y_offset  # genotype 行下方更远一些，向上移动20像素

            half_width = w // (4 * n)  # 小下划线半宽度 (~w/(4*n))
            for seg_start, seg_end, g_label in segments:
                start_x = xs[seg_start] - half_width
                end_x = xs[seg_end] + half_width
                draw.line([(start_x, underline_y), (end_x, underline_y)], fill=0, width=1)

                # 计算 genotype 标签中心位置
                center_x = (xs[seg_start] + xs[seg_end]) // 2

                if g_label:
                    # 获取文字尺寸
                    if hasattr(draw, "textbbox"):
                        bbox = draw.textbbox((0, 0), g_label, font=font)
                        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    else:
                        tw, th = draw.textsize(g_label, font=font)
                    # 文字位置：在下划线之上，留出5-8像素间距
                    text_y = underline_y - th - 6
                    draw.text((center_x - tw // 2, text_y), g_label, fill=0, font=font)

    return np.array(row_img)


def main():
    root = Path(__file__).resolve().parents[2]
    expo_yaml = root / "04_data/interim/wb/exposure_selected/exposure_selected.yaml"
    materials_root = root / "04_data/interim/wb/materials"
    manifests_root = root / "04_data/interim/wb/manifests"
    output_root = root / "04_data/processed/wb/montage"
    output_root.mkdir(parents=True, exist_ok=True)

    exposure = load_yaml(expo_yaml)
    if pd is None:
        print("[WARN] 未安装 pandas/openpyxl，将跳过泳道图注（仅做拼接）。可通过 `pip install pandas openpyxl` 安装后重试。")

    for shot_id, gels in exposure.items():
        print(f"[INFO] Building montage for {shot_id} ...")
        imgs = []

        # 定位清单：日期取自 shot_id 前缀（例如 2025-09-22_SHOT1 → 2025-09-22.xlsx）
        date_str = shot_id.split("_")[0]
        manifest_path = manifests_root / f"{date_str}.xlsx"

        for gel_name in gels.keys():
            img_path = materials_root / shot_id / f"{gel_name}_patch.tif"
            if not img_path.exists():
                print(f"[WARN] Missing material patch: {img_path}")
                continue
            im = np.array(Image.open(img_path).convert('L'))

            # 为当前 gel 读取 lane 标签（按 shot+gel_id 过滤）
            labels_for_row = read_lane_labels_from_manifest(manifest_path, shot_id, gel_name)

            # 合成：上方标签带 + 下方条带
            row_img = compose_row_with_labels(im, labels_for_row, top_h=60)
            imgs.append(row_img)

        if not imgs:
            print(f"[WARN] No images for {shot_id}.")
            continue

        panel = montage_vert(images=imgs, spacing=30)
        out_path = output_root / f"{shot_id}_montage.tif"
        Image.fromarray(panel.astype(np.uint8)).save(out_path)
        print(f"[OK] Montage saved → {out_path}")

    print("[ALL DONE] Montage generation complete.")


if __name__ == "__main__":
    main()