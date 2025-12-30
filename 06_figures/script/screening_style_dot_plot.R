#!/usr/bin/env Rscript
# ============================================================
# screening-style dot plot.R
# - Reads a YAML config (panel-style schema)
# - Loads Nature-like style yaml: 02_protocols/figure_style_nature.yaml
# - Reads raw screening excel (wide: wt_1..wt_n, ho_1..ho_n)
# - Outputs:
#     (1) long table for dot plot (each dot = one replicate)
#     (2) summary stats table (n/mean/sd/se on normalized values)
#     (3) WT baseline table
#     (4) PDF + PNG in 06_figures/figure_1
# ============================================================

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(tidyr)
  library(stringr)
  library(ggplot2)
  library(yaml)
  library(readr)
})

mm_to_in <- function(mm) mm / 25.4
`%||%` <- function(a, b) {
  if (is.null(a)) return(b)
  if (length(a) == 0) return(b)

  # If atomic vector with length > 1 (e.g., font fallback list), keep it unless all NA
  if (is.atomic(a) && length(a) > 1) {
    if (all(is.na(a))) return(b)
    return(a)
  }

  # Scalar atomic: NA or empty string => fallback
  if (is.atomic(a) && length(a) == 1) {
    if (is.na(a) || a == "") return(b)
  }

  a
}

pt_to_lwd <- function(pt, pt_per_lwd = 0.75) pt / pt_per_lwd

stop2 <- function(...) stop(paste0(...), call. = FALSE)

# ---- main ----
args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop2("Usage: Rscript 'screening-style dot plot.R' <config.yaml>")

config_path <- args[1]
cfg <- yaml::read_yaml(config_path)

if (is.null(cfg$panels) || length(cfg$panels) < 1) stop2("Config must contain panels: [...]")

panel <- cfg$panels[[1]]
if (panel$type != "screening_dotplot") stop2("First panel must have type: screening_dotplot")

# style
style_path <- cfg$style$style_yaml
style <- yaml::read_yaml(style_path)

font_family <- style$typography$font_family_primary %||% "Helvetica"
if (length(font_family) > 1) font_family <- font_family[1]
sizes <- style$typography$sizes_pt %||% list()
colors <- style$colors$wt_ho %||% list(WT="#F08A4B", HO="#4DB6AC")

axis_tick_pt   <- sizes$axis_tick_default  %||% 5.5
axis_label_pt  <- sizes$axis_label_default %||% 6.5
legend_text_pt <- sizes$legend_text_default %||% 6
legend_title_pt<- sizes$legend_title_default %||% 6.5
strip_text_pt  <- axis_tick_pt

line_pt <- style$lines$axis_line_default_pt %||% 0.25
pt_per_lwd <- style$lines$r_lwd_scale$pt_per_lwd %||% 0.75
lwd_axis <- pt_to_lwd(line_pt, pt_per_lwd)

# ---- layout (precedence: panel.layout > cfg.layout > style.layout > default) ----
style_layout  <- style$layout %||% list()
figure_layout <- cfg$layout %||% list()
panel_layout  <- panel$layout %||% list()

# axis_outer_frac (fractions of the whole canvas)
axis_outer_frac <- style_layout$axis_outer_frac %||% list(left = 0.00, right = 0.00, bottom = 0.00, top = 0.00)
if (!is.null(figure_layout$axis_outer_frac)) axis_outer_frac <- modifyList(axis_outer_frac, figure_layout$axis_outer_frac)
if (!is.null(panel_layout$axis_outer_frac))  axis_outer_frac <- modifyList(axis_outer_frac, panel_layout$axis_outer_frac)

# axis_gap_pt (pt)
axis_gap_pt <- style_layout$axis_gap_pt %||% list(x_title_to_ticks = 3, x_ticks_to_axis = 2, y_title_to_ticks = 3, y_ticks_to_axis = 2)
if (!is.null(figure_layout$axis_gap_pt)) axis_gap_pt <- modifyList(axis_gap_pt, figure_layout$axis_gap_pt)
if (!is.null(panel_layout$axis_gap_pt))  axis_gap_pt <- modifyList(axis_gap_pt, panel_layout$axis_gap_pt)

x_title_to_ticks <- axis_gap_pt$x_title_to_ticks %||% 5
x_ticks_to_axis  <- axis_gap_pt$x_ticks_to_axis  %||% 2
y_title_to_ticks <- axis_gap_pt$y_title_to_ticks %||% 5
y_ticks_to_axis  <- axis_gap_pt$y_ticks_to_axis  %||% 2

# i/o
plot_cfg <- panel$plot
p_cfg <- plot_cfg
interim_dir <- plot_cfg$interim_dir %||% "04_data/interim/炎症表型遗传筛选"
figure_dir  <- plot_cfg$figure_dir  %||% "06_figures/figure_1"
stem        <- plot_cfg$stem        %||% "001_genetic_screening_dotplot"

dir.create(interim_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(figure_dir,  recursive = TRUE, showWarnings = FALSE)

# read data
d <- panel$data
xlsx <- d$xlsx
sheet <- d$sheet %||% 1
raw <- readxl::read_excel(xlsx, sheet = sheet)

cols <- d$columns
strain_col <- cols$strain %||% "name"
treat_col  <- cols$treatment %||% "treatment"
conc_col   <- cols$concentration %||% "concentration"

req_cols <- c(strain_col, treat_col, conc_col)
missing <- setdiff(req_cols, colnames(raw))
if (length(missing) > 0) stop2("Missing required columns in xlsx: ", paste(missing, collapse = ", "))

# filter keep conditions
keep <- d$keep_conditions %||% NULL
if (!is.null(keep) && length(keep) > 0) {
  keep_df <- bind_rows(lapply(keep, as.data.frame))
  # ensure types consistent
  keep_df[[conc_col]] <- as.numeric(keep_df[[conc_col]])
  raw[[conc_col]] <- as.numeric(raw[[conc_col]])
  raw <- raw %>% inner_join(keep_df, by = setNames(c("treatment","concentration"), c(treat_col, conc_col)))
}

# replicate columns
rep_cols <- d$replicate_columns
wt_prefix <- rep_cols$wt_prefix %||% "wt_"
ho_prefix <- rep_cols$ho_prefix %||% "ho_"

# collect replicate columns dynamically
rep_pat <- paste0("^(", stringr::str_replace_all(wt_prefix, "([\\^\\$\\(\\)\\[\\]\\{\\}\\.\\+\\*\\?\\|\\\\])","\\\\\\1"),
                  "|",
                  stringr::str_replace_all(ho_prefix, "([\\^\\$\\(\\)\\[\\]\\{\\}\\.\\+\\*\\?\\|\\\\])","\\\\\\1"),
                  ")(\\d+)$")

long <- raw %>%
  pivot_longer(
    cols = matches(rep_pat),
    names_to = c("geno_prefix","replicate"),
    names_pattern = rep_pat,
    values_to = "value_raw",
    values_drop_na = TRUE
  ) %>%
  mutate(
    genotype = case_when(
      geno_prefix == wt_prefix ~ "WT",
      geno_prefix == ho_prefix ~ "HO",
      TRUE ~ NA_character_
    ),
    replicate = as.integer(replicate)
  ) %>%
  filter(!is.na(genotype)) %>%
  rename(
    strain = !!strain_col,
    treatment = !!treat_col,
    concentration = !!conc_col
  )

# analyte label (optional)
if (!is.null(d$analyte_map)) {
  amap <- d$analyte_map
  long$analyte <- unname(amap[long$treatment])
} else {
  long$analyte <- NA_character_
}

# condition label
unit_map <- d$concentration_unit %||% list()
get_unit <- function(trt) {
  u <- unit_map[[trt]]
  if (is.null(u)) "" else u
}
long <- long %>%
  mutate(
    unit = vapply(treatment, get_unit, FUN.VALUE = character(1)),
    treatment_upper = str_to_upper(treatment),
    condition = ifelse(unit == "",
                       paste0(treatment_upper, " ", concentration),
                       paste0(treatment_upper, " ", concentration, " ", unit))
  )

# WT baseline per (strain, condition)
wt_base <- long %>%
  filter(genotype == "WT") %>%
  group_by(strain, treatment, concentration, condition, analyte) %>%
  summarise(wt_mean = mean(value_raw, na.rm = TRUE),
            wt_sd = sd(value_raw, na.rm = TRUE),
            wt_n = n(),
            .groups = "drop")

# normalization
norm_method <- panel$normalization$method %||% "within_strain_by_wt_mean"
if (norm_method != "within_strain_by_wt_mean") stop2("Unsupported normalization.method: ", norm_method)

long_n <- long %>%
  left_join(wt_base %>% select(strain, treatment, concentration, wt_mean),
            by = c("strain","treatment","concentration")) %>%
  mutate(value_norm = value_raw / wt_mean)

# ---- significance: HO vs WT (unpaired two-sided t-test) per strain × condition ----
# Optional controls from YAML:
# panel$plot$significance$show: TRUE/FALSE (default TRUE)
# panel$plot$significance$label: "star" or "p" (default "star")
# panel$plot$significance$adjust_method: e.g., "BH" (default NULL)
# panel$plot$significance$y_offset: numeric offset added to max(y) (default 0.08)
sig_cfg <- p_cfg$significance %||% list()
sig_show <- sig_cfg$show %||% TRUE
sig_label_mode <- sig_cfg$label %||% "star"
sig_adjust <- sig_cfg$adjust_method %||% NULL
sig_y_offset <- sig_cfg$y_offset %||% 0.08

p_to_star <- function(p) {
  if (is.na(p)) return(NA_character_)
  if (p < 0.001) return("***")
  if (p < 0.01)  return("**")
  if (p < 0.05)  return("*")
  return("ns")
}

ttest_tbl <- long_n %>%
  group_by(strain, analyte, treatment, concentration, condition) %>%
  summarise(
    wt_n = sum(genotype == "WT"),
    ho_n = sum(genotype == "HO"),
    t_stat = tryCatch(stats::t.test(value_raw ~ genotype)$statistic[[1]], error = function(e) NA_real_),
    df     = tryCatch(stats::t.test(value_raw ~ genotype)$parameter[[1]], error = function(e) NA_real_),
    p_value = tryCatch(stats::t.test(value_raw ~ genotype)$p.value, error = function(e) NA_real_),
    .groups = "drop"
  )

# Optional multiple-testing adjustment across all strain×condition tests in this panel
if (!is.null(sig_adjust) && is.character(sig_adjust) && length(sig_adjust) == 1 && sig_adjust != "") {
  ttest_tbl <- ttest_tbl %>%
    mutate(p_adj = p.adjust(p_value, method = sig_adjust))
  p_for_star <- ttest_tbl$p_adj
} else {
  ttest_tbl <- ttest_tbl %>% mutate(p_adj = NA_real_)
  p_for_star <- ttest_tbl$p_value
}

ttest_tbl <- ttest_tbl %>%
  mutate(
    p_star = vapply(p_for_star, p_to_star, FUN.VALUE = character(1))
  )

# summary stats
sum_stats <- long_n %>%
  group_by(strain, analyte, treatment, concentration, condition, genotype) %>%
  summarise(
    n = n(),
    mean_norm = mean(value_norm, na.rm = TRUE),
    sd_norm   = sd(value_norm, na.rm = TRUE),
    se_norm   = sd_norm / sqrt(n),
    .groups = "drop"
  )

# write tables
readr::write_tsv(long_n, file.path(interim_dir, paste0(stem, "_long_for_dotplot.tsv")))
readr::write_tsv(sum_stats, file.path(interim_dir, paste0(stem, "_summary_stats.tsv")))
readr::write_tsv(wt_base, file.path(interim_dir, paste0(stem, "_wt_baseline.tsv")))
readr::write_tsv(ttest_tbl, file.path(interim_dir, paste0(stem, "_ttest_ho_vs_wt.tsv")))

# ---- plot ----
p_cfg <- panel$plot
facet_nrow <- p_cfg$facet$nrow %||% 2

show_genos <- p_cfg$show_genotypes %||% c("WT","HO")
long_p <- long_n %>% filter(genotype %in% show_genos)
long_p <- long_p %>% mutate(genotype = factor(genotype, levels = c("WT","HO")))
# strain order
order_mode <- p_cfg$x$order %||% "as_in_file"
if (order_mode == "as_in_file") {
  strain_levels <- unique(long_p$strain)
} else if (order_mode == "by_HO_mean") {
  strain_levels <- long_p %>%
    filter(genotype == "HO") %>%
    group_by(strain) %>%
    summarise(m = mean(value_norm, na.rm = TRUE), .groups = "drop") %>%
    arrange(m) %>%
    pull(strain)
} else {
  strain_levels <- unique(long_p$strain)
}
long_p <- long_p %>% mutate(strain = factor(strain, levels = strain_levels))
long_p <- long_p %>% mutate(x_pos = as.numeric(strain))

# condition order as in file
cond_levels <- unique(long_p$condition)
long_p <- long_p %>% mutate(condition = factor(condition, levels = cond_levels))

# aesthetics
a <- p_cfg$aesthetics %||% list()
point_alpha <- a$point_alpha %||% 0.85
point_size  <- a$point_size %||% 1.2
jitter_width <- a$jitter_width %||% 0.18
mean_marker <- a$mean_marker %||% "dash"

mean_shape <- if (mean_marker == "point") 18 else 95
mean_size  <- if (mean_marker == "point") 1.8 else 4.0

# axis options
x_rotate <- p_cfg$x$rotate_deg %||% 45
x_hjust  <- p_cfg$x$hjust %||% 1

y_cfg <- p_cfg$y %||% list()
y_label <- y_cfg$label %||% "Normalized IL-1β release (WT mean = 1)"
y_limits <- y_cfg$limits %||% list(0, NULL)
y_lower <- y_limits[[1]]
y_upper <- y_limits[[2]]
if (is.null(y_lower)) y_lower <- NA_real_
if (is.null(y_upper)) y_upper <- NA_real_

# annotation data for significance (bracket + stars, boxplot-like)
ann_df <- NULL
if (isTRUE(sig_show)) {

  # y-span per facet for stable offsets
  y_span_df <- long_p %>%
    group_by(condition) %>%
    summarise(
      y_min = min(value_norm, na.rm = TRUE),
      y_max_all = max(value_norm, na.rm = TRUE),
      y_span = y_max_all - y_min,
      .groups = "drop"
    ) %>%
    mutate(y_span = ifelse(!is.finite(y_span) | y_span == 0, 1, y_span))

  # use normalized values for y positioning; p-values from ttest_tbl (computed on raw)
  y_max_df <- long_p %>%
    group_by(strain, condition) %>%
    summarise(y_max = max(value_norm, na.rm = TRUE), .groups = "drop") %>%
    mutate(x_pos = as.numeric(strain))

  ann_df <- ttest_tbl %>%
    left_join(y_max_df, by = c("strain", "condition")) %>%
    left_join(y_span_df %>% select(condition, y_span), by = "condition") %>%
    mutate(
      label = dplyr::case_when(
        sig_label_mode == "p" ~ ifelse(is.na(p_value), NA_character_, formatC(p_value, format = "e", digits = 2)),
        TRUE ~ p_star
      ),
      label = ifelse(is.na(label), "", label),

      # bracket geometry (similar to boxplot script)
      x_center = x_pos,
      x_min = x_pos - 0.25,
      x_max = x_pos + 0.25,
      y_bracket = y_max + sig_y_offset,
      tick = 0.02 * y_span,
      y_tick = y_bracket - tick,
      y_label = y_bracket + 0.03 * y_span
    )
}

p <- ggplot(long_p, aes(x = x_pos, y = value_norm, color = genotype)) +
  geom_hline(yintercept = 1, linewidth = 0.2, linetype = "dashed") +
  geom_point(
    position = position_jitterdodge(jitter.width = 0.05, dodge.width = 0.6),
    alpha = point_alpha,
    size = point_size
  ) +
  stat_summary(
    fun = mean,
    geom = "point",
    shape = mean_shape,
    size = mean_size,
    position = position_dodge(width = 0.6),
    alpha = 0.9
  ) +
  {if (!is.null(ann_df)) geom_segment(data = ann_df, aes(x = x_min, xend = x_max, y = y_bracket, yend = y_bracket),
                                      inherit.aes = FALSE, linewidth = 0.25, color = "black") } +
  {if (!is.null(ann_df)) geom_segment(data = ann_df, aes(x = x_min, xend = x_min, y = y_bracket, yend = y_tick),
                                      inherit.aes = FALSE, linewidth = 0.25, color = "black") } +
  {if (!is.null(ann_df)) geom_segment(data = ann_df, aes(x = x_max, xend = x_max, y = y_bracket, yend = y_tick),
                                      inherit.aes = FALSE, linewidth = 0.25, color = "black") } +
  {if (!is.null(ann_df)) geom_text(data = ann_df, aes(x = x_center, y = y_label, label = label),
                                   inherit.aes = FALSE, family = font_family, size = 2.6, vjust = 0, color = "black") } +
  facet_wrap(~ condition, nrow = facet_nrow, scales = "fixed") +
  scale_x_continuous(breaks = seq_along(strain_levels), labels = strain_levels) +
  theme(panel.spacing = unit(2, "pt")) +
  scale_color_manual(
    values = c(WT = colors$WT %||% "#F08A4B", HO = colors$HO %||% "#4DB6AC"),
    breaks = c("WT","HO"),
    limits = c("WT","HO")
  ) +
  labs(x = NULL, y = y_label, color = NULL) +
  coord_cartesian(ylim = c(y_lower, y_upper)) +
  theme_classic(base_family = font_family) +
  theme(
    axis.text.x = element_text(
      size = axis_tick_pt,
      angle = x_rotate,
      hjust = x_hjust,
      vjust = 1,
      margin = margin(t = x_ticks_to_axis, unit = "pt")
    ),
    axis.text.y = element_text(
      size = axis_tick_pt,
      margin = margin(r = y_ticks_to_axis, unit = "pt")
    ),
    axis.title.x = element_text(
      size = axis_label_pt,
      margin = margin(t = x_title_to_ticks, unit = "pt")
    ),
    axis.title.y = element_text(
      size = axis_label_pt,
      margin = margin(r = y_title_to_ticks, unit = "pt")
    ),

    axis.line = element_line(linewidth = lwd_axis),
    axis.ticks = element_line(linewidth = lwd_axis),
    axis.ticks.length = unit(2, "pt"),

    plot.title = element_blank(),

    legend.position      = c(0.02, 0.98),
    legend.justification = c(0, 1),
    legend.direction     = "vertical",
    legend.background    = element_rect(fill = "white", colour = NA),
    legend.key           = element_blank(),
    legend.key.size      = unit(3, "mm"),
    legend.title         = element_blank(),
    legend.text          = element_text(size = legend_text_pt),

    strip.text = element_blank(),
    strip.background = element_blank(),

    panel.grid = element_blank(),

    plot.margin = {
      mm_per_inch <- 25.4
      w_mm <- cfg$size$width_mm %||% 173
      h_mm <- cfg$size$height_mm %||% 95
      mm_to_pt <- function(mm) (72 / mm_per_inch) * mm
      top_pt    <- mm_to_pt((axis_outer_frac$top    %||% 0) * h_mm)
      right_pt  <- mm_to_pt((axis_outer_frac$right  %||% 0) * w_mm)
      bottom_pt <- mm_to_pt((axis_outer_frac$bottom %||% 0) * h_mm)
      left_pt   <- mm_to_pt((axis_outer_frac$left   %||% 0) * w_mm)
      margin(top_pt, right_pt, bottom_pt, left_pt, unit = "pt")
    }
  )

# output
w_mm <- cfg$size$width_mm %||% 173
h_mm <- cfg$size$height_mm %||% 95
out_pdf <- file.path(figure_dir, paste0(stem, ".pdf"))
out_png <- file.path(figure_dir, paste0(stem, ".png"))

grDevices::cairo_pdf(out_pdf, width = mm_to_in(w_mm), height = mm_to_in(h_mm), family = font_family)
print(p)
dev.off()

ggsave(out_png, plot = p, width = mm_to_in(w_mm), height = mm_to_in(h_mm), dpi = 600, bg = "white")

message("Done.\nPDF: ", out_pdf, "\nPNG: ", out_png,
        "\nTables: ", interim_dir)
