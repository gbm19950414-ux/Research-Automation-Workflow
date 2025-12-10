#!/usr/bin/env Rscript

# line_chart.R
# 函数库：从 YAML 配置 + 样式文件 + *_stats.xlsx 生成 WT vs HO 时间序列折线图 (mean ± SD)
# 供 figure_3_b.R 等启动脚本调用。

suppressPackageStartupMessages({
  library(yaml)
  library(readxl)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
  library(purrr)
})

# ---------- 项目根路径与默认样式路径（按需修改） ----------
ROOT <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"
DEFAULT_STYLE_PATH <- file.path(ROOT, "02_protocols/figure_style_nature.yaml")

`%||%` <- function(x, y) if (!is.null(x)) x else y

mm_to_in <- function(mm, mm_per_inch = 25.4) {
  mm / mm_per_inch
}

p_to_stars <- function(p) {
  ifelse(
    is.na(p), "",
    ifelse(
      p <= 0.001, "***",
      ifelse(p <= 0.01, "**",
             ifelse(p <= 0.05, "*", ""))
    )
  )
}

# ---------- 加载 Nature 风格 YAML ----------
load_style_nature <- function(style_path = DEFAULT_STYLE_PATH) {
  if (!file.exists(style_path)) {
    warning("样式文件未找到: ", style_path, "，使用 ggplot2 默认主题。")
    return(list(style = NULL, theme = theme_minimal(), colors = list()))
  }
  style <- yaml::read_yaml(style_path)

  sizes <- style$typography$sizes_pt
  cols  <- style$colors

  theme_base <- theme_classic(base_family = style$typography$font_family_primary) +
    theme(
      axis.text  = element_text(size = sizes$axis_tick_default),
      axis.title = element_text(size = sizes$axis_label_default),
      legend.text  = element_text(size = sizes$legend_text_default),
      legend.title = element_text(size = sizes$legend_title_default),
      plot.margin = margin(
        t = style$layout$plot_margin_pt$top,
        r = style$layout$plot_margin_pt$right,
        b = style$layout$plot_margin_pt$bottom,
        l = style$layout$plot_margin_pt$left,
        unit = "pt"
      ),
      panel.grid.major = element_blank(),
      panel.grid.minor = element_blank(),
      panel.border     = element_blank(),
      axis.line        = element_line()
    )

  list(
    style = style,
    theme = theme_base,
    colors = cols
  )
}

apply_wt_ho_colors <- function(p, color_cfg, legend_order = NULL) {
  if (!is.null(color_cfg$wt_ho)) {
    pal <- unlist(color_cfg$wt_ho)
    if (!is.null(legend_order)) {
      pal <- pal[legend_order]
    }
    p <- p + scale_color_manual(values = pal, breaks = legend_order)
  }
  p
}

# ---------- 数据预处理工具 ----------

# 把 stats 宽表中的 WT/HO 列 pivot 成 genotype-long
pivot_stats_long <- function(df, mapping) {
  geno_cols <- mapping$genotype_cols

  long_list <- imap(geno_cols, function(cols, geno) {
    df %>%
      mutate(
        genotype = geno,
        mean = .data[[cols$mean]],
        sd   = .data[[cols$sd]]
      )
  })

  bind_rows(long_list)
}

# 条件过滤
apply_filters <- function(df, filters) {
  if (is.null(filters)) return(df)
  out <- df
  for (nm in names(filters)) {
    vals <- filters[[nm]]
    out <- out %>% dplyr::filter(.data[[nm]] %in% vals)
  }
  out
}

# ---------- 绘制单 panel 的折线图 ----------
plot_panel_line <- function(panel_cfg, style_env) {
  message("[INFO] 读取数据: ", panel_cfg$data)
  df_raw <- readxl::read_xlsx(panel_cfg$data, sheet = panel_cfg$sheet %||% 1)

  # 应用过滤条件
  df_flt <- apply_filters(df_raw, panel_cfg$filter)

  # pivot 宽表为长表
  df_long <- pivot_stats_long(df_flt, panel_cfg$mapping)
  message("[DEBUG] nrow(df_raw)  = ", nrow(df_raw))
  message("[DEBUG] nrow(df_flt)  = ", nrow(df_flt))
  message("[DEBUG] nrow(df_long) = ", nrow(df_long))
  message("[DEBUG] 非 NA 的 mean 个数 = ", sum(!is.na(df_long$mean)))
  x_var <- panel_cfg$mapping$x
  x_lab <- panel_cfg$mapping$x_label %||% x_var
  y_lab <- panel_cfg$mapping$y_label %||% "value"
  hue_var <- panel_cfg$mapping$hue %||% "genotype"
  group_var <- panel_cfg$mapping$group %||% hue_var

  # 若配置文件提供了 p 值列，则准备显著性星号注释数据
  p_col <- panel_cfg$mapping$p_value %||% NULL
  ann_df <- NULL
  if (!is.null(p_col) && p_col %in% names(df_flt) && nrow(df_long) > 0) {
    # 1) 每个 x 上，找到当前图中 mean+sd 的最大值，作为注释基线
    y_max_df <- df_long %>%
      dplyr::group_by(.data[[x_var]]) %>%
      dplyr::summarise(
        y_base = max(mean + sd, na.rm = TRUE),
        .groups = "drop"
      )

    # 2) 从原始 stats 表中取 x 和 p 值，并去重
    ann_raw <- df_flt[, c(x_var, p_col)]
    colnames(ann_raw) <- c("x", "p")

    ann_df <- ann_raw %>%
      dplyr::distinct() %>%
      dplyr::filter(!is.na(p))

    # 3) 将 y 基线并入，并计算星号与纵坐标
    if (nrow(ann_df) > 0) {
      y_max_df2 <- y_max_df
      colnames(y_max_df2)[colnames(y_max_df2) == x_var] <- "x"

      ann_df <- ann_df %>%
        dplyr::left_join(y_max_df2, by = "x") %>%
        dplyr::mutate(
          label = p_to_stars(p),
          y = y_base * 1.05
        ) %>%
        dplyr::filter(label != "")
    }
  }

  # 坐标轴 breaks / limits
  x_breaks <- panel_cfg$mapping$x_breaks %||% sort(unique(df_long[[x_var]]))
  x_breaks <- as.numeric(unlist(x_breaks))

  x_limits <- panel_cfg$mapping$x_limits %||% c(min(df_long[[x_var]]), max(df_long[[x_var]]))
  x_limits <- as.numeric(unlist(x_limits))

  y_limits <- panel_cfg$mapping$y_limits %||% c(NA, NA)
  y_limits <- as.numeric(unlist(y_limits))
  p <- ggplot(
    df_long,
    aes(
      x = .data[[x_var]],
      y = mean,
      color = .data[[hue_var]],
      group = .data[[group_var]]
    )
  ) +
    geom_line(size = 0.4) +
    geom_point(size = 1.0) +
    geom_errorbar(
      aes(ymin = mean - sd, ymax = mean + sd),
      width = 0.4,
      size = 0.3
    ) +
    # 显著性星号（若 ann_df 非空）
    { if (!is.null(ann_df) && nrow(ann_df) > 0) {
        geom_text(
          data = ann_df,
          aes(x = x, y = y, label = label),
          inherit.aes = FALSE,
          vjust = 0,
          size = 3
        )
      } else {
        NULL
      } } +
    scale_x_continuous(
      breaks = x_breaks,
      limits = x_limits
    ) +
    scale_y_continuous(
      limits = y_limits
    ) +
    labs(
      x = x_lab,
      y = y_lab,
      color = panel_cfg$legend$title %||% NULL
    ) +
    style_env$theme

  legend_order <- panel_cfg$legend$order %||% NULL
  p <- apply_wt_ho_colors(p, style_env$colors, legend_order)

  p
}

# ---------- 从 YAML 绘制整张图（目前支持单 panel） ----------

draw_figure_from_yaml <- function(cfg_path,
                                  style_path = DEFAULT_STYLE_PATH,
                                  out_dir = NULL,
                                  out_basename = NULL) {
  if (!file.exists(cfg_path)) {
    stop("找不到图配置文件: ", cfg_path)
  }
  cfg <- yaml::read_yaml(cfg_path)

  style_env <- load_style_nature(style_path)

  width_mm  <- cfg$size$width_mm
  height_mm <- cfg$size$high_mm
  w_in <- mm_to_in(width_mm)
  h_in <- mm_to_in(height_mm)

  if (is.null(out_basename)) {
    out_basename <- cfg$out %||% tools::file_path_sans_ext(basename(cfg_path))
  }
  if (is.null(out_dir)) {
    out_dir <- file.path(ROOT, "04_data/processed/figures")
  }
  if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

  panel_cfg <- cfg$panels[[1]]

  p <- plot_panel_line(panel_cfg, style_env)

  out_file <- file.path(out_dir, paste0(out_basename, ".pdf"))
  message("[INFO] 写出图像: ", out_file)

  pdf(out_file, width = w_in, height = h_in, useDingbats = FALSE)
  print(p)
  dev.off()

  invisible(out_file)
}

# 若单独运行 line_chart.R，可在此做简单测试或提示
if (sys.nframe() == 0) {
  message("line_chart.R 作为函数库使用，请在 figure_X_Y.R 中调用 draw_figure_from_yaml()。")
}