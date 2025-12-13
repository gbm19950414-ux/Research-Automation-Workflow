###############################
## NAO 统计分析与绘图脚本 (R)
## 1) 单细胞水平 WT vs HO，支持新增 treatment 因子（control/treated）
## 2) well 水平 WT vs HO，支持新增 treatment 因子（control/treated）
## 3) Area vs 强度 关系
###############################

## 需要的 R 包 -----------------
packages <- c("tidyverse", "readxl", "writexl")
for (p in packages) {
  if (!requireNamespace(p, quietly = TRUE)) {
    stop("缺少 R 包: ", p,
         "\n请在当前 micromamba 环境中先安装，例如：",
         "\n  micromamba install r-", p,
         "\n然后再运行脚本。")
  }
}
library(tidyverse)
library(readxl)
library(writexl)
input_files <- c(
  "04_data/raw/imaging_if/E32_NAO/E32_statistic.xlsx",
  "04_data/raw/imaging_if/E29_NAO/E29_statistic.xlsx",
  "04_data/raw/imaging_if/E30_NAO/E30_statistic.xlsx",
  "04_data/raw/imaging_if/E33_NAO/E33_statistic.xlsx",
  "04_data/raw/imaging_if/E36_NAO/E36_statistic.xlsx"
)
metrics <- c("norm_intden", "Mean", "IntDen")
output_dir <- "04_data/interim/imaging_if"

theme_pub <- function(base_size = 14) {
  ggplot2::theme_classic(base_size = base_size) +
    theme(
      axis.title = element_text(face = "bold"),
      axis.text  = element_text(color = "black"),
      legend.position = "none",
      strip.background = element_rect(fill = "grey90", color = NA),
      strip.text = element_text(face = "bold")
    )
}

for (input_file in input_files) {
  message("Processing file: ", input_file)
  sheet_name <- "sheet1"
  
  # auto-generate sample name from filename
  sample_name <- tools::file_path_sans_ext(basename(input_file))
  
  for (use_metric in metrics) {
    message("  Using metric: ", use_metric)
    
    output_prefix <- file.path(output_dir, paste0(sample_name, "_", use_metric))
    
    raw <- read_excel(input_file, sheet = sheet_name)
    
    # Some ImageJ/Excel exports contain duplicated headers like "IntDen" which are repaired to "IntDen...11", "IntDen...16".
    # Prefer the first matching repaired column if the canonical one is absent.
    if (!"IntDen" %in% names(raw)) {
      intden_candidates <- grep("^IntDen(\\.\\.\\.)?", names(raw), value = TRUE)
      if (length(intden_candidates) > 0) {
        raw <- raw %>% dplyr::rename(IntDen = !!rlang::sym(intden_candidates[1]))
      }
    }
    if (!"Area" %in% names(raw)) {
      area_candidates <- grep("^Area(\\.\\.\\.)?", names(raw), value = TRUE)
      if (length(area_candidates) > 0) {
        raw <- raw %>% dplyr::rename(Area = !!rlang::sym(area_candidates[1]))
      }
    }
    if (!"Mean" %in% names(raw)) {
      mean_candidates <- grep("^Mean(\\.\\.\\.)?", names(raw), value = TRUE)
      if (length(mean_candidates) > 0) {
        raw <- raw %>% dplyr::rename(Mean = !!rlang::sym(mean_candidates[1]))
      }
    }
    if (!"RawIntDen" %in% names(raw)) {
      rawintden_candidates <- grep("^RawIntDen(\\.\\.\\.)?", names(raw), value = TRUE)
      if (length(rawintden_candidates) > 0) {
        raw <- raw %>% dplyr::rename(RawIntDen = !!rlang::sym(rawintden_candidates[1]))
      }
    }
    # Backward compatibility: older files may not have a `treatment` column
    if (!"treatment" %in% names(raw)) {
      raw$treatment <- "control"
    }
    
    df <- raw %>%
      dplyr::select(
        dplyr::any_of(c(
          "genotype", "treatment", "short", "dye_concentration", "dye_time", "dye", "well", "test",
          "Area", "Mean", "IntDen", "RawIntDen"
        ))
      ) %>%
      mutate(
        across(
          any_of(c("Area", "Mean", "IntDen", "RawIntDen")),
          ~ readr::parse_number(as.character(.x))
        )
      ) %>%
      filter(!is.na(genotype)) %>%
      filter(is.na(dye) | dye == "nao") %>%
      mutate(
        genotype = ifelse(tolower(genotype) == "wt", "WT",
                          ifelse(tolower(genotype) == "ho", "HO", NA)),
        genotype = factor(genotype, levels = c("WT", "HO")),
        # treatment normalization:
        # - keep the original (normalized) label in `treatment_detail` for traceability
        # - collapse into two groups: control vs treated
        treatment_detail = tolower(trimws(as.character(treatment))),
        treatment_detail = ifelse(is.na(treatment_detail) | treatment_detail == "", "control", treatment_detail),
        treatment = dplyr::case_when(
          treatment_detail %in% c("control", "ctrl", "vehicle", "veh", "untreated", "untreatment", "baseline") ~ "control",
          treatment_detail %in% c("treated", "treat") ~ "treated",
          TRUE ~ "treated"  # any other non-control label is treated (e.g., ephb1_fc(500ng/ml)+anti_fc)
        ),
        treatment = factor(treatment, levels = c("control", "treated"))
      )
    
    df <- df %>%
      mutate(
        norm_intden = IntDen / Area,
        log_norm_intden = log2(norm_intden)
      ) %>%
      filter(is.finite(norm_intden), norm_intden > 0)
    
    metric_col <- switch(
      use_metric,
      "Mean" = "Mean",
      "IntDen" = "IntDen",
      "norm_intden" = "norm_intden"
    )
    
    cell_metric <- df %>%
      dplyr::select(treatment, treatment_detail, genotype, well, Area, Mean, IntDen, norm_intden, log_norm_intden) %>%
      mutate(metric_value = .data[[metric_col]])
    
    cell_summary <- cell_metric %>%
      group_by(treatment, genotype) %>%
      summarise(
        n_cell = n(),
        mean = mean(metric_value),
        sd = sd(metric_value),
        median = median(metric_value),
        IQR = IQR(metric_value),
        .groups = "drop"
      )
    
    # WT vs HO within each treatment
    cell_p_genotype_within_treatment <- cell_metric %>%
      group_by(treatment) %>%
      summarise(
        contrast = "WT_vs_HO",
        p_value = tryCatch(wilcox.test(metric_value ~ genotype, data = dplyr::pick(everything()))$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )

    # control vs treated within each genotype
    cell_p_treatment_within_genotype <- cell_metric %>%
      group_by(genotype) %>%
      summarise(
        contrast = "control_vs_treated",
        p_value = tryCatch(wilcox.test(metric_value ~ treatment, data = dplyr::pick(everything()))$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )
    
    well_metric <- cell_metric %>%
      group_by(treatment, genotype, well) %>%
      summarise(
        mean_metric = mean(metric_value),
        n_cell = n(),
        .groups = "drop"
      )
    
    well_summary <- well_metric %>%
      group_by(treatment, genotype) %>%
      summarise(
        n_well = n(),
        mean_of_means = mean(mean_metric),
        sd_of_means = sd(mean_metric),
        .groups = "drop"
      )
    
    # WT vs HO within each treatment (well-level)
    well_p_genotype_within_treatment <- well_metric %>%
      group_by(treatment) %>%
      summarise(
        contrast = "WT_vs_HO",
        p_value = tryCatch(wilcox.test(mean_metric ~ genotype, data = dplyr::pick(everything()))$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )

    # control vs treated within each genotype (well-level)
    well_p_treatment_within_genotype <- well_metric %>%
      group_by(genotype) %>%
      summarise(
        contrast = "control_vs_treated",
        p_value = tryCatch(wilcox.test(mean_metric ~ treatment, data = dplyr::pick(everything()))$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )
    
    area_df <- cell_metric %>%
      select(treatment, genotype, Area, metric_value)
    
    area_cor <- area_df %>%
      group_by(treatment, genotype) %>%
      summarise(
        n = n(),
        cor_spearman = suppressWarnings(cor(Area, metric_value, method = "spearman")),
        .groups = "drop"
      )
    
    cell_subtitle <- paste0(
      "WT vs HO (cell-level) p: ",
      paste0(cell_p_genotype_within_treatment$treatment, "=", signif(cell_p_genotype_within_treatment$p_value, 3), collapse = "; ")
    )

    p_cell <- ggplot(cell_metric, aes(x = genotype, y = metric_value, fill = genotype)) +
      geom_violin(trim = FALSE, alpha = 0.6) +
      geom_jitter(width = 0.15, size = 1, alpha = 0.4) +
      facet_wrap(~ treatment, nrow = 1) +
      labs(
        x = "Genotype", y = metric_col,
        title = paste0(sample_name, ": Cell-level NAO intensity"),
        subtitle = cell_subtitle
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_cell_violin.png"), p_cell, width = 5, height = 5, dpi = 300)
    
    well_subtitle <- paste0(
      "WT vs HO (well-level) p: ",
      paste0(well_p_genotype_within_treatment$treatment, "=", signif(well_p_genotype_within_treatment$p_value, 3), collapse = "; ")
    )

    p_well <- ggplot(well_metric, aes(x = genotype, y = mean_metric)) +
      geom_point(position = position_jitter(width = 0.1), size = 2) +
      stat_summary(fun = mean, geom = "crossbar", width = 0.4, color = "black") +
      facet_wrap(~ treatment, nrow = 1) +
      labs(
        x = "Genotype", y = paste0("Mean ", metric_col),
        title = paste0(sample_name, ": Well-level NAO intensity"),
        subtitle = well_subtitle
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_well_mean.png"), p_well, width = 5, height = 5, dpi = 300)
    
    p_area <- ggplot(area_df, aes(x = Area, y = metric_value, color = genotype)) +
      geom_point(alpha = 0.5, size = 1) +
      geom_smooth(method = "lm", se = FALSE) +
      facet_wrap(~ treatment, nrow = 1) +
      labs(
        x = "Area", y = metric_col,
        title = paste0(sample_name, ": Area vs NAO intensity")
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_area.png"), p_area, width = 6, height = 5, dpi = 300)
    
    # 汇总 p 值信息（单细胞层面与 well 层面，多重比较）
    p_values <- dplyr::bind_rows(
      cell_p_genotype_within_treatment %>% mutate(metric = metric_col, level = "cell", group = treatment),
      cell_p_treatment_within_genotype %>% mutate(metric = metric_col, level = "cell", group = genotype),
      well_p_genotype_within_treatment %>% mutate(metric = metric_col, level = "well", group = treatment),
      well_p_treatment_within_genotype %>% mutate(metric = metric_col, level = "well", group = genotype)
    ) %>%
      dplyr::select(metric, level, contrast, group, p_value)
    output_excel <- paste0(output_prefix, "_stats.xlsx")
    write_xlsx(
      list(
        cell_summary    = cell_summary,
        cell_data       = cell_metric,
        well_summary    = well_summary,
        well_data       = well_metric,
        area_correlation = area_cor,
        p_values        = p_values
      ),
      path = output_excel
    )
  }
}