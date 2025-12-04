#!/usr/bin/env python3
"""
05_lane_intensity.py

功能：
- 从 04_data/interim/wb/gel_crops/<shot_id>/<gel_name>/ 读取最佳曝光 + ROI（四边形）。
- 对每个 ROI：
  1) 在原始 gel 图上按 4 点 ROI 拉正成一条水平 band 图（不缩放到 480x50）。
  2) 在 band 上自动识别每条泳道的中心位置（沿 x 方向投影）。
  3) 对每个 lane 在 band 区域内积分灰度，输出 densitometry 表格。

输出：
- 04_data/interim/wb/intensity/lane_intensity.tsv (tab 分隔)
"""

import yaml
import numpy as np
from PIL import Image
from pathlib import Path
import warnings
import math
import argparse

# ------------------ 基础 I/O ------------------

def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def ensure_gray(img):
    # 将 RGB 转灰度但不归一化；2D 保持原样
    if img.ndim == 3:
        return img.mean(axis=2)
    return img

# ------------------ ROI 解析（复用 04 的逻辑，注意只保留前 4 点作为四边形） ------------------

def read_roi_yaml(roi_path):
    """
    读取 roi.yaml，返回 ROI 列表（每个 ROI 为 {'points': [...], 'band': 可选条带名}）。
    兼容格式：
      - [[x,y], ...] x4
      - [{"points":[[x,y],...], "band": <str>}]
      - {"roi":[[x,y],...]}
      - [{"rect":[x,y,w,h], "band": <str>}]  # 自动转四点
    注意：目前仍按“四边形”处理：如果给了多点，只取前 4 点。
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
                    pts = [
                        [float(x), float(y)],
                        [float(x + w), float(y)],
                        [float(x + w), float(y + h)],
                        [float(x), float(y + h)],
                    ]
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
                            pts = [
                                [float(x), float(y)],
                                [float(x + w), float(y)],
                                [float(x + w), float(y + h)],
                                [float(x), float(y + h)],
                            ]
                            polys.append({"points": pts, "band": None})
        return polys
    except Exception as e:
        warnings.warn(f"Failed to read ROI yaml: {roi_path} ({e})")
        return []

# ------------------ 几何工具（从 04 中提取） ------------------

def order_quad(pts):
    pts = np.array(pts, dtype=float)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:,1]-c[1], pts[:,0]-c[0])
    idx = np.argsort(ang)
    return pts[idx]

def edge_lengths(pts):
    P = np.vstack([pts, pts[0]])
    return np.sqrt(((P[1:] - P[:-1]) ** 2).sum(axis=1))

def mid(p, q):
    return (p + q) / 2.0

def centerline_from_quad(pts):
    """
    输入四边形顶点，返回：
      - center: 中心点
      - theta: 中线方向角度（度）
      - pts_ordered: 重新排序后的四顶点
      - length: 中线长度
    约定与 04_generate_materials.py 一致：
      - e0: 0-1, e1: 1-2, e2: 2-3, e3: 3-0
      - 取两条最短边的中点连线作为“中线”（大致沿条带方向）。
    """
    pts = order_quad(pts)
    L = edge_lengths(pts)
    idx = np.argsort(L)[:2]  # 两条最短边
    edges = [(pts[i], pts[(i + 1) % 4]) for i in idx]
    m1 = mid(*edges[0])
    m2 = mid(*edges[1])
    theta = math.degrees(math.atan2(m2[1] - m1[1], m2[0] - m1[0]))
    center = (m1 + m2) / 2.0
    length = np.linalg.norm(m2 - m1)
    return center, theta, pts, length

def oriented_rect_corners(center, angle_deg, W, H):
    """
    返回以 center 为中心、宽 W 高 H、旋转 angle_deg 的矩形四个顶点（UL, LL, LR, UR），坐标在原图坐标系。
    与 04_generate_materials.py 一致。
    """
    cx, cy = float(center[0]), float(center[1])
    rad = math.radians(angle_deg)
    dx = np.array([math.cos(rad), math.sin(rad)])      # 沿中线方向
    dy = np.array([-math.sin(rad), math.cos(rad)])     # 垂直中线
    hw, hh = W / 2.0, H / 2.0
    c = np.array([cx, cy], dtype=float)
    UL = c - dx * hw - dy * hh
    LL = c - dx * hw + dy * hh
    LR = c + dx * hw + dy * hh
    UR = c + dx * hw - dy * hh
    return np.array([UL, LL, LR, UR], dtype=float)

def crop_by_quad_upright(img2d, quad_UL_LL_LR_UR, out_W, out_H, bg=None):
    """
    在原图上用 QUAD 变换裁剪这个四边形，并映射成水平的 out_W×out_H 小图。
    与 04_generate_materials.py 一致。
    """
    if bg is None:
        bg = float(np.median(img2d))
    pil = Image.fromarray(img2d.astype(np.float32))
    src = tuple(float(v) for pt in quad_UL_LL_LR_UR for v in pt)  # UL,LL,LR,UR
    patch = pil.transform(
        (int(out_W), int(out_H)),
        Image.QUAD,
        src,
        resample=Image.BILINEAR,
        fillcolor=bg,
    )
    return np.array(patch)

def width_along_direction(pts, center, angle_deg):
    """
    ROI 多边形在中线方向上的投影长度，用于估算条带长度。
    """
    rad = math.radians(angle_deg)
    dx = np.array([math.cos(rad), math.sin(rad)], dtype=float)
    c = np.array(center, dtype=float)
    ts = [np.dot(np.array(p, dtype=float) - c, dx) for p in pts]
    return float(max(ts) - min(ts))

# ------------------ lane 检测 + 灰度积分 ------------------

def detect_lane_centers(row_img, lane_count=None, central_frac=0.5, smooth_win=9,
                        max_lanes=20, peak_thresh_frac=0.1):
    """
    在拉正后的 band 小图 row_img 上自动检测 lane 中心（沿 x 方向）。

    参数：
      - row_img: 2D numpy array，高度 H，宽度 W。
      - lane_count: 预期泳道数（例如 6 或 12）；若为 None，则自动估计。
      - central_frac: 只取 band 垂直方向中间部分做投影，例如 0.5 表示中间 50% 高度。
      - smooth_win: 1D 平滑窗口长度（奇数）。
      - max_lanes: 自动检测模式下允许的最大泳道数量。
      - peak_thresh_frac: 峰值相对于最大值的最小比例阈值，过滤很弱的峰。

    返回：
      - centers: x 中心坐标列表（浮点），长度为自动或指定的 lane 数。
    """
    H, W = row_img.shape

    # 只取垂直方向中间部分，避免上下边缘噪音
    h_frac = float(central_frac)
    h0 = int(max(0, H * 0.5 * (1.0 - h_frac)))
    h1 = int(min(H, H * 0.5 * (1.0 + h_frac)))
    if h1 <= h0:
        h0, h1 = 0, H

    sub = row_img[h0:h1, :].astype(np.float64)

    # 假设 band 是“暗带”，背景偏亮 → 用 median - I 作为信号
    med = np.median(sub)
    signal = med - sub  # 暗带 → 正值
    profile = signal.sum(axis=0)  # 沿 y 累积，得到列投影

    # 简单平滑
    if smooth_win > 1:
        k = smooth_win
        if k % 2 == 0:
            k += 1
        kernel = np.ones(k, dtype=float) / k
        profile_smooth = np.convolve(profile, kernel, mode="same")
    else:
        profile_smooth = profile

    # 自动估计泳道数
    if lane_count is None:
        centers = []
        ps = profile_smooth
        if W < 3:
            return []
        max_val = ps.max()
        if max_val <= 0:
            return []
        thresh = max_val * float(peak_thresh_frac)

        for i in range(1, W - 1):
            if ps[i] >= ps[i-1] and ps[i] >= ps[i+1] and ps[i] >= thresh:
                centers.append(float(i))

        # 限制最大 lane 数
        if len(centers) > max_lanes:
            idx_sorted = sorted(
                range(len(centers)),
                key=lambda k: ps[int(centers[k])],
                reverse=True
            )
            centers = [centers[k] for k in idx_sorted[:max_lanes]]
            centers = sorted(centers)

        return centers

    # 固定 lane_count 的模式：贪心找 lane_count 个 peak，保证峰之间有最小距离
    if lane_count < 1:
        raise ValueError("lane_count 必须 >= 1")

    centers = []
    prof_copy = profile_smooth.copy()
    min_dist = max(1, W // (lane_count * 2))  # 粗略最小间距：总宽度 / (2*lane_count)

    for _ in range(lane_count):
        idx = int(np.argmax(prof_copy))
        peak_val = prof_copy[idx]
        if peak_val <= 0:
            break
        centers.append(float(idx))
        left = max(0, idx - min_dist)
        right = min(W, idx + min_dist + 1)
        prof_copy[left:right] = 0.0

    centers = sorted(centers)
    return centers

def lane_bounds_from_centers(W, centers):
    """
    给定宽度 W 和若干 lane 中心，返回每个 lane 的 [x_min, x_max] 整数范围。
    策略：相邻中心之间的中点作为边界；最左边界=0，最右边界=W-1。
    """
    if not centers:
        return []

    centers = sorted(centers)
    bounds = []
    # 构造边界列表
    edges = [0]
    for i in range(len(centers) - 1):
        mid = 0.5 * (centers[i] + centers[i+1])
        edges.append(mid)
    edges.append(W - 1)

    for i in range(len(centers)):
        x_min = int(math.floor(edges[i]))
        x_max = int(math.ceil(edges[i+1]))
        x_min = max(0, x_min)
        x_max = min(W - 1, x_max)
        bounds.append((x_min, x_max))
    return bounds

def quantify_lanes(row_img, lane_count):
    """
    在拉正 band 小图 row_img 上，检测 lane 中心并对每个 lane 计算灰度积分。
    返回：
      - 一个列表，每个元素为 dict:
        {
          "lane_index": 1..N,
          "x_center": float,
          "x_min": int,
          "x_max": int,
          "height_px": H,
          "signal_sum": float,
          "signal_mean": float,
        }
    """
    H, W = row_img.shape
    centers = detect_lane_centers(row_img, lane_count=lane_count)
    if not centers:
        return []

    bounds = lane_bounds_from_centers(W, centers)
    results = []

    # 再次用“med - I”定义 densitometry signal
    med = np.median(row_img)
    signal_full = med - row_img.astype(np.float64)

    for i, (c, (x_min, x_max)) in enumerate(zip(centers, bounds), start=1):
        lane_region = signal_full[:, x_min:x_max+1]
        sig_sum = float(lane_region.sum())
        sig_mean = float(lane_region.mean()) if lane_region.size > 0 else 0.0
        results.append(
            dict(
                lane_index=i,
                x_center=float(c),
                x_min=int(x_min),
                x_max=int(x_max),
                height_px=int(H),
                signal_sum=sig_sum,
                signal_mean=sig_mean,
            )
        )
    return results

# ------------------ 主流程 ------------------

def main():
    # 项目根目录（EphB1）
    root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(description="从 WB panel YAML 读取 bands 信息，对每个 lane 进行 densitometry。")

    # 默认使用 figure_1_a.yaml 作为 panel 配置
    default_cfg = root / "06_figures" / " script" / "figure_1_a.yaml"
    parser.add_argument(
        "--config",
        type=str,
        default=str(default_cfg),
        help="WB panel 配置 YAML（例如 06_figures/ script/figure_1_a.yaml）"
    )

    parser.add_argument(
        "--lanes",
        type=int,
        default=None,
        help="每个 gel 中的泳道数量（例如 6 或 12）；若省略，则优先用 YAML 中的 lanes 配置，再自动估计"
    )
    parser.add_argument(
        "--rectified_height",
        type=int,
        default=40,
        help="拉正 band 的高度（像素），需与 04_generate_materials.py 的 rectified_height 对应"
    )
    parser.add_argument(
        "--width_margin",
        type=float,
        default=0.0,
        help="沿 band 中线方向的额外 margin（相对于 ROI 长度的比例）"
    )
    args = parser.parse_args()

    lane_count_arg = args.lanes
    rectified_height = args.rectified_height
    width_margin = args.width_margin

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config YAML 不存在: {cfg_path}")
    panel_cfg = load_yaml(cfg_path)

    # 读取 bands 列表（必需）
    bands_cfg = panel_cfg.get("bands")
    if not bands_cfg:
        raise ValueError("Config YAML 缺少必需字段: bands")

    # 可选：读取 lanes 配置（例如 lanes: 6 或 lanes: {count: 6}）
    lane_count_yaml = None
    lanes_cfg = panel_cfg.get("lanes")
    if isinstance(lanes_cfg, dict) and "count" in lanes_cfg:
        try:
            lane_count_yaml = int(lanes_cfg["count"])
        except Exception:
            lane_count_yaml = None
    elif isinstance(lanes_cfg, int):
        lane_count_yaml = lanes_cfg

    # 组合 lane_count：命令行 > YAML > 自动（None）
    lane_count_global = lane_count_arg if lane_count_arg is not None else lane_count_yaml

    gel_crops_root = root / "04_data/interim/wb/gel_crops"
    exposure_path = root / "04_data/interim/wb/exposure_selected/exposure_selected.yaml"

    # 输出路径：06_figures/<figure_x>/<panel_name>.tsv，例如 figure_1_a.yaml → 06_figures/figure_1/figure_1_a.tsv
    panel_name = cfg_path.stem  # figure_1_a
    panel_group = panel_name.rsplit("_", 1)[0]  # figure_1
    out_dir = root / "06_figures" / panel_group
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{panel_name}.tsv"

    # exposure_selected.yaml 可选：有就读，没有就用空 dict
    if exposure_path.exists():
        exposure = load_yaml(exposure_path) or {}
    else:
        exposure = {}

    rows = []

    # 遍历 panel YAML 中声明的 bands，而不是所有 gel_crops
    for band_idx, band_cfg in enumerate(bands_cfg, start=1):
        prefix = band_cfg.get("prefix")
        shot_id = band_cfg.get("shot_id")
        if not prefix or not shot_id:
            print(f"[WARN] bands[{band_idx}] 缺少 prefix 或 shot_id，跳过。")
            continue

        # gel_name 由 prefix 的左半部分推断：Gx_xxx...
        gel_name = prefix.split("__", 1)[0]

        # ROI 中用于匹配的 band 名：优先显式 roi_band，其次 band 字段，其次 label，再次 prefix
        band_label = band_cfg.get("roi_band") or band_cfg.get("band") or band_cfg.get("label") or prefix

        shot_dir = gel_crops_root / shot_id
        gel_dir = shot_dir / gel_name

        if not gel_dir.exists():
            print(f"[WARN] {shot_id}/{gel_name}: gel 目录不存在，跳过。")
            continue

        roi_path = gel_dir / "roi.yaml"
        if not roi_path.exists():
            print(f"[WARN] {shot_id}/{gel_name}: 缺少 roi.yaml，跳过。")
            continue

        # 1) 选择最佳曝光文件：优先 exposure_selected.yaml 中的 best_file
        best_file = None
        shot_expo = exposure.get(shot_id, {}) if isinstance(exposure, dict) else {}
        info = shot_expo.get(gel_name) if isinstance(shot_expo, dict) else None
        if isinstance(info, dict):
            best_file = info.get("best_file")

        # 2) 如果 exposure_selected 没有记录，则自动从该 gel 目录中选择一张图像
        if not best_file:
            candidates = sorted(
                p.name
                for p in gel_dir.iterdir()
                if p.is_file() and p.suffix.lower() in (".tif", ".tiff", ".png", ".jpg", ".jpeg")
            )
            if not candidates:
                print(f"[WARN] {shot_id}/{gel_name}: 未找到图像文件，跳过。")
                continue
            best_file = candidates[0]

        img_path = gel_dir / best_file
        if not img_path.exists():
            print(f"[WARN] 缺少图像文件: {img_path}，跳过。")
            continue

        img = np.array(Image.open(img_path))
        img2d = ensure_gray(img)

        roi_entries = read_roi_yaml(roi_path)
        rois_all = [
            r for r in (roi_entries or [])
            if isinstance(r, dict) and "points" in r and isinstance(r["points"], list) and len(r["points"]) >= 4
        ]
        print(f"[DEBUG-ROI] {shot_id}/{gel_name}: parsed ROIs = {len(rois_all)}")

        if not rois_all:
            continue

        # 尝试按 band_label 匹配 ROI（roi.yaml 中的 'band' 字段）
        rois = [r for r in rois_all if str(r.get("band")) == str(band_label)]
        if not rois:
            # 如果没有匹配到，退回用全部 ROI，但打警告
            print(f"[WARN] {shot_id}/{gel_name}: 未找到 band='{band_label}' 的 ROI，改用所有 ROI。")
            rois = rois_all

        for roi_idx, roi in enumerate(rois, start=1):
            poly = roi.get("points", [])
            if not poly or len(poly) < 4:
                continue

            center, theta, ordered_pts, centerline_length = centerline_from_quad(poly)

            # 角度规范到 (-90°, 90°]
            if theta > 90:
                theta -= 180
            elif theta <= -90:
                theta += 180

            # 沿中线方向的基准宽度
            roi_width_line = width_along_direction(ordered_pts, center, theta)

            margin = float(width_margin)
            target_H = int(rectified_height)
            target_W = max(1, int(round(roi_width_line * (1.0 + 2.0 * margin))))

            quad = oriented_rect_corners(center, theta, target_W, target_H)
            cropped = crop_by_quad_upright(img2d, quad, target_W, target_H, bg=None)

            lane_stats = quantify_lanes(cropped, lane_count=lane_count_global)
            if not lane_stats:
                print(f"[WARN] {shot_id}/{gel_name} | band={band_label}: no lane detected.")
                continue

            for st in lane_stats:
                rows.append(
                    dict(
                        panel=panel_name,
                        shot_id=shot_id,
                        gel_name=gel_name,
                        band=str(band_label),
                        band_prefix=prefix,
                        roi_index=roi_idx,
                        lane_index=st["lane_index"],
                        x_center=st["x_center"],
                        x_min=st["x_min"],
                        x_max=st["x_max"],
                        height_px=st["height_px"],
                        signal_sum=st["signal_sum"],
                        signal_mean=st["signal_mean"],
                    )
                )

    # 写出 TSV
    if rows:
        cols = [
            "panel",
            "shot_id",
            "gel_name",
            "band",
            "band_prefix",
            "roi_index",
            "lane_index",
            "x_center",
            "x_min",
            "x_max",
            "height_px",
            "signal_sum",
            "signal_mean",
        ]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\t".join(cols) + "\n")
            for r in rows:
                f.write("\t".join(str(r[c]) for c in cols) + "\n")
        print(f"[OK] lane intensity table for panel '{panel_name}' saved → {out_path}")
    else:
        print("[WARN] No lane intensity rows produced; nothing written.")

if __name__ == "__main__":
    main()