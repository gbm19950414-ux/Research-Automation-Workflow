#!/usr/bin/env Rscript

# wide_to_long.R
# Convert E40_raw.xlsx (wide microplate layout) to long table (one row per well cell).
#
# Layout assumptions (matching your description):
# - Total range: A1:DP41
# - Row 1: attribute/measurement names (repeated across each 12-column block)
# - Rows 2-41: 5 vertically stacked plates, each 8x12 (so 40 rows total)
# - A:BH  (60 cols)  = 5 attribute blocks, each 12 cols
# - BI:DP (60 cols)  = 5 measurement blocks, each 12 cols
#
# Output: one row per well per block (5*8*12 = 480 rows),
# columns: block_id, well, well_row, well_col, + 5 attributes + 5 measurements

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(tidyr)
  library(readr)
  library(stringr)
})

# -----------------------------
# Helpers
# -----------------------------
stopf <- function(...) stop(sprintf(...), call. = FALSE)

get_block_names <- function(h, expected_blocks = 5, block_width = 12, label = "attribute") {
  # h: character vector length expected_blocks*block_width
  if (length(h) != expected_blocks * block_width) {
    stopf("Header length for %s is %d, expected %d.", label, length(h), expected_blocks * block_width)
  }
  rr <- rle(h)
  if (length(rr$values) != expected_blocks) {
    stopf("Detected %d %s-name blocks in header; expected %d. (Check if row 1 has repeated names across 12 columns.)",
          length(rr$values), label, expected_blocks)
  }
  if (!all(rr$lengths == block_width)) {
    stopf("Not all %s header blocks are width %d. Detected widths: %s",
          label, block_width, paste(rr$lengths, collapse = ", "))
  }
  rr$values
}

# -----------------------------
# Paths (defaults match your project)
# -----------------------------
default_input  <- "04_data/raw/microplate_reader/NAO检测心磷脂含量及MTT检测细胞活力/E40_raw.xlsx"
default_output <- "04_data/interim/microplate_reader/nao+mtt/E40_long.csv"

args <- commandArgs(trailingOnly = TRUE)
input_path  <- if (length(args) >= 1) args[[1]] else default_input
output_path <- if (length(args) >= 2) args[[2]] else default_output

# -----------------------------
# Read data
# -----------------------------
# Read everything as text to avoid mixed-type headaches; we'll parse measurements later.
col_types <- rep("text", 120)

raw <- read_xlsx(
  path = input_path,
  sheet = 1,
  range = "A1:DP41",
  col_names = FALSE,
  col_types = col_types
)

if (nrow(raw) < 2) stopf("No data rows found in %s", input_path)

header <- raw[1, ] |> unlist(use.names = FALSE) |> as.character()
body   <- raw[-1, ]

# Infer vertical blocks (plates)
n_total_rows <- nrow(body)
if (n_total_rows %% 8 != 0) stopf("Body has %d rows; expected a multiple of 8.", n_total_rows)
n_blocks <- n_total_rows / 8

# Split headers into attribute and measurement parts
attr_header <- header[1:60]
meas_header <- header[61:120]

attr_names <- get_block_names(attr_header, expected_blocks = 5, block_width = 12, label = "attribute")
meas_names <- get_block_names(meas_header, expected_blocks = 5, block_width = 12, label = "measurement")

# Make sure names are unique (keep original wording as much as possible)
make_unique <- function(x) {
  x <- ifelse(is.na(x) | x == "", "unnamed", x)
  # disambiguate duplicates by suffix
  ave(x, x, FUN = function(v) if (length(v) == 1) v else paste0(v, "_", seq_along(v)))
}
attr_names <- make_unique(attr_names)
meas_names <- make_unique(meas_names)

# Build matrices for each block (40x12 each)
block_width <- 12
plate_nrow <- 8
plate_ncol <- 12

attr_mats <- lapply(seq_len(5), function(i) {
  cols <- ((i - 1) * block_width + 1):(i * block_width)
  as.matrix(body[, cols, drop = FALSE])
})
names(attr_mats) <- attr_names

meas_mats <- lapply(seq_len(5), function(i) {
  cols <- 60 + ((i - 1) * block_width + 1):(i * block_width)
  as.matrix(body[, cols, drop = FALSE])
})
names(meas_mats) <- meas_names

# -----------------------------
# Build long table grid
# -----------------------------
grid <- tidyr::expand_grid(
  block_id = seq_len(n_blocks),
  row_id   = seq_len(plate_nrow),
  col_id   = seq_len(plate_ncol)
) |>
  mutate(
    well_row   = LETTERS[row_id],
    well_col   = col_id,
    well       = sprintf("%s%02d", well_row, well_col),
    row_global = (block_id - 1) * plate_nrow + row_id
  )

# Fill attributes
for (nm in names(attr_mats)) {
  mat <- attr_mats[[nm]]
  grid[[nm]] <- mat[cbind(grid$row_global, grid$col_id)]
}

# Fill measurements
for (nm in names(meas_mats)) {
  mat <- meas_mats[[nm]]
  grid[[nm]] <- mat[cbind(grid$row_global, grid$col_id)]
}

# Parse measurement columns to numeric when possible
for (nm in names(meas_mats)) {
  grid[[nm]] <- suppressWarnings(readr::parse_double(grid[[nm]], na = c("", "NA", "NaN")))
}

out <- grid |>
  select(-row_global, -row_id, -col_id) |>
  relocate(block_id, well, well_row, well_col)

# -----------------------------
# Write output
# -----------------------------
dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
readr::write_csv(out, output_path, na = "")

message(sprintf("[OK] Wrote %d rows x %d cols to: %s", nrow(out), ncol(out), output_path))
