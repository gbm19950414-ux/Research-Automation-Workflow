#!/usr/bin/env Rscript
# 03_model_results.R
# Fit mixed models and export inferential result tables.
#
# Outputs (in interim_dir):
# - E40_model_terms_nao.csv
# - E40_model_terms_mtt.csv
# - E40_posthoc_wt_vs_ho_nao.csv
# - E40_posthoc_wt_vs_ho_mtt.csv

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(tidyr)
  library(lme4)
  library(lmerTest)
  library(emmeans)
})

source("05_analysis/scripts/microplate_reader/nao+mtt/00_config.R")
dir.create(cfg$interim_dir, recursive = TRUE, showWarnings = FALSE)

rds_path <- file.path(cfg$interim_dir, "E40_analysis_ready.rds")
if (!file.exists(rds_path)) stop("Missing E40_analysis_ready.rds. Run 01_prepare_analysis_table.R first.", call. = FALSE)
dat <- readRDS(rds_path)

# Prefer folded 2-level genotype if available
if ("geno_simple" %in% names(dat)) {
  dat <- dat %>%
    filter(!is.na(geno_simple)) %>%
    mutate(geno_simple = droplevels(geno_simple))
}

# -----------------------------
# Filtering rules for inference
# -----------------------------
# 1) Background (no_cell) wells should not enter models
if (!is.null(cfg$background_label) && "genotype" %in% names(dat)) {
  dat <- dat %>% filter(as.character(genotype) != cfg$background_label)
}

# 2) NAO model: exclude low-viability wells (recommended)
dat_nao <- dat
if ("low_viability" %in% names(dat_nao)) {
  dat_nao <- dat_nao %>% filter(!(low_viability %in% TRUE))
}

# 3) Robust outliers: exclude from models if configured and flags exist
use_outlier_drop <- !is.null(cfg$drop_outliers_in_models) && isTRUE(cfg$drop_outliers_in_models)

if (use_outlier_drop && "outlier_nao" %in% names(dat_nao)) {
  dat_nao <- dat_nao %>% filter(!(outlier_nao %in% TRUE))
}

dat_mtt <- dat
if (use_outlier_drop && "outlier_mtt" %in% names(dat_mtt)) {
  dat_mtt <- dat_mtt %>% filter(!(outlier_mtt %in% TRUE))
}

# Random effect term
re_terms <- cfg$random_effect[cfg$random_effect %in% names(dat)]
re_formula <- if (length(re_terms) > 0) paste0("(1|", paste(re_terms, collapse=") + (1|"), ")") else "0"

#
# Fixed effects
# Treat time as factor (already ordered), dose_f as factor.
geno_var <- if ("geno_simple" %in% names(dat)) "geno_simple" else "genotype"
fixed <- paste0(geno_var, " * drug * time * dose_f")

# Build formulas
f_nao <- as.formula(paste("NAO_rel ~", fixed, "+", re_formula))
f_mtt <- as.formula(paste("MTT_rel ~", fixed, "+", re_formula))

# Fit
m_nao <- lmer(f_nao, data = dat_nao, REML = FALSE)
m_mtt <- lmer(f_mtt, data = dat_mtt, REML = FALSE)
message(sprintf("[INFO] Rows used: NAO=%d, MTT=%d", nrow(dat_nao), nrow(dat_mtt)))

# Term tests (Type III)
terms_nao <- anova(m_nao, type = 3) %>% as.data.frame() %>% tibble::rownames_to_column("term")
terms_mtt <- anova(m_mtt, type = 3) %>% as.data.frame() %>% tibble::rownames_to_column("term")

#
# Posthoc: WT vs HO within each drug:dose_f:time (or pairwise for genotype variable)
# (You can later subset to key timepoints for figure annotations.)
emm_nao <- emmeans(m_nao, as.formula(paste0("~ ", geno_var, " | drug * dose_f * time")))
emm_mtt <- emmeans(m_mtt, as.formula(paste0("~ ", geno_var, " | drug * dose_f * time")))

ph_nao <- contrast(emm_nao, method = "pairwise") %>%
  as.data.frame() %>%
  mutate(p_adj = p.adjust(p.value, method = cfg$p_adjust_method))

ph_mtt <- contrast(emm_mtt, method = "pairwise") %>%
  as.data.frame() %>%
  mutate(p_adj = p.adjust(p.value, method = cfg$p_adjust_method))

# -----------------------------
# Compact significance tables for plotting
# -----------------------------
# These tables are designed for Layer 4 (04_make_figures.R) to add star annotations.
# Output columns: drug, dose_f, time, contrast, estimate, p.value, p_adj, p_used, signif

get_sig_levels <- function(cfg) {
  # Expect a named character vector like c(`0.0001`='****', `0.001`='***', `0.01`='**', `0.05`='*')
  if (!is.null(cfg$sig_levels)) {
    sl <- cfg$sig_levels
    # coerce names to numeric thresholds
    thr <- suppressWarnings(as.numeric(names(sl)))
    if (all(is.finite(thr))) {
      o <- order(thr)
      return(list(thr = thr[o], sym = as.character(sl[o])))
    }
  }
  # default
  return(list(thr = c(1e-4, 1e-3, 1e-2, 5e-2), sym = c("****", "***", "**", "*")))
}

sig_levels <- get_sig_levels(cfg)

p_used_col <- if (!is.null(cfg$sig_p_column)) cfg$sig_p_column else "p_adj"

p_to_stars <- function(p) {
  if (is.na(p)) return(NA_character_)
  # return the first (smallest) threshold matched
  for (i in seq_along(sig_levels$thr)) {
    if (p < sig_levels$thr[i]) return(sig_levels$sym[i])
  }
  # not significant: return empty string (or cfg$sig_ns_label)
  if (!is.null(cfg$sig_ns_label)) return(as.character(cfg$sig_ns_label))
  ""
}

compact_sig <- function(ph_df) {
  df <- ph_df
  # If more than 2 genotype levels exist, keep only the WT vs HO comparison when possible
  if (geno_var == "geno_simple" && "contrast" %in% names(df)) {
    df <- df %>%
      filter(grepl("wt", contrast, ignore.case = TRUE) & grepl("ho", contrast, ignore.case = TRUE))
  }

  # Choose p column used for annotation
  if (!(p_used_col %in% names(df))) {
    p_used <- df$p_adj
  } else {
    p_used <- df[[p_used_col]]
  }

  out <- df %>%
    mutate(
      p_used = p_used,
      signif = vapply(p_used, p_to_stars, FUN.VALUE = character(1))
    ) %>%
    select(any_of(c("drug", "dose_f", "time", "contrast", "estimate", "p.value", "p_adj", "p_used", "signif")))

  out
}

sig_nao <- compact_sig(ph_nao)
sig_mtt <- compact_sig(ph_mtt)

#
# Write
out_terms_nao <- file.path(cfg$interim_dir, "E40_model_terms_nao.csv")
out_terms_mtt <- file.path(cfg$interim_dir, "E40_model_terms_mtt.csv")
ph_suffix <- if (geno_var == "geno_simple") "wt_vs_ho" else "genotype_pairwise"
out_ph_nao    <- file.path(cfg$interim_dir, paste0("E40_posthoc_", ph_suffix, "_nao.csv"))
out_ph_mtt    <- file.path(cfg$interim_dir, paste0("E40_posthoc_", ph_suffix, "_mtt.csv"))
out_sig_nao   <- file.path(cfg$interim_dir, paste0("E40_sig_", ph_suffix, "_nao.csv"))
out_sig_mtt   <- file.path(cfg$interim_dir, paste0("E40_sig_", ph_suffix, "_mtt.csv"))

readr::write_csv(terms_nao, out_terms_nao, na = "")
readr::write_csv(terms_mtt, out_terms_mtt, na = "")
readr::write_csv(ph_nao, out_ph_nao, na = "")
readr::write_csv(ph_mtt, out_ph_mtt, na = "")
readr::write_csv(sig_nao, out_sig_nao, na = "")
readr::write_csv(sig_mtt, out_sig_mtt, na = "")

message(sprintf("[OK] Model results written:\n- %s\n- %s\n- %s\n- %s\n- %s\n- %s",
                out_terms_nao, out_terms_mtt, out_ph_nao, out_ph_mtt, out_sig_nao, out_sig_mtt))
