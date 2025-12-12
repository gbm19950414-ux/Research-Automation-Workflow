
#!/usr/bin/env python3
"""
ddct_analysis.py
────────────────────────────────────────────────────────
· 读取固定路径的长格式 qPCR 数据
· 保留空单元格行，但计算时跳过
· 在 ΔCt 层面用 MAD-z（|z|>2.5） 标记离群值
· 基线 ΔCt₀ 与 Fold-Change 只用“非离群 & 数据完整”行计算
· 最终结果表包含所有原始行，新增 is_outlier 列
"""

import pandas as pd, numpy as np
import pathlib, sys

# -------- 用户一次性配置 ---------------------------------
INPUT_FILE  = ("04_data/interim/qpcr/qpcr_original_data_long_format.csv")
OBJECTIVES  = ["EphB1缺失NLRP3炎症小体引发的线粒体损伤减少_mtDNA释放减少"]
OUTPUT_FILE = f"04_data/interim/qpcr/ddct_analysis_{'_'.join(OBJECTIVES)}.csv"
# === 本次 mtDNA 释放分析的处理条件（按需修改） ===
TREATMENT = "lps_1ngul_4h+nigericin_10ngul_7.5min"
ONLY_THIS_BATCH_ID = None  # 如果只想固定到某一个 batch_id，就把这里改成那个字符串
# ---------------------------------------------------------
KEYS = ["batch_id", "sample_id", "component", "gene"]     # 主键列（按组分区分）
# ---------- 1. 读文件 & 基础过滤 ----------
try:
    df_all = pd.read_csv(INPUT_FILE)
except FileNotFoundError:
    sys.exit(f"[✗] 输入文件不存在：{INPUT_FILE}")

df_all = df_all[df_all["experimental_objective"].isin(OBJECTIVES)].copy()
orig_rows = len(df_all)

# ① mean_cp 转成数值，不可转换者设为 NaN（但不删除）
df_all["mean_cp"] = pd.to_numeric(df_all["mean_cp"], errors="coerce")

# ---------- 2. 仅对“可计算行”进行后续运算 ----------
work = df_all.dropna(subset=["mean_cp"]).copy()          # 仅保留可用 mean_cp
if work.empty:
    sys.exit("数据中 mean_cp 全为空，无法计算。")

# ---------- 2.x 选择一次独立重复实验（按 treatment + 同批次 WT/HO） ----------
# 说明：这里只在“可计算行（mean_cp 非空）”的 work 上继续筛选
work = work[work["treatment"] == TREATMENT].copy()
if ONLY_THIS_BATCH_ID:
    work = work[work["batch_id"] == ONLY_THIS_BATCH_ID].copy()
# ---------- 2.x.a 创建/规范 group 列（缺失则从 sample_id 推断） ----------
WT_ALIASES = {"wt", "wildtype", "wild-type", "wild_type", "control", "ctrl"}
HO_ALIASES = {"ho", "ko", "knockout", "ephb1-/-", "ephb1_ko"}

# 如果已有 group/Genotype 等列，优先使用并规范化
_group_col = None
for c in work.columns:
    if c.lower() in {"group", "genotype", "geno", "type"}:
        _group_col = c
        break

if _group_col is not None:
    work["group"] = (
        work[_group_col].astype("string").str.lower().map(
            lambda x: "wt" if x in WT_ALIASES
            else ("ho" if x in HO_ALIASES else x)
        )
    )
else:
    # 没有分组列则从 sample_id 推断：WT_1 / HO_2 这类前缀
    sid = work["sample_id"].astype("string").str.lower()
    work["group"] = pd.Series(index=work.index, dtype="string")
    work.loc[sid.str.startswith(("wt","wildtype","ctrl","control")), "group"] = "wt"
    work.loc[
        sid.str.startswith(("ho","ko")) |
        sid.str.contains("knockout|ephb1-/-|ephb1_ko", regex=True, na=False),
        "group"
    ] = "ho"

work["group"] = work["group"].astype("string").str.lower()
# ---------- 3. 计算 ΔCt（component 法：Ct(cyto-DNA) - Ct(total-DNA)） ----------
# 规范 component：把 "-DNA" 后缀去掉，统一成 {'cyto','total'}
work["_component_norm"] = work["component"].str.lower().str.replace("-dna","", regex=False)

# 用 batch_id + sample_id + gene 作为键，按 component 类型选择不同的参考 Ct
_pivot_keys = ["batch_id", "sample_id", "gene"]

# 3.1 在 total 组件中，计算每个 (batch_id, sample_id, gene) 的 Ct(total, gene)
_total_gene = (
    work[work["_component_norm"] == "total"]
    .groupby(_pivot_keys, dropna=False)["mean_cp"]
    .mean()
    .rename("ct_total_gene")
    .reset_index()
)

# 3.2 在 total 组件中，计算每个 (batch_id, sample_id) 下 hk2 的 Ct(total, hk2) 作为 total 组分的参考
_hk2_mask = (
    (work["_component_norm"] == "total") &
    (work["gene"].astype("string").str.lower() == "hk2")
)
_hk2_ref = (
    work[_hk2_mask]
    .groupby(["batch_id", "sample_id"], dropna=False)["mean_cp"]
    .mean()
    .rename("ref_ct_hk2")
    .reset_index()
)

# 3.3 合并到 work，每一行都带上 ct_total_gene 和 ref_ct_hk2（若存在）
work = work.merge(_total_gene, on=_pivot_keys, how="left")
work = work.merge(_hk2_ref, on=["batch_id", "sample_id"], how="left")

# 3.4 按 component 类型选择 ref_ct 并计算 ΔCt
is_cyto  = work["_component_norm"] == "cyto"
is_total = work["_component_norm"] == "total"

# cyto 行：ref_ct = Ct(total, 同一 gene)
# total 行：ref_ct = Ct(total, hk2)
work["ref_ct"] = np.where(
    is_cyto,
    work["ct_total_gene"],
    work["ref_ct_hk2"]
)

# ΔCt = Ct(当前行) - ref_ct
work["delta_ct"] = work["mean_cp"] - work["ref_ct"]

# 清理临时列
work = work.drop(columns=["_component_norm", "ct_total_gene", "ref_ct_hk2"], errors="ignore")

# …… 3.4 按 component 类型选择 ref_ct 并计算 ΔCt 后

# DEBUG: 导出一个只含某个 batch 的几行，看明白 cyto / total / hk2 的 ΔCt/ ref_ct 逻辑
debug_batch = work["batch_id"].iloc[0]   # 或者直接写成你关心的某个 batch_id
debug = work.query("batch_id == @debug_batch and gene in ['16s','16S','hk2','HK2']").copy()
debug = debug.sort_values(["sample_id","component","gene"])
debug.to_csv("04_data/interim/qpcr/zz_debug_delta_ct_component_check.csv", index=False)
# ---------- 4. ΔCt及离群值判断 ----------
# （ΔCt 已在上一步由 cyto-total 得到）

# 4.0 统一分组标签（避免大小写差异）
work["group"] = work["group"].str.lower()

# 4.1 在“每个样本的一条 ΔCt”层面判定离群，避免同一样本因多行记录（cyto/total重复）被重复计权
_u_keys = ["batch_id", "sample_id", "gene", "group", "component"]  # 按组分区分 ΔCt
u = work.drop_duplicates(subset=_u_keys).copy()

def _robust_z_numpy(arr: np.ndarray) -> np.ndarray:
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med))
    sigma = max(1e-9, 1.4826 * mad)     # MAD=0 的兜底，等价 Excel IFERROR 保护
    return (arr - med) / sigma

# 4.2 在 “batch_id + gene + group(WT/HO)” 内做稳健 z（|z|>2.5 判为离群）
_grp_keys = ["batch_id", "gene", "group", "treatment", "component"]
u["robust_z"] = (
    u.groupby(_grp_keys, dropna=False)["delta_ct"]
     .transform(lambda s: pd.Series(_robust_z_numpy(s.to_numpy()), index=s.index))
)
u["is_outlier"] = u["robust_z"].abs() > 2.5

# 4.3 把每个样本层面的离群结果合并回原 work（所有原始行都会带上相同的 is_outlier）
work = work.merge(u[_u_keys + ["robust_z","is_outlier"]], on=_u_keys, how="left")

# ---------- 6. 基线 ΔCt₀ (仅 WT 且非离群；按 batch_id + gene 聚合) ----------
# 用 group 列识别 WT；确保大小写无关
mask_wt = work["group"].str.lower().eq("wt")
mask_ok = (~work["is_outlier"]) & work["delta_ct"].notna()

baseline = (work[mask_wt & mask_ok]
            .groupby(["batch_id", "gene", "treatment", "component"], dropna=False)["delta_ct"]
            .mean()
            .rename("baseline_ct")
            .reset_index())

# 合并基线（注意此处用 batch_id+gene，而不是 plate_id）
work = work.merge(baseline, on=["batch_id","gene","treatment","component"], how="left")
# ---------- 7. ΔΔCt & Fold-Change (仅非离群可参与运算) ----------
work["deltadelta_ct"] = work["delta_ct"] - work["baseline_ct"]
work.loc[work["is_outlier"], ["deltadelta_ct", "fold_change"]] = np.nan
work.loc[~work["is_outlier"], "fold_change"] = 2 ** (-work.loc[~work["is_outlier"], "deltadelta_ct"])
# ---------- 8. 合并回所有原始行（确保右表按 KEYS 唯一） ----------
cols_result = ["ref_ct","delta_ct","baseline_ct","deltadelta_ct","fold_change","is_outlier"]

work_res = (
    work[KEYS + cols_result]
    .drop_duplicates(subset=KEYS, keep="last")  # 关键：先去重，避免多对多
)

# validate="m:1" 保证左表多行→右表一行；若右表仍重复会直接报错，方便定位
df_out = df_all.merge(work_res, on=KEYS, how="left", validate="m:1")
# ---------- 9. 保存 ----------
out_path = pathlib.Path(OUTPUT_FILE)
out_path.parent.mkdir(parents=True, exist_ok=True)
df_out.to_csv(out_path, index=False, encoding="utf-8-sig")

print(f"[✓]   原始行数: {orig_rows}")
print(f"[✓]   结果行数: {len(df_out)}  （应与原始一致）")
print(f"[✓]   输出文件: {out_path}")
print("     列解释: is_outlier=True 表示 ΔCt 被判定为离群（fold_change 已置 NaN）")
print("     MAD-z 离群比例：", round(work["is_outlier"].mean(), 3))