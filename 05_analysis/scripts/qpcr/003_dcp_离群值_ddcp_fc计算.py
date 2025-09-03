
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
INPUT_FILE  = ("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/qpcr_original_data_long_format.csv")
OBJECTIVES  = ["心磷脂代谢过程关键基因变化", "线粒体总量变化"]
OUTPUT_FILE = f"/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/04_data/interim/qpcr/ddct_analysis_{'_'.join(OBJECTIVES)}.csv"


IQR_FACTOR  = 1.5          # 离群阈值：median ± 1.5×IQR
# ---------------------------------------------------------

KEYS = ["plate_id", "sample_id", "gene"]     # 主键列

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

# ---------- 3. 计算参考 Ct (GAPDH/HPRT1) ----------
def get_ref(s):
    pivot = s.pivot_table(index="sample_id", columns="gene",
                          values="mean_cp", aggfunc="mean")
    g, h = "gapdh" in pivot, "hprt1" in pivot
    if g and h:
        ref = np.exp(np.log(pivot[["gapdh", "hprt1"]]).mean(axis=1))
    elif g:
        ref = pivot["gapdh"]
    elif h:
        ref = pivot["hprt1"]
    else:
        ref = pd.Series(np.nan, index=pivot.index)
    ref.name = "ref_ct";  return ref

refs = (work.groupby("plate_id").apply(get_ref)
        .reset_index())                                # plate_id | sample_id | ref_ct

work = work.merge(refs, on=["plate_id","sample_id"], how="left")

# ---------- 4. ΔCt及离群值判断 ----------
work["delta_ct"] = work["mean_cp"] - work["ref_ct"]
# === 新增 A1：为离群分组建立“样本大类”（WT_1/2/3/… 都算 WT；HO 同理）===
work["sample_group"] = work["sample_id"].str.split("_", n=1, expand=True)[0].fillna(work["sample_id"])

# === 新增 A2：定义离群判定的分组范围（按你的要求）===
OUTLIER_KEYS = ["plate_id", "experimental_objective", "experiment_id", "batch_id",
                "sample_group", "treatment", "component", "gene"]

# === 新增 A3：按 Excel 同逻辑计算稳健 z-score，并据 |z|>2.5 标记离群 ===
def _robust_z_numpy(arr: np.ndarray) -> np.ndarray:
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med))
    sigma = max(1e-9, 1.4826 * mad)     # 对齐 IFERROR：mad=0 时兜底，避免除零
    return (arr - med) / sigma

work["robust_z"] = (
    work.groupby(OUTLIER_KEYS, dropna=False)["delta_ct"]
        .transform(lambda s: pd.Series(_robust_z_numpy(s.to_numpy()), index=s.index))
)
work["is_outlier"] = work["robust_z"].abs() > 2.5

# ---------- 6. 基线 ΔCt₀ (仅 WT 且非离群) ----------
mask_baseline = (~work["is_outlier"]) & work["sample_id"].str.startswith("WT_")
baseline = (work[mask_baseline]
            .groupby(["plate_id","gene"])["delta_ct"]
            .mean()
            .rename("baseline_ct")
            .reset_index())

work = work.merge(baseline, on=["plate_id","gene"], how="left")

# ---------- 7. ΔΔCt & Fold-Change (仅非离群可参与运算) ----------
work["deltadelta_ct"] = work["delta_ct"] - work["baseline_ct"]
work.loc[work["is_outlier"], ["deltadelta_ct", "fold_change"]] = np.nan
work.loc[~work["is_outlier"], "fold_change"] = 2 ** (-work.loc[~work["is_outlier"], "deltadelta_ct"])

# ---------- 8. 合并回所有原始行 ----------
cols_result = ["ref_ct","delta_ct","baseline_ct","deltadelta_ct","fold_change","is_outlier"]
df_out = df_all.merge(work[KEYS + cols_result], on=KEYS, how="left")

# ---------- 9. 保存 ----------
out_path = pathlib.Path(OUTPUT_FILE)
out_path.parent.mkdir(parents=True, exist_ok=True)
df_out.to_csv(out_path, index=False, encoding="utf-8-sig")

print(f"[✓]   原始行数: {orig_rows}")
print(f"[✓]   结果行数: {len(df_out)}  （应与原始一致）")
print(f"[✓]   输出文件: {out_path}")
print("     列解释: is_outlier=True 表示 ΔCt 被判定为离群（fold_change 已置 NaN）")
print("     MAD-z 离群比例：", round(work["is_outlier"].mean(), 3))