#!/usr/bin/env Rscript
suppressPackageStartupMessages({
  library(yaml)
  library(readr)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
  library(stringr)
})

`%||%` <- function(a, b) if (!is.null(a)) a else b

args <- commandArgs(trailingOnly = TRUE)
yaml_path <- if (length(args) >= 1) args[[1]] else "06_figures/script/figure_4_c_class_stack.yaml"
cfg <- yaml::read_yaml(yaml_path)

# find project root (expects 02_protocols under root)
project_root <- function() {
  wd <- normalizePath(getwd())
  p <- wd
  for (i in 1:12) {
    if (dir.exists(file.path(p, "02_protocols"))) return(p)
    p2 <- dirname(p)
    if (p2 == p) break
    p <- p2
  }
  wd
}
root <- project_root()

# style
style_cfg <- yaml::read_yaml(file.path(root, cfg$style_yaml))
font_family <- style_cfg$typography$font_family_primary %||% "Helvetica"
sizes <- style_cfg$typography$sizes_pt %||% list(axis_tick_default=5.5, axis_label_default=6.5, legend_text_default=6, legend_title_default=6.5, title_optional=7)
axis_w <- style_cfg$lines$axis_line_default_pt %||% 0.25

wt_ho_cols <- style_cfg$colors$wt_ho %||% list(WT="#F08A4B", HO="#4DB6AC")
col_wt <- wt_ho_cols$WT %||% "#F08A4B"
col_ho <- wt_ho_cols$HO %||% "#4DB6AC"

# IO
src <- cfg$source_csv
if (!file.exists(src)) {
  # fall back to project-root-relative path
  src <- file.path(root, cfg$source_csv)
}
if (!file.exists(src)) stop("Source CSV not found: ", src)

out_pdf <- file.path(root, cfg$out_pdf)
dir.create(dirname(out_pdf), recursive = TRUE, showWarnings = FALSE)

# read stats table
df <- readr::read_csv(src, show_col_types = FALSE)

# column mapping
cx <- cfg$columns$x
c_m_wt <- cfg$columns$mean_wt
c_sd_wt <- cfg$columns$sd_wt
c_m_ho <- cfg$columns$mean_ho
c_sd_ho <- cfg$columns$sd_ho
c_p <- cfg$columns$p

need_cols <- c(cx, c_m_wt, c_sd_wt, c_m_ho, c_sd_ho)
missing <- setdiff(need_cols, names(df))
if (length(missing) > 0) stop("Missing columns in stats csv: ", paste(missing, collapse = ", "))

# optional: pick top_n by total mean
top_n <- cfg$plot$top_n %||% 0
if (!is.null(top_n) && top_n > 0) {
  df <- df %>%
    mutate(total_mean = .data[[c_m_wt]] + .data[[c_m_ho]]) %>%
    arrange(desc(total_mean)) %>%
    slice_head(n = top_n)
}

# long format for plotting
long <- df %>%
  transmute(
    lipidName = .data[[cx]],
    mean_WT = .data[[c_m_wt]],
    sd_WT   = .data[[c_sd_wt]],
    mean_HO = .data[[c_m_ho]],
    sd_HO   = .data[[c_sd_ho]],
    p_value = if (c_p %in% names(df)) .data[[c_p]] else NA_real_
  ) %>%
  pivot_longer(
    cols = c(mean_WT, mean_HO),
    names_to = "group",
    values_to = "mean"
  ) %>%
  mutate(
    group = ifelse(group == "mean_WT", "WT", "HO"),
    sd = ifelse(group == "WT", sd_WT, sd_HO),
    ymin = mean - sd,
    ymax = mean + sd
  )

# order x by total mean (stable)
x_levels <- df %>%
  mutate(total_mean = .data[[c_m_wt]] + .data[[c_m_ho]]) %>%
  arrange(desc(total_mean)) %>%
  pull(.data[[cx]])
long$lipidName <- factor(long$lipidName, levels = x_levels)
long$group <- factor(long$group, levels = c("WT", "HO"))

# p-value to stars (optional)
p_to_star <- function(p) {
  if (is.na(p)) return("")
  if (p < 0.0001) return("****")
  if (p < 0.001)  return("***")
  if (p < 0.01)   return("**")
  if (p < 0.05)   return("*")
  "ns"
}

show_p <- isTRUE(cfg$plot$show_p_stars)
anno <- NULL
if (show_p && "p_value" %in% names(long)) {
  anno <- df %>%
    transmute(
      lipidName = .data[[cx]],
      p_value = if (c_p %in% names(df)) .data[[c_p]] else NA_real_
    ) %>%
    mutate(
      label = vapply(p_value, p_to_star, character(1))
    )

  # y position = max(mean+sd) per lipidName
  y_pos <- long %>%
    group_by(lipidName) %>%
    summarise(y = max(ymax, na.rm = TRUE), .groups = "drop") %>%
    mutate(y = y + 0.05 * (max(y, na.rm = TRUE) - min(y, na.rm = TRUE) + 1e-6))

  anno <- anno %>%
    left_join(y_pos, by = "lipidName") %>%
    mutate(lipidName = factor(lipidName, levels = x_levels))
}

# plot
p <- ggplot(long, aes(x = lipidName, y = mean, fill = group)) +
  geom_col(position = position_dodge(width = 0.8), width = 0.7, color = NA) +
  geom_errorbar(
    aes(ymin = ymin, ymax = ymax),
    position = position_dodge(width = 0.8),
    width = 0.25,
    linewidth = axis_w
  ) +
  scale_fill_manual(values = c("WT" = col_wt, "HO" = col_ho)) +
  labs(
    title = cfg$title %||% "",
    x = "",
    y = cfg$plot$y_label %||% "Intensity (a.u.)",
    fill = "Group"
  ) +
  theme_classic(base_family = font_family) +
  theme(
    plot.title = element_text(size = sizes$title_optional %||% 7),
    axis.text = element_text(size = sizes$axis_tick_default %||% 5.5, color = "black"),
    axis.title = element_text(size = sizes$axis_label_default %||% 6.5, color = "black"),
    axis.text.x = element_text(angle = cfg$plot$x_tick_rotation %||% 45, hjust = 1, vjust = 1),
    legend.text = element_text(size = sizes$legend_text_default %||% 6),
    legend.title = element_text(size = sizes$legend_title_default %||% 6.5),
    axis.line = element_line(linewidth = axis_w)
  )

if (!is.null(anno)) {
  p <- p + geom_text(
    data = anno,
    aes(x = lipidName, y = y, label = label),
    inherit.aes = FALSE,
    size = (sizes$legend_text_default %||% 6) / 2.845,
    family = font_family
  )
}

# export
w_mm <- cfg$plot$width_mm %||% 173
h_mm <- cfg$plot$height_mm %||% 70
ggsave(out_pdf, p, width = w_mm, height = h_mm, units = "mm", device = cairo_pdf)
message("[INFO] Saved: ", out_pdf)