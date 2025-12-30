#!/usr/bin/env Rscript
# ============================================================
# 001_genetic screening of inflammatory phenotypes.R
# Launcher:
#   - defines config + plot script locations
#   - runs the plotting pipeline
#   - outputs figures into 06_figures/figure_1
# ============================================================

config_path <- "06_figures/script/001_genetic_screening_inflammatory_phenotypes.yaml"
plot_script <- "06_figures/script/screening_style_dot_plot.R"

cmd <- sprintf("Rscript %s %s", shQuote(plot_script), shQuote(config_path))
cat("[RUN] ", cmd, "\n")
status <- system(cmd)
if (status != 0) stop("Plotting failed with status: ", status)
