import os
import pandas as pd

def load_table(spec, required_cols=None, sheet_name=None):
    """
    读取表格数据，支持 Excel 指定 sheet，和自动兜底。
    
    参数
    ----
    spec : str | dict
        - str: "/path/to/file.xlsx" 或 "/path/to/file.xlsx::sheetname"
        - dict: {"path": "...", "sheet": "final_values"}（也兼容 "file" 键）
    required_cols : list[str] | None
        可选；若提供且初读不到这些列，将自动遍历所有 sheet 尝试找到含这些列的表。
    sheet_name : str | int | None
        可选；来自调用方的显式 sheet 参数（例如 boxplot 里传入）。当 `spec` 未提供 sheet 时优先使用该参数。
    """
    def _ensure_expr_cols(df, cols):
        # 遍历 cols，处理表达式列生成
        for c in cols:
            if isinstance(c, str) and '+' in c and c not in df.columns:
                parts = c.split('+')
                expr_parts = []
                for p in parts:
                    p = p.strip()
                    if p.startswith("'") and p.endswith("'"):
                        expr_parts.append(eval(p))
                    else:
                        if p in df.columns:
                            expr_parts.append(df[p].astype(str).fillna(""))
                        else:
                            # 如果列不存在，用空字符串占位
                            expr_parts.append('')
                # 连接所有部分
                df[c] = pd.Series(expr_parts[0])
                for part in expr_parts[1:]:
                    if isinstance(part, pd.Series):
                        df[c] = df[c] + part
                    else:
                        df[c] = df[c] + part

    sheet = None
    if isinstance(spec, dict):
        path = spec.get("path") or spec.get("file")
        sheet = spec.get("sheet")
    else:
        path = spec
        # 兼容 "path::sheet" 写法
        if isinstance(path, str) and "::" in path:
            path, sheet = path.split("::", 1)

    # 兼容 dict 中使用 "sheet_name" 的写法；并且函数参数优先级高于 spec 内的配置
    if isinstance(spec, dict) and spec.get("sheet_name") is not None:
        sheet = spec.get("sheet_name")
    if sheet is None and sheet_name is not None:
        sheet = sheet_name

    ext = os.path.splitext(path)[1].lower()

    # Excel
    if ext in (".xlsx", ".xls"):
        # 先按显式 sheet 或默认第一个 sheet 读
        df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)

        # 处理 required_cols 中的表达式列
        if required_cols:
            _ensure_expr_cols(df, required_cols)

        # 如果需要特定列而当前 sheet 不包含，则尝试在其他 sheet 兜底搜索
        if required_cols:
            missing = [c for c in required_cols if (isinstance(c, str) and c not in df.columns)]
            if missing:
                try:
                    xls = pd.ExcelFile(path)
                    for s in xls.sheet_names:
                        try:
                            tmp = pd.read_excel(path, sheet_name=s)
                        except Exception:
                            continue
                        # 同样处理表达式列
                        _ensure_expr_cols(tmp, required_cols)
                        if all((c in tmp.columns) for c in required_cols if isinstance(c, str)):
                            return tmp
                except Exception:
                    pass
        return df

    # CSV / TSV
    if ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext in (".tsv", ".txt") else ","
        df = pd.read_csv(path, sep=sep)

        # 处理 required_cols 中的表达式列
        if required_cols:
            for c in required_cols:
                if isinstance(c, str) and '+' in c and c not in df.columns:
                    parts = c.split('+')
                    expr_cols = []
                    sep_str = ''
                    for p in parts:
                        p = p.strip()
                        if p.startswith("'") and p.endswith("'"):
                            sep_str += eval(p)
                        else:
                            expr_cols.append(p)
                    if len(expr_cols) == 2:
                        col1, col2 = expr_cols
                        if col1 in df.columns and col2 in df.columns:
                            df[c] = df[col1].astype(str) + sep_str + df[col2].astype(str)
        return df

    # 其他：尝试 read_table
    return pd.read_table(path)