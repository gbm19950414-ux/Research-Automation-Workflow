#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
  library(readxl)
  library(dplyr)
  library(purrr)
  library(rlang)
  library(ggplot2)
})

`%||%` <- function(a, b) if (!is.null(a)) a else b

mm_to_in <- function(mm, mm_per_inch = 25.4) {
  mm / mm_per_inch
}

# （预留：以后如果想在 AUC 图里也加星号，可以用这个）
p_to_stars <- function(p) {
  ifelse(
    is.na(p), "",
    ifelse(
      p <= 0.001, "***",
      ifelse(p <= 0.01, "**",
             ifelse(p <= 0.05, "*", ""))
    )
  )
}

# 过滤函数：支持 yaml 中 filter: 下的简单等值过滤
apply_filters <- function(df, flt) {
  if (is.null(flt) || length(flt) == 0) return(df)
  out <- df
  for (nm in names(flt)) {
    vals <- flt[[nm]]
    if (!nm %in% names(out)) next
    out <- out[out[[nm]] %in% vals, , drop = FALSE]
  }
  out
}

# 计算每条曲线（一个 sample / gene / drug / group / dye / 浓度）的 AUC
compute_auc_per_curve <- function(df, x_col, y_col, group_cols) {
  df %>%
    dplyr::filter(!is.na(.data[[y_col]])) %>%
    dplyr::group_by(dplyr::across(all_of(group_cols))) %>%
    dplyr::group_modify(function(dat, key) {
      x <- dat[[x_col]]
      y <- dat[[y_col]]

      ord <- order(x)
      x <- x[ord]
      y <- y[ord]

      if (length(x) < 2) {
        tibble(auc = NA_real_)
      } else {
        dx <- diff(x)
        y_mid <- (y[-1] + y[-length(y)]) / 2
        auc <- sum(dx * y_mid)
        tibble(auc = auc)
      }
    }) %>%
    dplyr::ungroup()
}

# 将 gene 标注成 genotype（WT / HO）
label_genotype <- function(gene) {
  g <- tolower(as.character(gene))
  ifelse(
    grepl("wt", g), "WT",
    ifelse(grepl("ho", g), "HO", NA_character_)
  )
}

welch_p <- function(a, b) {
  a <- as.numeric(a)
  b <- as.numeric(b)
  a <- a[!is.na(a)]
  b <- b[!is.na(b)]
  if (length(a) < 2 || length(b) < 2) {
    return(NA_real_)
  }
  stats::t.test(a, b, var.equal = FALSE)$p.value
}

# 🔴 核心接口：给 figure_3_b.R 调用的函数
#    注意：签名必须是 (cfg_path, out_dir, out_basename)
draw_auc_from_yaml <- function(cfg_path, out_dir, out_basename) {
  cfg <- yaml::read_yaml(cfg_path)
  if (is.null(cfg$panels) || length(cfg$panels) == 0) {
    stop("YAML 中未找到 panels 配置。")
  }

  # figure_3_b.R 已经为每个 panel 写好了单独的临时 yaml，
  # 所以这里取 cfg$panels[[1]] 即可
  panel   <- cfg$panels[[1]]
  mapping <- panel$mapping

  # AUC 源文件优先使用 panel$auc_data，其次回退到 panel$data
  data_path <- panel$auc_data %||% panel$data
  sheet     <- panel$auc_sheet %||% panel$sheet %||% 1

  value_col <- mapping$auc_value_col %||% "value_t0_ratio"
  x_var     <- mapping$x
  hue_var   <- mapping$hue %||% "genotype"

  # 定义一条时间曲线的分组键（可通过 mapping$auc_curve_group_cols 覆盖）
  default_curve_groups <- c(
    "sample_batch",
    "gene",
    "drug",
    "group",
    "dye",
    "Dye_concentration",
    "Dye_time"
  )
  curve_group_cols <- mapping$auc_curve_group_cols %||% default_curve_groups

  message("[AUC] 读取数据: ", data_path)
  df_raw <- readxl::read_xlsx(data_path, sheet = sheet)

  # 过滤（例如 drug, Dye_concentration 等）
  df_flt <- apply_filters(df_raw, panel$filter %||% list())
  message("[AUC] 过滤后行数: ", nrow(df_flt))

  # 逐条时间曲线计算 AUC
  df_auc_samples <- compute_auc_per_curve(
    df = df_flt,
    x_col = x_var,
    y_col = value_col,
    group_cols = curve_group_cols
  )

  # 标注 genotype（WT / HO）
  if (!"gene" %in% names(df_auc_samples)) {
    stop("AUC 源数据中缺少 'gene' 列，无法标注 WT / HO。")
  }
  df_auc_samples <- df_auc_samples %>%
    dplyr::mutate(
      genotype = label_genotype(.data[["gene"]])
    ) %>%
    dplyr::filter(!is.na(genotype))

  # 按 genotype 汇总 AUC 的 mean / sd / n
  df_auc_summary <- df_auc_samples %>%
    dplyr::group_by(.data[[hue_var]]) %>%
    dplyr::summarise(
      auc_mean = mean(auc, na.rm = TRUE),
      auc_sd   = ifelse(sum(!is.na(auc)) > 1, stats::sd(auc, na.rm = TRUE), NA_real_),
      auc_n    = sum(!is.na(auc)),
      .groups  = "drop"
    )

  # 计算 WT vs HO 的 p 值（若存在这两个水平）
  p_val <- NA_real_
  if (hue_var == "genotype" &&
      all(c("WT", "HO") %in% df_auc_samples[[hue_var]])) {
    wt_auc <- df_auc_samples$auc[df_auc_samples[[hue_var]] == "WT"]
    ho_auc <- df_auc_samples$auc[df_auc_samples[[hue_var]] == "HO"]
    p_val  <- welch_p(wt_auc, ho_auc)
  }

  message("[AUC] per-sample AUC 汇总：")
  print(df_auc_summary)
  message("[AUC] WT vs HO p 值: ", p_val)

  # 仅负责统计分析：返回每个 sample 的 AUC、汇总结果和 p 值，不在本脚本中绘图
  res <- list(
    samples = df_auc_samples,
    summary = df_auc_summary,
    p_value = p_val
  )
  return(invisible(res))
}