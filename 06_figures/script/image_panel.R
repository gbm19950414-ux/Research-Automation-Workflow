#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
  library(magick)
  library(grid)
  library(purrr)
  library(dplyr)
  library(rlang)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript image_panel.R <panel_yaml>")

panel_yaml_path <- args[1]
panel_cfg <- yaml::read_yaml(panel_yaml_path)
# panel YAML can optionally include a global `curve:` block, and each cell can override via `cells: - curve:`

# project root: 和之前脚本保持一致的定位方式
project_root <- normalizePath(file.path(dirname(panel_yaml_path), "..", ".."))

# ---- 样式文件 ----
style_yaml_path <- file.path(project_root, "02_protocols/figure_style_nature.yaml")
style_cfg <- yaml::read_yaml(style_yaml_path)

typography   <- style_cfg$typography
sizes_pt     <- typography$sizes_pt
font_family  <- typography$font_family_primary %||% "Helvetica"

line_cfg     <- style_cfg$lines
layout_style <- style_cfg$layout

axis_label_size   <- sizes_pt$axis_label_default   %||% 6.5
axis_tick_size    <- sizes_pt$axis_tick_default    %||% 5.5
panel_label_size  <- sizes_pt$panel_label_default  %||% axis_label_size

axis_title_margin_cfg <- layout_style$axis_title_margin_pt
style_plot_margin     <- layout_style$plot_margin_pt

mm_per_inch <- 25.4
mm_to_pt <- function(mm) (72 / mm_per_inch) * mm

# ---- panel 自身 layout（外边距按 previous pipeline 的方式处理）----
layout_cfg <- panel_cfg$layout
outer_frac <- layout_cfg$axis_outer_frac

width_mm  <- panel_cfg$size$width_mm
height_mm <- panel_cfg$size$high_mm

style_margin_top    <- style_plot_margin$top    %||% 0
style_margin_bottom <- style_plot_margin$bottom %||% 0
style_margin_left   <- style_plot_margin$left   %||% 0
style_margin_right  <- style_plot_margin$right  %||% 0

plot_margin_pt <- list(
  top    = style_margin_top    + mm_to_pt((outer_frac$top    %||% 0) * height_mm),
  bottom = style_margin_bottom + mm_to_pt((outer_frac$bottom %||% 0) * height_mm),
  left   = style_margin_left   + mm_to_pt((outer_frac$left   %||% 0) * width_mm),
  right  = style_margin_right  + mm_to_pt((outer_frac$right  %||% 0) * width_mm)
)

# ---- grid 配置 ----
grid_cfg   <- panel_cfg$grid
n_rows     <- grid_cfg$n_rows
n_cols     <- grid_cfg$n_cols
row_labels <- grid_cfg$row_labels
col_labels <- grid_cfg$col_labels
cells_cfg  <- grid_cfg$cells

# image size and layout gaps from yaml
nimg_size        <- grid_cfg$image_size_mm
img_width_mm     <- nimg_size$width
img_height_mm    <- nimg_size$height
label_height_mm  <- grid_cfg$label_height_mm %||% 4
gap_mm           <- grid_cfg$gap_mm %||% 2

# optional: width of the row-label (left) column; keep simple fixed value
label_col_width_mm <- 10

# 把 cell 配置整理成 data.frame，方便操作
cells_df <- tibble::tibble(
  row     = purrr::map_int(cells_cfg, "row"),
  col     = purrr::map_int(cells_cfg, "col"),
  enabled = purrr::map_lgl(cells_cfg, ~ .x$enabled %||% TRUE),
  images  = purrr::map(cells_cfg, "images"),
  blend   = purrr::map_chr(cells_cfg, ~ .x$blend %||% "single"),
  curve   = purrr::map(cells_cfg, ~ .x$curve %||% NULL)
)

# ---- 辅助函数：读取并合成单元格图像 ----
# curve adjustment (Photoshop-like): implemented as an S-curve (sigmoid) in [0,1]
# YAML examples:
# curve:
#   enable: true
#   type: sigmoid        # currently supported: sigmoid, gamma
#   strength: 0.6        # 0..1 (0 = no change)
#   mid: 0.5             # sigmoid midpoint (0..1)
#   gamma: 0.85          # only used when type: gamma
apply_curve_adjustment <- function(img, curve_cfg) {
  if (is.null(curve_cfg)) return(img)
  if (isFALSE(curve_cfg$enable %||% TRUE)) return(img)

  type <- (curve_cfg$type %||% "sigmoid")

  # no-op fast path
  strength <- suppressWarnings(as.numeric(curve_cfg$strength %||% 0))
  if (is.na(strength) || strength <= 0) return(img)

  if (type == "sigmoid") {
    # strength in [0,1] -> steepness in [0, ~12]
    a   <- max(0, min(1, strength)) * 12
    mid <- suppressWarnings(as.numeric(curve_cfg$mid %||% 0.5))
    if (is.na(mid)) mid <- 0.5
    mid <- max(0, min(1, mid))

    # Magick FX language: u is the pixel value in [0,1]
    expr <- sprintf("1/(1+exp(-%0.6f*(u-%0.6f)))", a, mid)
    return(magick::image_fx(img, expression = expr))
  }

  if (type == "gamma") {
    # gamma curve: out = u^gamma ; gamma < 1 brightens shadows, > 1 darkens
    gamma <- suppressWarnings(as.numeric(curve_cfg$gamma %||% 1))
    if (is.na(gamma) || gamma <= 0) return(img)

    # blend gamma effect by strength: effective gamma moves from 1 -> gamma
    g_eff <- 1 + (gamma - 1) * max(0, min(1, strength))
    expr  <- sprintf("pow(u,%0.6f)", g_eff)
    return(magick::image_fx(img, expression = expr))
  }

  # unknown type -> no-op
  img
}

build_cell_image <- function(img_paths, blend, curve_cfg, project_root, img_width_mm, img_height_mm) {
  if (length(img_paths) == 0) {
    return(NULL)
  }

  imgs <- img_paths %>%
    purrr::map(~ magick::image_read(file.path(project_root, .x)))

  if (length(imgs) == 1 || blend == "single") {
    # 只有一张图，或者显式要求 single，就直接用
    img <- imgs[[1]]
  } else if (blend == "lighten") {
    # 使用最后一张作为底图（背景），前面的图层依次以 "lighten" 模式叠加
    base <- imgs[[length(imgs)]]

    if (length(imgs) > 1) {
      # 依次把前面的图（1 到 length-1）叠加到 base 上
      for (i in seq_len(length(imgs) - 1)) {
        base <- magick::image_composite(base, imgs[[i]], operator = "lighten")
      }
      img <- base
    } else {
      img <- base
    }
  } else {
    # 未知 blend 模式时，退回简单第一张
    img <- imgs[[1]]
  }

  # Apply optional curves adjustment AFTER blending and BEFORE rasterizing
  img <- apply_curve_adjustment(img, curve_cfg)

  grid::rasterGrob(
    as.raster(img),
    interpolate = TRUE,
    width  = grid::unit(img_width_mm, "mm"),
    height = grid::unit(img_height_mm, "mm")
  )
}


# ---- 输出 PDF ----
# Allow output directory to be configured in panel YAML via `out_dir`
out_dir_cfg <- panel_cfg$out_dir %||% "06_figures/figure_4"
out_dir <- file.path(project_root, out_dir_cfg)
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

out_file <- file.path(out_dir, paste0(panel_cfg$out, ".pdf"))

# compute content-driven height in mm: label row + n_rows * (gap + image height)
content_height_mm <- label_height_mm + n_rows * (gap_mm + img_height_mm)

pdf(out_file,
    width  = panel_cfg$size$width_mm / mm_per_inch,
    height = content_height_mm / mm_per_inch)

# ---- 布局：额外加一行一列用于标题 ----
grid::grid.newpage()

layout <- grid::grid.layout(
  nrow = 1 + 2 * n_rows,  # 1 行标题 + n_rows*(gap + image)
  ncol = 1 + 2 * n_cols,  # 1 列标题 + n_cols*(gap + image)
  widths  = grid::unit.c(
    grid::unit(label_col_width_mm, "mm"),                         # col 1: 行标题列固定宽度
    rep(grid::unit.c(grid::unit(gap_mm, "mm"),                    # gap 列
                     grid::unit(img_width_mm, "mm")), n_cols)     # 图像列
  ),
  heights = grid::unit.c(
    grid::unit(label_height_mm, "mm"),                            # row 1: 列标题行固定高度
    rep(grid::unit.c(grid::unit(gap_mm, "mm"),                    # gap 行
                     grid::unit(img_height_mm, "mm")), n_rows)    # 图像行
  )
)

vp <- grid::viewport(
  layout = layout,
  name   = "figure_4_b_image_vp"
)

grid::pushViewport(vp)

# ---- 绘制列标题（顶行，跳过左上角空格）----
for (j in seq_len(n_cols)) {
  label <- col_labels[[j]]
  if (!is.null(label)) {
    grid::grid.text(
      label,
      x = 0.5, y = 0.5,
      gp = grid::gpar(
        fontfamily = font_family,
        fontsize   = panel_label_size
      ),
      vp = grid::viewport(
        layout.pos.row = 1,
        layout.pos.col = 2 * j + 1,   # 图像列的索引
        name = paste0("col_label_", j)
      )
    )
  }
}

# ---- 绘制行标题（左列，跳过左上角空格），竖排也可以改为 rot=90 ----
for (i in seq_len(n_rows)) {
  label <- row_labels[[i]]
  if (!is.null(label)) {
    grid::grid.text(
      label,
      x = 0.5, y = 0.5,
      gp = grid::gpar(
        fontfamily = font_family,
        fontsize   = panel_label_size
      ),
      vp = grid::viewport(
        layout.pos.row = 2 * i + 1,   # 图像行的索引
        layout.pos.col = 1,
        name = paste0("row_label_", i)
      )
    )
  }
}

# ---- 绘制每个 cell 的图像 ----
for (k in seq_len(nrow(cells_df))) {
  row_idx <- cells_df$row[k]
  col_idx <- cells_df$col[k]

  # allow disabling a specific cell from YAML
  if (isFALSE(cells_df$enabled[k])) next

  imgs       <- cells_df$images[[k]]
  blend      <- cells_df$blend[k]
  curve_cell <- cells_df$curve[[k]]
  curve_cfg  <- curve_cell %||% (panel_cfg$curve %||% NULL)

  g <- build_cell_image(imgs, blend, curve_cfg, project_root, img_width_mm, img_height_mm)
  if (is.null(g)) next

  grid::pushViewport(
    grid::viewport(
      layout.pos.row = 2 * row_idx + 1,  # 图像行
      layout.pos.col = 2 * col_idx + 1,  # 图像列
      name = paste0("cell_", row_idx, "_", col_idx)
    )
  )
  grid::grid.draw(g)
  grid::popViewport()
}

# 可以根据需要在外层增加整体 margin（目前 PDF 尺寸即为最终尺寸）
grid::upViewport(1)
dev.off()

message("[INFO] Saved image panel to: ", out_file)