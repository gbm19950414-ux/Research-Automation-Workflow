# 00_config.R
# Central configuration for NAO + MTT microplate analysis
# Run scripts from project root so relative paths resolve.

cfg <- list(
  # I/O
  input_long_csv = "04_data/interim/microplate_reader/nao+mtt/E40_long.csv",
  interim_dir    = "04_data/interim/microplate_reader/nao+mtt",
  processed_dir  = "04_data/processed/microplate_reader/nao+mtt",

  # Column mapping (edit these to match your E40_long.csv)
  # The scripts will try a few common aliases if these are NULL/empty,
  # but it's best to set them explicitly.
  col = list(
    genotype = c("genotype", "Genotype", "geno", "cell_group"),
    drug     = c("drug", "Drug"),
    dose     = c("dose", "Dose", "conc", "concentration"),
    time     = c("time", "Time", "time_h", "hour", "hours"),

    # Readouts (must point to numeric columns)
    mtt      = c("MTT", "mtt", "od570", "OD570", "abs570"),

    # NAO can be recorded at multiple detection depths/channels.
    # Use `nao_channels` to list all NAO columns you want to combine.
    # If your CSV column names are exactly like the ones below, keep them.
    # Otherwise, edit to match your real column names.
    nao_channels = c(
      "519-555(test_in_5nm)",
      "519-555(test_in_7.5nm)",
      "519-555(test_in_9.5nm)",
      "519-555(test_in_13nm)"
    ),

    # Fallback single-NAO column (used only if `nao_channels` are not found)
    nao      = c("NAO", "nao", "nao_580", "580", "rfu580", "RFU580")
  ),

  # How to combine multiple NAO channels into one composite NAO signal
  nao_combine_method = "mean",   # supported: "mean", "median"
  nao_primary_name   = "NAO_combined",
  # Significance annotation
  annotate_significance = TRUE,
  sig_levels = c(`0.0001`="****", `0.001`="***", `0.01`="**", `0.05`="*"),
  sig_ns_label = "",
  sig_p_column = "p_adj",     # 用 p_adj 还是 p.value
  fig3_key_time = "24h",
  # Factor levels / ordering (aligned to E40_long.csv)
  # NOTE: In this dataset, `genotype` encodes replicate IDs (wt_1..wt_4, ho_1..ho_4) and a no-cell control.
  # If you later decide to collapse wt_*/ho_* into wt/ho, we can add that transform in 01_prepare.
  genotype_levels = c("no_cell", "wt_1", "wt_2", "wt_3", "wt_4", "ho_1", "ho_2", "ho_3", "ho_4"),

  # Drugs present in this dataset
  drug_levels     = c("untreated", "dmso", "ephb1_fc", "bel", "ad"),

  # Timepoints present in this dataset
  time_levels     = c("0h", "5h", "10h", "24h", "48h"),



  # QC / normalization
  viability_threshold = 0.70,   # MTT_rel < threshold => low viability flag
  baseline_time       = "0h",   # for time-baseline normalization
  normalize_within = c("geno_simple", "drug", "dose_f"),  # groups to compute baseline

  
  # If you have vehicle control instead of 0h baseline, you can change logic in 01_prepare.

  # Modeling
  p_adjust_method = "BH",
  random_effect   = c("block_id"),   # you can add "plate_id" if present
  # If you have technical replicates per plate, consider random slope per time later.
  # 背景孔标签（你的数据里就是 no_cell）
  background_label = "no_cell",

  # 背景均值按哪些键计算（推荐至少按 block_id；如果你每个时间/药物都加了 no_cell，也可以加 time/drug）
  background_group_vars = c("block_id"),

  # 阴性对照（仅细胞无处理孔）
  control_drug = "untreated",
  # 可选：如果你有“仅细胞无处理”的 dose 水平（例如 0），就在这里指定；没有就留 NULL
  control_dose_f = NULL,
  # 阴性对照均值按哪些键算（推荐：geno_simple + time + block_id）
  control_group_vars = c("geno_simple", "time", "block_id"),

  # 组内稳健异常值（robust z）设置
  robust_z_threshold = 3.5,
  robust_z_group_vars = c("geno_simple", "drug", "dose_f", "time"),
  drop_outliers_in_summary = TRUE,
  drop_outliers_in_models  = TRUE,
  # Plot output formats
  plot_formats    = c("pdf", "png"),
  plot_width      = 11,
  plot_height     = 7
)

cfg
