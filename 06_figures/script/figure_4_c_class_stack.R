#!/usr/bin/env Rscript
args <- commandArgs(trailingOnly = TRUE)

yaml_path <- if (length(args) >= 1) args[[1]] else "06_figures/script/figure_4_c_class_stack.yaml"
plot_script <- "06_figures/script/class_stack_from_yaml.R"

cmd <- sprintf("Rscript %s %s", shQuote(plot_script), shQuote(yaml_path))
message("[INFO] Running command:\n ", cmd)

status <- system(cmd)
if (status != 0) stop("Command failed with exit status ", status)