#!/usr/bin/env python3
"""
05_generate_materials.py
从 gel_crops 读取最佳曝光 + ROI，按“先取倾斜矩形→拉正”的策略，
生成用于拼接的 patch 以及核查用的 overlay 到 04_data/interim/wb/materials/<shot_id>/。

输入：
- 04_data/interim/wb/gel_crops/<shot_id>/<gel_name>/
  ├── <best_exposure>.tif
  └── roi.yaml
- 04_data/interim/wb/exposure_selected/exposure_selected.yaml

输出（每个 gel_name 两个文件）：
- 04_data/interim/wb/materials/<shot_id>/<gel_name>_patch.tif
- 04_data/interim/wb/materials/<shot_id>/<gel_name>_02_rot_overlay.png
"""

import yaml
import numpy as np
from PIL import Image, ImageDraw
from pathlib import Path
import warnings
import math

# ------------------ 基础 I/O ------------------
def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def ensure_gray(img):
    # 将RGB转灰度但不归一化；2D保持原样
    if img.ndim == 3:
        return img.mean(axis=2)
    return img

# ------------------ ROI 解析 ------------------
def read_roi_yaml(roi_path):
    """读取 roi.yaml，返回 ROI 列表（每个 ROI 为 {'points': [...], 'band': 可选条带名}）。
    兼容格式：
      - [[x,y], ...] x4
      - [{"points":[[x,y],...], "band": <str>}]
      - {"roi":[[x,y],...]}
      - [{"rect":[x,y,w,h], "band": <str>}]  # 自动转四点
    """
    try:
        data = load_yaml(roi_path)
        polys = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, list) and len(item) >= 4 and isinstance(item[0], (list, tuple)):
                    pts = [[float(x), float(y)] for x, y in item[:4]]
                    polys.append({"points": pts, "band": None})
                elif isinstance(item, dict) and "points" in item and isinstance(item["points"], list):
                    pts = item["points"]
                    if len(pts) >= 4:
                        ptsf = [[float(x), float(y)] for x, y in pts[:4]]
                        polys.append({"points": ptsf, "band": item.get("band")})
                elif isinstance(item, dict) and "rect" in item and isinstance(item["rect"], (list, tuple)) and len(item["rect"]) == 4:
                    x, y, w, h = item["rect"]
                    pts = [[float(x), float(y)], [float(x+w), float(y)], [float(x+w), float(y+h)], [float(x), float(y+h)]]
                    polys.append({"points": pts, "band": item.get("band") if "band" in item else None})
        elif isinstance(data, dict):
            if "points" in data and isinstance(data["points"], list) and len(data["points"]) >= 4:
                pts = data["points"]
                ptsf = [[float(x), float(y)] for x, y in pts[:4]]
                polys.append({"points": ptsf, "band": None})
            else:
                for v in data.values():
                    if isinstance(v, list):
                        if v and isinstance(v[0], (list, tuple)):
                            if len(v) >= 4:
                                ptsf = [[float(x), float(y)] for x, y in v[:4]]
                                polys.append({"points": ptsf, "band": None})
                        elif len(v) == 4 and all(isinstance(n, (int, float)) for n in v):
                            x, y, w, h = v
                            pts = [[float(x), float(y)], [float(x+w), float(y)], [float(x+w), float(y+h)], [float(x), float(y+h)]]
                            polys.append({"points": pts, "band": None})
        return polys
    except Exception as e:
        warnings.warn(f"Failed to read ROI yaml: {roi_path} ({e})")
        return []

# ------------------ 几何工具 ------------------
def order_quad(pts):
    pts = np.array(pts, dtype=float)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:,1]-c[1], pts[:,0]-c[0])
    idx = np.argsort(ang)
    return pts[idx]

def edge_lengths(pts):
    P = np.vstack([pts, pts[0]])
    return np.sqrt(((P[1:]-P[:-1])**2).sum(axis=1))

def mid(p, q):
    return (p+q)/2.0

def centerline_from_quad(pts):
    pts = order_quad(pts)
    L = edge_lengths(pts)   # e0:0-1, e1:1-2, e2:2-3, e3:3-0
    idx = np.argsort(L)[:2] # 两条最短边索引
    edges = [(pts[i], pts[(i+1)%4]) for i in idx]
    m1 = mid(*edges[0]); m2 = mid(*edges[1])
    theta = math.degrees(math.atan2(m2[1]-m1[1], m2[0]-m1[0]))
    center = (m1 + m2) / 2.0
    length = np.linalg.norm(m2 - m1)
    return center, theta, pts, length

def oriented_rect_corners(center, angle_deg, W, H):
    """返回以 center 为中心、宽 W 高 H、旋转 angle_deg 的矩形四个顶点（UL, LL, LR, UR），坐标在原图坐标系。"""
    cx, cy = float(center[0]), float(center[1])
    rad = math.radians(angle_deg)
    dx = np.array([math.cos(rad), math.sin(rad)])      # 沿中线方向
    dy = np.array([-math.sin(rad), math.cos(rad)])     # 垂直中线（向“上”）
    hw, hh = W / 2.0, H / 2.0
    c = np.array([cx, cy], dtype=float)
    UL = c - dx * hw - dy * hh
    LL = c - dx * hw + dy * hh
    LR = c + dx * hw + dy * hh
    UR = c + dx * hw - dy * hh
    return np.array([UL, LL, LR, UR], dtype=float)

def crop_by_quad_upright(img2d, quad_UL_LL_LR_UR, out_W, out_H, bg=None):
    """在【原图】上用 QUAD 变换裁剪这个四边形，并把它映射成水平的 out_W×out_H 小图。"""
    if bg is None:
        bg = float(np.median(img2d))
    pil = Image.fromarray(img2d.astype(np.float32))
    src = tuple(float(v) for pt in quad_UL_LL_LR_UR for v in pt)  # UL,LL,LR,UR
    patch = pil.transform((int(out_W), int(out_H)),
                          Image.QUAD, src,
                          resample=Image.BILINEAR,
                          fillcolor=bg)
    return np.array(patch)

def width_along_direction(pts, center, angle_deg):
    """ROI 多边形在中线方向上的投影长度（作为条带长度基准）。"""
    rad = math.radians(angle_deg)
    dx = np.array([math.cos(rad), math.sin(rad)], dtype=float)
    c = np.array(center, dtype=float)
    ts = [np.dot(np.array(p, dtype=float) - c, dx) for p in pts]
    return float(max(ts) - min(ts))

# ------------------ 可视化 ------------------
def to_uint8_vis(im, pmin=1, pmax=99):
    im = np.array(im, dtype=np.float64)
    lo, hi = np.percentile(im, pmin), np.percentile(im, pmax)
    if hi <= lo:
        hi = lo + 1.0
    out = (im - lo) / (hi - lo)
    out = np.clip(out, 0, 1)
    return (out * 255).astype(np.uint8)

def draw_cross(draw, x, y, size=4, color=(255,0,0)):
    draw.line((x-size, y, x+size, y), fill=color, width=1)
    draw.line((x, y-size, x, y+size), fill=color, width=1)

def draw_poly(draw, pts, color=(0,255,0), width=2):
    pts = [(float(x), float(y)) for x,y in pts]
    n = len(pts)
    for i in range(n):
        x0,y0 = pts[i]
        x1,y1 = pts[(i+1)%n]
        draw.line((x0,y0,x1,y1), fill=color, width=width)

def debug_save_overlays(rot_img, target_W, target_H, out_path_png):
    """仅保存已拉正的小图的叠加图（矩形框+水平中线），用于核查。"""
    vis1 = to_uint8_vis(rot_img)
    rgb1 = Image.fromarray(vis1).convert('RGB')
    d1 = ImageDraw.Draw(rgb1)
    # 绿色边框
    d1.rectangle((0, 0, target_W-1, target_H-1), outline=(0,255,0), width=2)
    # 红色水平中心线
    d1.line((int(0.05*target_W), target_H//2, int(0.95*target_W), target_H//2), fill=(255,0,0), width=2)
    rgb1.save(out_path_png)

# ------------------ 对比度增强（给 patch 用） ------------------
def percentile_stretch(im, pmin=1, pmax=99):
    lower = np.percentile(im, pmin)
    upper = np.percentile(im, pmax)
    if upper == lower:
        return im.astype(np.float64)
    stretched = (im.astype(np.float64) - lower) / (upper - lower)
    stretched = np.clip(stretched, 0, 1) * 255
    return stretched

# ------------------ 主流程 ------------------
def main():
    # 默认参数（与之前一致）
    rectified_height = 40
    width_margin = 0

    root = Path(__file__).resolve().parents[2]
    gel_crops_root = root / "04_data/interim/wb/gel_crops"
    exposure_path = root / "04_data/interim/wb/exposure_selected/exposure_selected.yaml"
    materials_root = root / "04_data/interim/wb/materials"
    materials_root.mkdir(parents=True, exist_ok=True)

    exposure = load_yaml(exposure_path)

    for shot_id, gels in exposure.items():
        print(f"[INFO] Generating materials for {shot_id} ...")
        shot_dir = gel_crops_root / shot_id
        out_dir = materials_root / shot_id
        out_dir.mkdir(parents=True, exist_ok=True)

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

            # 读取最佳曝光图像
            img = np.array(Image.open(img_path))

            roi_path = gel_dir / "roi.yaml"

            if roi_path.exists():
                roi_entries = read_roi_yaml(roi_path)
                # 只保留包含 points 且点数 >=4 的 ROI
                rois = [r for r in (roi_entries or []) if isinstance(r, dict) and "points" in r and isinstance(r["points"], list) and len(r["points"]) >= 4]
                print(f"[DEBUG-ROI] ROI path: {roi_path} | parsed ROIs: {len(rois)}")
            else:
                rois = []
                print(f"[DEBUG-ROI] ROI path: {roi_path} | missing, fallback to full image")

            used_overlay = False

            if rois:
                img2d = ensure_gray(img)
                display_W, display_H = 480, 50

                for idx, roi in enumerate(rois, start=1):
                    poly = roi.get("points", [])
                    if not poly or len(poly) < 4:
                        continue

                    band_label = roi.get("band") or f"band{idx}"

                    center, theta, ordered_pts, centerline_length = centerline_from_quad(poly)

                    # 角度规范到 (-90°, 90°]
                    if theta > 90:
                        theta -= 180
                    elif theta <= -90:
                        theta += 180
                    print(
                        f"[DEBUG-ROT] {gel_name} | band={band_label}: "
                        f"theta_norm={theta:.2f}°, center=({center[0]:.1f},{center[1]:.1f}), "
                        f"centerline_length={centerline_length:.2f}"
                    )

                    margin = float(width_margin)
                    target_H = int(rectified_height)
                    roi_width_line = centerline_length
                    target_W = max(1, int(round(roi_width_line * (1.0 + 2.0 * margin))))

                    quad = oriented_rect_corners(center, theta, target_W, target_H)
                    cropped = crop_by_quad_upright(img2d, quad, target_W, target_H, bg=None)

                    # 统一输出大小 480×50
                    cropped_disp = np.array(
                        Image.fromarray(cropped.astype(np.float32)).resize(
                            (display_W, display_H), resample=Image.BILINEAR
                        )
                    )
                    sx = display_W / cropped.shape[1]
                    sy = display_H / cropped.shape[0]
                    print(
                        f"[DEBUG-RESIZE] {gel_name} | band={band_label}: "
                        f"resized from {cropped.shape[1]}x{cropped.shape[0]} to "
                        f"{display_W}x{display_H} (sx={sx:.3f}, sy={sy:.3f})"
                    )

                    patch_u8 = np.clip(percentile_stretch(cropped_disp, 1, 99), 0, 255).astype(np.uint8)

                    # 安全化 band 名用于文件名
                    band_safe = "".join(
                        ch if (ch.isalnum() or ch in ("-", "_")) else "_"
                        for ch in str(band_label)
                    )

                    # 每个 band 独立一个 patch / overlay
                    band_patch_path = out_dir / f"{gel_name}__{band_safe}_patch.tif"
                    band_overlay_path = out_dir / f"{gel_name}__{band_safe}_02_rot_overlay.png"

                    if band_patch_path.exists():
                        print(
                            f"[SKIP] {gel_name} | band={band_label}: "
                            f"patch already exists at {band_patch_path} → skipping this band."
                        )
                    else:
                        Image.fromarray(patch_u8).save(band_patch_path)
                        print(f"[OK] Saved band patch → {band_patch_path}")
                        try:
                            debug_save_overlays(
                                rot_img=cropped_disp,
                                target_W=display_W,
                                target_H=display_H,
                                out_path_png=band_overlay_path,
                            )
                            print(f"[OK] Saved band overlay → {band_overlay_path}")
                            used_overlay = True
                        except Exception as e:
                            print(f"[WARN] Band overlay save failed for {gel_name} | band={band_label}: {e}")

                    # 兼容旧逻辑：第一条 ROI 也写一份主 patch/overlay（无 band 后缀）
                    if idx == 1:
                        main_patch_path = out_dir / f"{gel_name}_patch.tif"
                        main_overlay_path = out_dir / f"{gel_name}_02_rot_overlay.png"
                        Image.fromarray(patch_u8).save(main_patch_path)
                        print(f"[OK] Saved main patch (first ROI) → {main_patch_path}")
                        try:
                            debug_save_overlays(
                                rot_img=cropped_disp,
                                target_W=display_W,
                                target_H=display_H,
                                out_path_png=main_overlay_path,
                            )
                            print(f"[OK] Saved main overlay (first ROI) → {main_overlay_path}")
                        except Exception as e:
                            print(f"[WARN] Main overlay save failed for {gel_name}: {e}")

            else:
                # Fallback：没有 ROI，就把原图（灰度+拉伸）作为 patch
                cropped = ensure_gray(img)
                display_W, display_H = 480, 50
                cropped_disp = np.array(
                    Image.fromarray(cropped.astype(np.float32)).resize((display_W, display_H), resample=Image.BILINEAR)
                )
                patch_u8 = np.clip(percentile_stretch(cropped_disp, 1, 99), 0, 255).astype(np.uint8)
                patch_path = out_dir / f"{gel_name}_patch.tif"
                Image.fromarray(patch_u8).save(patch_path)
                print(f"[FALLBACK] {gel_name}: saved full-image patch → {patch_path}")

                # overlay 可不生成（因为没有 ROI）

        print(f"[INFO] Materials ready for {shot_id}: {out_dir}")

    print("[ALL DONE] Materials generation complete.")

if __name__ == "__main__":
    main()