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
import math

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

import math

def ensure_gray(img):
    # 将RGB转灰度但不归一化；2D保持原样
    if img.ndim == 3:
        return img.mean(axis=2)
    return img

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
    return center, theta, pts

def rotate_about_center(img2d, angle_deg):
    # 使用 float32 的 'F' 模式旋转；空白区用背景（中位灰度）填充，确保旋转绝对到位
    pil = Image.fromarray(img2d.astype(np.float32))
    fill = float(np.median(img2d))
    rot = pil.rotate(-angle_deg, resample=Image.BILINEAR, expand=True, fillcolor=fill)
    return np.array(rot)

def rotate_points(points, angle_deg, orig_shape, new_shape=None):
    """Rotate points by -angle_deg around the original image center, then translate so that
    the rotated original image fits in a new canvas with origin (0,0), mimicking
    PIL.Image.rotate(..., expand=True).

    `new_shape` is kept for backward compatibility but is ignored.
    """
    h, w = orig_shape[:2]
    cx, cy = w / 2.0, h / 2.0
    rad = math.radians(-angle_deg)
    c, s = math.cos(rad), math.sin(rad)

    # 1) 先把原图四个角绕中心旋转，求 expand=True 对应的平移（让最小角对齐到 (0,0)）
    corners = np.array([[0.0, 0.0],
                        [w * 1.0, 0.0],
                        [w * 1.0, h * 1.0],
                        [0.0, h * 1.0]])
    corners_rc = corners - np.array([cx, cy])
    corners_rot = np.empty_like(corners_rc)
    corners_rot[:, 0] = c * corners_rc[:, 0] - s * corners_rc[:, 1]
    corners_rot[:, 1] = s * corners_rc[:, 0] + c * corners_rc[:, 1]
    corners_rot += np.array([cx, cy])

    min_x = float(corners_rot[:, 0].min())
    min_y = float(corners_rot[:, 1].min())

    # 2) 再把 ROI 的点同样绕中心旋转，然后按上面的平移量位移
    out = []
    for (x, y) in points:
        dx, dy = x - cx, y - cy
        xr = c * dx - s * dy + cx
        yr = s * dx + c * dy + cy
        out.append([xr - min_x, yr - min_y])
    return np.array(out)
def bbox_of_points(pts):
    xs = pts[:,0]; ys = pts[:,1]
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())

def crop_center(img2d, cx, cy, W, H):
    h, w = img2d.shape[:2]
    x0 = int(round(cx - W/2)); y0 = int(round(cy - H/2))
    x1 = x0 + W; y1 = y0 + H
    # 优先平移窗口回到图像范围内
    dx0 = max(0, -x0); dy0 = max(0, -y0)
    dx1 = max(0, x1 - w); dy1 = max(0, y1 - h)
    x0 += dx0 - dx1; x1 += dx0 - dx1
    y0 += dy0 - dy1; y1 += dy0 - dy1
    # 最小必要填充
    patch = np.ones((H, W), dtype=img2d.dtype) * (np.median(img2d) if np.issubdtype(img2d.dtype, np.floating) else np.median(img2d))
    xs0 = max(0, x0); ys0 = max(0, y0)
    xs1 = min(w, x1); ys1 = min(h, y1)
    px0 = max(0, - (x0 - xs0)); py0 = max(0, - (y0 - ys0))
    if ys1>ys0 and xs1>xs0:
        patch[py0:py0+(ys1-ys0), px0:px0+(xs1-xs0)] = img2d[ys0:ys1, xs0:xs1]
    return patch

def crop_center_strict(img2d, cx, cy, W, H, bg=None):
    """严格以 (cx,cy) 为中心裁剪 W×H：不把窗口平移回图内；越界部分用背景填充"""
    h, w = img2d.shape[:2]
    x0 = int(round(cx - W/2)); y0 = int(round(cy - H/2))
    x1 = x0 + W;               y1 = y0 + H

    if bg is None:
        bg = np.median(img2d)

    patch = np.ones((H, W), dtype=img2d.dtype) * bg

    xs0 = max(0, x0); ys0 = max(0, y0)
    xs1 = min(w, x1); ys1 = min(h, y1)

    px0 = xs0 - x0
    py0 = ys0 - y0
    if ys1 > ys0 and xs1 > xs0:
        patch[py0:py0+(ys1-ys0), px0:px0+(xs1-xs0)] = img2d[ys0:ys1, xs0:xs1]

    return patch

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

def to_uint8_vis(im, pmin=1, pmax=99):
    """For visualization overlays only: map image to uint8 using percentiles (no effect on processing)."""
    im = np.array(im, dtype=np.float64)
    lo, hi = np.percentile(im, pmin), np.percentile(im, pmax)
    if hi <= lo:
        hi = lo + 1.0
    out = (im - lo) / (hi - lo)
    out = np.clip(out, 0, 1)
    return (out * 255).astype(np.uint8)

from PIL import ImageDraw, ImageFont

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
    """在【原图】上用 QUAD 透视变换裁剪这个四边形，并把它映射成水平的 out_W×out_H 小图。"""
    if bg is None:
        bg = float(np.median(img2d))
    pil = Image.fromarray(img2d.astype(np.float32))
    src = tuple(float(v) for pt in quad_UL_LL_LR_UR for v in pt)  # 顺序：UL, LL, LR, UR
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
def debug_save_overlays(orig_img, rot_img, ordered_pts, rot_pts, m1, m2, rot_m1, rot_m2, center, center_rot, theta_norm, crop_cx, crop_cy, target_W, target_H, out_dir, stem, crop_quad=None):
    """Save only the rotated overlay per gel: rotated with crop box. Visualization only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Only Rotated overlay + crop rect
    vis1 = to_uint8_vis(rot_img)
    rgb1 = Image.fromarray(vis1).convert('RGB')
    d1 = ImageDraw.Draw(rgb1)
    draw_poly(d1, rot_pts, color=(0,255,0), width=2)
    # draw rotated centerline (actual orientation)
    d1.line((rot_m1[0], rot_m1[1], rot_m2[0], rot_m2[1]), fill=(255,0,0), width=2)
    midx = (rot_m1[0] + rot_m2[0]) / 2.0
    midy = (rot_m1[1] + rot_m2[1]) / 2.0
    draw_cross(d1, midx, midy, size=5, color=(255,0,0))
    # crop rectangle
    x0 = crop_cx - target_W/2; y0 = crop_cy - target_H/2
    x1 = x0 + target_W;       y1 = y0 + target_H
    d1.rectangle((x0, y0, x1, y1), outline=(255,255,0), width=2)
    d1.text((5,5), f"theta_norm={theta_norm:.2f}°  crop={target_W}x{target_H}", fill=(255,255,0))
    rgb1.save(out_dir / f"{stem}_02_rot_overlay.png")

def main():
    # Hardcoded default options as per requirements
    rectified_height = 50
    width_margin = 0.08
    rect_crop_first = True
    debug_dump = True

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
                print(f"[DEBUG-ROI] ROI path: {roi_path} | parsed polygons: {len(rois)}")
                if rois and isinstance(rois[0], list) and len(rois[0]) >= 4:
                    # 只用第一个ROI（每个gel只有一个条带）
                    poly = rois[0]
                    # 确保二维灰度，不改变动态范围
                    img2d = ensure_gray(img)
                    # 由 ROI 四点求中线与角度
                    center, theta, ordered_pts = centerline_from_quad(poly)
                    # 计算两条最短边及其中点（用于可视化）
                    L_all = edge_lengths(ordered_pts)
                    idx_short = np.argsort(L_all)[:2]
                    edges = [(ordered_pts[i], ordered_pts[(i+1)%4]) for i in idx_short]
                    m1 = (edges[0][0] + edges[0][1]) / 2.0
                    m2 = (edges[1][0] + edges[1][1]) / 2.0

                    # 将角度规范到 (-90°, 90°]，保证旋转不超过 90°，且朝向原始水平线
                    if theta > 90:
                        theta -= 180
                    elif theta <= -90:
                        theta += 180
                    print(f"[DEBUG-ROT] {gel_name}: theta_norm={theta:.2f}°, center=({center[0]:.1f},{center[1]:.1f}) | orig size={img2d.shape[1]}x{img2d.shape[0]}")

                    # --- 只保留 rect_crop_first 路径 ---
                    margin = float(width_margin)
                    target_H = int(rectified_height)
                    # 用“投影到中线方向”的长度作为条带长度（再加左右边距），比旋转后 bbox 更稳健
                    roi_width_line = width_along_direction(ordered_pts, center, theta)
                    target_W = max(1, int(round(roi_width_line * (1.0 + 2.0*margin))))

                    # 在【原图坐标系】下构造要裁下的倾斜矩形四点（UL,LL,LR,UR）
                    quad = oriented_rect_corners(center, theta, target_W, target_H)

                    # 在【原图】上直接用 QUAD 方式裁取，并把结果“拉正”为 W×H 小图（这张 patch 就是水平的）
                    cropped = crop_by_quad_upright(ensure_gray(img), quad, target_W, target_H, bg=None)

                    # ——以下仅用于 debug 画图（第二张叠加图就直接画这个 patch）——
                    rot_img_dbg = cropped
                    rot_pts_dbg = np.array([[0,0],[target_W,0],[target_W,target_H],[0,target_H]], dtype=float)
                    center_rot_dbg = np.array([target_W/2.0, target_H/2.0])
                    rot_m1_dbg = np.array([target_W*0.05, target_H/2.0])
                    rot_m2_dbg = np.array([target_W*0.95, target_H/2.0])

                    print(f"[DEBUG-ROT] {gel_name}: MODE=rect-crop-first | quad={ [tuple(np.round(q,1)) for q in quad] }")
                    print(f"[DEBUG-ROT] {gel_name}: patch size={target_W}x{target_H}; centerline angle=0.00° (by construction)")

                    if debug_dump:
                        dbg_root = root / '04_data/interim/wb/materials' / shot_id
                        stem = gel_name
                        try:
                            debug_save_overlays(
                                orig_img=img,
                                rot_img=rot_img_dbg,
                                ordered_pts=ordered_pts,
                                rot_pts=rot_pts_dbg,
                                m1=m1, m2=m2,
                                rot_m1=rot_m1_dbg, rot_m2=rot_m2_dbg,
                                center=center,
                                center_rot=center_rot_dbg,
                                theta_norm=theta,
                                crop_cx=target_W/2.0, crop_cy=target_H/2.0,
                                target_W=target_W, target_H=target_H,
                                out_dir=dbg_root, stem=stem,
                                crop_quad=quad
                            )
                            print(f"[DEBUG-ROT] {gel_name}: debug overlays saved (rect-crop-first): {dbg_root}/{stem}_02_rot_overlay.png")
                        except Exception as e:
                            print(f"[DEBUG-ROT] {gel_name}: failed to save debug overlays (rect-crop-first): {e}")

                    # 输出本 gel 的结果并继续下一个（保持与原来分支一致的后处理）
                    cropped_out = percentile_stretch(cropped, pmin=1, pmax=99)
                    imgs.append(cropped_out)
                    labels.append(gel_name)
                    continue
                else:
                    warnings.warn(f"[FALLBACK] No valid ROI found in {roi_path}. Using FULL IMAGE (no rotation/crop).")
                    cropped = img
                    use_full_img = True
            else:
                warnings.warn(f"[FALLBACK] ROI file missing: {roi_path}. Using FULL IMAGE (no rotation/crop).")
                cropped = img
                use_full_img = True

            # Always percentile stretch (preserve_raw removed)
            cropped = percentile_stretch(cropped, pmin=1, pmax=99)
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