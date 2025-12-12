#!/usr/bin/env Rscript

# 启动器：调用 box_panel_from_yaml.R 画 figure_1_b

cmd <- paste(
  "Rscript",
  shQuote("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/script/box_panel_from_yaml.R"),
  shQuote("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/script/figure_4_a_box.yaml")
)

cat("[INFO] Running command:\n", cmd, "\n")
ret <- system(cmd)

if (ret != 0) {
  stop("Command failed with exit status ", ret)
}