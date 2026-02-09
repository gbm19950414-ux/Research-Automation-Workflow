# figure_1_a.R
# 仅负责指定路径 & 调用通用 WB panel 模板（wb_panel_from_yaml）

root <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"

# 引用通用 WB panel 模板函数
source(file.path(root, "06_figures", "script", "wb_panel.R"))

# YAML config reader (install if needed): install.packages("yaml")

config_rel <- file.path("06_figures", "script", "20260204_wb.yaml")
style_rel  <- file.path("02_protocols", "figure_style_nature.yaml")

# --- output naming: inherit from config.yaml `name:` ---
# Expect `name:` in YAML. If missing, fall back to the YAML filename stem.
config_path <- file.path(root, config_rel)
if (!file.exists(config_path)) stop("Config not found: ", config_path)

cfg  <- yaml::read_yaml(config_path)
name <- cfg$name
if (is.null(name) || !nzchar(name)) {
  name <- tools::file_path_sans_ext(basename(config_rel))
}

# Keep outputs grouped by analysis instance
out_dir <- file.path(root, "06_figures", "results", name)
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

out_pdf <- file.path(out_dir, paste0(name, ".pdf"))

wb_panel_from_yaml(
  root       = root,
  config_rel = config_rel,
  style_rel  = style_rel,
  out_pdf    = out_pdf
)