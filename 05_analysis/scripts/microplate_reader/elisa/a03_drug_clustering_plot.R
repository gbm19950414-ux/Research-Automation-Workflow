#!/usr/bin/env Rscript
# -*- coding: utf-8 -*-

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(stringr)
  library(ggplot2)
  library(yaml)
  library(grid)
})

# ---- paths ----
base_dir <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"
in_path  <- file.path(base_dir, "04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA_clustering_relative_change copy.xlsx")

out_dir  <- file.path(base_dir, "04_data/processed/microplate_reader/elisa检测细胞因子")
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

if (!file.exists(in_path)) stop("找不到输入文件：", in_path)

`%||%` <- function(a, b) if (!is.null(a)) a else b

# ---- figure style (Nature-like) ----
style_path <- file.path(base_dir, "02_protocols/figure_style_nature.yaml")
if (!file.exists(style_path)) {
  stop("找不到风格配置文件：", style_path, "（请确认该文件存在；或把它拷贝到该路径）")
}
style <- yaml::read_yaml(style_path)

mm_per_inch <- as.numeric(style$units$mm_per_inch %||% 25.4)
pt_to_mm <- function(pt) pt * mm_per_inch / 72.27

get_pt <- function(path, default) {
  # path example: c("typography","sizes_pt","axis_tick_default")
  x <- style
  for (k in path) {
    if (is.null(x[[k]])) return(default)
    x <- x[[k]]
  }
  as.numeric(x)
}

get_chr <- function(path, default) {
  x <- style
  for (k in path) {
    if (is.null(x[[k]])) return(default)
    x <- x[[k]]
  }
  as.character(x)
}

theme_nature_from_yaml <- function() {
  base_family <- get_chr(c("typography","font_family_primary"), "Helvetica")

  axis_tick_pt   <- get_pt(c("typography","sizes_pt","axis_tick_default"), 5.5)
  axis_label_pt  <- get_pt(c("typography","sizes_pt","axis_label_default"), 6.5)
  legend_text_pt <- get_pt(c("typography","sizes_pt","legend_text_default"), 6)
  legend_tit_pt  <- get_pt(c("typography","sizes_pt","legend_title_default"), 6.5)
  title_pt       <- get_pt(c("typography","sizes_pt","title_optional"), 7)

  axis_line_pt   <- get_pt(c("lines","axis_line_default_pt"), 0.25)
  major_grid_pt  <- get_pt(c("lines","major_grid_default_pt"), 0.35)
  minor_grid_pt  <- get_pt(c("lines","minor_grid_default_pt"), 0.25)

  x_margin_pt <- get_pt(c("layout","axis_title_margin_pt","x"), 3)
  y_margin_pt <- get_pt(c("layout","axis_title_margin_pt","y"), 3)
  m_top_pt    <- get_pt(c("layout","plot_margin_pt","top"), 0)
  m_right_pt  <- get_pt(c("layout","plot_margin_pt","right"), 0)
  m_bottom_pt <- get_pt(c("layout","plot_margin_pt","bottom"), 0)
  m_left_pt   <- get_pt(c("layout","plot_margin_pt","left"), 0)

  theme_bw(base_family = base_family) +
    theme(
      plot.title = element_text(size = title_pt, face = "plain"),
      axis.text  = element_text(size = axis_tick_pt),
      axis.title = element_text(size = axis_label_pt, margin = margin(t = y_margin_pt, r = x_margin_pt, unit = "pt")),

      axis.line  = element_line(linewidth = pt_to_mm(axis_line_pt)),
      panel.border = element_rect(linewidth = pt_to_mm(axis_line_pt), fill = NA),
      panel.grid.major = element_line(linewidth = pt_to_mm(major_grid_pt)),
      panel.grid.minor = element_line(linewidth = pt_to_mm(minor_grid_pt)),

      legend.text  = element_text(size = legend_text_pt),
      legend.title = element_text(size = legend_tit_pt),
      legend.key.height = unit(3, "mm"),
      legend.key.width  = unit(3, "mm"),
      legend.spacing.y  = unit(1, "mm"),
      legend.box.spacing = unit(1.5, "mm"),

      plot.margin = margin(t = m_top_pt, r = m_right_pt, b = m_bottom_pt, l = m_left_pt, unit = "pt")
    )
}

wt_col <- style$colors$wt_ho$WT %||% "#F08A4B"
ho_col <- style$colors$wt_ho$HO %||% "#4DB6AC"

# ---- read ----
sheets <- readxl::excel_sheets(in_path)
sheet_to_read <- if ("relative_change" %in% sheets) "relative_change" else sheets[[1]]
df <- readxl::read_excel(in_path, sheet = sheet_to_read)

# ---- required columns ----
need_cols <- c("batch", "genotype", "drug", "relative_change", "concentration")
missing <- setdiff(need_cols, names(df))
if (length(missing) > 0) stop("缺少必要列：", paste(missing, collapse = ", "))

# ---- preprocess ----
df2 <- df %>%
  mutate(
    batch = as.character(.data$batch),
    genotype = as.character(.data$genotype),
    drug = as.character(.data$drug),
    drug_lower = str_to_lower(.data$drug),
    concentration = suppressWarnings(as.numeric(.data$concentration)),
    relative_change = suppressWarnings(as.numeric(.data$relative_change)),
    log2_fc = log2(.data$relative_change),
    log10_conc = log10(.data$concentration)
  ) %>%
  filter(is.finite(.data$log2_fc), is.finite(.data$log10_conc))

# ---- drug_class (fc/bel/ad/anti) ----
# 注意：ad 可能误匹配（如 add），你如果有更稳定的命名规则我可以再收紧
df2 <- df2 %>%
  mutate(
    drug_class = case_when(
      str_detect(drug_lower, "fc")   ~ "fc",
      str_detect(drug_lower, "bel")  ~ "bel",
      str_detect(drug_lower, "anti") ~ "anti",
      str_detect(drug_lower, "ad")   ~ "ad",
      TRUE ~ "other"
    )
  ) %>%
  filter(.data$drug_class != "other")

# 可选：如果存在 antibody/analyte，则纳入分面（避免把不同因子混在一张里）
# 注意：这里不再把 batch 放到分面里，而是跨批次汇总到同一坐标系
facet_cols <- character(0)
if ("antibody" %in% names(df2)) facet_cols <- c(facet_cols, "antibody")
if ("analyte"  %in% names(df2)) facet_cols <- c(facet_cols, "analyte")

# 为了让 facet_grid 使用方便：拼一个列分面标签（若无 antibody/analyte，则统一为 "all"）
if (length(facet_cols) == 0) {
  df2 <- df2 %>% mutate(facet_col = "all")
} else {
  df2 <- df2 %>% mutate(facet_col = do.call(paste, c(across(all_of(facet_cols)), sep = " | ")))
}

batch_n <- dplyr::n_distinct(df2$batch)
show_batch_legend <- batch_n <= 12

# ---- plot: Scheme 1 (pooled across batches) | one file per drug_class ----
classes <- intersect(c("fc", "bel", "ad", "anti"), unique(df2$drug_class))
if (length(classes) == 0) stop("drug_class 中未找到 fc/bel/ad/anti，无法绘图")

for (cls in classes) {
  dsub <- df2 %>% filter(.data$drug_class == cls)

  p <- ggplot(dsub, aes(x = log10_conc, y = log2_fc)) +
    geom_hline(yintercept = 0, linewidth = pt_to_mm(get_pt(c("lines","axis_line_default_pt"), 0.25))) +
    geom_point(aes(color = genotype, shape = batch), alpha = 0.85, size = 2) +
    # 跨批次总体趋势：每个 genotype 一条线
    geom_smooth(aes(color = genotype, group = genotype), method = "lm", se = FALSE,
                linewidth = pt_to_mm(get_pt(c("lines","line_width_pt"), 0.5))) +
    scale_color_manual(values = c(WT = wt_col, HO = ho_col, wt = wt_col, ho = ho_col)) +
    facet_grid(cols = vars(facet_col)) +
    labs(
      title = paste0("Scheme 1: log10(concentration) vs log2(relative_change) (pooled) | ", cls),
      x = "log10(concentration)",
      y = "log2(relative_change)",
      color = "genotype",
      shape = "batch"
    ) +
    guides(
      color = guide_legend(order = 1, override.aes = list(shape = 16, size = 2.5, alpha = 1)),
      shape = guide_legend(order = 2, nrow = if (show_batch_legend) 2 else 1, byrow = TRUE,
                           override.aes = list(color = "black", size = 2.5, alpha = 1))
    ) +
    theme_nature_from_yaml() +
    theme(legend.position = "bottom", legend.box = "vertical")

  if (!show_batch_legend) {
    p <- p + guides(shape = "none")
  }

  out_png <- file.path(out_dir, paste0("ELISA_drug_clustering_", cls, "_scheme1_log10conc_vs_log2FC.png"))
  out_pdf <- file.path(out_dir, paste0("ELISA_drug_clustering_", cls, "_scheme1_log10conc_vs_log2FC.pdf"))

  max_w_mm <- as.numeric(style$page_layout$max_width_mm %||% 173)
  w_in <- max_w_mm / mm_per_inch
  h_in <- 65 / mm_per_inch
  ggsave(out_png, p, width = w_in, height = h_in, dpi = 300)
  ggsave(out_pdf, p, width = w_in, height = h_in)

  message("完成输出：")
  message(" - ", out_png)
  message(" - ", out_pdf)
  message("用于作图的行数（", cls, "）：", nrow(dsub))
}

message("读取 sheet：", sheet_to_read)
message("总行数（过滤后）：", nrow(df2))