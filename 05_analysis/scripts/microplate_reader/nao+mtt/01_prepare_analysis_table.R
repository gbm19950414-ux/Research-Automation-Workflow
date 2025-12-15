#!/usr/bin/env Rscript
# 01_prepare_analysis_table.R
# Long (raw-ish) -> analysis-ready table with:
# - standardized factors
# - QC flags
# - normalization columns (MTT_rel, NAO_rel)
#
# Outputs (in interim_dir):
# - E40_analysis_ready.rds
# - E40_analysis_ready.csv

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(tidyr)
  library(rlang)
})

source("05_analysis/scripts/microplate_reader/nao+mtt/00_config.R")

dir.create(cfg$interim_dir, recursive = TRUE, showWarnings = FALSE)

stopf <- function(...) stop(sprintf(...), call. = FALSE)

pick_col <- function(df, candidates, label) {
  candidates <- candidates[!is.na(candidates) & candidates != ""]
  hit <- candidates[candidates %in% names(df)]
  if (length(hit) == 0) {
    stopf("Cannot find column for '%s'. Tried: %s\nAvailable columns: %s",
          label, paste(candidates, collapse = ", "), paste(names(df), collapse = ", "))
  }
  hit[[1]]
}

# Multi-column matcher for NAO channels
pick_cols_any <- function(df, candidates, label) {
  candidates <- candidates[!is.na(candidates) & candidates != ""]
  hit <- candidates[candidates %in% names(df)]
  if (length(hit) == 0) {
    character(0)
  } else {
    hit
  }
}

# Read
dat <- readr::read_csv(cfg$input_long_csv, show_col_types = FALSE)

# Resolve columns
col_geno <- pick_col(dat, cfg$col$genotype, "genotype")
col_drug <- pick_col(dat, cfg$col$drug,     "drug")
col_dose <- pick_col(dat, cfg$col$dose,     "dose")
col_time <- pick_col(dat, cfg$col$time,     "time")
col_mtt  <- pick_col(dat, cfg$col$mtt,      "mtt")

# NAO: support multiple channels (scheme A+B)
nao_cols <- character(0)
if (!is.null(cfg$col$nao_channels)) {
  nao_cols <- pick_cols_any(dat, cfg$col$nao_channels, "nao_channels")
}

# Fallback single-NAO column if channels not found
col_nao <- NULL
if (length(nao_cols) == 0) {
  col_nao <- pick_col(dat, cfg$col$nao, "nao")
}

# Name for combined NAO
nao_primary_name <- if (!is.null(cfg$nao_primary_name) && nzchar(cfg$nao_primary_name)) cfg$nao_primary_name else "NAO_combined"
nao_combine_method <- if (!is.null(cfg$nao_combine_method) && nzchar(cfg$nao_combine_method)) cfg$nao_combine_method else "mean"

# Helper: coerce time to canonical "0h/5h/12h/24h/36h"
canon_time <- function(x) {
  x <- as.character(x)
  x <- str_trim(tolower(x))
  # accept "0", "0h", "0 hr", "0hours"
  x <- str_replace_all(x, "\\s+", "")
  x <- str_replace(x, "^([0-9]+)$", "\\1h")
  x <- str_replace(x, "^([0-9]+)hr$", "\\1h")
  x <- str_replace(x, "^([0-9]+)hrs$", "\\1h")
  x <- str_replace(x, "^([0-9]+)hour(s)?$", "\\1h")
  x
}

# Helper: coerce genotype/drug to lowercase
canon_low <- function(x) str_trim(tolower(as.character(x)))

# Coerce numeric safely
to_num <- function(x) suppressWarnings(readr::parse_double(as.character(x), na = c("", "NA", "NaN")))

dat2 <- dat %>%
  mutate(
    genotype_raw = .data[[col_geno]],
    genotype = canon_low(.data[[col_geno]]),
    drug     = canon_low(.data[[col_drug]]),
    dose_raw = .data[[col_dose]],
    dose     = to_num(.data[[col_dose]]),
    time     = canon_time(.data[[col_time]]),
    MTT_raw  = .data[[col_mtt]],
    MTT      = to_num(.data[[col_mtt]])
  )

# ---- NAO channels (scheme A+B): keep per-channel numeric, then create composite ----
if (length(nao_cols) > 0) {
  # Create numeric columns for each channel (safe names)
  safe_names <- make.names(nao_cols)
  for (i in seq_along(nao_cols)) {
    dat2[[safe_names[[i]]]] <- to_num(dat2[[nao_cols[[i]]]])
  }

  # Composite
  mat <- as.matrix(dat2[, safe_names, drop = FALSE])
  if (tolower(nao_combine_method) == "median") {
    dat2[[nao_primary_name]] <- apply(mat, 1, function(v) median(v, na.rm = TRUE))
  } else {
    dat2[[nao_primary_name]] <- rowMeans(mat, na.rm = TRUE)
  }

  # For downstream, set NAO/NAO_raw to composite
  dat2$NAO_raw <- as.character(dat2[[nao_primary_name]])
  dat2$NAO     <- dat2[[nao_primary_name]]

  # Record which original columns were used
  dat2$NAO_channels_used <- paste(nao_cols, collapse = ";")
} else {
  # Single-column NAO fallback
  dat2 <- dat2 %>%
    mutate(
      NAO_raw = .data[[col_nao]],
      NAO     = to_num(.data[[col_nao]]),
      NAO_channels_used = NA_character_
    )
}


# ---- Fold genotype column (scheme A+B support): wt_1..wt_4 / ho_1..ho_4 -> geno_simple (wt/ho) ----
# Keeps the original `genotype` (replicate-coded) for traceability.
# `geno_simple` is the primary 2-level genotype used for downstream stats/plots.
# `geno_rep` stores the replicate index when present.
# NOTE: rows like `no_cell` will get NA in geno_simple unless you handle them explicitly later.

dat2 <- dat2 %>%
  mutate(
    geno_simple = case_when(
      str_detect(genotype, "^wt") ~ "wt",
      str_detect(genotype, "^ho") ~ "ho",
      TRUE ~ NA_character_
    ),
    geno_rep = case_when(
      str_detect(genotype, "^(wt|ho)_[0-9]+$") ~ str_extract(genotype, "[0-9]+$"),
      TRUE ~ NA_character_
    )
  )

# Factor ordering
dat2 <- dat2 %>%
  mutate(
    genotype    = factor(genotype, levels = cfg$genotype_levels),
    geno_simple = factor(geno_simple, levels = c("wt", "ho")),
    drug        = factor(drug,     levels = cfg$drug_levels),
    time        = factor(time,     levels = cfg$time_levels, ordered = TRUE)
  )

# If dose couldn't parse numeric, keep as factor of original
dat2 <- dat2 %>%
  mutate(
    dose_f = ifelse(is.na(dose), as.character(dose_raw), as.character(dose)),
    dose_f = factor(dose_f, levels = unique(dose_f))
  )
# -----------------------------
# Background correction (no_cell)
# -----------------------------
dat2 <- dat2 %>%
  mutate(is_background = (as.character(genotype) == cfg$background_label))

bg_keys <- intersect(cfg$background_group_vars, names(dat2))
if (length(bg_keys) == 0) stop("No valid background_group_vars found in data.", call. = FALSE)

bg_tbl <- dat2 %>%
  filter(is_background) %>%
  group_by(across(all_of(bg_keys))) %>%
  summarise(
    bg_mtt = mean(MTT, na.rm = TRUE),
    bg_nao = mean(NAO, na.rm = TRUE),
    .groups = "drop"
  )

dat2 <- dat2 %>%
  left_join(bg_tbl, by = bg_keys) %>%
  mutate(
    MTT_bg = MTT - bg_mtt,
    NAO_bg = NAO - bg_nao
  )

# -----------------------------
# Optional: control-normalization (cells-only untreated)
# -----------------------------
ctrl_keys <- intersect(cfg$control_group_vars, names(dat2))
dat2 <- dat2 %>%
  mutate(
    is_control = !is_background & as.character(drug) == cfg$control_drug
  )

if (!is.null(cfg$control_dose_f)) {
  dat2 <- dat2 %>% mutate(is_control = is_control & as.character(dose_f) == as.character(cfg$control_dose_f))
}

ctrl_tbl <- dat2 %>%
  filter(is_control) %>%
  group_by(across(all_of(ctrl_keys))) %>%
  summarise(
    ctrl_mtt = mean(MTT_bg, na.rm = TRUE),
    ctrl_nao = mean(NAO_bg, na.rm = TRUE),
    .groups = "drop"
  )

dat2 <- dat2 %>%
  left_join(ctrl_tbl, by = ctrl_keys) %>%
  mutate(
    MTT_ctrl = ifelse(is.na(ctrl_mtt) | ctrl_mtt <= 0, NA_real_, MTT_bg / ctrl_mtt),
    NAO_ctrl = ifelse(is.na(ctrl_nao) | ctrl_nao <= 0, NA_real_, NAO_bg / ctrl_nao)
  )
# Build baseline within groups (default: genotype+drug+dose_f at baseline_time)
group_vars <- cfg$normalize_within
group_syms <- rlang::syms(group_vars)

dat2 <- dat2 %>%
  group_by(!!!group_syms) %>%
  mutate(
    baseline_mtt = mean(MTT_bg[time == cfg$baseline_time], na.rm = TRUE),
    baseline_nao = mean(NAO_bg[time == cfg$baseline_time], na.rm = TRUE)
  ) %>%
  ungroup()

# Relative normalization (protect against 0/NA baselines)
dat2 <- dat2 %>%
  mutate(
    MTT_rel = ifelse(is.na(baseline_mtt) | baseline_mtt <= 0, NA_real_, MTT_bg / baseline_mtt),
    NAO_rel = ifelse(is.na(baseline_nao) | baseline_nao <= 0, NA_real_, NAO_bg / baseline_nao),
    low_viability = ifelse(is.na(MTT_rel), NA, MTT_rel < cfg$viability_threshold)
  )
# -----------------------------
# Robust z-score outliers (median + MAD) within groups
# -----------------------------
rz <- function(x) {
  x <- as.numeric(x)
  med <- median(x, na.rm = TRUE)
  madv <- mad(x, constant = 1, na.rm = TRUE) # raw MAD
  if (is.na(madv) || madv == 0) return(rep(NA_real_, length(x)))
  0.6745 * (x - med) / madv
}

oz_keys <- intersect(cfg$robust_z_group_vars, names(dat2))

dat2 <- dat2 %>%
  group_by(across(all_of(oz_keys))) %>%
  mutate(
    robust_z_mtt = rz(MTT_rel),
    robust_z_nao = rz(NAO_rel),
    outlier_mtt  = ifelse(is.na(robust_z_mtt), FALSE, abs(robust_z_mtt) > cfg$robust_z_threshold),
    outlier_nao  = ifelse(is.na(robust_z_nao), FALSE, abs(robust_z_nao) > cfg$robust_z_threshold)
  ) %>%
  ungroup()
# Keep original columns but add standardized set
# Ensure we keep any identifiers (well/block_id etc.)
# and append standardized columns at end.
core_cols <- c(
  "genotype","geno_simple","geno_rep","drug","dose","dose_f","time",
  "MTT","NAO","MTT_rel","NAO_rel","low_viability",
  "baseline_mtt","baseline_nao",
  "NAO_channels_used"
)
# If composite NAO exists, also relocate it for visibility
if (exists("nao_primary_name") && nao_primary_name %in% names(dat2)) {
  core_cols <- c(core_cols, nao_primary_name)
}
dat_out <- dat2 %>%
  relocate(any_of(core_cols), .after = last_col())

# Write
rds_path <- file.path(cfg$interim_dir, "E40_analysis_ready.rds")
csv_path <- file.path(cfg$interim_dir, "E40_analysis_ready.csv")

saveRDS(dat_out, rds_path)
readr::write_csv(dat_out, csv_path, na = "")

used_msg <- if (length(nao_cols) > 0) {
  sprintf("NAO composite: %s (method=%s) from channels: %s", nao_primary_name, nao_combine_method, paste(nao_cols, collapse = ", "))
} else {
  sprintf("NAO single column used: %s", col_nao)
}
message(sprintf("[OK] analysis-ready table written:\n- %s\n- %s\nRows: %d\n%s", rds_path, csv_path, nrow(dat_out), used_msg))
