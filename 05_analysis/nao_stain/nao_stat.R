###############################
## NAO 统计分析与绘图脚本 (R)
## 1) 单细胞水平 WT vs HO
## 2) well 水平 WT vs HO
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
  "04_data/raw/imaging_if/E30_NAO/E30_statistic.xlsx"
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
  sheet_name <- 1
  
  # auto-generate sample name from filename
  sample_name <- tools::file_path_sans_ext(basename(input_file))
  
  for (use_metric in metrics) {
    message("  Using metric: ", use_metric)
    
    output_prefix <- file.path(output_dir, paste0(sample_name, "_", use_metric))
    
    raw <- read_excel(input_file, sheet = sheet_name)
    
    df <- raw %>%
      dplyr::select(
        genotype, short, dye_concentration, dye_time, dye, well, test,
        Area, Mean, IntDen, RawIntDen
      ) %>%
      filter(!is.na(genotype)) %>%
      filter(is.na(dye) | dye == "nao") %>%
      mutate(
        genotype = tolower(genotype),
        genotype = factor(genotype, levels = c("wt", "ho"))
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
      dplyr::select(genotype, well, Area, Mean, IntDen, norm_intden, log_norm_intden) %>%
      mutate(metric_value = .data[[metric_col]])
    
    cell_summary <- cell_metric %>%
      group_by(genotype) %>%
      summarise(
        n_cell = n(),
        mean = mean(metric_value),
        sd = sd(metric_value),
        median = median(metric_value),
        IQR = IQR(metric_value),
        .groups = "drop"
      )
    
    cell_test <- wilcox.test(metric_value ~ genotype, data = cell_metric)
    cell_p_value <- cell_test$p.value
    
    well_metric <- cell_metric %>%
      group_by(genotype, well) %>%
      summarise(
        mean_metric = mean(metric_value),
        n_cell = n(),
        .groups = "drop"
      )
    
    well_summary <- well_metric %>%
      group_by(genotype) %>%
      summarise(
        n_well = n(),
        mean_of_means = mean(mean_metric),
        sd_of_means = sd(mean_metric),
        .groups = "drop"
      )
    
    well_test <- wilcox.test(mean_metric ~ genotype, data = well_metric)
    well_p_value <- well_test$p.value
    
    area_df <- cell_metric %>%
      select(genotype, Area, metric_value)
    
    area_cor <- area_df %>%
      group_by(genotype) %>%
      summarise(
        n = n(),
        cor_spearman = suppressWarnings(cor(Area, metric_value, method = "spearman")),
        .groups = "drop"
      )
    
    p_cell <- ggplot(cell_metric, aes(x = genotype, y = metric_value, fill = genotype)) +
      geom_violin(trim = FALSE, alpha = 0.6) +
      geom_jitter(width = 0.15, size = 1, alpha = 0.4) +
      labs(
        x = "Genotype", y = metric_col,
        title = paste0(sample_name, ": Cell-level NAO intensity"),
        subtitle = paste0("Wilcoxon p = ", signif(cell_p_value, 3))
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_cell_violin.png"), p_cell, width = 5, height = 5, dpi = 300)
    
    p_well <- ggplot(well_metric, aes(x = genotype, y = mean_metric)) +
      geom_point(position = position_jitter(width = 0.1), size = 2) +
      stat_summary(fun = mean, geom = "crossbar", width = 0.4, color = "black") +
      labs(
        x = "Genotype", y = paste0("Mean ", metric_col),
        title = paste0(sample_name, ": Well-level NAO intensity"),
        subtitle = paste0("Wilcoxon p = ", signif(well_p_value, 3))
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_well_mean.png"), p_well, width = 5, height = 5, dpi = 300)
    
    p_area <- ggplot(area_df, aes(x = Area, y = metric_value, color = genotype)) +
      geom_point(alpha = 0.5, size = 1) +
      geom_smooth(method = "lm", se = FALSE) +
      labs(
        x = "Area", y = metric_col,
        title = paste0(sample_name, ": Area vs NAO intensity")
      ) +
      theme_pub()
    
    ggsave(paste0(output_prefix, "_area.png"), p_area, width = 6, height = 5, dpi = 300)
    
    output_excel <- paste0(output_prefix, "_stats.xlsx")
    write_xlsx(
      list(
        cell_summary = cell_summary,
        cell_data = cell_metric,
        well_summary = well_summary,
        well_data = well_metric,
        area_correlation = area_cor
      ),
      path = output_excel
    )
  }
}