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
  "04_data/raw/imaging_if/E36_NAO/E36_statistic.xlsx",
  "04_data/raw/imaging_if/E39_NAO/E39_statistic.xlsx"
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
        # - do NOT collapse to 2 groups; support 3+ treatments
        treatment_detail = tolower(trimws(as.character(treatment))),
        treatment_detail = ifelse(is.na(treatment_detail) | treatment_detail == "", "control", treatment_detail),
        treatment = dplyr::case_when(
          treatment_detail %in% c("control", "ctrl", "vehicle", "veh", "untreated", "untreatment", "baseline") ~ "control",
          # allow a few generic names
          treatment_detail %in% c("treated", "treat") ~ "treated",
          TRUE ~ treatment_detail
        )
      )
    
    # Set treatment factor levels dynamically (control first if present)
    trt_levels <- sort(unique(as.character(df$treatment)))
    if ("control" %in% trt_levels) {
      trt_levels <- c("control", setdiff(trt_levels, "control"))
    }
    df <- df %>% mutate(treatment = factor(as.character(treatment), levels = trt_levels))
    
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
    
    # ---------- Robust Z-score outlier detection ----------
    cell_metric <- cell_metric %>%
      group_by(treatment, genotype) %>%
      mutate(
        median_val = median(metric_value, na.rm = TRUE),
        mad_val    = mad(metric_value, constant = 1.4826, na.rm = TRUE),
        z_robust   = ifelse(mad_val > 0,
                            (metric_value - median_val) / mad_val,
                            NA_real_),
        is_outlier = abs(z_robust) > 3
      ) %>%
      ungroup()

    # Option A: 剔除离群值（最常用）
    cell_metric <- cell_metric %>%
      filter(!is_outlier | is.na(is_outlier))

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
        p_value = tryCatch(wilcox.test(metric_value ~ genotype, data = dplyr::pick(everything()), exact = FALSE)$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )

    # treatment comparisons within each genotype
    # - if 2 treatments: Wilcoxon (same as before)
    # - if 3+ treatments: pairwise Wilcoxon with BH adjustment
    cell_p_treatment_within_genotype <- cell_metric %>%
      group_by(genotype) %>%
      group_modify(~{
        d <- .x %>% filter(!is.na(treatment), !is.na(metric_value))
        trt <- droplevels(d$treatment)
        k <- nlevels(trt)
        if (k < 2) {
          return(tibble(contrast = "treatment_pairwise", group1 = NA_character_, group2 = NA_character_, p_value = NA_real_, p_adj = NA_real_))
        }
        if (k == 2) {
          pv <- tryCatch(wilcox.test(metric_value ~ treatment, data = d, exact = FALSE)$p.value, error = function(e) NA_real_)
          levs <- levels(trt)
          return(tibble(contrast = "treatment_pairwise", group1 = levs[1], group2 = levs[2], p_value = pv, p_adj = pv))
        }
        pw <- tryCatch(stats::pairwise.wilcox.test(d$metric_value, d$treatment, p.adjust.method = "BH"),
                       error = function(e) NULL)
        if (is.null(pw)) {
          return(tibble(contrast = "treatment_pairwise", group1 = NA_character_, group2 = NA_character_, p_value = NA_real_, p_adj = NA_real_))
        }
        m_p   <- pw$p.value
        m_adj <- pw$p.value  # pairwise.wilcox.test already returns adjusted p-values when p.adjust.method is set
        rn <- rownames(m_p)
        cn <- colnames(m_p)
        out <- list()
        idx <- 1
        for (i in seq_along(rn)) {
          for (j in seq_along(cn)) {
            pv <- m_p[i, j]
            if (!is.na(pv)) {
              out[[idx]] <- tibble(contrast = "treatment_pairwise", group1 = rn[i], group2 = cn[j], p_value = pv, p_adj = pv)
              idx <- idx + 1
            }
          }
        }
        bind_rows(out)
      }) %>%
      ungroup()
    
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
        p_value = tryCatch(wilcox.test(mean_metric ~ genotype, data = dplyr::pick(everything()), exact = FALSE)$p.value,
                           error = function(e) NA_real_),
        .groups = "drop"
      )

    # treatment comparisons within each genotype (well-level)
    well_p_treatment_within_genotype <- well_metric %>%
      group_by(genotype) %>%
      group_modify(~{
        d <- .x %>% filter(!is.na(treatment), !is.na(mean_metric))
        trt <- droplevels(d$treatment)
        k <- nlevels(trt)
        if (k < 2) {
          return(tibble(contrast = "treatment_pairwise", group1 = NA_character_, group2 = NA_character_, p_value = NA_real_, p_adj = NA_real_))
        }
        if (k == 2) {
          pv <- tryCatch(wilcox.test(mean_metric ~ treatment, data = d, exact = FALSE)$p.value, error = function(e) NA_real_)
          levs <- levels(trt)
          return(tibble(contrast = "treatment_pairwise", group1 = levs[1], group2 = levs[2], p_value = pv, p_adj = pv))
        }
        pw <- tryCatch(stats::pairwise.wilcox.test(d$mean_metric, d$treatment, p.adjust.method = "BH"),
                       error = function(e) NULL)
        if (is.null(pw)) {
          return(tibble(contrast = "treatment_pairwise", group1 = NA_character_, group2 = NA_character_, p_value = NA_real_, p_adj = NA_real_))
        }
        m_p <- pw$p.value
        rn <- rownames(m_p)
        cn <- colnames(m_p)
        out <- list(); idx <- 1
        for (i in seq_along(rn)) {
          for (j in seq_along(cn)) {
            pv <- m_p[i, j]
            if (!is.na(pv)) {
              out[[idx]] <- tibble(contrast = "treatment_pairwise", group1 = rn[i], group2 = cn[j], p_value = pv, p_adj = pv)
              idx <- idx + 1
            }
          }
        }
        bind_rows(out)
      }) %>%
      ungroup()
    
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
      # genotype test within each treatment
      cell_p_genotype_within_treatment %>% mutate(metric = metric_col, level = "cell", group = as.character(treatment), group1 = "WT", group2 = "HO", p_adj = p_value),
      # treatment pairwise within each genotype
      cell_p_treatment_within_genotype %>% mutate(metric = metric_col, level = "cell", group = as.character(genotype)),
      # genotype test within each treatment (well-level)
      well_p_genotype_within_treatment %>% mutate(metric = metric_col, level = "well", group = as.character(treatment), group1 = "WT", group2 = "HO", p_adj = p_value),
      # treatment pairwise within each genotype (well-level)
      well_p_treatment_within_genotype %>% mutate(metric = metric_col, level = "well", group = as.character(genotype))
    ) %>%
      dplyr::mutate(
        group1 = as.character(group1),
        group2 = as.character(group2),
        p_adj  = as.numeric(p_adj)
      ) %>%
      dplyr::select(metric, level, contrast, group, group1, group2, p_value, p_adj)
    
    output_excel <- paste0(output_prefix, "_stats.xlsx")

    # ---- NEW: pairwise treatment stats formatted for x-vs-x plotting (all genotypes) ----
    # For violin/box panels where x is an interaction like "<treatment>_<genotype>",
    # this sheet provides x1/x2 + p_value per genotype.
    treatment_pair_stats <- p_values %>%
      filter(contrast == "treatment_pairwise") %>%
      mutate(
        # here `group` is genotype (WT/HO) for treatment_pairwise rows
        genotype = as.character(group),
        x1 = paste0(group1, "_", genotype),
        x2 = paste0(group2, "_", genotype)
      ) %>%
      select(metric, level, genotype, group1, group2, x1, x2, p_value, p_adj)

    write_xlsx(
      list(
        cell_summary    = cell_summary,
        cell_data       = cell_metric,
        well_summary    = well_summary,
        well_data       = well_metric,
        area_correlation = area_cor,
        treatment_pair_stats = treatment_pair_stats,
        p_values        = p_values
      ),
      path = output_excel
    )
  }
}