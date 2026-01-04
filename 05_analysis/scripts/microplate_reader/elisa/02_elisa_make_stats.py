#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats
from scipy.stats import median_abs_deviation
import glob
import itertools

def p_to_star(p):
    if pd.isna(p):
        return ""
    return "****" if p <= 1e-4 else \
           "***"  if p <= 1e-3 else \
           "**"   if p <= 1e-2 else \
           "*"    if p <= 5e-2 else "ns"

def robust_z(x):
    med = np.median(x)
    mad = median_abs_deviation(x, scale='normal', nan_policy='omit')
    if mad == 0:
        return np.zeros_like(x)
    return (x - med) / mad

def main():
    pattern = "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/04_data/interim/microplate_reader/ELISA检测细胞因子/ELISA_statistic_*.xlsx"
    input_files = glob.glob(pattern)
    if not input_files:
        raise SystemExit("未找到匹配的输入文件")

    for file in input_files:
        INPUT_PATH = Path(file)
        OUTPUT_PATH = INPUT_PATH.parent / (INPUT_PATH.stem + "_summary.xlsx")
        print(f"处理文件: {INPUT_PATH.name}")

        df = pd.read_excel(INPUT_PATH)
        if "genotype" not in df.columns and "genetype" in df.columns:
            df = df.rename(columns={"genetype": "genotype"})

        needed = {"batch","antibody","group","drug","genotype","final_value"}
        miss = needed - set(df.columns)
        if miss:
            print(f"{INPUT_PATH.name} 缺少必要列：{miss}，跳过该文件")
            continue

        d = df.copy()
        d = d[~d["group"].astype(str).str.contains("sc", case=False, na=False)]
        d = d[np.isfinite(d["final_value"])]
        d["genotype"] = d["genotype"].astype(str).str.strip().str.upper()
        d["drug"] = d["drug"].fillna("").astype(str).str.strip()

        d["zscore"] = (
            d.groupby(["batch","antibody","group","drug","genotype"], dropna=False)["final_value"]
             .transform(robust_z)
        )
        d["outlier"] = d["zscore"].abs() > 2     # zscore threshold

        full_df = d.copy()
        full_df.loc[full_df["outlier"], "final_value"] = np.nan
        d = d[~d["outlier"]].copy()

        grp_keys = ["batch","antibody","group","drug","genotype"]
        cell_stats = (
            d.groupby(grp_keys, dropna=False)["final_value"]
             .agg(n="count", mean="mean", sd="std")
             .reset_index()
        )
        cell_stats["sd"] = cell_stats["sd"].fillna(0.0)

        pair_keys = ["batch","antibody","group","drug"]
        out_rows = []
        for keys, sub in d.groupby(pair_keys, dropna=False):
            wt_vals = sub.loc[sub["genotype"]=="WT", "final_value"].to_numpy(dtype=float)
            ho_vals = sub.loc[sub["genotype"]=="HO", "final_value"].to_numpy(dtype=float)

            if wt_vals.size == 0 and ho_vals.size == 0:
                continue

            wt_n, ho_n = int(wt_vals.size), int(ho_vals.size)
            wt_mean = float(np.mean(wt_vals)) if wt_n > 0 else np.nan
            ho_mean = float(np.mean(ho_vals)) if ho_n > 0 else np.nan
            wt_sd = float(np.std(wt_vals, ddof=1)) if wt_n > 1 else 0.0
            ho_sd = float(np.std(ho_vals, ddof=1)) if ho_n > 1 else 0.0

            if wt_n > 0 and ho_n > 0:
                t_stat, p_val = stats.ttest_ind(wt_vals, ho_vals, equal_var=False, nan_policy="omit")
            else:
                t_stat, p_val = np.nan, np.nan

            out_rows.append({
                "batch": keys[0], "antibody": keys[1], "group": keys[2], "drug": keys[3],
                "wt_n": wt_n, "wt_mean": wt_mean, "wt_sd": wt_sd,
                "ho_n": ho_n, "ho_mean": ho_mean, "ho_sd": ho_sd,
                "delta(ho-wt)": (ho_mean - wt_mean) if np.isfinite(ho_mean) and np.isfinite(wt_mean) else np.nan,
                "t_stat": t_stat, "p_value": p_val, "p_star": p_to_star(p_val),
            })

        pair_stats = pd.DataFrame(out_rows).sort_values(pair_keys, ignore_index=True)

        # ---- drug vs drug comparisons (within each genotype) ----
        # This table is designed for plotting "group vs group" significance (e.g., Control vs AD) when hue/drug is the grouping variable.
        drug_pair_keys = ["batch", "antibody", "genotype"]
        drug_rows = []
        for keys, sub in d.groupby(drug_pair_keys, dropna=False):
            # collect non-empty drug levels present in this stratum
            drugs = (
                sub["drug"].dropna().astype(str).str.strip()
                  .replace({"": np.nan}).dropna().unique().tolist()
            )
            if len(drugs) < 2:
                continue

            for drug1, drug2 in itertools.combinations(drugs, 2):
                v1 = sub.loc[sub["drug"] == drug1, "final_value"].to_numpy(dtype=float)
                v2 = sub.loc[sub["drug"] == drug2, "final_value"].to_numpy(dtype=float)

                n1, n2 = int(v1.size), int(v2.size)
                mean1 = float(np.mean(v1)) if n1 > 0 else np.nan
                mean2 = float(np.mean(v2)) if n2 > 0 else np.nan
                sd1 = float(np.std(v1, ddof=1)) if n1 > 1 else 0.0
                sd2 = float(np.std(v2, ddof=1)) if n2 > 1 else 0.0

                if n1 > 0 and n2 > 0:
                    t_stat, p_val = stats.ttest_ind(v1, v2, equal_var=False, nan_policy="omit")
                else:
                    t_stat, p_val = np.nan, np.nan

                drug_rows.append({
                    "batch": keys[0], "antibody": keys[1], "genotype": keys[2],
                    "drug1": drug1, "drug2": drug2,
                    "drug1_n": n1, "drug1_mean": mean1, "drug1_sd": sd1,
                    "drug2_n": n2, "drug2_mean": mean2, "drug2_sd": sd2,
                    "delta(drug2-drug1)": (mean2 - mean1) if np.isfinite(mean2) and np.isfinite(mean1) else np.nan,
                    "t_stat": t_stat, "p_value": p_val, "p_star": p_to_star(p_val),
                })

        drug_pair_stats = pd.DataFrame(drug_rows)
        if not drug_pair_stats.empty:
            drug_pair_stats = drug_pair_stats.sort_values(["batch", "antibody", "genotype", "drug1", "drug2"], ignore_index=True)

        with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as w:
            cell_stats.to_excel(w, sheet_name="cell_stats", index=False)
            pair_stats.to_excel(w, sheet_name="pair_stats", index=False)
            if not drug_pair_stats.empty:
                drug_pair_stats.to_excel(w, sheet_name="drug_pair_stats", index=False)
            full_df[["batch","antibody","group","drug","genotype","final_value","zscore","outlier"]].to_excel(w, sheet_name="final_values", index=False)

        print(f"完成：{OUTPUT_PATH.name}")

if __name__ == "__main__":
    main()