# 项目结构说明

## data/raw/
存放原始数据，按实验方法分类，不得更改或覆盖。子文件夹如：
- qPCR/
- imaging_IF/
- metabolomics/

## data/interim/
对 raw 数据初步整理后的“长格式”整洁表，包含 QC、排除信息等。

## data/processed/
按图（fig）编号组织的分析就绪数据，如：
- fig1_metabolic_assay.tsv
- fig2_cardio_lipin_qPCR.tsv

## notebooks/
用于单图或单实验问题的 Jupyter / RMarkdown 脚本。

## src/
封装的可复用函数，例如：
- qPCR 数据处理（ΔCt、ΔΔCt、2^-ΔΔCt）
- boxplot+statannotations 绘图函数

## reports/
最终可供图注与论文使用的图像和表格。

## env/
环境依赖、环境说明文档，供复现用。
