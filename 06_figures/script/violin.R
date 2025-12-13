#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
  library(readxl)
  library(dplyr)
  library(ggplot2)
  library(rlang)
  library(grid)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript violin.R <panel_yaml>")

panel_yaml_path <- args[1]
panel_cfg <- yaml::read_yaml(panel_yaml_path)

project_root <- normalizePath(file.path(dirname(panel_yaml_path), "..", ".."))

# style
style_yaml_path <- file.path(project_root, "02_protocols/figure_style_nature.yaml")
style_cfg <- yaml::read_yaml(style_yaml_path)

# extract typography, line, and layout defaults from style yaml
typography   <- style_cfg$typography
sizes_pt     <- typography$sizes_pt
font_family  <- typography$font_family_primary %||% "Helvetica"

line_cfg     <- style_cfg$lines
layout_style <- style_cfg$layout

# fallbacks for sizes
axis_label_size   <- sizes_pt$axis_label_default   %||% 6.5
axis_tick_size    <- sizes_pt$axis_tick_default    %||% 5.5
legend_text_size  <- sizes_pt$legend_text_default  %||% axis_tick_size
legend_title_size <- sizes_pt$legend_title_default %||% axis_label_size

axis_title_margin_cfg <- layout_style$axis_title_margin_pt
style_plot_margin     <- layout_style$plot_margin_pt

# ---- Layout helpers ----
mm_per_inch <- 25.4
mm_to_pt <- function(mm) (72/mm_per_inch) * mm

layout_cfg <- panel_cfg$layout
outer_frac <- layout_cfg$axis_outer_frac
gap_pt     <- layout_cfg$axis_gap_pt

width_mm  <- panel_cfg$size$width_mm
height_mm <- panel_cfg$size$high_mm

# style-level plot margins in pt
style_margin_top    <- style_plot_margin$top    %||% 0
style_margin_bottom <- style_plot_margin$bottom %||% 0
style_margin_left   <- style_plot_margin$left   %||% 0
style_margin_right  <- style_plot_margin$right  %||% 0

# combine style margins with panel outer_frac-based margins
plot_margin_pt <- list(
  top    = style_margin_top    + mm_to_pt((outer_frac$top    %||% 0) * height_mm),
  bottom = style_margin_bottom + mm_to_pt((outer_frac$bottom %||% 0) * height_mm),
  left   = style_margin_left   + mm_to_pt((outer_frac$left   %||% 0) * width_mm),
  right  = style_margin_right  + mm_to_pt((outer_frac$right  %||% 0) * width_mm)
)

# p to symbol
p_to_symbol <- function(p){
  if (is.na(p)) return("ns")
  if (p < 0.0001) return("****")
  if (p < 0.001) return("***")
  if (p < 0.01) return("**")
  if (p < 0.05) return("*")
  "ns"
}

# --- Iterate panels ---
for (panel in panel_cfg$panels){

  message("[INFO] Plotting panel ", panel$id)

  df <- read_excel(file.path(project_root, panel$data), sheet = panel$sheet)

  x_var <- panel$mapping$x
  y_var <- panel$mapping$y
  hue_var <- panel$mapping$hue

  df <- df %>%
    filter(!is.na(.data[[x_var]])) %>%
    mutate(
      !!sym(x_var) := factor(.data[[x_var]], levels = panel$order),
      !!sym(hue_var) := factor(.data[[hue_var]], levels = panel$hue_order),
      x_pos = as.numeric(.data[[x_var]])
    )

  # --- stats ---
  stats_df <- NULL
  if (panel$stats$enabled){
    stats_raw <- read_excel(
      file.path(project_root, panel$stats$source),
      sheet = panel$stats$sheet
    )

    p_val <- stats_raw[[panel$stats$column]][1]

    stats_df <- tibble(
      x_center = 1.5,
      y        = max(df[[y_var]], na.rm = TRUE) * 1.08,
      label    = p_to_symbol(p_val)
    )
  }

  fill_pal <- style_cfg$colors$wt_ho[panel$hue_order]

  p <- ggplot(df, aes(x = x_pos, y = .data[[y_var]], fill = .data[[hue_var]])) +
    geom_violin(trim=FALSE, alpha=0.85) +
    geom_jitter(aes(color=.data[[hue_var]]),
                width=0.1, size=1.2, alpha=0.85) +
    scale_fill_manual(values = fill_pal) +
    scale_color_manual(values = fill_pal) +
    scale_x_continuous(
      breaks = seq_along(panel$order),
      labels = panel$rename_x
    ) +
    labs(x = panel$x_label, y = panel$y_label) +
    theme_classic() +
    theme(
      text = element_text(family = font_family),
      axis.title.x = element_text(
        size  = axis_label_size,
        margin = margin(t = (axis_title_margin_cfg$x %||% 0) + (gap_pt$x_title_to_ticks %||% 0))
      ),
      axis.title.y = element_text(
        size  = axis_label_size,
        margin = margin(r = (axis_title_margin_cfg$y %||% 0) + (gap_pt$y_title_to_ticks %||% 0))
      ),
      axis.text.x = element_text(
        size  = axis_tick_size,
        margin = margin(t = gap_pt$x_ticks_to_axis %||% 0)
      ),
      axis.text.y = element_text(
        size  = axis_tick_size,
        margin = margin(r = gap_pt$y_ticks_to_axis %||% 0)
      ),
      axis.line = element_line(linewidth = (line_cfg$axis_line_default_pt %||% 0.25)),
      axis.ticks = element_line(linewidth = (line_cfg$axis_line_default_pt %||% 0.25)),
      legend.text  = element_text(size = legend_text_size),
      legend.title = element_text(size = legend_title_size),
      plot.margin = margin(
        plot_margin_pt$top,
        plot_margin_pt$right,
        plot_margin_pt$bottom,
        plot_margin_pt$left
      )
    )

if (!is.null(stats_df)){
  p <- p + geom_text(
    data = stats_df,
    inherit.aes = FALSE,
    aes(x = x_center, y = y, label = label),
    size = 3,
    color = "black"
  )
}

  out_dir <- file.path(project_root, "06_figures/figure_4")
  if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

  out_file <- file.path(out_dir, paste0(panel_cfg$out, "_", panel$id, ".pdf"))

  ggsave(out_file, p,
         width = panel_cfg$size$width_mm/mm_per_inch,
         height = panel_cfg$size$high_mm/mm_per_inch)

  message("[INFO] Saved: ", out_file)
}