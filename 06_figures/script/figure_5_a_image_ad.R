#!/usr/bin/env Rscript

panel_yaml <- "06_figures/script/figure_5_a_image_ad.yaml"

cmd <- sprintf(
  "Rscript 06_figures/script/image_panel.R %s",
  panel_yaml
)

message("[INFO] Running:\n ", cmd)
system(cmd)