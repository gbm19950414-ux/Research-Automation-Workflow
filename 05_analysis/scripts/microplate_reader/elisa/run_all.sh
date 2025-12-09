#!/bin/bash
# 进入项目根目录
cd "$(dirname "$0")"

# 依次执行 4 个脚本
python3 00_wide_to_long.py
python3 01_elisa_statistics.py
python3 02_elisa_make_stats.py
python3 03_elisa_plot.py
