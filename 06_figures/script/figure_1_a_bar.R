#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
  library(readr)
  library(dplyr)
  library(tidyr)
  library(purrr)
  library(stringr)
  library(ggplot2)
})

`%||%` <- function(x, y) if (is.null(x)) y else x

# ------------------ 定位项目根目录 ------------------
# 简化：假设当前工作目录就是项目根目录 EphB1
# 在终端中请先 cd 到 EphB1 再调用 Rscript。
root_dir <- normalizePath(getwd())
message("[INFO] Project root: ", root_dir)

# ------------------ 路径配置 ------------------
tsv_path       <- file.path(root_dir, "06_figures", "figure_1", "figure_1_a.tsv")
panel_yaml     <- file.path(root_dir, "06_figures", "script", "figure_1_a.yaml")
style_yaml     <- file.path(root_dir, "02_protocols", "figure_style_nature.yaml")

message("[INFO] Reading TSV from: ", tsv_path)
message("[INFO] Reading panel config from: ", panel_yaml)
message("[INFO] Reading style config from: ", style_yaml)

# ------------------ 读入数据 ------------------

dens <- readr::read_tsv(tsv_path, show_col_types = FALSE)

panel_cfg <- yaml::read_yaml(panel_yaml)
style_cfg <- yaml::read_yaml(style_yaml)

# bands 信息（当前脚本主要用 band label 作分面；band_prefix 只是备用）
bands_cfg <- panel_cfg$bands
bands_df <- map_dfr(bands_cfg, function(b) {
  tibble::tibble(
    band_prefix = b$prefix %||% NA_character_,
    band_label  = b$label  %||% b$band %||% NA_character_,
    shot_id     = b$shot_id %||% NA_character_
  )
})

# lanes / sample 信息：每个 lane 的 genotype + condition（根据 treatments 组合）
lanes_cfg <- panel_cfg$lanes
lane_items <- lanes_cfg$items

lane_meta <- map_dfr(lane_items, function(it) {
  lane   <- it$lane
  geno   <- it$genotype %||% NA_character_
  trt    <- it$treatments %||% list()
  # 把 "+" 的 treatment 拼成一个 condition label，例如 "Ctrl+LPS"
  if (length(trt) > 0) {
    on_trt <- names(trt)[unlist(trt) == "+"]
    cond   <- if (length(on_trt) == 0) "None" else paste(on_trt, collapse = "+")
  } else {
    cond <- NA_character_
  }
  tibble::tibble(
    lane_index = lane,
    genotype   = geno,
    condition  = cond
  )
})

# ------------------ 合并 dens + bands + sample 信息 ------------------

# dens.tsv 结构（按你之前 Python 脚本）：panel, shot_id, gel_name, band, band_prefix, lane_index, signal_sum, signal_mean, ...
# 这里假设 dens$band 就是 panel_yaml 里的 label / band 字段

dens2 <- dens %>%
  # 合并 lane 的 genotype / condition
  left_join(lane_meta, by = "lane_index") %>%
  # 也可以用 bands_df 做 sanity check（可选）
  left_join(
    bands_df %>% distinct(band_prefix, band_label, shot_id),
    by = c("band_prefix" = "band_prefix", "shot_id" = "shot_id")
  ) %>%
  mutate(
    band_plot = coalesce(band_label, band),  # 用 YAML 中的 band_label 优先，否则退回 dens$band
    condition = if_else(is.na(condition), "NA", condition)
  )

# ------------------ 选择用哪个指标画图 ------------------
# 这里用 signal_sum 作为条带强度；你可以改成 signal_mean
dens_long <- dens2 %>%
  mutate(
    y_value = signal_sum
  )

# ------------------ 统计方式 ------------------
# 当前每个 lane 就对应一个样本；如果以后一个 condition 有多个 lane，可在这里改成 mean/sem
summary_df <- dens_long %>%
  group_by(band_plot, genotype, condition, lane_index) %>%
  summarise(
    intensity = mean(y_value, na.rm = TRUE),
    .groups = "drop"
  )

# 为了柱状图更清晰，可以按 condition + lane 排个顺序
summary_df <- summary_df %>%
  mutate(
    condition = factor(condition),
    genotype  = factor(genotype, levels = c("WT", "KO"))
  )

# ------------------ 使用 GAPDH 进行归一化 ------------------
# 这里假定 GAPDH 的 band_plot 名字为 "GAPDH"（不区分大小写）
gapdh_df <- summary_df %>%
  dplyr::filter(stringr::str_to_lower(band_plot) == "gapdh") %>%
  dplyr::transmute(
    genotype,
    condition,
    lane_index,
    gapdh_intensity = intensity
  )

# 把 GAPDH 强度拼回所有 band，用于归一化
norm_df <- summary_df %>%
  dplyr::left_join(
    gapdh_df,
    by = c("genotype", "condition", "lane_index")
  ) %>%
  dplyr::mutate(
    norm_intensity = intensity / gapdh_intensity
  )

# ------------------ 应用 Nature 风格配置 ------------------

# 字体 & 字号
font_family_primary <- style_cfg$typography$font_family_primary %||% "Helvetica"

size_axis_tick  <- style_cfg$typography$sizes_pt$axis_tick_default   %||% 6
size_axis_label <- style_cfg$typography$sizes_pt$axis_label_default  %||% 7
size_legend     <- style_cfg$typography$sizes_pt$legend_text_default %||% 6
size_title      <- style_cfg$typography$sizes_pt$title_optional      %||% 7

# 线宽换算：pt → lwd
line_pt   <- style_cfg$lines$axis_line_default_pt %||% 0.5
pt_per_lwd <- style_cfg$lines$r_lwd_scale$pt_per_lwd %||% 0.75
axis_lwd  <- line_pt / pt_per_lwd

# 图像尺寸（mm → inch）
page_cfg <- panel_cfg$page
width_mm  <- page_cfg$width_mm  %||% 84
height_mm <- 40   # 柱状图高度可以稍微小一点，也可以用 page_cfg$height_mm

width_in  <- width_mm  / style_cfg$units$mm_per_inch
height_in <- height_mm / style_cfg$units$mm_per_inch

# ------------------ 每个条带单独输出一个 PDF（使用归一化后的强度） ------------------

# 需要输出图的 band 列表：排除 GAPDH 自身
plot_bands <- norm_df %>%
  dplyr::filter(stringr::str_to_lower(band_plot) != "gapdh") %>%
  dplyr::distinct(band_plot) %>%
  dplyr::pull(band_plot)

for (b in plot_bands) {
  df_band <- norm_df %>%
    dplyr::filter(band_plot == b, !is.na(norm_intensity))

  if (nrow(df_band) == 0) {
    next
  }

  # 每个条带单独一个 PDF 文件，命名：figure_1_a_<band>.pdf
  out_pdf <- file.path(root_dir, "06_figures", "figure_1", paste0("figure_1_a_", b, ".pdf"))
  message("[INFO] Writing barplot PDF for band ", b, " to: ", out_pdf)

  pdf(out_pdf, width = width_in, height = height_in, family = font_family_primary)

  # x 轴用 condition，顶部用 facet_wrap 标注 genotype（满足“文件上方是基因型标注”）
  p <- ggplot(df_band,
              aes(x = condition,
                  y = norm_intensity,
                  fill = genotype)) +
    geom_col(
      position = position_dodge(width = 0.8),
      width = 0.7,
      colour = "black",
      size = axis_lwd * 0.5
    ) +
    facet_wrap(~ genotype, nrow = 1) +
    scale_fill_manual(
      values = c("WT" = "grey60", "KO" = "grey20"),
      na.value = "grey80"
    ) +
    labs(
      title = b,
      x = NULL,
      y = "Normalized intensity (band / GAPDH)",
      fill = NULL
    ) +
    theme_bw(base_family = font_family_primary) +
    theme(
      panel.grid = element_blank(),
      axis.text.x  = element_text(size = size_axis_tick, colour = "black", angle = 45, hjust = 1),
      axis.text.y  = element_text(size = size_axis_tick, colour = "black"),
      axis.title.y = element_text(size = size_axis_label, colour = "black"),
      strip.text   = element_text(size = size_axis_label, colour = "black"),
      strip.background = element_rect(colour = "black", fill = "white", size = axis_lwd),
      legend.position = "none",
      axis.ticks = element_line(size = axis_lwd),
      axis.line  = element_line(size = axis_lwd, colour = "black"),
      panel.border = element_rect(size = axis_lwd, colour = "black")
    )

  print(p)
  dev.off()
}

message("[OK] Per-band normalized barplots saved for bands: ", paste(plot_bands, collapse = ", "))