#!/usr/bin/env Rscript

ROOT <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"
SRC  <- file.path(ROOT, "06_figures/script")

# 加载核心功能：折线图和 AUC 图
source(file.path(SRC, "line_chart.R"))
source(file.path(SRC, "AUC.R"))

# 配置文件路径
cfg_file <- file.path(SRC, "figure_3_b.yaml")

# 输出目录
out_dir <- file.path(ROOT, "06_figures/figure_3")

if (!dir.exists(out_dir)) {
  dir.create(out_dir, recursive = TRUE)
}

# 从 YAML 中按 panel 拆分，然后分别绘制 line / AUC 图
draw_all_panels <- function(cfg_path, out_dir, base_prefix = "figure_3_b") {
  cfg <- yaml::read_yaml(cfg_path)

  if (is.null(cfg$panels) || length(cfg$panels) == 0) {
    stop("配置文件中未找到 panels 字段或为空。")
  }

  for (i in seq_along(cfg$panels)) {
    panel <- cfg$panels[[i]]
    panel_id <- panel$id %||% paste0("panel", i)

    message("[INFO] 处理 panel: ", panel_id)

    # 构建仅包含该 panel 的临时配置
    tmp_cfg <- cfg
    tmp_cfg$panels <- list(panel)

    tmp_cfg_path <- file.path(
      dirname(cfg_path),
      paste0("figure_3_b_panel_", panel_id, "_tmp.yaml")
    )
    yaml::write_yaml(tmp_cfg, tmp_cfg_path)

    # 1) 折线图
    out_basename_line <- paste0(base_prefix, "_line_", panel_id)
    draw_figure_from_yaml(
      cfg_path = tmp_cfg_path,
      out_dir  = out_dir,
      out_basename = out_basename_line
    )

    # 2) AUC 图
    out_basename_auc <- paste0(base_prefix, "_auc_", panel_id)
    draw_auc_from_yaml(
      cfg_path = tmp_cfg_path,
      out_dir  = out_dir,
      out_basename = out_basename_auc
    )
  }

  message("[DONE] 所有 panel 的折线图与 AUC 图已生成。")
}

# 启动
draw_all_panels(
  cfg_path = cfg_file,
  out_dir  = out_dir,
  base_prefix = "figure_3_b"
)