#!/usr/bin/env Rscript
# run_nao_mtt_pipeline.R
# One-click runner for NAO + MTT microplate analysis pipeline

scripts <- c(
  "05_analysis/scripts/microplate_reader/nao+mtt/00_wide_to_long.R",
  "05_analysis/scripts/microplate_reader/nao+mtt/01_prepare_analysis_table.R",
  "05_analysis/scripts/microplate_reader/nao+mtt/02_summarise_common.R",
  "05_analysis/scripts/microplate_reader/nao+mtt/03_model_results.R",
  "05_analysis/scripts/microplate_reader/nao+mtt/04_make_figures.R"
)

cat("========================================\n")
cat(" NAO + MTT microplate analysis pipeline \n")
cat("========================================\n\n")

for (s in scripts) {
  cat(sprintf("▶ Running: %s\n", s))
  
  if (!file.exists(s)) {
    stop(sprintf("Script not found: %s", s), call. = FALSE)
  }
  
  t0 <- Sys.time()
  tryCatch(
    {
      source(s, local = new.env())
      dt <- difftime(Sys.time(), t0, units = "secs")
      cat(sprintf("✔ Finished: %s (%.1f sec)\n\n", s, as.numeric(dt)))
    },
    error = function(e) {
      cat("\n✖ ERROR in script:\n")
      cat(sprintf("  %s\n\n", s))
      stop(e)
    }
  )
}

cat("========================================\n")
cat(" Pipeline finished successfully 🎉\n")
cat("========================================\n")