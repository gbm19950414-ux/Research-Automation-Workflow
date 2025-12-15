#!/usr/bin/env Rscript
# 04_make_figures.R
# Generate Figure 1/2/3/4 from common tables.
#
# Outputs (in processed_dir):
# - fig1_mtt_over_time.(pdf/png)
# - fig2_nao_over_time.(pdf/png)
# - fig3_dose_response_24h.(pdf/png)
# - fig4_nao_vs_mtt_scatter.(pdf/png)

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(ggplot2)
  library(stringr)
  library(rlang)
})

source("05_analysis/scripts/microplate_reader/nao+mtt/00_config.R")
dir.create(cfg$processed_dir, recursive = TRUE, showWarnings = FALSE)

# Inputs
analysis_rds <- file.path(cfg$interim_dir, "E40_analysis_ready.rds")
sum_group_csv <- file.path(cfg$interim_dir, "E40_summary_group.csv")

if (!file.exists(analysis_rds)) stop("Missing E40_analysis_ready.rds. Run 01_prepare_analysis_table.R first.", call. = FALSE)
if (!file.exists(sum_group_csv)) stop("Missing E40_summary_group.csv. Run 02_summarise_common.R first.", call. = FALSE)

dat <- readRDS(analysis_rds)
sumg <- readr::read_csv(sum_group_csv, show_col_types = FALSE)

# -----------------------
# Fixed axis ordering
# -----------------------
# Time order (categorical)
time_levels_fixed <- c("0h", "5h", "10h", "24h", "48h")

# Dose order (categorical, keep as character to avoid numeric/character mixing)
dose_levels_fixed <- c("0", "0.5", "1", "2", "4", "12.5", "25", "50")

# Prefer folded 2-level genotype if available
if ("geno_simple" %in% names(dat)) {
  dat <- dat %>% mutate(geno_plot = geno_simple)
} else {
  dat <- dat %>% mutate(geno_plot = genotype)
}
if ("geno_simple" %in% names(sumg)) {
  sumg <- sumg %>% mutate(geno_plot = geno_simple)
} else {
  sumg <- sumg %>% mutate(geno_plot = genotype)
}

# Standardize keys for joining/plotting
# Use a dedicated discrete dose key to avoid numeric/character mixing across layers
sumg <- sumg %>%
  mutate(
    drug_key  = as.character(drug),
    time_key  = as.character(time),
    dose_key  = as.character(dose_f),
    # enforce fixed factor ordering if levels exist in data
    time_plot = factor(time_key, levels = intersect(time_levels_fixed, unique(time_key))),
    dose_plot = factor(dose_key, levels = intersect(dose_levels_fixed, unique(dose_key)))
  )

# -----------------------
# Choose which metrics to plot
# Prefer control-normalized ( *_ctrl_* ) if present; otherwise relative-to-baseline ( *_mean / *_sem )
# -----------------------

pick_summary_metric <- function(df, base) {
  # base: "mtt" or "nao"
  # returns list(mean_col=..., sem_col=..., ylab=...)
  if (paste0(base, "_ctrl_mean") %in% names(df) && paste0(base, "_ctrl_sem") %in% names(df)) {
    return(list(mean_col = paste0(base, "_ctrl_mean"), sem_col = paste0(base, "_ctrl_sem"), ylab = paste0(toupper(base), " (relative to cells-only untreated)")))
  }
  if (paste0(base, "_mean") %in% names(df) && paste0(base, "_sem") %in% names(df)) {
    return(list(mean_col = paste0(base, "_mean"), sem_col = paste0(base, "_sem"), ylab = paste0(toupper(base), " (relative to baseline)")))
  }
  stop(sprintf("Cannot find summary columns for '%s'. Need either %s_ctrl_mean/%s_ctrl_sem or %s_mean/%s_sem", base, base, base, base, base), call. = FALSE)
}

mtt_metric <- pick_summary_metric(sumg, "mtt")
nao_metric <- pick_summary_metric(sumg, "nao")

# -----------------------
# Read compact significance tables (if present)
# Produced by 03_model_results.R
# -----------------------
read_sig_table <- function(kind) {
  # kind: "mtt" or "nao"
  cand <- c(
    file.path(cfg$interim_dir, paste0("E40_sig_wt_vs_ho_", kind, ".csv")),
    file.path(cfg$interim_dir, paste0("E40_sig_genotype_pairwise_", kind, ".csv"))
  )
  f <- cand[file.exists(cand)][1]
  if (is.na(f) || length(f) == 0) return(NULL)
  df <- readr::read_csv(f, show_col_types = FALSE)
  # keep only rows with a non-empty star label
  if ("signif" %in% names(df)) {
    df <- df %>% mutate(signif = as.character(signif)) %>% filter(!is.na(signif) & signif != "")
  }
  df
}

sig_mtt <- read_sig_table("mtt")
sig_nao <- read_sig_table("nao")

# Compute y-positions for annotations from the summary table
# For time-series figures (facet_grid drug ~ dose_f): y_position per (drug, dose_f, time)
compute_ypos_time <- function(sum_df, mean_col, sem_col, pad = 1.07) {
  sum_df %>%
    group_by(drug_key, dose_key, time_key) %>%
    summarise(
      y_position = max(.data[[mean_col]] + .data[[sem_col]], na.rm = TRUE) * pad,
      .groups = "drop"
    )
}

# For dose-response (facet_wrap ~ drug): y_position per (drug, dose_f) at a fixed time
compute_ypos_dose <- function(sum_df, mean_col, sem_col, pad = 1.07) {
  sum_df %>%
    group_by(drug_key, dose_key) %>%
    summarise(
      y_position = max(.data[[mean_col]] + .data[[sem_col]], na.rm = TRUE) * pad,
      .groups = "drop"
    )
}

# For well-level scatter, prefer *_ctrl, then *_rel, then *_bg, then raw
pick_well_metric <- function(df, base) {
  # base: "MTT" or "NAO" (case-sensitive columns)
  if (paste0(base, "_ctrl") %in% names(df)) return(paste0(base, "_ctrl"))
  if (paste0(base, "_rel") %in% names(df))  return(paste0(base, "_rel"))
  if (paste0(base, "_bg") %in% names(df))   return(paste0(base, "_bg"))
  if (base %in% names(df))                   return(base)
  stop(sprintf("Cannot find well-level metric for '%s'", base), call. = FALSE)
}

mtt_well_col <- pick_well_metric(dat, "MTT")
nao_well_col <- pick_well_metric(dat, "NAO")

# Optional filters/flags
has_bg_flag <- "is_background" %in% names(dat)
has_out_mtt <- "outlier_mtt" %in% names(dat)
has_out_nao <- "outlier_nao" %in% names(dat)

# Exclude background wells from plots (keep them in data files)
if (has_bg_flag) {
  dat <- dat %>% filter(!(is_background %in% TRUE))
}

save_plot <- function(p, filename_base) {
  for (fmt in cfg$plot_formats) {
    out <- file.path(cfg$processed_dir, paste0(filename_base, ".", fmt))
    ggsave(out, p, width = cfg$plot_width, height = cfg$plot_height)
  }
}

# -----------------------
# Figure 1: MTT over time
# -----------------------
p1 <- ggplot(sumg, aes(x = time_plot, group = geno_plot, linetype = geno_plot)) +
  geom_line(aes(y = .data[[mtt_metric$mean_col]])) +
  geom_point(aes(y = .data[[mtt_metric$mean_col]])) +
  geom_errorbar(
    aes(
      ymin = .data[[mtt_metric$mean_col]] - .data[[mtt_metric$sem_col]],
      ymax = .data[[mtt_metric$mean_col]] + .data[[mtt_metric$sem_col]]
    ),
    width = 0.15
  ) +
  facet_grid(drug ~ dose_plot, scales = "free_y") +
  labs(x = "Time", y = mtt_metric$ylab, title = "Figure 1: Cell viability (MTT)") +
  theme_bw()

# Add significance stars if available
if (!is.null(sig_mtt) && all(c("drug", "dose_f", "time", "signif") %in% names(sig_mtt))) {
  anno1_y <- compute_ypos_time(sumg, mtt_metric$mean_col, mtt_metric$sem_col)
  anno1 <- sig_mtt %>%
    mutate(
      drug_key = as.character(drug),
      dose_key = as.character(dose_f),
      time_key = as.character(time)
    ) %>%
    left_join(anno1_y, by = c("drug_key", "dose_key", "time_key"))

  p1 <- p1 +
    geom_text(
      data = anno1,
      aes(x = factor(time_key, levels = levels(sumg$time_plot)), y = y_position, label = signif),
      inherit.aes = FALSE,
      vjust = 0
    )
}

save_plot(p1, "fig1_mtt_over_time")

# -----------------------
# Figure 2: NAO over time (flag low-viability)
# -----------------------
# use group summary; additionally overlay low_viability_rate shading via alpha on points
p2 <- ggplot(sumg, aes(x = time_plot, group = geno_plot, linetype = geno_plot)) +
  geom_line(aes(y = .data[[nao_metric$mean_col]])) +
  {
    if ("low_viability_rate" %in% names(sumg)) {
      geom_point(aes(y = .data[[nao_metric$mean_col]], alpha = 1 - low_viability_rate))
    } else {
      geom_point(aes(y = .data[[nao_metric$mean_col]]))
    }
  } +
  geom_errorbar(
    aes(
      ymin = .data[[nao_metric$mean_col]] - .data[[nao_metric$sem_col]],
      ymax = .data[[nao_metric$mean_col]] + .data[[nao_metric$sem_col]]
    ),
    width = 0.15
  ) +
  {
    if ("low_viability_rate" %in% names(sumg)) {
      scale_alpha(range = c(0.2, 1), guide = "none")
    } else {
      NULL
    }
  } +
  facet_grid(drug ~ dose_plot, scales = "free_y") +
  labs(x = "Time", y = nao_metric$ylab, title = "Figure 2: Cardiolipin signal (NAO)") +
  theme_bw()

# Add significance stars if available
if (!is.null(sig_nao) && all(c("drug", "dose_f", "time", "signif") %in% names(sig_nao))) {
  anno2_y <- compute_ypos_time(sumg, nao_metric$mean_col, nao_metric$sem_col)
  anno2 <- sig_nao %>%
    mutate(
      drug_key = as.character(drug),
      dose_key = as.character(dose_f),
      time_key = as.character(time)
    ) %>%
    left_join(anno2_y, by = c("drug_key", "dose_key", "time_key"))

  p2 <- p2 +
    geom_text(
      data = anno2,
      aes(x = factor(time_key, levels = levels(sumg$time_plot)), y = y_position, label = signif),
      inherit.aes = FALSE,
      vjust = 0
    )
}

save_plot(p2, "fig2_nao_over_time")

# -----------------------
# Figure 3: Dose response at key time (default 24h)
# -----------------------
key_time <- if (!is.null(cfg$fig3_key_time)) cfg$fig3_key_time else "24h"
sumg_24 <- sumg %>% filter(time_key == as.character(key_time))

p3 <- ggplot(sumg_24, aes(x = dose_plot, group = geno_plot, linetype = geno_plot)) +
  geom_line(aes(y = .data[[nao_metric$mean_col]])) +
  geom_point(aes(y = .data[[nao_metric$mean_col]])) +
  geom_errorbar(
    aes(
      ymin = .data[[nao_metric$mean_col]] - .data[[nao_metric$sem_col]],
      ymax = .data[[nao_metric$mean_col]] + .data[[nao_metric$sem_col]]
    ),
    width = 0.15
  ) +
  facet_wrap(~ drug, scales = "free_y") +
  labs(x = "Dose", y = nao_metric$ylab, title = paste0("Figure 3: Dose response at ", key_time)) +
  theme_bw() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))

# Add significance stars for the key timepoint if available
if (!is.null(sig_nao) && all(c("drug", "dose_f", "time", "signif") %in% names(sig_nao))) {
  sig3 <- sig_nao %>% filter(as.character(time) == as.character(key_time))
  if (nrow(sig3) > 0) {
    anno3_y <- compute_ypos_dose(sumg_24, nao_metric$mean_col, nao_metric$sem_col)
    anno3 <- sig3 %>%
      mutate(
        drug_key = as.character(drug),
        dose_key = as.character(dose_f)
      ) %>%
      left_join(anno3_y, by = c("drug_key", "dose_key"))

    p3 <- p3 +
      geom_text(
        data = anno3,
        aes(x = factor(dose_key, levels = levels(sumg_24$dose_plot)), y = y_position, label = signif),
        inherit.aes = FALSE,
        vjust = 0
      )
  }
}

save_plot(p3, paste0("fig3_dose_response_", key_time))

# -----------------------
# Figure 4: NAO vs MTT scatter (well-level)
# -----------------------
# prefer per-well data; grey out low-viability and outliers if present
if (!all(c(mtt_well_col, nao_well_col, "geno_plot", "drug", "time") %in% names(dat))) {
  stop("analysis-ready table missing required columns for Figure 4.", call. = FALSE)
}


# Precompute alpha for points (avoid using dplyr::n() inside ggplot aesthetics)
dat <- dat %>%
  mutate(
    alpha_plot = 0.9,
    alpha_plot = if ("low_viability" %in% names(dat)) ifelse(low_viability %in% TRUE, 0.2, alpha_plot) else alpha_plot,
    alpha_plot = if (has_out_mtt) ifelse(outlier_mtt %in% TRUE, pmin(alpha_plot, 0.2), alpha_plot) else alpha_plot,
    alpha_plot = if (has_out_nao) ifelse(outlier_nao %in% TRUE, pmin(alpha_plot, 0.2), alpha_plot) else alpha_plot
  )

p4 <- ggplot(dat, aes(x = .data[[mtt_well_col]], y = .data[[nao_well_col]], linetype = geno_plot)) +
  geom_point(aes(alpha = alpha_plot)) +
  facet_grid(time ~ drug) +
  scale_alpha_identity() +
  labs(
    x = mtt_well_col,
    y = nao_well_col,
    title = "Figure 4: NAO vs MTT (per well)"
  ) +
  theme_bw()

save_plot(p4, "fig4_nao_vs_mtt_scatter")

message(sprintf("[OK] Figures saved to: %s", cfg$processed_dir))
