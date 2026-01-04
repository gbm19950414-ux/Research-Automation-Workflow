#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
  library(readxl)
  library(dplyr)
  library(ggplot2)
  library(rlang)
  library(grid)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript violin.R <panel_yaml>")

panel_yaml_path <- args[1]
panel_cfg <- yaml::read_yaml(panel_yaml_path)

project_root <- normalizePath(file.path(dirname(panel_yaml_path), "..", ".."))

# style
style_yaml_path <- file.path(project_root, "02_protocols/figure_style_nature.yaml")
style_cfg <- yaml::read_yaml(style_yaml_path)

# extract typography, line, and layout defaults from style yaml
typography   <- style_cfg$typography
sizes_pt     <- typography$sizes_pt
font_family  <- typography$font_family_primary %||% "Helvetica"

line_cfg     <- style_cfg$lines
layout_style <- style_cfg$layout

# geom/style (optional; if absent, fall back to sensible defaults)
geoms_cfg    <- style_cfg$geoms %||% list()
violin_cfg   <- geoms_cfg$violin %||% list()
jitter_cfg   <- geoms_cfg$jitter %||% list()
bracket_cfg  <- geoms_cfg$stats_bracket %||% list()
legend_cfg   <- style_cfg$legend %||% list()

# ---- Unit helpers ----
mm_per_inch <- style_cfg$units$mm_per_inch %||% 25.4
mm_to_pt <- function(mm) (72/mm_per_inch) * mm
pt_to_mm <- function(pt) pt * mm_per_inch / 72

# ggplot linewidth is not in pt; box_panel_from_yaml.R uses an empirical pt->linewidth scale
pt_per_lwd <- style_cfg$lines$r_lwd_scale$pt_per_lwd %||% 0.75
pt_to_lwd  <- function(pt) pt / pt_per_lwd

# ggplot text/point size is also not pt; box_panel_from_yaml.R uses pt/2.5
pt_to_text_size <- function(pt) pt / 2.5

# fallbacks for sizes
axis_label_size   <- sizes_pt$axis_label_default   %||% 6.5
axis_tick_size    <- sizes_pt$axis_tick_default    %||% 5.5
legend_text_size  <- sizes_pt$legend_text_default  %||% axis_tick_size
legend_title_size <- sizes_pt$legend_title_default %||% axis_label_size

axis_title_margin_cfg <- layout_style$axis_title_margin_pt
style_plot_margin     <- layout_style$plot_margin_pt

# ---- Layout from panel yaml ----
layout_cfg <- panel_cfg$layout
outer_frac <- layout_cfg$axis_outer_frac
# gap_pt is treated as the final spacing (NOT additive with style axis_title_margin_pt)
gap_pt     <- layout_cfg$axis_gap_pt

width_mm  <- panel_cfg$size$width_mm
height_mm <- panel_cfg$size$high_mm

# style-level plot margins in pt
style_margin_top    <- style_plot_margin$top    %||% 0
style_margin_bottom <- style_plot_margin$bottom %||% 0
style_margin_left   <- style_plot_margin$left   %||% 0
style_margin_right  <- style_plot_margin$right  %||% 0

# combine style margins with panel outer_frac-based margins
plot_margin_pt <- list(
  top    = style_margin_top    + mm_to_pt((outer_frac$top    %||% 0) * height_mm),
  bottom = style_margin_bottom + mm_to_pt((outer_frac$bottom %||% 0) * height_mm),
  left   = style_margin_left   + mm_to_pt((outer_frac$left   %||% 0) * width_mm),
  right  = style_margin_right  + mm_to_pt((outer_frac$right  %||% 0) * width_mm)
)

# p to symbol
p_to_symbol <- function(p){
  if (is.na(p)) return("ns")
  if (p < 0.0001) return("****")
  if (p < 0.001) return("***")
  if (p < 0.01) return("**")
  if (p < 0.05) return("*")
  "ns"
}

# Case-insensitive palette mapping helper
get_palette <- function(pal, levels_vec) {
  if (is.null(pal)) return(NULL)
  if (is.list(pal)) pal <- unlist(pal)
  pal <- as.character(pal)
  if (is.null(names(pal))) {
    out <- rep(pal, length.out = length(levels_vec))
    names(out) <- levels_vec
    return(out)
  }
  pal_names_l <- tolower(names(pal))
  out <- vapply(levels_vec, function(k) {
    idx <- match(tolower(k), pal_names_l)
    if (is.na(idx)) NA_character_ else pal[[idx]]
  }, character(1))
  names(out) <- levels_vec
  if (any(is.na(out))) {
    fallback <- rep(unname(pal), length.out = length(levels_vec))
    names(fallback) <- levels_vec
    out[is.na(out)] <- fallback[is.na(out)]
  }
  out
}

# Build bracket segments for pairwise annotations
make_brackets <- function(df, y_col, order_levels, pairs, p_values = NULL,
                          y_start_mult = 1.05, y_step_mult = 0.08) {
  ymax <- max(df[[y_col]], na.rm = TRUE)
  if (!is.finite(ymax) || ymax <= 0) ymax <- 1
  if (is.null(p_values)) p_values <- rep(NA_real_, length(pairs))
  stopifnot(length(p_values) == length(pairs))

  br <- lapply(seq_along(pairs), function(i) {
    a <- pairs[[i]][1]
    b <- pairs[[i]][2]
    x1 <- match(a, order_levels)
    x2 <- match(b, order_levels)
    if (is.na(x1) || is.na(x2)) {
      stop("Stats pair not found in panel$order: ", a, " vs ", b)
    }
    if (x2 < x1) { tmp <- x1; x1 <- x2; x2 <- tmp }
    y <- ymax * (y_start_mult + (i - 1) * y_step_mult)
    tibble(
      x1 = x1, x2 = x2,
      y = y,
      label = p_to_symbol(p_values[[i]]),
      x_center = (x1 + x2) / 2
    )
  })
  dplyr::bind_rows(br)
}

# --- Iterate panels ---
for (panel in panel_cfg$panels){

  message("[INFO] Plotting panel ", panel$id)

  df <- read_excel(file.path(project_root, panel$data), sheet = panel$sheet)

  x_var <- panel$mapping$x
  y_var <- panel$mapping$y
  hue_var <- panel$mapping$hue

  # Optional: build an interaction x variable from multiple columns
  x_interaction <- panel$mapping$x_interaction %||% NULL
  x_sep <- panel$mapping$x_sep %||% "_"
  if (!is.null(x_interaction)) {
    x_interaction <- as.character(unlist(x_interaction))
    stopifnot(length(x_interaction) >= 2)
    missing_cols <- setdiff(x_interaction, names(df))
    if (length(missing_cols) > 0) {
      stop("Missing columns for x_interaction: ", paste(missing_cols, collapse = ", "))
    }
    if (!is.null(hue_var) && identical(x_var, hue_var)) {
      stop("mapping$x_interaction would overwrite the hue column ('", hue_var, "'). ",
           "Please set mapping$x to a new column name like 'group' and keep mapping$hue = 'genotype'.")
    }
    df[[x_var]] <- do.call(paste, c(df[x_interaction], sep = x_sep))
  }

  # Optional: facet
  facet_var <- panel$mapping$facet %||% NULL
  if (!is.null(facet_var) && !facet_var %in% names(df)) {
    stop("Facet column not found: ", facet_var)
  }

  df <- df %>%
    filter(!is.na(.data[[x_var]]))

  df <- df %>%
    mutate(
      !!sym(x_var) := factor(.data[[x_var]], levels = panel$order),
      x_pos = as.numeric(.data[[x_var]])
    )

  if (any(is.na(df$x_pos))) {
    bad_x <- unique(as.character(df[[x_var]][is.na(df$x_pos)]))
    message("[WARN] Some x values are not in panel$order and were dropped: ",
            paste(head(bad_x, 10), collapse = ", "))
    df <- df %>% filter(!is.na(x_pos))
  }

  if (!is.null(hue_var) && hue_var %in% names(df)) {
    hue_vals <- unique(as.character(df[[hue_var]]))
    hue_levels <- panel$hue_order %||% sort(hue_vals)
    hue_levels <- unique(c(as.character(hue_levels), sort(setdiff(hue_vals, hue_levels))))
    df <- df %>% mutate(!!sym(hue_var) := factor(as.character(.data[[hue_var]]), levels = hue_levels))
  }

  # --- stats ---
  brackets_df <- NULL
  if (panel$stats$enabled){
    stats_raw <- read_excel(
      file.path(project_root, panel$stats$source),
      sheet = panel$stats$sheet
    )

    pairs <- panel$stats$pairs %||% list()
    if (length(pairs) == 0) {
      pairs <- list(panel$order[1:2])
    }

    p_vals <- rep(NA_real_, length(pairs))

    if (all(c("p_value") %in% names(stats_raw))) {
      if (all(c("level", "contrast", "group") %in% names(stats_raw)) && !is.null(panel$stats$pair_groups)) {
        lvl <- panel$stats$level %||% "cell"
        ctr <- panel$stats$contrast %||% "WT_vs_HO"
        grp_vec <- as.character(unlist(panel$stats$pair_groups))
        if (length(grp_vec) != length(pairs)) {
          stop("stats$pair_groups length must match stats$pairs length")
        }
        for (i in seq_along(pairs)) {
          r <- stats_raw %>%
            filter(.data[["level"]] == lvl, .data[["contrast"]] == ctr, as.character(.data[["group"]]) == grp_vec[[i]])
          if (nrow(r) >= 1) p_vals[[i]] <- r[["p_value"]][1]
        }
      } else {
        p_vals[] <- stats_raw[[panel$stats$column]][1]
      }
    }

    brackets_df <- make_brackets(
      df, y_var, panel$order, pairs, p_vals,
      y_start_mult = (bracket_cfg$y_start_mult %||% 1.05),
      y_step_mult  = (bracket_cfg$y_step_mult %||% 0.08)
    )
  }

  hue_levels_for_pal <- if (!is.null(hue_var) && hue_var %in% names(df)) levels(df[[hue_var]]) else NULL
  fill_pal <- get_palette(style_cfg$colors$wt_ho, hue_levels_for_pal %||% panel$hue_order %||% character(0))

  x_labels <- panel$order
  if (!is.null(panel$rename_x)) {
    x_labels <- vapply(panel$order, function(k) {
      v <- panel$rename_x[[k]]
      if (is.null(v)) k else as.character(v)
    }, character(1))
  }

  if (!is.null(hue_var) && hue_var %in% names(df)) {
    p <- ggplot(df, aes(x = x_pos, y = .data[[y_var]])) +
      geom_violin(
        aes(fill = .data[[hue_var]], group = x_pos),
        trim = FALSE,
        alpha = (violin_cfg$alpha %||% 0.85),
        linewidth = pt_to_lwd(violin_cfg$line_width_pt %||% line_cfg$boxplot_default_pt %||% line_cfg$line_width_pt %||% 0.25),
        color = (violin_cfg$edge_color %||% "black")
      ) +
      geom_jitter(
        aes(color = .data[[hue_var]]),
        width = (jitter_cfg$width %||% 0.1),
        size   = (jitter_cfg$size_mm %||% 1.4),
        shape = (jitter_cfg$shape %||% 16),
        alpha = (jitter_cfg$alpha %||% 1)
      ) +
      scale_fill_manual(values = fill_pal) +
      scale_color_manual(values = fill_pal)
  } else {
    p <- ggplot(df, aes(x = x_pos, y = .data[[y_var]])) +
      geom_violin(
        aes(group = x_pos),
        trim = FALSE,
        alpha = (violin_cfg$alpha %||% 0.85),
        linewidth = pt_to_lwd(violin_cfg$line_width_pt %||% line_cfg$boxplot_default_pt %||% line_cfg$line_width_pt %||% 0.25),
        color = (violin_cfg$edge_color %||% "black"),
        fill = (violin_cfg$fill_no_hue %||% "grey80")
      ) +
      geom_jitter(
        width = (jitter_cfg$width %||% 0.1),
        size   = (jitter_cfg$size_mm %||% 1.4),
        shape = (jitter_cfg$shape %||% 16),
        alpha = (jitter_cfg$alpha %||% 1)
      )
  }

  p <- p +
    scale_x_continuous(
      breaks = seq_along(panel$order),
      labels = x_labels
    ) +
    labs(x = panel$x_label, y = panel$y_label) +
    theme_classic(base_size = axis_tick_size, base_family = font_family) +
    theme(
      text = element_text(family = font_family),
      axis.title.x = element_text(
        size = axis_label_size,
        margin = margin(t = (gap_pt$x_title_to_ticks %||% (axis_title_margin_cfg$x %||% 0)))
      ),
      axis.title.y = element_text(
        size = axis_label_size,
        margin = margin(r = (gap_pt$y_title_to_ticks %||% (axis_title_margin_cfg$y %||% 0)))
      ),
      axis.text.x = element_text(
        size = axis_tick_size,
        margin = margin(t = gap_pt$x_ticks_to_axis %||% 0)
      ),
      axis.text.y = element_text(
        size = axis_tick_size,
        margin = margin(r = gap_pt$y_ticks_to_axis %||% 0)
      ),
      axis.line  = element_line(linewidth = pt_to_lwd(line_cfg$axis_line_default_pt %||% 0.25), colour = "black"),
      axis.ticks = element_line(linewidth = pt_to_lwd(line_cfg$axis_line_default_pt %||% 0.25), colour = "black"),
      legend.text  = element_text(size = legend_text_size),
      legend.title = element_text(size = legend_title_size),

      plot.margin = margin(
        plot_margin_pt$top,
        plot_margin_pt$right,
        plot_margin_pt$bottom,
        plot_margin_pt$left
      ),

      legend.position      = (legend_cfg$position %||% c(0.1, 0.95)),
      legend.justification = (legend_cfg$justification %||% c(0, 1)),
      legend.background    = element_rect(fill = "white", colour = NA),
      legend.key.size      = unit((legend_cfg$key_size_mm %||% 3), "mm"),
      legend.direction     = (legend_cfg$direction %||% "vertical")
    )

  # ---- y limits (panel yaml) ----
  if (!is.null(panel$ylim)) {
    y_raw <- panel$ylim
    # yaml::read_yaml parses `[0, null]` as a list(0, NULL); unlist() would drop NULL.
    if (is.atomic(y_raw)) {
      if (length(y_raw) != 2) stop("panel$ylim must be length-2: [lower, upper]")
      ylims <- as.numeric(y_raw)
    } else {
      y_raw <- as.list(y_raw)
      if (length(y_raw) != 2) stop("panel$ylim must be length-2: [lower, upper]")
      ylims <- vapply(y_raw, function(v) {
        if (is.null(v)) NA_real_ else as.numeric(v)
      }, numeric(1))
    }
    p <- p + coord_cartesian(ylim = ylims)
  }

  if (!is.null(facet_var)) {
    p <- p + facet_wrap(as.formula(paste0("~", facet_var)))
  }

  if (!is.null(brackets_df)) {
    p <- p +
      geom_segment(
        data = brackets_df,
        inherit.aes = FALSE,
        aes(x = x1, xend = x2, y = y, yend = y),
        linewidth = pt_to_lwd(bracket_cfg$line_width_pt %||% line_cfg$line_width_pt %||% 0.5),
        color = "black"
      ) +
      geom_segment(
        data = brackets_df,
        inherit.aes = FALSE,
        aes(x = x1, xend = x1, y = y,
            yend = y - (bracket_cfg$tick_height_frac %||% 0.02) * max(df[[y_var]], na.rm = TRUE)),
        linewidth = pt_to_lwd(bracket_cfg$line_width_pt %||% line_cfg$line_width_pt %||% 0.5),
        color = "black"
      ) +
      geom_segment(
        data = brackets_df,
        inherit.aes = FALSE,
        aes(x = x2, xend = x2, y = y,
            yend = y - (bracket_cfg$tick_height_frac %||% 0.02) * max(df[[y_var]], na.rm = TRUE)),
        linewidth = pt_to_lwd(bracket_cfg$line_width_pt %||% line_cfg$line_width_pt %||% 0.5),
        color = "black"
      ) +
      geom_text(
        data = brackets_df,
        inherit.aes = FALSE,
        aes(x = x_center,
            y = y + (bracket_cfg$tick_height_frac %||% 0.02) * max(df[[y_var]], na.rm = TRUE),
            label = label),
        size = pt_to_text_size(bracket_cfg$label_size_pt %||% (sizes_pt$legend_text_default %||% 6)),
        color = "black"
      )
  }

  out_dir_cfg <- panel_cfg$out_dir %||% "06_figures/figure_4"
  out_dir <- file.path(project_root, out_dir_cfg)
  if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

  out_file <- file.path(out_dir, paste0(panel_cfg$out, "_", panel$id, ".pdf"))

  ggsave(out_file, p,
         width = panel_cfg$size$width_mm/mm_per_inch,
         height = panel_cfg$size$high_mm/mm_per_inch)

  message("[INFO] Saved: ", out_file)
}