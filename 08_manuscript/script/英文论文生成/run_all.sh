#!/usr/bin/env bash
set -euo pipefail

MANU="/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/08_manuscript"
RECORD="/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/record"
SCRIPT="${MANU}/script/英文论文生成"

python "${SCRIPT}/005_export_introduction_IR.py"
python "${SCRIPT}/003_build_results_IR.py" "${RECORD}/paper_logic.yaml"
python "${SCRIPT}/004_discussion_yaml_to_IR.py"
python "${SCRIPT}/001_abstract_to_docx_IR.py"
python "${SCRIPT}/002_method_to_docx_IR.py"
python "${SCRIPT}/005a_build_figure_ir.py"
python "${SCRIPT}/006_assemble_ir.py"
python "${SCRIPT}/007_render_docx.py"

# 可选
python "${SCRIPT}/008_render_figures_docx.py"

echo "[OK] run all done."