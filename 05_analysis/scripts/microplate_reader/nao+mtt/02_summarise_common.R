#!/usr/bin/env Rscript
# 02_summarise_common.R
# Analysis-ready -> common summary tables for multiple figures
#
# Outputs (in interim_dir):
# - E40_summary_group.csv  (genotype x drug x dose_f x time)
# - E40_summary_block.csv  (optional: adds block_id if present)
# - E40_qc_overview.csv    (low_viability rate per condition)

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(tidyr)
  library(stringr)
})

source("05_analysis/scripts/microplate_reader/nao+mtt/00_config.R")
dir.create(cfg$interim_dir, recursive = TRUE, showWarnings = FALSE)

rds_path <- file.path(cfg$interim_dir, "E40_analysis_ready.rds")
if (!file.exists(rds_path)) stop("Missing E40_analysis_ready.rds. Run 01_prepare_analysis_table.R first.", call. = FALSE)

dat <- readRDS(rds_path)

group_keys <- if ("geno_simple" %in% names(dat)) {
  c("geno_simple","drug","dose_f","time")
} else {
  c("genotype","drug","dose_f","time")
}

# Main group summary (for line plots)
sum_group <- dat %>%
  group_by(across(all_of(group_keys))) %>%
  summarise(
    # MTT
    mtt_n    = sum(is.finite(MTT_rel)),
    mtt_mean = mean(MTT_rel, na.rm = TRUE),
    mtt_sd   = ifelse(mtt_n > 1, sd(MTT_rel, na.rm = TRUE), NA_real_),
    mtt_sem  = ifelse(mtt_n > 1, mtt_sd / sqrt(mtt_n), NA_real_),

    # NAO
    nao_n    = sum(is.finite(NAO_rel)),
    nao_mean = mean(NAO_rel, na.rm = TRUE),
    nao_sd   = ifelse(nao_n > 1, sd(NAO_rel, na.rm = TRUE), NA_real_),
    nao_sem  = ifelse(nao_n > 1, nao_sd / sqrt(nao_n), NA_real_),

    # QC
    n_total = n(),
    low_viability_n    = sum(low_viability %in% TRUE, na.rm = TRUE),
    low_viability_rate = mean(low_viability %in% TRUE, na.rm = TRUE),
    .groups = "drop"
  )

# Block-level summary (if block_id exists)
sum_block <- NULL
if ("block_id" %in% names(dat)) {
  sum_block <- dat %>%
    group_by(across(all_of(c(group_keys,"block_id")))) %>%
    summarise(
      mtt_mean = mean(MTT_rel, na.rm = TRUE),
      nao_mean = mean(NAO_rel, na.rm = TRUE),
      mtt_n    = sum(is.finite(MTT_rel)),
      nao_n    = sum(is.finite(NAO_rel)),
      n_total  = n(),
      low_viability_rate = mean(low_viability %in% TRUE, na.rm = TRUE),
      .groups = "drop"
    )
}

qc_overview <- dat %>%
  group_by(across(all_of(group_keys))) %>%
  summarise(
    n_total = n(),
    pct_low_viability = mean(low_viability %in% TRUE, na.rm = TRUE),
    .groups = "drop"
  )

# Write
out_group <- file.path(cfg$interim_dir, "E40_summary_group.csv")
out_qc    <- file.path(cfg$interim_dir, "E40_qc_overview.csv")
readr::write_csv(sum_group, out_group, na = "")
readr::write_csv(qc_overview, out_qc, na = "")

if (!is.null(sum_block)) {
  out_block <- file.path(cfg$interim_dir, "E40_summary_block.csv")
  readr::write_csv(sum_block, out_block, na = "")
  message(sprintf("[OK] Wrote:\n- %s\n- %s\n- %s", out_group, out_qc, out_block))
} else {
  message(sprintf("[OK] Wrote:\n- %s\n- %s\n(block_id not found; skipped block summary)", out_group, out_qc))
}
