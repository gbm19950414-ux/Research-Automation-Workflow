#!/usr/bin/env Rscript

panel_yaml <- "06_figures/script/20260203_NAO_image.yaml"

cmd <- sprintf(
  "Rscript 06_figures/script/image_panel.R %s",
  panel_yaml
)

message("[INFO] Running:\n ", cmd)
system(cmd)