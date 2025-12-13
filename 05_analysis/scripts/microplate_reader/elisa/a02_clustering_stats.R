#!/usr/bin/env Rscript
# -*- coding: utf-8 -*-

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(stringr)
  library(writexl)
  library(tidyr)
  library(purrr)
})

# ---- paths ----
base_dir <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"
input_path <- file.path(base_dir, "04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA_drug_fc_bel_ad_anti_master.xlsx")
out_path   <- file.path(base_dir, "04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA_clustering_relative_change.xlsx")

if (!file.exists(input_path)) {
  stop("找不到输入文件：", input_path)
}

# ---- read ----
df <- readxl::read_excel(input_path, sheet = 1)

# ---- required columns ----
need_cols <- c("batch", "genotype", "drug", "mean")
missing <- setdiff(need_cols, names(df))
if (length(missing) > 0) {
  stop("输入文件缺少必要列：", paste(missing, collapse = ", "))
}

# 可选：antibody / analyte 存在则纳入分组（更合理）
group_dims <- c("batch", "genotype")
if ("antibody" %in% names(df)) group_dims <- c(group_dims, "antibody")
if ("analyte"  %in% names(df)) group_dims <- c(group_dims, "analyte")

# ---- patterns ----
# treated: LPS + nigericin + (fc/anti/bel/ad)
target_pattern <- "(fc|anti|bel|ad)"

# baseline: LPS + nigericin but NOT (fc/anti/bel/ad/dl/de)
# 说明：dl/de 用于排除你不希望作为 baseline 的药物条件
baseline_exclude_pattern <- "(fc|anti|bel|ad|dl|de)"

# 必须同时含 lps 和 nigericin（不区分大小写）
# 注意：部分批次可能把 nigericin 误写为 nigeiricin，因此这里同时兼容两种拼写
lps_pattern <- "lps"
nig_pattern <- "(nigericin|nigeiricin)"

# ---- preprocess ----
df2 <- df %>%
  mutate(
    batch    = as.character(.data$batch),
    genotype = as.character(.data$genotype),
    drug     = as.character(.data$drug),
    drug_lower = str_to_lower(.data$drug),
    has_lps = str_detect(.data$drug_lower, lps_pattern),
    has_nig = str_detect(.data$drug_lower, nig_pattern),
    has_target = str_detect(.data$drug_lower, target_pattern),
    baseline_exclude = str_detect(.data$drug_lower, baseline_exclude_pattern),
    mean = suppressWarnings(as.numeric(.data$mean))
  ) %>%
  filter(!is.na(.data$mean))  # 只对有数值的行算均值

# ---- define treated rows & baseline reference within group ----
# 输入表每行已经是均值(mean)，这里不再对 treated 重新求均值；
# baseline 作为同一 group_dims 内的参考值：对符合 baseline 条件的行取 mean(mean)。

treated_rows <- df2 %>%
  filter(.data$has_lps, .data$has_nig, .data$has_target) %>%
  mutate(treated_mean = .data$mean)

baseline_ref <- df2 %>%
  filter(.data$has_lps, .data$has_nig, !.data$baseline_exclude) %>%
  group_by(across(all_of(group_dims))) %>%
  summarise(
    baseline_n = n(),
    baseline_mean = mean(.data$mean, na.rm = TRUE),
    baseline_sd   = sd(.data$mean,  na.rm = TRUE),
    baseline_drugs = paste(sort(unique(.data$drug)), collapse = "; "),
    .groups = "drop"
  )

# ---- normalize within same batch + genotype (+ antibody/analyte if present) ----
out <- treated_rows %>%
  left_join(baseline_ref, by = group_dims) %>%
  mutate(
    relative_change = treated_mean / baseline_mean,
    log2_fc = log2(relative_change),
    qa_flag = case_when(
      is.na(.data$baseline_mean) ~ "NO_BASELINE(lps+nigericin without fc/anti/bel/ad/dl/de)",
      .data$baseline_mean == 0   ~ "BASELINE_ZERO",
      TRUE ~ ""
    )
  ) %>%
  arrange(across(all_of(group_dims)), .data$drug)

# ---- output ----
# 同时输出 baseline/treated 汇总，方便你核对
writexl::write_xlsx(
  list(
    relative_change = out,
    baseline_reference = baseline_ref,
    treated_rows = treated_rows
  ),
  path = out_path
)

message("完成：", out_path)