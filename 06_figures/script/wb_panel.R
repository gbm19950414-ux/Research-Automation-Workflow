suppressPackageStartupMessages({
  library(yaml)
  library(magick)
  library(grid)
})

# 安全取默认值的小工具：如果 x 为 NULL，则返回 y
`%||%` <- function(x, y) if (is.null(x)) y else x
# =============================================================================
# 通用 WB panel 模板函数：从 YAML 读取配置，按 grid.layout 表格布局输出 PDF
# =============================================================================
wb_panel_from_yaml <- function(root,
                               config_rel,
                               style_rel,
                               out_pdf) {
  # ---- 读 YAML ----
  config_yaml <- file.path(root, config_rel)
  style_yaml  <- file.path(root, style_rel)

  cfg   <- yaml::read_yaml(config_yaml)
  style <- yaml::read_yaml(style_yaml)

  mm_per_inch <- style$units$mm_per_inch %||% 25.4

  # ---- 基本路径：materials 目录（不再使用顶层 shot_id，每个 band 自己带 shot_id）----
  materials_rel_dir <- cfg$materials_rel_dir
  if (is.null(materials_rel_dir)) {
    stop("Config 缺少必需字段: materials_rel_dir (相对于 root 的 materials 子路径)")
  }

  # ---- 页面尺寸和布局参数（全部要求在 YAML 中显式给出）----
  page_cfg <- cfg$page
  if (is.null(page_cfg)) stop("Config 缺少必需字段: page")

  required_page_fields <- c(
    "width_mm", "height_mm",
    "top_margin_mm", "bottom_margin_mm",
    "left_margin_mm", "right_margin_mm",
    "band_spacing_mm",
    "label_gap_mm",
    "band_label_gap_mm"
  )
  missing_page <- required_page_fields[sapply(required_page_fields, function(k) is.null(page_cfg[[k]]))]
  if (length(missing_page) > 0) {
    stop("Config$page 缺少必需字段: ", paste(missing_page, collapse = ", "))
  }

  width_mm          <- page_cfg$width_mm
  height_mm         <- page_cfg$height_mm
  top_margin_mm     <- page_cfg$top_margin_mm
  bottom_margin_mm  <- page_cfg$bottom_margin_mm
  left_margin_mm    <- page_cfg$left_margin_mm
  right_margin_mm   <- page_cfg$right_margin_mm
  band_spacing_mm   <- page_cfg$band_spacing_mm
  label_gap_mm      <- page_cfg$label_gap_mm
  band_label_gap_mm <- page_cfg$band_label_gap_mm

  # band_height_mm 可选：给出时使用固定高度；缺省时按 patch 像素比例推导
  band_height_mm <- page_cfg$band_height_mm

  # ---- bands 信息：prefix & label；每个 band 必须带 shot_id ----
  bands <- cfg$bands
  if (is.null(bands) || length(bands) == 0) {
    stop("Config 缺少必需字段: bands")
  }

  band_prefixes      <- character(length(bands))
  band_display_names <- character(length(bands))
  band_shot_ids      <- character(length(bands))

  for (i in seq_along(bands)) {
    b <- bands[[i]]
    if (is.null(b$prefix)) {
      stop("Config$bands[[", i, "]] 缺少必需字段: prefix")
    }
    if (is.null(b$label)) {
      stop("Config$bands[[", i, "]] 缺少必需字段: label")
    }
    if (is.null(b$shot_id)) {
      stop("Config$bands[[", i, "]] 缺少必需字段: shot_id（每个 band 现在必须指定来自哪个 shot）")
    }
    band_prefixes[i]      <- b$prefix
    band_display_names[i] <- b$label
    band_shot_ids[i]      <- b$shot_id
  }

  # ---- lanes 信息：只支持 treatment_rows + treatments 格式 ----
  lanes <- cfg$lanes
  if (is.null(lanes)) {
    stop("Config 缺少必需字段: lanes")
  }

  lane_items     <- lanes$items
  lane_count     <- lanes$count
  treatment_rows <- lanes$treatment_rows

  if (is.null(lane_items) || length(lane_items) == 0) {
    stop("Config$lanes 缺少必需字段: items")
  }
  if (is.null(lane_count)) {
    lane_count <- length(lane_items)
  }
  if (lane_count != length(lane_items)) {
    stop("Config$lanes$count 与 items 数量不一致")
  }
  if (is.null(treatment_rows) || length(treatment_rows) == 0) {
    stop("Config$lanes 缺少必需字段: treatment_rows (处理方式行名称)")
  }
  # 简化：要求 treatment_rows 是字符向量
  if (!is.character(treatment_rows)) {
    stop("Config$lanes$treatment_rows 目前只支持字符向量，例如 [\"Ctrl\", \"LPS\", \"Nig\"]")
  }

  # 校验每个 lane 中的 treatments 字典
  for (i in seq_len(lane_count)) {
    lane <- lane_items[[i]]
    if (is.null(lane$genotype)) {
      stop("Config$lanes$items[[", i, "]] 缺少必需字段: genotype")
    }
    if (is.null(lane$treatments)) {
      stop("Config$lanes$items[[", i, "]] 缺少必需字段: treatments (列表/命名向量)")
    }
    missing_rows <- treatment_rows[is.na(match(treatment_rows, names(lane$treatments)))]
    if (length(missing_rows) > 0) {
      stop("Config$lanes$items[[", i, "]]$treatments 缺少以下处理方式键: ",
           paste(missing_rows, collapse = ", "))
    }
  }

  # ---- 读 band patch 图像（每个 band 使用自己的 shot_id）----
  band_imgs <- vector("list", length(bands))

  for (i in seq_along(bands)) {
    prefix  <- band_prefixes[i]
    shot_id <- band_shot_ids[i]

    materials_dir_i <- file.path(root, materials_rel_dir, shot_id)
    tif_path <- file.path(materials_dir_i, paste0(prefix, "_patch.tif"))

    message("[INFO] Band ", i, ": prefix=", prefix, " | shot_id=", shot_id,
            " | materials_dir=", materials_dir_i)

    if (!file.exists(tif_path)) {
      stop("缺少必需的 patch 图像文件: ", tif_path)
    }

    img_magick <- magick::image_read(tif_path)
    img <- as.raster(img_magick)

    band_imgs[[i]] <- img
  }

  n_bands <- length(band_imgs)
  if (n_bands == 0) {
    stop("bands 列表为空或没有有效的 patch 图像")
  }

  # ---- 打开 PDF 设备 ----
  width_in  <- width_mm  / mm_per_inch
  height_in <- height_mm / mm_per_inch

  message("[INFO] Writing PDF to: ", out_pdf)
  grDevices::cairo_pdf(
    filename = out_pdf,
    width    = width_in,
    height   = height_in,
    family   = "Helvetica"
  )

  on.exit({
    grDevices::dev.off()
    message("[OK] figure saved → ", out_pdf)
  }, add = TRUE)

  grid::grid.newpage()

  # ---- 内部面板区域（去掉页边距）----
  inner_width_mm  <- width_mm  - left_margin_mm - right_margin_mm
  inner_height_mm <- height_mm - top_margin_mm  - bottom_margin_mm
  if (inner_width_mm <= 0 || inner_height_mm <= 0) {
    stop("页面尺寸/页边距配置错误：可用区域宽或高 <= 0")
  }

  # ---- 列配置：sample_type / antibody_label / band ----
  layout_cfg <- page_cfg$layout
  if (is.null(layout_cfg)) {
    stop("Config$page 缺少必需字段: layout（需提供 band_width_ratio / antibody_label_ratio，可选 sample_type_ratio）")
  }

  band_width_ratio  <- layout_cfg$band_width_ratio
  label_width_ratio <- layout_cfg$antibody_label_ratio
  sample_type_ratio <- layout_cfg$sample_type_ratio %||% 0

  if (is.null(band_width_ratio) || is.null(label_width_ratio)) {
    stop("Config$page$layout 需要字段: band_width_ratio, antibody_label_ratio")
  }

  n_col <- if (sample_type_ratio > 0) 3L else 2L

  if (n_col == 3L) {
    total_ratio <- band_width_ratio + label_width_ratio + sample_type_ratio
    if (total_ratio <= 0) {
      stop("Config$page$layout 列比例之和必须大于 0")
    }
    sample_ratio_norm <- sample_type_ratio / total_ratio
    label_ratio_norm  <- label_width_ratio  / total_ratio
    band_ratio_norm   <- band_width_ratio   / total_ratio
    col_ratios <- c(sample_ratio_norm, label_ratio_norm, band_ratio_norm)
    sample_col_index <- 1L
    label_col_index  <- 2L
    band_col_index   <- 3L
  } else {
    total_ratio <- band_width_ratio + label_width_ratio
    if (total_ratio <= 0) {
      stop("Config$page$layout 列比例之和必须大于 0")
    }
    label_ratio_norm <- label_width_ratio / total_ratio
    band_ratio_norm  <- band_width_ratio  / total_ratio
    col_ratios <- c(label_ratio_norm, band_ratio_norm)
    sample_col_index <- NA_integer_
    label_col_index  <- 1L
    band_col_index   <- 2L
  }

  col_widths_mm <- inner_width_mm * col_ratios

  # ---- 行配置：1 行 genotype + n_bands 行条带 + n_treat 行处理矩阵 ----
  n_treat <- length(treatment_rows)
  n_row   <- 1L + n_bands + n_treat

  genotype_row_height_mm  <- page_cfg$genotype_row_height_mm %||% (band_label_gap_mm %||% 6)
  band_row_height_mm      <- page_cfg$band_row_height_mm      %||% (band_spacing_mm %||% 10)
  treatment_row_height_mm <- page_cfg$treatment_row_height_mm %||% (band_label_gap_mm %||% 6)

  row_heights_mm <- c(
    genotype_row_height_mm,
    rep(band_row_height_mm, n_bands),
    rep(treatment_row_height_mm, n_treat)
  )

  total_row_height_mm <- sum(row_heights_mm)
  if (total_row_height_mm <= 0) {
    stop("垂直布局错误：所有行高度之和为 0")
  }
  if (total_row_height_mm > inner_height_mm) {
    scale <- inner_height_mm / total_row_height_mm
    row_heights_mm <- row_heights_mm * scale
  }

  # ---- 整体 viewport：整页 + 内部 panel + grid.layout ----
  vp_outer <- viewport(
    x      = unit(0, "mm"),
    y      = unit(0, "mm"),
    width  = unit(width_mm,  "mm"),
    height = unit(height_mm, "mm"),
    just   = c("left", "bottom")
  )
  pushViewport(vp_outer)

  vp_inner <- viewport(
    x      = unit(left_margin_mm,   "mm"),
    y      = unit(bottom_margin_mm, "mm"),
    width  = unit(inner_width_mm,   "mm"),
    height = unit(inner_height_mm,  "mm"),
    just   = c("left", "bottom"),
    name   = "wb_panel_inner"
  )
  pushViewport(vp_inner)

  layout <- grid.layout(
    nrow    = n_row,
    ncol    = n_col,
    widths  = unit(col_widths_mm,  "mm"),
    heights = unit(row_heights_mm, "mm")
  )
  pushViewport(viewport(layout = layout))

  # ---- 顶部 genotype 分组 ----
  lane_width_npc <- 1 / lane_count

  geno_vec    <- vapply(lane_items, function(x) x$genotype, character(1))
  unique_geno <- unique(geno_vec[geno_vec != ""])

  pushViewport(viewport(
    layout.pos.row = 1L,
    layout.pos.col = band_col_index
  ))

  if (length(unique_geno) > 0L) {
    # 对每一种非空 genotype 画一段水平线，并把文字放在该 genotype block 的几何中心
    for (g in unique_geno) {
      idx <- which(geno_vec == g)
      if (length(idx) == 0L) next

      # 覆盖该 genotype 的 lane 范围（在 band 列内的 npc 坐标）
      full_start <- (min(idx) - 1) * lane_width_npc
      full_end   <- max(idx) * lane_width_npc

      # 在线段两端各留出 10% 的水平 padding
      pad_frac   <- 0.10
      line_start <- full_start + (full_end - full_start) * pad_frac
      line_end   <- full_end   - (full_end - full_start) * pad_frac

      # 文本位置使用整个 genotype block 的中点
      x_mid <- (full_start + full_end) / 2

      grid::grid.lines(
        x = unit(c(line_start, line_end), "npc"),
        y = unit(c(0.3, 0.3), "npc"),
        gp = gpar(lwd = 0.7)
      )

      grid::grid.text(
        label = g,
        x     = unit(x_mid, "npc"),
        y     = unit(0.75, "npc"),
        just  = c("centre", "centre"),
        gp    = gpar(
          fontsize = style$typography$axis_tick_default$font_size_pt %||% 6
        )
      )
    }
  } else {
    # 所有 genotype 都是空字符串的 fallback：逐 lane 打标签（不画横线）
    for (k in seq_len(lane_count)) {
      geno_label <- geno_vec[k]
      if (!nzchar(geno_label)) next
      x_mid <- (k - 0.5) * lane_width_npc
      grid::grid.text(
        label = geno_label,
        x     = unit(x_mid, "npc"),
        y     = unit(0.5, "npc"),
        just  = c("centre", "centre"),
        gp    = gpar(
          fontsize = style$typography$axis_tick_default$font_size_pt %||% 6
        )
      )
    }
  }

  upViewport() # 退出 genotype 行

  # ---- 中间 band 行 ----
  for (i in seq_len(n_bands)) {
    row_index <- 1L + i

    # 抗体标签（右对齐 + 右侧黑色三角形指向条带中心）
    if (!is.na(label_col_index)) {
      pushViewport(viewport(
        layout.pos.row = row_index,
        layout.pos.col = label_col_index
      ))

      # 文本位置：在该列内右对齐，略微留出一点空间给箭头
      text_x <- 0.78   # 文本右端的 x（相对该列 cell）
      text_y <- 0.5

      grid::grid.text(
        label = band_display_names[i],
        x     = unit(text_x, "npc"),
        y     = unit(text_y, "npc"),
        just  = c("right", "centre"),
        gp    = gpar(
          fontsize = style$typography$axis_title_default$font_size_pt %||% 7
        )
      )

      # 黑色三角形：指向右侧条带中心，位于文本右侧
      tri_tip_x   <- 0.94   # 三角形尖端（靠近 band 列的一侧）
      tri_base_x  <- 0.82   # 靠近文本一侧，略高于 text_x
      tri_mid_y   <- text_y
      tri_half_h  <- 0.09   # 三角形高度的一半（控制上下大小）

      grid::grid.polygon(
        x = unit(c(tri_base_x, tri_base_x, tri_tip_x), "npc"),
        y = unit(c(tri_mid_y - tri_half_h,
                   tri_mid_y + tri_half_h,
                   tri_mid_y), "npc"),
        gp = gpar(fill = "black", col = NA)
      )

      upViewport()
    }

    # 条带图像
    pushViewport(viewport(
      layout.pos.row = row_index,
      layout.pos.col = band_col_index
    ))

    img <- band_imgs[[i]]
    dims <- dim(img)
    if (!is.null(dims) && length(dims) >= 2) {
      img_h_px <- dims[1]
      img_w_px <- dims[2]
      asp_img  <- img_h_px / img_w_px
    } else {
      asp_img <- 1
    }

    cell_height_mm <- row_heights_mm[row_index]
    cell_width_mm  <- col_widths_mm[band_col_index]
    asp_cell       <- cell_height_mm / cell_width_mm

    if (asp_img <= 0 || asp_cell <= 0) {
      width_npc  <- 1
      height_npc <- 1
    } else if (asp_img <= asp_cell) {
      width_npc  <- 1
      height_npc <- asp_img / asp_cell
    } else {
      height_npc <- 1
      width_npc  <- asp_cell / asp_img
    }

    grid::grid.raster(
      img,
      x      = unit(0.5, "npc"),
      y      = unit(0.5, "npc"),
      width  = unit(width_npc,  "npc"),
      height = unit(height_npc, "npc"),
      just   = "centre",
      interpolate = TRUE
    )

    upViewport()
  }

  # ---- sample_type 分组标注：跨多条 band 画一条竖线，并只显示一次文字 ----
  if (!is.na(sample_col_index)) {
    # 从 bands 中提取每一条 band 的 sample_type
    sample_types <- vapply(bands, function(b) {
      st <- b$sample_type
      if (is.null(st)) "" else as.character(st)
    }, character(1))

    # 把相邻且非空、相同的 sample_type 合并成分组
    groups <- list()
    i <- 1L
    while (i <= n_bands) {
      st <- sample_types[i]
      if (!nzchar(st)) {
        i <- i + 1L
      } else {
        start_i <- i
        while (i + 1L <= n_bands && identical(sample_types[i + 1L], st)) {
          i <- i + 1L
        }
        end_i <- i
        groups[[length(groups) + 1L]] <- list(label = st, start = start_i, end = end_i)
        i <- i + 1L
      }
    }

    # 对每个分组：画连续竖线 + 只在中间那条 band 上写一次文字（严格几何居中）
    if (length(groups) > 0L) {
      for (g in groups) {
        st        <- g$label
        start_row <- 1L + g$start  # 对应 grid.layout 的起始行号（第一条 band）
        end_row   <- 1L + g$end    # 对应 grid.layout 的结束行号（最后一条 band）

        # 使用一个覆盖 start_row:end_row 的 viewport，
        # 在同一个几何区域内同时画竖线和文字，从而保证文字在整个分组高度上的严格居中。
        pushViewport(viewport(
          layout.pos.row = start_row:end_row,
          layout.pos.col = sample_col_index
        ))

        # 竖线：在 sample_type 列上，跨越该分组所有 band 行
        grid::grid.lines(
          x = unit(c(0.95, 0.95), "npc"),  # 靠右一点的竖线
          y = unit(c(0.1, 0.9), "npc"),    # 在整个分组的 10%–90% 高度范围内
          gp = gpar(lwd = 0.7)
        )

        # 文本：在同一个 viewport 中，以 y = 0.5 严格几何居中
        grid::grid.text(
          label = st,
          x     = unit(0.8, "npc"),       # 略小于竖线的 x，靠近竖线左侧
          y     = unit(0.5, "npc"),       # 使用整个分组高度的中心作为对齐点
          just  = c("right", "centre"),   # 文字右对齐，贴近竖线
          gp    = gpar(
            fontsize = style$typography$axis_tick_default$font_size_pt %||% 6
          )
        )

        upViewport()
      }
    }
  }

  # ---- 底部处理方式矩阵 ----
  if (n_treat > 0) {
    for (r in seq_along(treatment_rows)) {
      row_label <- treatment_rows[r]
      row_index <- 1L + n_bands + r

      # 左侧行名：放在 label 列，右对齐，并与右侧 +/- 保持一定距离
      if (!is.na(label_col_index)) {
        pushViewport(viewport(
          layout.pos.row = row_index,
          layout.pos.col = label_col_index
        ))

        grid::grid.text(
          label = row_label,
          x     = unit(0.85, "npc"),     # 靠右对齐，但不贴边，留出到 band 列的间距
          y     = unit(0.5, "npc"),
          just  = c("right", "centre"),
          gp    = gpar(
            fontsize = style$typography$axis_tick_default$font_size_pt %||% 6
          )
        )

        upViewport()
      }

      # 每个 lane 的 + / -
      pushViewport(viewport(
        layout.pos.row = row_index,
        layout.pos.col = band_col_index
      ))

      for (k in seq_len(lane_count)) {
        lane <- lane_items[[k]]
        mark <- lane$treatments[[row_label]]
        mark <- if (is.null(mark)) "" else as.character(mark)
        if (!nzchar(mark)) next

        x_mid <- (k - 0.5) * lane_width_npc
        grid::grid.text(
          label = mark,
          x     = unit(x_mid, "npc"),
          y     = unit(0.5, "npc"),
          just  = c("centre", "centre"),
          gp    = gpar(
            fontsize = style$typography$axis_tick_default$font_size_pt %||% 6
          )
        )
      }

      upViewport()
    }
  }

  # 退出 layout / inner / outer viewport
  upViewport(3)
}
