#!/usr/bin/env Rscript

panel_yaml <- "06_figures/script/figure_5_a_violin.yaml"

cmd <- sprintf("Rscript 06_figures/script/violin.R %s", panel_yaml)

message("[INFO] Running:\n ", cmd)
system(cmd)