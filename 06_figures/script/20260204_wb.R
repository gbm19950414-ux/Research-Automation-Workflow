# figure_1_a.R
# 仅负责指定路径 & 调用通用 WB panel 模板（wb_panel_from_yaml）

root <- "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1"

# 引用通用 WB panel 模板函数
source(file.path(root, "06_figures", "script", "wb_panel.R"))

# YAML config reader (install if needed): install.packages("yaml")

config_rel <- file.path("06_figures", "script", "20260204_wb.yaml")
style_rel  <- file.path("02_protocols", "figure_style_nature.yaml")

# --- output naming & multi-panel dispatch ---
# Support:
#   (A) single-panel YAML with top-level `name`, `bands`, `lanes`
#   (B) multi-panel YAML with top-level `panels: - name: ...`

# Small helper for defaulting
`%||%` <- function(x, y) if (is.null(x)) y else x

config_path <- file.path(root, config_rel)
if (!file.exists(config_path)) stop("Config not found: ", config_path)

cfg_all <- yaml::read_yaml(config_path)

# minimal deep-merge for `page` (panel can override a few fields)
merge_page <- function(base_page, override_page) {
  if (is.null(base_page)) base_page <- list()
  if (is.null(override_page)) return(base_page)
  for (nm in names(override_page)) base_page[[nm]] <- override_page[[nm]]
  base_page
}

# ---- MULTI-PANEL MODE ----
if (!is.null(cfg_all$panels) && length(cfg_all$panels) > 0) {
  base_cfg <- cfg_all
  base_cfg$panels <- NULL

  # temp YAMLs are written under project root so wb_panel_from_yaml() can resolve paths
  tmp_dir_abs <- file.path(root, "06_figures", "script", "_tmp")
  if (!dir.exists(tmp_dir_abs)) dir.create(tmp_dir_abs, recursive = TRUE)

  for (p in cfg_all$panels) {
    if (is.null(p$name) || !nzchar(p$name)) {
      stop("Each panel must have a non-empty `name` under `panels:`")
    }

    # Build effective per-panel config: defaults + panel overrides
    cfg_one <- base_cfg
    cfg_one$name  <- p$name
    cfg_one$bands <- p$bands %||% base_cfg$bands
    cfg_one$lanes <- p$lanes %||% base_cfg$lanes
    cfg_one$page  <- merge_page(base_cfg$page, p$page)

    # Write a temporary YAML for this panel under project root
    tmp_yaml_rel <- file.path("06_figures", "script", "_tmp", paste0("wbpanel_", p$name, ".yaml"))
    tmp_yaml_abs <- file.path(root, tmp_yaml_rel)
    yaml::write_yaml(cfg_one, tmp_yaml_abs)

    # Outputs grouped by panel name
    out_dir <- file.path(root, "06_figures", "results", p$name)
    if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)
    out_pdf <- file.path(out_dir, paste0(p$name, ".pdf"))

    wb_panel_from_yaml(
      root       = root,
      config_rel = tmp_yaml_rel,
      style_rel  = style_rel,
      out_pdf    = out_pdf
    )
  }

  quit(save = "no", status = 0)
}

# ---- SINGLE-PANEL MODE (backward compatible) ----
name <- cfg_all$name
if (is.null(name) || !nzchar(name)) {
  name <- tools::file_path_sans_ext(basename(config_rel))
}

# Keep outputs grouped by analysis instance
out_dir <- file.path(root, "06_figures", "results", name)
if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

out_pdf <- file.path(out_dir, paste0(name, ".pdf"))