#!/usr/bin/env Rscript
suppressPackageStartupMessages({
  library(yaml)
  library(ggplot2)
  library(dplyr)
  library(tidyr)
  library(readr)
  library(stringr)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript box_species_from_yaml.R <panel_yaml>")

panel_yaml <- args[[1]]
cfg <- yaml::read_yaml(panel_yaml)

# ---- helpers ----
project_root <- function() {
  # 从当前工作目录向上找一个包含 02_protocols 的目录
  wd <- normalizePath(getwd())
  p <- wd
  for (i in 1:10) {
    if (dir.exists(file.path(p, "02_protocols"))) return(p)
    p2 <- dirname(p)
    if (p2 == p) break
    p <- p2
  }
  return(wd)
}
root <- project_root()

style_path <- file.path(root, cfg$style_yaml)
style_cfg <- yaml::read_yaml(style_path)

# style fields (minimal)
font_family <- style_cfg$typography$font_family_primary %||% "Helvetica"
sizes <- style_cfg$typography$sizes_pt
line_w <- style_cfg$lines$line_width_pt %||% 0.5
axis_w <- style_cfg$lines$axis_line_default_pt %||% 0.25
wt_ho_cols <- style_cfg$colors$wt_ho
col_wt <- wt_ho_cols$WT %||% "#F08A4B"
col_ho <- wt_ho_cols$HO %||% "#4DB6AC"

`%||%` <- function(a, b) if (!is.null(a)) a else b

out_pdf <- file.path(root, cfg$out_pdf)
out_dir <- dirname(out_pdf)
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

# ---- read & clean source csv ----
src <- cfg$source_csv
if (!file.exists(src)) stop("Source CSV not found: ", src)

raw <- readr::read_csv(src, show_col_types = FALSE)

# 去掉第一行“Group”（这行会把样本列变成字符，必须去掉）
if ("lipidName" %in% names(raw)) {
  raw <- raw %>% filter(!is.na(.data$lipidName), .data$lipidName != "Group")
}

# 样本列识别
sample_regex <- cfg$columns$sample_regex
sample_cols <- names(raw)[str_detect(names(raw), sample_regex)]
if (length(sample_cols) == 0) stop("No sample columns matched regex: ", sample_regex)

# 转 numeric（防止有字符残留）
raw <- raw %>%
  mutate(across(all_of(sample_cols), ~ suppressWarnings(as.numeric(.x))))

# 是否排除 QC
include_qc <- isTRUE(cfg$include_qc)
if (!include_qc) sample_cols <- sample_cols[!str_detect(sample_cols, "^QC_")]

# 过滤 CL 类
cls_col <- cfg$columns$class
raw_cl <- raw %>% filter(.data[[cls_col]] == cfg$lipid_class)

if (nrow(raw_cl) == 0) stop("No rows found for class == ", cfg$lipid_class)

# 选 top N species（按全样本均值）
name_col <- cfg$columns$lipid_name
top_n <- cfg$top_n_species %||% 8

top_tbl <- raw_cl %>%
  select(all_of(c(name_col, sample_cols))) %>%
  pivot_longer(cols = all_of(sample_cols), names_to = "sample", values_to = "value") %>%
  group_by(.data[[name_col]]) %>%
  summarise(mean_value = mean(value, na.rm = TRUE), .groups = "drop") %>%
  arrange(desc(mean_value)) %>%
  slice_head(n = top_n)

top_species <- top_tbl[[name_col]]

dat <- raw_cl %>%
  filter(.data[[name_col]] %in% top_species) %>%
  select(all_of(c(name_col, sample_cols))) %>%
  pivot_longer(cols = all_of(sample_cols), names_to = "sample", values_to = "value") %>%
  mutate(
    genetype = case_when(
      str_detect(sample, "^WT_") ~ "WT",
      str_detect(sample, "^HO_") ~ "HO",
      TRUE ~ NA_character_
    )
  ) %>%
  filter(!is.na(genetype))

# log10 transform
if (isTRUE(cfg$transform$log10)) {
  pseudo <- cfg$transform$pseudo_count %||% 1.0
  dat <- dat %>% mutate(value = log10(value + pseudo))
}

# 保持 facet 顺序
dat[[name_col]] <- factor(dat[[name_col]], levels = top_species)

# ---- stats: WT vs HO within each species ----
anno <- NULL
if (isTRUE(cfg$stats$enabled)) {
  stat_method <- cfg$stats$method %||% "wilcox"
  p_label <- cfg$stats$p_label %||% "p.format"

  p_df <- dat %>%
    group_by(.data[[name_col]]) %>%
    summarise(
      p_value = {
        x <- value[genetype == "WT"]
        y <- value[genetype == "HO"]
        if (length(na.omit(x)) < 2 || length(na.omit(y)) < 2) NA_real_
        else {
          if (stat_method == "t") t.test(x, y)$p.value else wilcox.test(x, y)$p.value
        }
      },
      y_max = max(value, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    mutate(
      label = if (p_label == "p.format") {
        ifelse(is.na(p_value), "p=NA", paste0("p=", formatC(p_value, format = "f", digits = 3)))
      } else {
        ifelse(is.na(p_value), "NA", as.character(p_value))
      },
      y_pos = y_max + 0.08 * (max(y_max, na.rm = TRUE) - min(y_max, na.rm = TRUE) + 1e-6)
    )
  anno <- p_df
}

# ---- plot ----
p <- ggplot(dat, aes(x = genetype, y = value, fill = genetype)) +
  geom_boxplot(width = 0.6, outlier.shape = NA, alpha = cfg$plot$box_alpha %||% 0.25, linewidth = axis_w) +
  { if (isTRUE(cfg$plot$show_points)) geom_jitter(width = 0.10, size = cfg$plot$point_size %||% 0.9, alpha = 0.85) } +
  facet_wrap(as.formula(paste("~", name_col)), ncol = cfg$plot$facet_ncol %||% 4, scales = "free_y") +
  scale_fill_manual(values = c("WT" = col_wt, "HO" = col_ho)) +
  labs(
    title = cfg$title %||% "",
    x = cfg$plot$x_label %||% "",
    y = cfg$plot$y_label %||% ""
  ) +
  theme_classic(base_family = font_family) +
  theme(
    plot.title = element_text(size = sizes$title_optional %||% 7, face = "plain"),
    axis.text = element_text(size = sizes$axis_tick_default %||% 5.5, color = "black"),
    axis.title = element_text(size = sizes$axis_label_default %||% 6.5, color = "black"),
    strip.text = element_text(size = sizes$legend_text_default %||% 6),
    legend.position = "none",
    axis.line = element_line(linewidth = axis_w),
    panel.spacing = unit(3, "mm")
  )

if (!is.null(anno)) {
  p <- p + geom_text(
    data = anno,
    aes(x = 1.5, y = y_pos, label = label),
    inherit.aes = FALSE,
    size = (sizes$legend_text_default %||% 6) / 2.845,  # pt -> mm-ish
    family = font_family
  )
}

# ---- export ----
w_mm <- cfg$plot$width_mm %||% 173
h_mm <- cfg$plot$height_mm %||% 85
ggsave(out_pdf, p, width = w_mm, height = h_mm, units = "mm", device = cairo_pdf)
message("[INFO] Saved: ", out_pdf)