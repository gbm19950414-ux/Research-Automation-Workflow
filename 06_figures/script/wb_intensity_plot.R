# wb_intensity_plot.R
# Purpose: visualize WB lane intensity tables as bar plots with normalization.
# - Input: multi/single-panel YAML (like wb_panel) + intensity TSV from 04.1_lane_intensity.py
# - Default plot: bar chart
# - Grouping: same treatments + genotype => one group
# - Normalization: phospho/total if total exists else /GAPDH

suppressPackageStartupMessages({
  library(yaml)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
  library(readr)
  library(stringr)
  library(purrr)
  library(tibble)
})

`%||%` <- function(x, y) if (is.null(x)) y else x

read_yaml_safe <- function(path) {
  if (!file.exists(path)) stop("YAML not found: ", path)
  yaml::read_yaml(path)
}

merge_page_like <- function(base, override) {
  # shallow merge for lists
  if (is.null(base)) base <- list()
  if (is.null(override)) return(base)
  for (nm in names(override)) base[[nm]] <- override[[nm]]
  base
}

# ---- config normalization: support single-panel and multi-panel YAML ----
explode_panels <- function(cfg_all, panel_name = NULL) {
  if (is.list(cfg_all$panels) && length(cfg_all$panels) > 0) {
    base_cfg <- cfg_all
    base_cfg$panels <- NULL
    panels <- list()

    for (p in cfg_all$panels) {
      if (is.null(p$name) || !nzchar(p$name)) stop("Each panel under panels: must have non-empty name")
      if (!is.null(panel_name) && as.character(p$name) != as.character(panel_name)) next

      cfg_one <- base_cfg
      cfg_one$name  <- p$name
      cfg_one$bands <- p$bands %||% base_cfg$bands
      cfg_one$lanes <- p$lanes %||% base_cfg$lanes
      cfg_one$page  <- merge_page_like(base_cfg$page, p$page)

      panels[[length(panels) + 1]] <- cfg_one
    }
    if (!is.null(panel_name) && length(panels) == 0) stop("Panel not found in panels: ", panel_name)
    return(panels)
  }

  # single-panel mode
  list(cfg_all)
}

# ---- build lane metadata from YAML lanes.items ----
lane_meta_from_yaml <- function(lanes_cfg) {
  if (is.null(lanes_cfg$items) || length(lanes_cfg$items) == 0) stop("lanes.items missing/empty")
  items <- lanes_cfg$items

  df <- purrr::map_dfr(items, function(it) {
    lane <- as.integer(it$lane %||% NA_integer_)
    genotype <- as.character(it$genotype %||% "")
    tr <- it$treatments %||% list()

    # flatten treatments into columns
    tr_df <- as.list(tr)
    tibble::tibble(lane_index = lane, genotype = genotype) %>%
      dplyr::bind_cols(as_tibble(tr_df))
  })

  # helpful: coerce common time-like column to numeric if possible
  if ("Refeeding (min)" %in% colnames(df)) {
    df[["Refeeding (min)"]] <- suppressWarnings(as.numeric(df[["Refeeding (min)"]]))
  }
  df
}

# ---- band mapping from YAML bands ----
band_map_from_yaml <- function(bands_cfg) {
  if (is.null(bands_cfg) || length(bands_cfg) == 0) stop("bands missing/empty")
  purrr::map_dfr(bands_cfg, function(b) {
    tibble::tibble(
      band_prefix = as.character(b$prefix %||% ""),
      band_label  = as.character(b$label %||% b$prefix %||% "")
    )
  }) %>% dplyr::filter(nzchar(band_prefix))
}

# ---- pick total target for a phospho label (heuristic + optional map) ----
infer_total_label <- function(phospho_label, available_labels, total_map = NULL) {
  if (!is.null(total_map) && !is.null(total_map[[phospho_label]])) {
    cand <- as.character(total_map[[phospho_label]])
    if (cand %in% available_labels) return(cand)
  }

  # Heuristic: p-XXX(...) -> XXX ; strip parentheses; trim
  base1 <- str_replace(phospho_label, "^p-\\s*", "")
  base2 <- str_replace(base1, "\\s*\\(.*\\)\\s*$", "")
  base2 <- str_trim(base2)

  # try exact
  if (base1 %in% available_labels) return(base1)
  if (base2 %in% available_labels) return(base2)

  # try case-insensitive match
  lower <- tolower(available_labels)
  if (tolower(base1) %in% lower) return(available_labels[which(lower == tolower(base1))[1]])
  if (tolower(base2) %in% lower) return(available_labels[which(lower == tolower(base2))[1]])

  NA_character_
}

# ---- normalization: phospho/total if possible else /GAPDH ----
normalize_intensity <- function(df_long, loading_label = "GAPDH", total_map = NULL) {
  # df_long columns: lane_index, band_label, raw (signal_sum), plus metadata columns
  available_labels <- unique(df_long$band_label)

  # phospho candidates: labels starting with "p-" (you can expand later)
  phospho_labels <- available_labels[str_detect(available_labels, "^p-")]

  out <- list()

  for (pl in phospho_labels) {
    total_label <- infer_total_label(pl, available_labels, total_map = total_map)

    denom_label <- NA_character_
    denom_type  <- NA_character_
    if (!is.na(total_label) && nzchar(total_label)) {
      denom_label <- total_label
      denom_type  <- "total"
    } else if (loading_label %in% available_labels) {
      denom_label <- loading_label
      denom_type  <- "loading"
    } else {
      # cannot normalize -> skip
      next
    }

    numer <- df_long %>% dplyr::filter(band_label == pl) %>%
      dplyr::rename(numer_raw = raw) %>%
      dplyr::select(-band_label)

    denom <- df_long %>% dplyr::filter(band_label == denom_label) %>%
      dplyr::rename(denom_raw = raw) %>%
      dplyr::select(-band_label)

    if (!("lane_index" %in% names(numer)) || !("lane_index" %in% names(denom))) {
      stop("normalize_intensity: lane_index missing in numer/denom data")
    }

    merged <- numer %>%
      dplyr::left_join(denom, by = c("lane_index")) %>%
      dplyr::mutate(
        target = pl,
        denom_used = denom_label,
        denom_type = denom_type,
        value = ifelse(is.na(denom_raw) | denom_raw == 0, NA_real_, numer_raw / denom_raw)
      )

    out[[length(out) + 1]] <- merged
  }

  if (length(out) == 0) {
    warning("No phospho targets could be normalized (missing total and loading).")
    return(tibble::tibble())
  }
  dplyr::bind_rows(out)
}

# ---- build group id = genotype + treatments(all columns except lane_index) ----
make_group_id <- function(df_norm) {
  meta_cols <- setdiff(names(df_norm), c("lane_index", "numer_raw", "denom_raw", "value"))
  # treatments cols are those that are not in fixed set
  fixed <- c("genotype", "target", "denom_used", "denom_type")
  treat_cols <- setdiff(meta_cols, fixed)

  df_norm %>%
    dplyr::mutate(
      group_treat = if (length(treat_cols) == 0) "" else
        do.call(paste, c(dplyr::across(dplyr::all_of(treat_cols)), sep = " | ")),
      group_id = paste(genotype, group_treat, sep = " :: ")
    )
}

# ---- bar plot ----
plot_bar <- function(df_norm, panel_name, out_pdf, x_prefer_time = TRUE) {
  df2 <- make_group_id(df_norm)

  # choose x-axis label: prefer numeric time column if exists
  x_col <- NULL
  if (x_prefer_time && ("Refeeding (min)" %in% names(df2))) x_col <- "Refeeding (min)"

  # summarize for bars, keep replicates as points
  # replicate unit: lane_index (since one lane = one sample)
  sum_df <- df2 %>%
    dplyr::group_by(target, genotype, group_id, .add = TRUE) %>%
    dplyr::summarise(
      n = sum(!is.na(value)),
      mean = mean(value, na.rm = TRUE),
      sem = sd(value, na.rm = TRUE) / sqrt(max(1, n)),
      .groups = "drop"
    )

  # build x aesthetic
  if (!is.null(x_col)) {
    # within each target & genotype, group by time
    # ensure numeric ordering
    df2[[x_col]] <- suppressWarnings(as.numeric(df2[[x_col]]))
    sum_df[[x_col]] <- suppressWarnings(as.numeric(sum_df[[x_col]] %||% NA_real_))
  }

  p <- ggplot() +
    geom_col(
      data = sum_df,
      aes(x = if (!is.null(x_col)) !!rlang::sym(x_col) else group_id, y = mean, fill = genotype),
      position = position_dodge(width = 0.85),
      width = 0.75
    ) +
    geom_errorbar(
      data = sum_df,
      aes(x = if (!is.null(x_col)) !!rlang::sym(x_col) else group_id, ymin = mean - sem, ymax = mean + sem, group = genotype),
      position = position_dodge(width = 0.85),
      width = 0.25
    ) +
    geom_point(
      data = df2,
      aes(x = if (!is.null(x_col)) !!rlang::sym(x_col) else group_id, y = value, shape = genotype),
      position = position_jitterdodge(jitter.width = 0.10, dodge.width = 0.85),
      size = 1.7,
      alpha = 0.85
    ) +
    facet_wrap(~ target, scales = "free_y") +
    labs(
      title = panel_name,
      x = if (!is.null(x_col)) x_col else "Group (genotype + treatments)",
      y = "Normalized intensity",
      fill = "Genotype",
      shape = "Genotype"
    ) +
    theme_bw(base_size = 10) +
    theme(
      panel.grid.minor = element_blank(),
      axis.text.x = element_text(angle = if (is.null(x_col)) 45 else 0, hjust = 1)
    )

  ggsave(out_pdf, p, width = 8.5, height = 5.5, units = "in")
}

# ---- main entry: run one panel ----
run_panel_intensity_plot <- function(root, panel_cfg, intensity_dir_rel = "04_data/interim/wb/intensity",
                                     signal_field = "signal_sum",
                                     loading_label = "GAPDH",
                                     total_map = NULL,
                                     out_dir_rel = "06_figures/results",
                                     out_suffix = "intensity_bar") {
  panel_name <- panel_cfg$name %||% "panel"
  lanes_cfg <- panel_cfg$lanes
  bands_cfg <- panel_cfg$bands

  lane_meta <- lane_meta_from_yaml(lanes_cfg)
  band_map  <- band_map_from_yaml(bands_cfg)

  # read intensity TSV
  tsv_path <- file.path(root, intensity_dir_rel, paste0(panel_name, ".lane_intensity.tsv"))
  if (!file.exists(tsv_path)) stop("Intensity TSV not found: ", tsv_path)

  df_raw <- readr::read_tsv(tsv_path, show_col_types = FALSE)

  # choose raw signal column
  if (!(signal_field %in% names(df_raw))) stop("signal_field not found in TSV: ", signal_field)

  df_use <- df_raw %>%
    dplyr::mutate(lane_index = as.integer(lane_index)) %>%
    dplyr::select(panel, lane_index, band_prefix, !!rlang::sym(signal_field)) %>%
    dplyr::rename(raw = !!rlang::sym(signal_field)) %>%
    dplyr::left_join(band_map, by = "band_prefix") %>%
    dplyr::left_join(lane_meta, by = "lane_index")

  # normalize
  df_norm <- normalize_intensity(df_use, loading_label = loading_label, total_map = total_map)
  if (nrow(df_norm) == 0) {
    warning("No normalized values produced for panel: ", panel_name)
    return(invisible(NULL))
  }

  # output
  out_dir <- file.path(root, out_dir_rel, panel_name)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  out_pdf <- file.path(out_dir, paste0(panel_name, ".", out_suffix, ".pdf"))

  plot_bar(df_norm, panel_name = panel_name, out_pdf = out_pdf, x_prefer_time = TRUE)
  message("[OK] intensity bar plot saved → ", out_pdf)
  invisible(out_pdf)
}

# ---- main entry: run from YAML config (multi-panel supported) ----
run_intensity_plots_from_yaml <- function(root, config_rel, panel = NULL,
                                         intensity_dir_rel = "04_data/interim/wb/intensity",
                                         signal_field = "signal_sum",
                                         loading_label = "GAPDH",
                                         total_map = NULL,
                                         out_dir_rel = "06_figures/results") {
  cfg_path <- file.path(root, config_rel)
  cfg_all <- read_yaml_safe(cfg_path)
  panels <- explode_panels(cfg_all, panel_name = panel)

  for (pcfg in panels) {
    if (is.null(pcfg$bands) || is.null(pcfg$lanes)) {
      warning("Skip panel (missing bands/lanes): ", pcfg$name %||% "<no-name>")
      next
    }
    run_panel_intensity_plot(
      root = root,
      panel_cfg = pcfg,
      intensity_dir_rel = intensity_dir_rel,
      signal_field = signal_field,
      loading_label = loading_label,
      total_map = total_map,
      out_dir_rel = out_dir_rel
    )
  }
  invisible(TRUE)
}