#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用长表筛选与切分脚本（针对“参数列 + 数据列”的科研数据）
=================================================================
设计目标：
- 适配“多次重复实验的总表”，参数列数量可能变化；支持通用筛选与可选分组切分；
- **不筛选 ≠ 相同**：未对某列写筛选条件，表示对该列“完全不约束”；
- 显式指定要按哪些列分组切分；若不指定，输出为一个整体文件。

【用法示例】
1) 最简单：只指定输入，按默认行为输出一个文件（整体，不分组）
   python3 split_long_dataset.py 原始数据_long.xlsx

2) 指定输出目录
   python3 split_long_dataset.py 原始数据_long.xlsx --output-dir ./out

3) 自动识别参数列（除 value 列之外全部），按条件筛选 + 不分组
   python3 split_long_dataset.py 原始数据_long.xlsx \
       --filter drug==tmrm --filter time_point>=10

4) 显式指定“数据列名”和“参数列名”（逗号分隔）
   python3 split_long_dataset.py 原始数据_long.xlsx \
       --value-col value \
       --param-cols sample_batch,drug,dye,Dye_concentration,Dye_time,time_point,group,gene

5) 按列分组切分（生成多文件），未写 filter 的列不会被约束
   python3 split_long_dataset.py 原始数据_long.xlsx \
       --group-by sample_batch,drug,dye,Dye_concentration,Dye_time

6) 复杂筛选：集合、空值、比较运算
   # 集合（包含）：
   --filter gene in [Nlrp3, Il1b, Tnf]
   # 集合（不包含）：
   --filter group not in [blank,control]
   # 空值：
   --filter drug is null
   --filter dye is not null
   # 数值比较：
   --filter time_point>=7.5
   --filter Dye_concentration<200

【筛选语法】（大小写与空格不敏感，多个 --filter 之间是 AND 关系）
- 等值/不等：        col=val   col==val   col!=val
- 比较：             col>v     col>=v     col<v     col<=v   （优先尝试数值比较；失败则回退到文本比较）
- 集合包含/排除：    col in [a,b,c]      col not in [x,y]
- 空值判断：         col is null         col is not null

【分组输出】
- 若提供 --group-by，则按这些列的唯一组合拆分为多个 Excel；
- 若不提供 --group-by，则输出单个 Excel（文件名为 ALL.xlsx）。

【其它参数】
- --value-col    数据列名（默认 value）；
- --param-cols   参数列，逗号分隔；默认 AUTO（除 value 列之外的所有列）；
- --nan-token    文件名中对空值的占位符（默认 NA）；
"""

import argparse
import ast
import re
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:"*?<>|]+', "_", str(name))
    return name[:150] or "UNNAMED"


def parse_csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _norm_text(x):
    return str(x).strip().lower()


def _is_null_token(s: str) -> bool:
    return _norm_text(s) in {"", "null", "none", "nan", "na"}


def build_condition_mask(series: pd.Series, expr: str) -> pd.Series:
    """
    将一条筛选表达式 expr 解析为布尔掩码；大小写不敏感。
    支持：==, =, !=, >, >=, <, <=, "in [..]", "not in [..]", "is null", "is not null".
    """
    s = expr.strip()
    # "col in [a,b]" / "col not in [a,b]"
    m_in = re.match(r"^(\w+)\s+(not\s+in|in)\s+\[(.+)\]$", s, flags=re.I)
    if m_in:
        col, op, inner = m_in.group(1), m_in.group(2).lower(), m_in.group(3)
        if col not in series.index and not isinstance(series, pd.Series):
            raise ValueError("内部实现错误：series 并非 Series。")
        vals_raw = [v.strip() for v in inner.split(",")]
        ser = series

        null_mask = ser.isna() | ser.astype(str).str.strip().str.lower().isin({"", "null","none","nan","na"})
        # 处理非空值列表
        txt_vals = [_norm_text(v) for v in vals_raw if not _is_null_token(v)]
        txt_mask = ser.astype(str).str.strip().str.lower().isin(txt_vals) if txt_vals else pd.Series(False, index=ser.index)
        # 尝试数值匹配
        try:
            num_vals = [float(v) for v in vals_raw if not _is_null_token(v)]
            num_mask = pd.to_numeric(ser, errors="coerce").isin(num_vals)
        except Exception:
            num_mask = pd.Series(False, index=ser.index)

        base = null_mask | txt_mask | num_mask
        return ~base if op.startswith("not") else base

    # "col is null" / "col is not null"
    m_is = re.match(r"^(\w+)\s+is\s+(not\s+)?null$", s, flags=re.I)
    if m_is:
        col, neg = m_is.group(1), m_is.group(2)
        ser = series
        base = ser.isna() | ser.astype(str).str.strip().str.lower().isin({"", "null","none","nan","na"})
        return ~base if neg else base

    # 比较与等值
    m_cmp = re.match(r"^(\w+)\s*(==|=|!=|>=|>|<=|<)\s*(.+)$", s)
    if m_cmp:
        col, op, val = m_cmp.group(1), m_cmp.group(2), m_cmp.group(3)
        ser = series
        # 空值 token
        if _is_null_token(val):
            base = ser.isna() | ser.astype(str).str.strip().str.lower().isin({"", "null","none","nan","na"})
            return ~base if op == "!=" else base

        # 优先数值比较
        s_num = pd.to_numeric(ser, errors="coerce")
        try:
            v = float(val)
            if op == "==":  return s_num == v
            if op == "=":   return s_num == v
            if op == "!=":  return s_num != v
            if op == ">":   return s_num >  v
            if op == ">=":  return s_num >= v
            if op == "<":   return s_num <  v
            if op == "<=":  return s_num <= v
        except Exception:
            # 回退到文本比较（不分大小写、去空白）
            s_txt = ser.astype(str).str.strip().str.lower()
            vtxt = _norm_text(val)
            if op in {"==", "="}: return s_txt == vtxt
            if op == "!=":        return s_txt != vtxt
            # 其他比较对文本不具备严格意义，这里回退为 False/True 的保守逻辑
            if op in {">", ">=", "<", "<="}:
                return pd.Series(False, index=ser.index)

    raise ValueError(f"无法解析筛选表达式：{expr!r}。示例：gene in [A,B]、drug is null、time_point>=10。")


def main():
    ap = argparse.ArgumentParser(description="通用长表筛选与切分脚本")
    ap.add_argument("input", help="输入 Excel（长格式）文件路径")
    ap.add_argument("--output-dir", default=None, help="输出目录；默认在输入同目录创建 '<stem>_split'")
    ap.add_argument("--value-col", default="value", help="数据列名（默认 value）")
    ap.add_argument("--param-cols", default="AUTO",
                    help="逗号分隔的参数列名；默认 AUTO=除 value 列之外的所有列")
    ap.add_argument("--group-by", default=None,
                    help="逗号分隔的分组列名；留空=不分组（输出一个文件）")
    ap.add_argument("--filter", action="append", default=[],
                    help="可重复：筛选表达式，如 drug==tmrm、time_point>=10、gene in [A,B]、drug is null")
    ap.add_argument("--nan-token", default="NA", help="文件名中的空值占位符（默认 NA）")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise FileNotFoundError(f"未找到输入文件：{in_path}")

    out_dir = Path(args.output_dir) if args.output_dir else in_path.parent / f"{in_path.stem}_split"
    out_dir.mkdir(parents=True, exist_ok=True)

    if in_path.suffix.lower() == ".csv":
        df = pd.read_csv(in_path)
    else:
        df = pd.read_excel(in_path)
    if args.value_col not in df.columns:
        raise KeyError(f"未找到数据列 '{args.value_col}'；表头列为：{list(df.columns)}")

    # 自动/显式参数列
    if args.param_cols.strip().upper() == "AUTO":
        param_cols = [c for c in df.columns if c != args.value_col]
    else:
        param_cols = parse_csv_list(args.param_cols)
        for c in param_cols:
            if c not in df.columns:
                raise KeyError(f"参数列 '{c}' 不在表头中。")

    # 应用筛选（未写 --filter 的列完全不约束）
    mask = pd.Series(True, index=df.index)
    for fexpr in args.filter:
        fexpr = fexpr.strip()
        # 从表达式中解析列名，再取对应列生成掩码
        # 这里通过正则抽取第一个单词作为列名（与 build_condition_mask 匹配）
        m_col = re.match(r"^(\w+)", fexpr)
        if not m_col:
            raise ValueError(f"无法识别筛选列名：{fexpr}")
        col = m_col.group(1)
        if col not in df.columns:
            raise KeyError(f"筛选列 '{col}' 不在表头中。")
        mask &= build_condition_mask(df[col], fexpr)

    df_f = df[mask].copy()
    print(f"[信息] 输入行数：{len(df)}，筛选后行数：{len(df_f)}")

    # 分组切分
    if args.group_by:
        group_cols = parse_csv_list(args.group_by)
        for c in group_cols:
            if c not in df_f.columns:
                raise KeyError(f"分组列 '{c}' 不在表头中。")
        if df_f.empty:
            print("[警告] 无数据可写。")
            return
        for keys, sub in df_f.groupby(group_cols, dropna=False):
            # groupby 对单列时，keys 不是 tuple；统一转 tuple
            if not isinstance(keys, tuple):
                keys = (keys,)
            parts = []
            for col, val in zip(group_cols, keys):
                if pd.isna(val) or _is_null_token(str(val)):
                    parts.append(args.nan_token)
                else:
                    parts.append(str(val))
            fname = safe_filename("_".join(parts) + ".xlsx")
            out_path = out_dir / fname
            sub.to_excel(out_path, index=False)
            print(f"[写出] {out_path}  行数：{len(sub)}")
    else:
        # 不分组：写一个整体文件
        out_path = out_dir / "ALL.xlsx"
        df_f.to_excel(out_path, index=False)
        print(f"[写出] {out_path}  行数：{len(df_f)}")


if __name__ == "__main__":
    main()
