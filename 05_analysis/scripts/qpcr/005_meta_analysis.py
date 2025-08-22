#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
从 ddct_analysis.csv 生成“真正变化基因”的量化对比：
1) 每个最小单元 (experiment × batch × gene) 计算 HO−WT 的 log2FC 均值差与方差
2) 按基因用随机效应元分析 (DerSimonian–Laird) 合并，得到总体效应、CI、p、I2、tau2
3) 做 BH-FDR，给出候选基因
"""

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import norm

# ========= 用户参数 =========
INPUT = "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/ddct_analysis.csv"
OUT_DIR = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/processed/qpcr")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_SAMPLES_PER_GROUP = 2   # 每个单元内 WT/HO 最少样本
MIN_UNITS_PER_GENE    = 2   # 一个基因至少需要多少个单元才能做合并
EFFECT_THRESH         = 0.5 # |总体效应|阈值（≈1.41x）
ALPHA_FDR             = 0.05
# ===========================

# 读数据 & 基础清洗
df = pd.read_csv(INPUT)
df.columns = df.columns.str.strip().str.lower()

if "log2fc" not in df.columns:
    if "fold_change" not in df.columns:
        raise ValueError("缺少 fold_change / log2fc 列。")
    df = df[df["fold_change"] > 0].copy()
    df["log2fc"] = np.log2(df["fold_change"])

# 过滤离群
if "is_outlier" in df.columns:
    df = df[~df["is_outlier"].fillna(False)]

# 分组（WT/HO）
def infer_group(s):
    s = str(s).upper()
    if "WT" in s: return "WT"
    if ("HO" in s) or ("KO" in s): return "HO"
    return "Other"
df["group"] = df["sample_id"].apply(infer_group)
df = df[df["group"].isin(["WT","HO"])]

# 仅保留“有对照且达标 n”的单元
counts = (df.groupby(["gene","experiment_id","batch_id","group"])
            .size().unstack("group").fillna(0))
ok_unit = (counts.get("WT",0) >= MIN_SAMPLES_PER_GROUP) & (counts.get("HO",0) >= MIN_SAMPLES_PER_GROUP)
valid_units = ok_unit[ok_unit].index
df = df.set_index(["gene","experiment_id","batch_id"]).loc[valid_units].reset_index()

# 计算每个单元的效应与方差：e = mean(HO)-mean(WT), var = s2_HO/n_HO + s2_WT/n_WT
def unit_effect(sub):
    wt = sub.loc[sub["group"]=="WT","log2fc"].to_numpy()
    ho = sub.loc[sub["group"]=="HO","log2fc"].to_numpy()
    e  = np.nanmean(ho) - np.nanmean(wt)
    s2_wt = np.nanvar(wt, ddof=1) if wt.size > 1 else 0.0
    s2_ho = np.nanvar(ho, ddof=1) if ho.size > 1 else 0.0
    v  = s2_wt/max(1, wt.size) + s2_ho/max(1, ho.size)
    if not np.isfinite(v) or v <= 0: v = 1e-6
    return pd.Series({
        "effect": e, "var": v, "se": np.sqrt(v),
        "n_wt": wt.size, "n_ho": ho.size,
        "mean_wt": np.nanmean(wt), "mean_ho": np.nanmean(ho)
    })

unit = (df.groupby(["gene","experiment_id","batch_id"], as_index=False)
          .apply(unit_effect).reset_index(drop=True))

# 随机效应元分析（DerSimonian–Laird）
def meta_dl(gdf: pd.DataFrame) -> pd.Series:
    k = len(gdf)
    e = gdf["effect"].values
    v = gdf["var"].values
    if k == 0:  # no data
        return pd.Series({c: np.nan for c in ["k","effect","se","z","p","ci_low","ci_high","tau2","I2","mu_fe","Q"]})
    # 固定效应
    w = 1.0 / v
    mu_fe = np.sum(w * e) / np.sum(w)
    Q = np.sum(w * (e - mu_fe)**2)
    if k == 1:
        tau2 = 0.0
    else:
        C = np.sum(w) - (np.sum(w**2) / np.sum(w))
        tau2 = max(0.0, (Q - (k - 1)) / C)
    # 随机效应权重
    w_re = 1.0 / (v + tau2)
    mu_re = np.sum(w_re * e) / np.sum(w_re)
    se_re = np.sqrt(1.0 / np.sum(w_re))
    z = mu_re / se_re if se_re > 0 else np.nan
    p = 2.0 * (1.0 - norm.cdf(abs(z))) if np.isfinite(z) else np.nan
    ci_low, ci_high = mu_re - 1.96*se_re, mu_re + 1.96*se_re
    I2 = max(0.0, (Q - (k - 1)) / Q) if (k > 1 and Q > 0) else 0.0
    return pd.Series({
        "k": k, "effect": mu_re, "se": se_re, "z": z, "p": p,
        "ci_low": ci_low, "ci_high": ci_high,
        "tau2": tau2, "I2": I2, "mu_fe": mu_fe, "Q": Q
    })

gene_stats = (unit.groupby("gene").apply(meta_dl).reset_index())

# 只保留至少 MIN_UNITS_PER_GENE 个单元的基因
gene_stats = gene_stats[gene_stats["k"] >= MIN_UNITS_PER_GENE].copy()

# 方向一致性/中位效应等直观指标
by_gene = unit.groupby("gene")["effect"]
gene_stats = gene_stats.merge(
    by_gene.apply(lambda s: (s > 0).mean()).rename("prop_pos"), on="gene", how="left"
)
gene_stats = gene_stats.merge(
    by_gene.median().rename("median_unit_effect"), on="gene", how="left"
)

# BH-FDR（自己实现，避免新依赖）
def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    p = np.asarray(pvals, float)
    m = p.size
    order = np.argsort(p)
    p_sorted = p[order]
    q_sorted = p_sorted * m / (np.arange(m) + 1)
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q = np.empty_like(q_sorted)
    q[order] = q_sorted
    return np.clip(q, 0, 1)

gene_stats["q"] = bh_fdr(gene_stats["p"].fillna(1.0).values)

# 候选标准（可按需调整）
gene_stats["promising"] = (
    (gene_stats["q"] < ALPHA_FDR) &
    (gene_stats["effect"].abs() >= EFFECT_THRESH) &
    (gene_stats["I2"] <= 0.6)  # 异质性不过大
)

# 保存
OUT_UNITS   = OUT_DIR / "per_unit_effects.csv"
OUT_SUMMARY = OUT_DIR / "meta_gene_summary.csv"
unit.to_csv(OUT_UNITS, index=False)
gene_stats.sort_values(["promising","effect"].copy(), ascending=[False, False]).to_csv(OUT_SUMMARY, index=False)

print(f"✅ 单元效应保存: {OUT_UNITS}")
print(f"✅ 基因合并结果: {OUT_SUMMARY}")
print("提示：effect 为 HO−WT 的总体 log2FC，I2 为异质性比例，q 为 BH-FDR。")