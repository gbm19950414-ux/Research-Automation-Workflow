#!/usr/bin/env Rscript

# box_panel_from_yaml.R
# 通用：根据 panel yaml + style yaml 画箱线图（支持多个 box panel）

suppressPackageStartupMessages({
  library(yaml)
  library(readxl)
  library(dplyr)
  library(ggplot2)
  library(rlang)
  library(grid)
})

`%||%` <- function(x, y) if (!is.null(x)) x else y

message("[INFO] ==== box_panel_from_yaml.R ====")

## ---------- 工具函数 ----------

get_script_path <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- "--file="
  path_idx <- grep(file_arg, args)
  if (length(path_idx) > 0) {
    return(normalizePath(sub(file_arg, "", args[path_idx])))
  }
  if (!is.null(sys.frames()[[1]]$ofile)) {
    return(normalizePath(sys.frames()[[1]]$ofile))
  }
  normalizePath(".")
}

is_absolute_path <- function(path) {
  if (is.null(path) || path == "") return(FALSE)
  # Unix / Mac
  if (startsWith(path, "/")) return(TRUE)
  # Windows C:/ 之类
  if (grepl("^[A-Za-z]:", path)) return(TRUE)
  FALSE
}

resolve_path <- function(path, project_root) {
  if (is.null(path) || path == "") return(NULL)
  if (is_absolute_path(path)) return(path)
  file.path(project_root, path)
}

# ---- 多文件数据源支持 ----
resolve_paths_multi <- function(data_spec, project_root) {
  # returns list entries describing each source
  # each entry: list(path=..., sheet=NULL, keep_x=NULL)
  if (is.null(data_spec)) return(list())

  # single string
  if (is.character(data_spec) && length(data_spec) == 1) {
    return(list(list(path = resolve_path(data_spec, project_root), sheet = NULL, keep_x = NULL)))
  }

  # list of objects with $path
  if (is.list(data_spec) && length(data_spec) > 0 && !is.null(data_spec[[1]]$path)) {
    out <- lapply(data_spec, function(item) {
      list(
        path   = resolve_path(item$path, project_root),
        sheet  = item$sheet %||% NULL,
        keep_x = item$keep_x %||% NULL
      )
    })
    return(out)
  }

  # list/vector of strings
  if (is.list(data_spec)) data_spec <- unlist(data_spec)
  if (is.character(data_spec)) {
    out <- lapply(data_spec, function(p) {
      list(path = resolve_path(p, project_root), sheet = NULL, keep_x = NULL)
    })
    return(out)
  }

  stop("Unsupported data spec type for multi-file input")
}

read_excel_multi <- function(data_spec, project_root, default_sheet = 1) {
  specs <- resolve_paths_multi(data_spec, project_root)
  if (length(specs) == 0) stop("Empty data spec")

  # existence check
  for (s in specs) {
    if (is.null(s$path) || !file.exists(s$path)) {
      stop("Data file not found: ", s$path)
    }
  }

  dfs <- lapply(specs, function(s) {
    sh <- s$sheet %||% default_sheet
    readxl::read_excel(s$path, sheet = sh)
  })
  dplyr::bind_rows(dfs)
}

p_to_symbol <- function(p) {
  if (is.na(p)) return("ns")
  if (p < 0.0001) return("****")
  if (p < 0.001)  return("***")
  if (p < 0.01)   return("**")
  if (p < 0.05)   return("*")
  "ns"
}

## ---------- 主函数：绘制一个 box panel ----------

plot_box_panel <- function(panel,
                           panel_cfg,
                           style_cfg,
                           project_root,
                           panel_yaml_path) {

  # ---- 解析 panel 基本信息 ----
  if (!identical(panel$type, "box")) {
    message("[WARN] panel id=", panel$id, " type != 'box'，跳过。")
    return(invisible(NULL))
  }

  x_var      <- panel$mapping$x
  y_var      <- panel$mapping$y
  hue_var    <- panel$mapping$hue
  x_order    <- panel$order
  hue_order  <- panel$hue_order
  x_label    <- panel$x_label %||% ""
  y_label    <- panel$y_label %||% ""
  x_rot      <- panel$x_tick_rotation %||% 0
  strip_dots <- panel$strip %||% TRUE
  stats_cfg  <- panel$stats

  # 数据来源：支持单文件 / 多文件（列表） / 多文件（对象列表带 keep_x）
  data_sheet <- panel$sheet %||% 1
  data_specs <- resolve_paths_multi(panel$data, project_root)
  if (length(data_specs) == 0) stop("Empty data spec for panel ", panel$id)

  # existence check + message
  msg_paths <- vapply(data_specs, function(s) s$path, character(1))
  message("[INFO] panel ", panel$id, " data sources: ", paste(msg_paths, collapse = " | "))

  # read and bind
  df_list <- lapply(data_specs, function(s) {
    sh <- s$sheet %||% data_sheet
    d <- readxl::read_excel(s$path, sheet = sh)
    d$.source_path <- basename(s$path)
    d$.keep_x <- if (is.null(s$keep_x)) NA_character_ else paste(s$keep_x, collapse = "||")
    d
  })
  df <- dplyr::bind_rows(df_list)

  # 如果 mapping$x 不是现有列名，则尝试按简单拼接表达式解析（例如 "antibody + '|' + drug"）
  # 语法约定：用 "+" 连接列名和带引号的常量字符串，最终结果为字符向量
  if (!is.null(x_var) && !x_var %in% colnames(df)) {
    # 按 "+" 拆分各个片段
    parts <- strsplit(x_var, "\\+")[[1]]
    parts <- trimws(parts)

    if (length(parts) < 2) {
      stop(
        "Panel ", panel$id, ": mapping$x = '", x_var,
        "' 既不是数据中的列名，也不是合法的拼接表达式（形如 \"col1 + '|' + col2\"）。"
      )
    }

    # 逐个片段解析：带引号的视为常量字符串，其余视为列名
    get_part_value <- function(p) {
      n <- nchar(p)
      if (n >= 2 && ((substr(p, 1, 1) == "'" && substr(p, n, n) == "'") ||
                     (substr(p, 1, 1) == "\"" && substr(p, n, n) == "\""))) {
        # 去掉首尾引号，返回常量字符串
        return(substr(p, 2, n - 1))
      } else {
        if (!p %in% colnames(df)) {
          stop(
            "Panel ", panel$id, ": mapping$x 片段 '", p,
            "' 不是数据中的列名，请检查 YAML 配置（原始 mapping$x = '", x_var, "')."
          )
        }
        return(df[[p]])
      }
    }

    vals <- lapply(parts, get_part_value)

    # 从第一个片段开始，逐个用 paste0 拼接，得到字符向量
    res <- vals[[1]]
    if (!is.character(res)) {
      res <- as.character(res)
    }
    if (length(vals) >= 2) {
      for (k in 2:length(vals)) {
        v <- vals[[k]]
        if (!is.character(v)) {
          v <- as.character(v)
        }
        res <- paste0(res, v)
      }
    }

    # 将结果写回 df，列名就叫 mapping$x 这一串（例如 "antibody + '|' + drug"）
    df[[x_var]] <- res
  }

  # ---- keep_x: 若 data 以对象列表形式提供，可按每个文件条目指定仅保留哪些 x 水平 ----
  if (length(data_specs) > 0) {
    # build map from source basename -> keep_x vector (NULL means keep all)
    keep_map <- list()
    for (s in data_specs) {
      bn <- basename(s$path)
      keep_map[[bn]] <- s$keep_x %||% NULL
    }

    if (".source_path" %in% colnames(df) && x_var %in% colnames(df)) {
      df <- df %>%
        rowwise() %>%
        mutate(.keep_flag = {
          k <- keep_map[[.source_path]]
          if (is.null(k)) TRUE else (.data[[x_var]] %in% k)
        }) %>%
        ungroup() %>%
        filter(.keep_flag) %>%
        select(-.keep_flag)
    }
  }

  # 检查 order 中是否有在数据里不存在的 x 水平，方便排查（例如拼写错误）
  if (!is.null(x_order)) {
    missing_x <- setdiff(x_order, unique(df[[x_var]]))
    if (length(missing_x) > 0) {
      warning(
        "Panel ", panel$id,
        " 的 order 中包含在数据中不存在的 drug: ",
        paste(missing_x, collapse = ", ")
      )
    }
  }

  needed_cols <- c(x_var, y_var, hue_var)
  miss <- setdiff(needed_cols, colnames(df))
  if (length(miss) > 0) {
    stop("Panel ", panel$id, " 缺少列: ", paste(miss, collapse = ", "))
  }

  df <- df %>%
    mutate(
      !!sym(x_var)   := factor(.data[[x_var]], levels = x_order),
      !!sym(hue_var) := factor(.data[[hue_var]], levels = hue_order)
    ) %>%
    # 最小修改：过滤掉不在 x_order 中的行（避免隐藏行抬高 y 轴）
    filter(!is.na(.data[[x_var]])) %>%
    mutate(
      x_pos = as.numeric(.data[[x_var]])
    )

  # 固定纵坐标从 0 开始
  y_min_fixed <- 0

  y_vals   <- df[[y_var]]
  data_max <- max(y_vals, na.rm = TRUE)

  # 以 [0, data_max] 作为基础范围
  y_range <- c(y_min_fixed, data_max)
  y_span  <- data_max - y_min_fixed
  if (!is.finite(y_span) || y_span == 0) {
    y_span <- max(1, data_max)
  }

  ## ---- 读统计表，生成括号位置 ----
  stats_df_plot <- NULL

  if (!is.null(stats_cfg) && isTRUE(stats_cfg$enabled)) {
    stats_sheet <- stats_cfg$sheet  %||% 1
    stats_specs <- resolve_paths_multi(stats_cfg$source %||% panel$data, project_root)
    stats_path  <- vapply(stats_specs, function(s) s$path, character(1))
    p_col       <- stats_cfg$column %||% "p_value"
    pairs_list  <- stats_cfg$pairs  %||% list(c("WT", "HO"))

    message("[INFO] panel ", panel$id,
            " stats sources: ", paste(stats_path, collapse = " | "),
            " (sheet=", stats_sheet, ")")

    missing_stats <- stats_path[!file.exists(stats_path)]
    if (length(missing_stats) > 0) {
      warning("Stats file not found: ", paste(missing_stats, collapse = " | "),
              "，该 panel 不画显著性括号。")
    } else {
      raw_list <- lapply(stats_specs, function(s) {
        sh <- s$sheet %||% stats_sheet
        d <- readxl::read_excel(s$path, sheet = sh)
        d$.source_path <- basename(s$path)
        d
      })
      raw_stats <- dplyr::bind_rows(raw_list)

      # stats keep_x: 若 stats.source 以对象列表形式提供，可按文件条目指定仅保留哪些 x 水平
      keep_map_s <- list()
      for (s in stats_specs) {
        bn <- basename(s$path)
        keep_map_s[[bn]] <- s$keep_x %||% NULL
      }

      # 这里允许两种风格：
      #   1) ELISA 风格：stats 里有 drug 列，x 轴也是 drug
      #   2) qPCR 风格：stats 里有 treatment 列，x 轴也是 treatment
      key_candidates <- c("drug", "treatment")
      key_col <- intersect(key_candidates, colnames(raw_stats))
      key_col <- if (length(key_col) > 0) key_col[[1]] else NA_character_

      if (!is.na(key_col) && ".source_path" %in% colnames(raw_stats)) {
        raw_stats <- raw_stats %>%
          rowwise() %>%
          mutate(.keep_flag = {
            k <- keep_map_s[[.source_path]]
            if (is.null(k)) TRUE else (.data[[key_col]] %in% k)
          }) %>%
          ungroup() %>%
          filter(.keep_flag) %>%
          select(-.keep_flag)
      }

      if (is.na(key_col) || !p_col %in% colnames(raw_stats)) {
        warning("Stats sheet for panel ", panel$id,
                " 缺少 {drug/treatment, ", p_col,
                "}，跳过显著性括号。")
      } else {
        stats_list <- list()

        for (x_level in x_order) {
          df_x <- df %>% filter(.data[[x_var]] == x_level)
          if (nrow(df_x) == 0) next

          top_y   <- max(df_x[[y_var]], na.rm = TRUE)
          base_y  <- top_y + 0.05 * y_span
          # 让显著性标记距离横线稍微远一点（原来是 0.03 * y_span）
          label_y <- base_y + 0.05 * y_span

          x_index <- as.numeric(df_x$x_pos[1])
          x_min   <- x_index - 0.25
          x_max   <- x_index + 0.25

          for (pair in pairs_list) {
            # 当前 stats.xlsx 的 pair_stats sheet 是每个 x 水平一行，
            # 隐含比较 WT vs HO，因此这里只按 key_col 取第一行 p 值
            row_p <- raw_stats %>%
              filter(.data[[key_col]] == x_level) %>%
              slice_head(n = 1)

            if (nrow(row_p) == 0) {
              p_val <- NA_real_
            } else {
              p_val <- row_p[[p_col]][[1]]
            }

            stats_list[[length(stats_list) + 1]] <- tibble(
              x_level   = x_level,
              p_value   = p_val,
              label     = p_to_symbol(p_val),
              x_center  = x_index,
              x_min     = x_min,
              x_max     = x_max,
              y_bracket = base_y,
              y_label   = label_y
            )
          }
        }

        stats_df_plot <- bind_rows(stats_list)
      }
    }
  }

  ## ---- 样式参数 ----
  mm_per_inch <- style_cfg$units$mm_per_inch %||% 25.4

  axis_tick_pt   <- style_cfg$typography$sizes_pt$axis_tick_default   %||% 5.5
  axis_label_pt  <- style_cfg$typography$sizes_pt$axis_label_default  %||% 6.5
  legend_text_pt <- style_cfg$typography$sizes_pt$legend_text_default %||% 6
  legend_title_pt<- style_cfg$typography$sizes_pt$legend_title_default%||% 6.5
  panel_label_pt <- style_cfg$typography$sizes_pt$panel_label_default %||% 8
  font_family    <- style_cfg$typography$font_family_primary %||% "Helvetica"

  axis_line_pt   <- style_cfg$lines$axis_line_default_pt  %||% 0.5
  box_lwd_pt     <- style_cfg$lines$boxplot_default_pt     %||% 0.5
  err_lwd_pt     <- style_cfg$lines$errorbar_default_pt    %||% 0.5
  pt_per_lwd     <- style_cfg$lines$r_lwd_scale$pt_per_lwd %||% 0.75

  axis_line_lwd  <- axis_line_pt / pt_per_lwd
  box_lwd        <- box_lwd_pt   / pt_per_lwd
  err_lwd        <- err_lwd_pt   / pt_per_lwd

  ## ---- 输出文件名和尺寸 ----
  size_cfg <- panel$size %||% panel_cfg$size
  width_mm  <- size_cfg$width_mm
  height_mm <- size_cfg$high_mm %||% size_cfg$height_mm

  width_in  <- width_mm  / mm_per_inch
  height_in <- height_mm / mm_per_inch

  # ---- 布局：根据 yaml 中的 axis_outer_frac + axis_gap_pt 控制 ----
  # 优先级：panel.layout > figure.layout > style.layout > 默认
  style_layout  <- style_cfg$layout %||% list()
  figure_layout <- panel_cfg$layout %||% list()
  panel_layout  <- panel$layout %||% list()

  # 1) axis_outer_frac：控制整体画布中，四周留给“轴标题 + 刻度标签”的比例
  axis_outer_frac <- style_layout$axis_outer_frac %||% list(
    left   = 0.20,
    right  = 0.05,
    bottom = 0.25,
    top    = 0.10
  )
  if (!is.null(figure_layout$axis_outer_frac)) {
    axis_outer_frac <- modifyList(axis_outer_frac, figure_layout$axis_outer_frac)
  }
  if (!is.null(panel_layout$axis_outer_frac)) {
    axis_outer_frac <- modifyList(axis_outer_frac, panel_layout$axis_outer_frac)
  }

  # 2) axis_gap_pt：控制轴标题与刻度、刻度与轴线之间的距离（pt）
  axis_gap_pt <- style_layout$axis_gap_pt %||% list(
    x_title_to_ticks = 3,
    x_ticks_to_axis  = 2,
    y_title_to_ticks = 3,
    y_ticks_to_axis  = 2
  )
  if (!is.null(figure_layout$axis_gap_pt)) {
    axis_gap_pt <- modifyList(axis_gap_pt, figure_layout$axis_gap_pt)
  }
  if (!is.null(panel_layout$axis_gap_pt)) {
    axis_gap_pt <- modifyList(axis_gap_pt, panel_layout$axis_gap_pt)
  }

  # 3) 将 axis_outer_frac 换算成 plot.margin 所需的 pt（基于当前 panel 的物理 size）
  frac_or0 <- function(x) if (is.null(x)) 0 else x

  margin_top_mm    <- frac_or0(axis_outer_frac$top)    * height_mm
  margin_bottom_mm <- frac_or0(axis_outer_frac$bottom) * height_mm
  margin_left_mm   <- frac_or0(axis_outer_frac$left)   * width_mm
  margin_right_mm  <- frac_or0(axis_outer_frac$right)  * width_mm

  mm_to_pt <- function(mm) (72 / mm_per_inch) * mm

  plot_margin_cfg <- list(
    top    = mm_to_pt(margin_top_mm),
    right  = mm_to_pt(margin_right_mm),
    bottom = mm_to_pt(margin_bottom_mm),
    left   = mm_to_pt(margin_left_mm)
  )

  ## ---- 输出文件名和尺寸 ----
  size_cfg <- panel$size %||% panel_cfg$size
  width_mm  <- size_cfg$width_mm
  height_mm <- size_cfg$high_mm %||% size_cfg$height_mm

  width_in  <- width_mm  / mm_per_inch
  height_in <- height_mm / mm_per_inch

  # 由 yaml 文件名推 figure 目录，例如 figure_1_b.yaml -> figure_1
  yaml_base   <- basename(panel_yaml_path)
  yaml_stem   <- sub("\\.yaml$", "", yaml_base)
  figure_name <- sub("_[^_]+$", "", yaml_stem) # 去掉最后一个下划线后的部分

  # out 基础名：panel$out 优先，其次 panel_cfg$out，再其次 figure_name
  out_base <- panel$out %||% panel_cfg$out %||% figure_name

  # 如果一个 yaml 内有多个 panel，同一 out_base 加 _id
  if (!is.null(panel$id)) {
    out_base_panel <- paste0(out_base, "_", panel$id)
  } else {
    out_base_panel <- out_base
  }

  out_dir <- file.path(project_root, "06_figures", figure_name)
  if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  out_pdf <- file.path(out_dir, paste0(out_base_panel, ".pdf"))

  message("[INFO] panel ", panel$id,
          " -> ", out_pdf,
          " (", width_mm, " x ", height_mm, " mm)")

## ---- 颜色方案：WT / HO 用样式配置中的色板，其它走默认 ----
hue_levels <- levels(df[[hue_var]])

fill_pal <- NULL
# 从 style yaml 中读取 WT / HO 调色板（例如 colors: wt_ho: {WT: "#F08A4B", HO: "#4DB6AC"}）
wt_ho_pal <- NULL
if (!is.null(style_cfg$colors) && !is.null(style_cfg$colors$wt_ho)) {
  wt_ho_pal <- unlist(style_cfg$colors$wt_ho)
}

if (length(hue_levels) == 2 &&
    all(c("WT", "HO") %in% hue_levels)) {
  # 优先使用样式文件中的配置；若缺失则退回到脚本内默认
  if (!is.null(wt_ho_pal) && all(c("WT", "HO") %in% names(wt_ho_pal))) {
    tmp <- wt_ho_pal
  } else {
    # fallback：保持原来的默认配色（WT 橙，HO 绿），以免样式文件未配置时报错
    tmp <- c(
      "WT" = "#F08A4B",
      "HO" = "#4DB6AC"
    )
  }
  fill_pal <- tmp[hue_levels]
}
  ## ---- 作图 ----
  p <- ggplot(
    df,
    aes(
      x = x_pos,
      y = .data[[y_var]],
      fill = .data[[hue_var]],
      group = interaction(.data[[x_var]], .data[[hue_var]])
    )
  ) +
    geom_boxplot(
      width    = 0.55,
      position = position_dodge(width = 0.6),
      outlier.shape = NA,
      colour   = "black",
      linewidth = box_lwd
    )

  if (isTRUE(strip_dots)) {
    p <- p +
      geom_point(
        aes(color = .data[[hue_var]]),
        position = position_jitterdodge(
          jitter.width = 0.05,
          dodge.width  = 0.6
        ),
        size   = 1.4,
        stroke = 0.2
      ) +
      scale_color_manual(values = fill_pal %||% hue_pal()(length(hue_levels)),
                         guide = "none")
  }

  if (!is.null(fill_pal)) {
    p <- p + scale_fill_manual(values = fill_pal)
  }

  # x 轴刻度名称：支持 rename_x（可以是命名向量或按顺序的列表）
  x_labels <- panel$rename_x
  if (is.null(x_labels)) {
    # 未提供 rename_x 时，直接使用 order 本身
    x_labels <- x_order
  } else {
    # 如果 rename_x 没有名字，按顺序与 x_order 对应
    if (is.null(names(x_labels))) {
      if (length(x_labels) != length(x_order)) {
        warning(
          "Panel ", panel$id,
          " 的 rename_x 长度(", length(x_labels),
          ") 与 order 长度(", length(x_order),
          ") 不一致，超出部分将被忽略。"
        )
      }
      x_labels <- x_labels[seq_len(min(length(x_labels), length(x_order)))]
      names(x_labels) <- x_order[seq_len(length(x_labels))]
    }
    # 若 rename_x 是命名向量，则按名字匹配；缺失的用原始值补齐
    tmp <- setNames(x_order, x_order)
    idx <- intersect(names(x_labels), names(tmp))
    tmp[idx] <- x_labels[idx]
    x_labels <- tmp
  }
  
  p <- p +
    scale_x_continuous(
      breaks = seq_along(x_order),
      labels = x_labels[x_order]
    ) +
    labs(
      x = x_label,
      y = y_label,
      fill = NULL
    )

  # y 上限留出空间给括号（先得到原始最大值）
  max_upper <- y_range[2]
  if (!is.null(stats_df_plot) && nrow(stats_df_plot) > 0) {
    max_upper <- max(max_upper, max(stats_df_plot$y_label, na.rm = TRUE))
  }

  # 在原始最大值基础上加一点 headroom，再做“规整化”
  raw_max <- max_upper + 0.02 * y_span

  nice_ceiling <- function(x) {
    if (!is.finite(x) || x <= 0) return(1)
    x_head <- x  # raw_max 已经包含了一点 headroom
    mag    <- 10 ^ floor(log10(x_head))
    norm   <- x_head / mag
    # 常用刻度：1, 2, 2.5, 5, 10
    candidates <- c(1, 2, 2.5, 5, 10)
    top_norm   <- candidates[min(which(candidates >= norm))]
    if (is.na(top_norm)) top_norm <- 10
    top_norm * mag
  }

  y_min <- y_min_fixed
  y_max <- nice_ceiling(raw_max)
  
  # ---- 允许 YAML 定义 y 轴范围 ----
  yaml_ylim <- panel$ylim %||% NULL
  if (!is.null(yaml_ylim)) {
    if (length(yaml_ylim) != 2)
      stop("panel ", panel$id, " 的 ylim 必须为长度 2 的数值数组，如 [0, 20000]")

    y_min <- yaml_ylim[1]
    y_max <- yaml_ylim[2]
  }

  # 固定 5 个 y 轴刻度标签（包含 0 和顶部），数字更“规整”
  p <- p +
    coord_cartesian(ylim = c(y_min, y_max)) +
    scale_y_continuous(breaks = seq(y_min, y_max, length.out = 5))

  # 显著性括号
  if (!is.null(stats_df_plot) && nrow(stats_df_plot) > 0) {
    p <- p +
      geom_segment(
        data = stats_df_plot,
        aes(x = x_min, xend = x_max,
            y = y_bracket, yend = y_bracket),
        inherit.aes = FALSE,
        linewidth = err_lwd
      ) +
      geom_segment(
        data = stats_df_plot,
        aes(x = x_min, xend = x_min,
            y = y_bracket, yend = y_bracket - 0.02 * y_span),
        inherit.aes = FALSE,
        linewidth = err_lwd
      ) +
      geom_segment(
        data = stats_df_plot,
        aes(x = x_max, xend = x_max,
            y = y_bracket, yend = y_bracket - 0.02 * y_span),
        inherit.aes = FALSE,
        linewidth = err_lwd
      ) +
      geom_text(
        data = stats_df_plot,
        aes(x = x_center, y = y_label, label = label),
        inherit.aes = FALSE,
        size = legend_text_pt / 2.5
      )
  }

  # 主题：接近 Nature
  p <- p +
    theme_classic(base_size = axis_tick_pt, base_family = font_family) +
    theme(
      axis.title.x = element_text(
        size   = axis_label_pt,
        margin = margin(t = axis_gap_pt$x_title_to_ticks %||% 0)
      ),
      axis.title.y = element_text(
        size   = axis_label_pt,
        margin = margin(r = axis_gap_pt$y_title_to_ticks %||% 0)
      ),
      axis.text.x  = element_text(
        size  = axis_tick_pt,
        angle = x_rot,
        hjust = if (x_rot == 0) 0.5 else 1,
        vjust = if (x_rot == 0) 0.5 else 1,
        margin = margin(t = axis_gap_pt$x_ticks_to_axis %||% 0)
      ),
      axis.text.y  = element_text(
        size   = axis_tick_pt,
        margin = margin(r = axis_gap_pt$y_ticks_to_axis %||% 0)
      ),
      axis.line    = element_line(linewidth = axis_line_lwd, colour = "black"),

      legend.position      = c(0.1, 0.95),
      legend.justification = c(0, 1),
      legend.background    = element_rect(fill = "white", colour = NA),
      legend.key.size      = unit(3, "mm"),
      legend.text          = element_text(size = legend_text_pt),
      legend.title         = element_text(size = legend_title_pt),

      plot.margin = margin(
        plot_margin_cfg$top    %||% 0,
        plot_margin_cfg$right  %||% 0,
        plot_margin_cfg$bottom %||% 0,
        plot_margin_cfg$left   %||% 0
      )
    )

  # ---- 导出 PDF ----
  grDevices::cairo_pdf(
    file   = out_pdf,
    width  = width_in,
    height = height_in,
    family = font_family
  )
  print(p)
  dev.off()

  message("[INFO] panel ", panel$id, " 完成: ", out_pdf)
}

## ---------- 主流程：读配置 & 遍历所有 box panel ----------

# 脚本路径 & project root（假定脚本放在 06_figures/script 下）
script_path  <- get_script_path()
script_dir   <- dirname(script_path)
project_root <- normalizePath(file.path(script_dir, "..", ".."))
message("[INFO] Project root: ", project_root)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("用法: Rscript box_panel_from_yaml.R 06_figures/script/figure_X_Y.yaml")
}
panel_yaml_rel <- args[1]
panel_yaml_path <- if (is_absolute_path(panel_yaml_rel)) {
  panel_yaml_rel
} else {
  file.path(project_root, panel_yaml_rel)
}

message("[INFO] Panel config yaml: ", panel_yaml_path)
if (!file.exists(panel_yaml_path)) {
  stop("Panel yaml not found: ", panel_yaml_path)
}

panel_cfg <- yaml::read_yaml(panel_yaml_path)

# 样式 yaml 固定路径；如果以后要自定义，也可以写进 panel_cfg 再改这里
style_yaml_rel  <- "02_protocols/figure_style_nature.yaml"
style_yaml_path <- file.path(project_root, style_yaml_rel)
message("[INFO] Style yaml: ", style_yaml_path)
if (!file.exists(style_yaml_path)) {
  stop("Style yaml not found: ", style_yaml_path)
}
style_cfg <- yaml::read_yaml(style_yaml_path)

if (is.null(panel_cfg$panels) || length(panel_cfg$panels) == 0) {
  stop("No panels defined in panel config.")
}

for (pnl in panel_cfg$panels) {
  if (!identical(pnl$type, "box")) next
  plot_box_panel(
    panel           = pnl,
    panel_cfg       = panel_cfg,
    style_cfg       = style_cfg,
    project_root    = project_root,
    panel_yaml_path = panel_yaml_path
  )
}

message("[INFO] All box panels done.")