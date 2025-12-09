# figure_1_a.R
# 仅负责指定路径 & 调用通用 WB panel 模板（wb_panel_from_yaml）

root <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"

# 引用通用 WB panel 模板函数
source(file.path(root, "06_figures", "script", "wb_panel.R"))

config_rel <- file.path("06_figures", "script", "figure_2_e.yaml")
style_rel  <- file.path("02_protocols", "figure_style_nature.yaml")

out_dir <- file.path(root, "06_figures", "figure_2")
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)
out_pdf <- file.path(out_dir, "figure_2_e.pdf")

wb_panel_from_yaml(
  root       = root,
  config_rel = config_rel,
  style_rel  = style_rel,
  out_pdf    = out_pdf
)