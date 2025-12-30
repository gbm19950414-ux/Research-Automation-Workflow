#!/usr/bin/env Rscript

# ============================================================
# Screening-style normalized dot-plot stats builder
# - Input : raw wide Excel with columns: name, treatment, concentration, wt_1..wt_10, ho_1..ho_10
# - Output:
#     1) long_for_dotplot.tsv  (each dot = one replicate)
#     2) summary_stats.tsv     (per strain/condition/genotype summary)
#     3) wt_baseline.tsv       (WT baseline mean used for normalization)
# ============================================================

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(tidyr)
  library(stringr)
  library(readr)
})

# -------- Paths (edit if needed) --------
# You can run this script from anywhere; it uses explicit paths by default.
in_xlsx  <- "04_data/raw/炎症表型遗传筛选/raw_data.xlsx"
out_dir  <- "04_data/interim/炎症表型遗传筛选"

# Optional: allow overriding via commandArgs
args <- commandArgs(trailingOnly = TRUE)
if (length(args) >= 1) in_xlsx <- args[[1]]
if (length(args) >= 2) out_dir <- args[[2]]

if (!file.exists(in_xlsx)) {
  stop("Input file not found: ", in_xlsx)
}
if (!dir.exists(out_dir)) {
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
}

# -------- Read --------
raw <- readxl::read_excel(in_xlsx, sheet = 1)

required_cols <- c("name", "treatment", "concentration")
missing_req <- setdiff(required_cols, names(raw))
if (length(missing_req) > 0) {
  stop("Missing required columns: ", paste(missing_req, collapse = ", "))
}

# Identify replicate columns
rep_cols <- names(raw)[str_detect(names(raw), "^(wt|ho)_\\d+$")]
if (length(rep_cols) == 0) {
  stop("No replicate columns found matching ^(wt|ho)_\\d+$")
}

# -------- Reshape to long (each dot = one replicate) --------
long <- raw %>%
  mutate(
    treatment = as.character(treatment),
    concentration = as.numeric(concentration)
  ) %>%
  pivot_longer(
    cols = all_of(rep_cols),
    names_to = c("genotype_raw", "replicate"),
    names_pattern = "^(wt|ho)_(\\d+)$",
    values_to = "value_raw"
  ) %>%
  mutate(
    genotype = recode(genotype_raw, wt = "WT", ho = "HO"),
    replicate = as.integer(replicate)
  ) %>%
  filter(!is.na(value_raw))

# Optional: annotate analyte/readout (edit mapping if your design differs)
long <- long %>%
  mutate(
    analyte = case_when(
      treatment %in% c("lps", "r848") ~ "TNFα",
      treatment %in% c("nigericin") ~ "IL-1β",
      TRUE ~ NA_character_
    )
  )

# -------- Compute WT baseline for normalization (WT mean within each strain+condition) --------
wt_baseline <- long %>%
  filter(genotype == "WT") %>%
  group_by(name, treatment, concentration) %>%
  summarise(
    wt_n = n(),
    wt_mean = mean(value_raw, na.rm = TRUE),
    wt_sd = sd(value_raw, na.rm = TRUE),
    .groups = "drop"
  )

# Join baseline to all rows; normalize each replicate to WT mean of the same strain+condition
long_norm <- long %>%
  left_join(wt_baseline, by = c("name", "treatment", "concentration")) %>%
  mutate(
    value_norm = value_raw / wt_mean
  )

# Safety check: any missing baselines?
n_missing_baseline <- long_norm %>%
  summarise(n = sum(is.na(wt_mean))) %>%
  pull(n)
if (n_missing_baseline > 0) {
  warning("Some rows are missing WT baseline (wt_mean). Check for conditions without WT replicates.")
}

# -------- Summary stats (for labels / tables; dot plot should use long_norm) --------
summary_stats <- long_norm %>%
  group_by(name, treatment, concentration, analyte, genotype) %>%
  summarise(
    n = n(),
    mean_raw = mean(value_raw, na.rm = TRUE),
    sd_raw = sd(value_raw, na.rm = TRUE),
    mean_norm = mean(value_norm, na.rm = TRUE),
    sd_norm = sd(value_norm, na.rm = TRUE),
    se_norm = sd_norm / sqrt(n),
    .groups = "drop"
  ) %>%
  arrange(treatment, concentration, name, genotype)

# -------- Write outputs --------
out_long   <- file.path(out_dir, "long_for_dotplot.tsv")
out_sum    <- file.path(out_dir, "summary_stats.tsv")
out_wtbase <- file.path(out_dir, "wt_baseline.tsv")

readr::write_tsv(long_norm, out_long)
readr::write_tsv(summary_stats, out_sum)
readr::write_tsv(wt_baseline, out_wtbase)

message("Done.\nWrote:\n- ", out_long, "\n- ", out_sum, "\n- ", out_wtbase, "\n")
