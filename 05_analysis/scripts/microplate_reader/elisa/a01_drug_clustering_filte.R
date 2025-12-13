#!/usr/bin/env Rscript
# -*- coding: utf-8 -*-

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(stringr)
  library(writexl)
  library(purrr)
  library(tibble)
})

# ---- paths ----
base_dir <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"
input_dir <- file.path(base_dir, "04_data/interim/microplate_reader/ELISA检测细胞因子")
out_path  <- file.path(input_dir, "ELISA_drug_fc_bel_ad_anti_master.xlsx")

# ---- file discovery ----
files <- list.files(
  input_dir,
  pattern = "^ELISA_statistic_E\\d+_summary\\.xlsx$",
  full.names = TRUE
)

if (length(files) == 0) {
  stop("未找到匹配的文件：", input_dir, " 下的 ELISA_statistic_E*_summary.xlsx")
}

# ---- helper ----
read_and_filter_one <- function(fp) {
  df <- readxl::read_excel(fp)

  # 基础列检查
  required_cols <- c("drug")
  missing <- setdiff(required_cols, names(df))
  if (length(missing) > 0) {
    message(basename(fp), " 缺少必要列：", paste(missing, collapse = ", "), "，跳过该文件")
    return(NULL)
  }

  # 目标药物关键词：fc / bel / ad / anti（不区分大小写）
  # 说明：ad 比较短，可能会误匹配（例如 "add"、"ad-" 等）。如需更严格匹配，可改成带边界的正则。
  target_pattern <- "(fc|bel|ad|anti)"

  # 额外刺激条件：如果同一 batch 命中 target_pattern，则把该 batch 的 lps / nigericin 也一并输出
  stim_pattern <- "(lps|nigericin)"

  df2 <- df %>%
    mutate(
      source_file = basename(fp),
      source_path = fp
    ) %>%
    # 如果没有 batch 列，就从文件名里提取 E## 作为 batch（summary 文件同样适用）
    mutate(
      batch = if ("batch" %in% names(.)) as.character(.data$batch) else str_extract(basename(fp), "E\\d+")
    ) %>%
    # 统一 drug 为字符
    mutate(drug = as.character(.data$drug)) %>%
    filter(!is.na(.data$drug)) %>%
    mutate(
      drug_lower = str_to_lower(.data$drug),
      target_hit = str_detect(.data$drug_lower, target_pattern),
      stim_hit   = str_detect(.data$drug_lower, stim_pattern)
    ) %>%
    group_by(.data$batch) %>%
    mutate(batch_has_target = any(.data$target_hit, na.rm = TRUE)) %>%
    ungroup() %>%
    # 规则：保留 target_hit；若 batch_has_target，则额外保留 stim_hit
    filter(.data$target_hit | (.data$batch_has_target & .data$stim_hit)) %>%
    select(-drug_lower, -target_hit, -stim_hit, -batch_has_target) %>%
    distinct()

  if (nrow(df2) == 0) {
    message(basename(fp), " 没有命中 drug 关键词（fc/bel/ad/anti），因此也不会附带输出 lps/nigericin")
    return(NULL)
  }

  df2
}

# ---- run ----
all_tbl <- purrr::map(files, read_and_filter_one) %>%
  purrr::compact() %>%
  bind_rows()

if (nrow(all_tbl) == 0) {
  stop("所有文件都未筛到任何符合条件的记录（drug 含 fc/bel/ad/anti）。")
}

# 给一个更稳定的列顺序：把元信息列放前面
meta_cols <- c("batch", "drug", "antibody", "genotype", "group", "matrix_index", "final_value", "source_file", "source_path")
front <- intersect(meta_cols, names(all_tbl))
rest  <- setdiff(names(all_tbl), front)

all_tbl <- all_tbl %>% select(all_of(front), all_of(rest))

# 输出
writexl::write_xlsx(list(master = all_tbl), path = out_path)
message("完成：", out_path)