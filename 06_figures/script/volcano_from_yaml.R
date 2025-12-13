#!/usr/bin/env Rscript
suppressPackageStartupMessages({
  library(yaml)
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(stringr)
})

`%||%` <- function(a, b) if (!is.null(a)) a else b

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript volcano_from_yaml.R <yaml>")
cfg <- yaml::read_yaml(args[[1]])

# --- layout helpers ---
pt_to_mm <- function(pt) pt * 0.352777778
mm_safe <- function(x, default = NA_real_) {
  if (is.null(x)) return(default)
  as.numeric(x)
}

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
line_w <- style_cfg$lines$line_width_pt %||% axis_w

# style-driven default layout (pt)
style_axis_title_margin_x_pt <- style_cfg$layout$axis_title_margin_pt$x %||% 0
style_axis_title_margin_y_pt <- style_cfg$layout$axis_title_margin_pt$y %||% 0
style_plot_margin_pt <- style_cfg$layout$plot_margin_pt %||% list(top=0, right=0, bottom=0, left=0)

# reuse WT/HO palette for highlight
wt_ho_cols <- style_cfg$colors$wt_ho %||% list(WT="#F08A4B", HO="#4DB6AC")
col_bg <- "grey70"
col_hl <- wt_ho_cols$HO %||% "#4DB6AC"

# IO (absolute path supported)
src <- cfg$source_csv
if (!file.exists(src)) src <- file.path(root, cfg$source_csv)
if (!file.exists(src)) stop("Source CSV not found: ", src)

out_pdf <- file.path(root, cfg$out_pdf)
dir.create(dirname(out_pdf), recursive = TRUE, showWarnings = FALSE)

# columns
cn <- cfg$columns$name
cc <- cfg$columns$class
cx <- cfg$columns$log2fc

# y can be provided explicitly (e.g., neglog10padj), otherwise we will infer/compute it
cy <- cfg$columns$y %||% NULL
cp <- cfg$columns$p %||% "p_value"
cpadj <- cfg$columns$padj %||% "padj"

df <- readr::read_csv(src, show_col_types = FALSE)

need <- c(cn, cx)
if (!is.null(cy)) need <- c(need, cy)
miss <- setdiff(need, names(df))
if (length(miss) > 0) stop("Missing columns in volcano csv: ", paste(miss, collapse = ", "))

df <- df %>%
  transmute(
    name = .data[[cn]],
    class = if (!is.null(cc) && cc %in% names(df)) .data[[cc]] else NA_character_,
    log2FC = as.numeric(.data[[cx]]),
    p = if (!is.null(cp) && cp %in% names(df)) as.numeric(.data[[cp]]) else NA_real_,
    padj = if (!is.null(cpadj) && cpadj %in% names(df)) as.numeric(.data[[cpadj]]) else NA_real_,
    y_raw = if (!is.null(cy) && cy %in% names(df)) as.numeric(.data[[cy]]) else NA_real_
  )

# thresholds (need these before y inference)
p_cut <- cfg$thresholds$p_cutoff %||% 0.05
lfc_cut <- cfg$thresholds$log2fc_cutoff %||% 1.0
use_padj <- isTRUE(cfg$thresholds$use_padj)

# infer/compute y
# Priority:
# 1) y_raw if provided in YAML
# 2) -log10(padj) if use_padj and padj available
# 3) -log10(p) if p available
# 4) fallback to NA

df <- df %>%
  mutate(
    y = dplyr::case_when(
      is.finite(y_raw) ~ y_raw,
      use_padj & is.finite(padj) ~ -log10(padj),
      is.finite(p) ~ -log10(p),
      TRUE ~ NA_real_
    )
  ) %>%
  select(-y_raw) %>%
  filter(is.finite(log2FC), is.finite(y))

# y threshold line
# (for FDR, still draw at -log10(p_cutoff) as a conventional reference)
y_cut <- -log10(p_cut)

# highlight
hl_class <- cfg$highlight$class_equals %||% "CL"
df <- df %>% mutate(is_hl = (!is.na(class) & class == hl_class))

# ---- figure size (prefer cfg$size) ----
fig_w_mm <- mm_safe(cfg$size$width_mm, default = mm_safe(cfg$plot$width_mm, default = 173))
fig_h_mm <- mm_safe(cfg$size$high_mm,  default = mm_safe(cfg$plot$height_mm, default = 90))

# ---- margins from axis_outer_frac (fractions of figure size) ----
outer <- cfg$layout$axis_outer_frac
if (!is.null(outer)) {
  m_left_mm   <- (outer$left   %||% 0) * fig_w_mm
  m_right_mm  <- (outer$right  %||% 0) * fig_w_mm
  m_top_mm    <- (outer$top    %||% 0) * fig_h_mm
  m_bottom_mm <- (outer$bottom %||% 0) * fig_h_mm
} else {
  m_left_mm <- m_right_mm <- m_top_mm <- m_bottom_mm <- NA_real_
}

# ---- axis gaps from axis_gap_pt (fallback to style yaml) ----
gap <- cfg$layout$axis_gap_pt
x_title_to_ticks_pt <- if (!is.null(gap)) gap$x_title_to_ticks %||% style_axis_title_margin_x_pt else style_axis_title_margin_x_pt
x_ticks_to_axis_pt  <- if (!is.null(gap)) gap$x_ticks_to_axis  %||% 0 else 0
y_title_to_ticks_pt <- if (!is.null(gap)) gap$y_title_to_ticks %||% style_axis_title_margin_y_pt else style_axis_title_margin_y_pt
y_ticks_to_axis_pt  <- if (!is.null(gap)) gap$y_ticks_to_axis  %||% 0 else 0

p <- ggplot(df, aes(x = log2FC, y = y)) +
  geom_point(data = df %>% filter(!is_hl),
             aes(x = log2FC, y = y),
             size = cfg$plot$point_size %||% 1.2,
             alpha = cfg$plot$alpha %||% 0.75,
             color = col_bg) +
  geom_point(data = df %>% filter(is_hl),
             aes(x = log2FC, y = y),
             size = (cfg$plot$point_size %||% 1.2) + 0.2,
             alpha = 0.95,
             color = col_hl) +
  geom_vline(xintercept = c(-lfc_cut, lfc_cut), linewidth = line_w, linetype = "dashed") +
  geom_hline(yintercept = y_cut, linewidth = line_w, linetype = "dashed") +
  labs(
    x = cfg$plot$x_label %||% "log2FC",
    y = cfg$plot$y_label %||% "-log10(p)"
  ) +
  scale_x_continuous(limits = c(-5, 5)) +
  scale_y_continuous(limits = c(0, 0.8)) +
  # base_family explicitly set from figure_style_nature.yaml (typography.font_family_primary)
  theme_classic(base_family = font_family) +
  theme(
    axis.text = element_text(size = sizes$axis_tick_default %||% 5.5, color = "black"),
    axis.title = element_text(size = sizes$axis_label_default %||% 6.5, color = "black"),
    axis.title.x = element_text(margin = margin(t = x_title_to_ticks_pt, unit = "pt")),
    axis.title.y = element_text(margin = margin(r = y_title_to_ticks_pt, unit = "pt")),
    axis.text.x  = element_text(margin = margin(t = x_ticks_to_axis_pt, unit = "pt")),
    axis.text.y  = element_text(margin = margin(r = y_ticks_to_axis_pt, unit = "pt")),
    axis.line = element_line(linewidth = axis_w),
    plot.margin = if (!is.na(m_left_mm)) {
      unit(c(m_top_mm, m_right_mm, m_bottom_mm, m_left_mm), "mm")
    } else {
      margin(
        t = style_plot_margin_pt$top %||% 0,
        r = style_plot_margin_pt$right %||% 0,
        b = style_plot_margin_pt$bottom %||% 0,
        l = style_plot_margin_pt$left %||% 0,
        unit = "pt"
      )
    }
  )

ggsave(out_pdf, p, width = fig_w_mm, height = fig_h_mm, units = "mm", device = cairo_pdf)
message("[INFO] Saved: ", out_pdf)