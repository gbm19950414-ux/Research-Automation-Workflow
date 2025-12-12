#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(yaml)
})

main <- function() {
  cfg_path   <- "06_figures/script/figure_4_a_auc.yaml"
  style_path <- "02_protocols/figure_style_nature.yaml"
  box_script <- "06_figures/script/box_panel_from_yaml.R"

  if (!file.exists(cfg_path)) {
    stop("找不到配置文件: ", cfg_path)
  }
  if (!file.exists(style_path)) {
    stop("找不到样式文件: ", style_path)
  }
  if (!file.exists(box_script)) {
    stop("找不到 box_panel_from_yaml.R: ", box_script)
  }

  message("[AUC] 使用配置文件: ", cfg_path)
  message("[AUC] 使用样式文件: ", style_path)

  # 读一遍 YAML，主要是提前发现语法错误
  cfg <- yaml::read_yaml(cfg_path)
  if (is.null(cfg$panels) || length(cfg$panels) == 0) {
    stop("配置文件中没有 panels 定义: ", cfg_path)
  }

  message("[AUC] 调用 box_panel_from_yaml.R 生成 AUC 箱线图...")
  # 约定调用方式：
  #   Rscript box_panel_from_yaml.R <cfg_yaml> <style_yaml>
  system2("Rscript", c(box_script, cfg_path, style_path))

  message("[AUC] 完成。")
}

if (sys.nframe() == 0) {
  main()
}