#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from pathlib import Path
from typing import Dict, List, Any

from docx import Document

try:
    from ruamel.yaml import YAML
except ImportError:
    print("Missing dependency: ruamel.yaml\nInstall: pip install ruamel.yaml", file=sys.stderr)
    raise


DOI_RE = re.compile(
    r"""
    (?:
        https?://(?:dx\.)?doi\.org/      # https://doi.org/
        |
        https?://doi\.org[:/]            # https://doi.org:  或 https://doi.org/
        |
        doi\s*[:：]\s*                   # doi:
    )
    (?P<doi>10\.\d{4,9}/[^\s<>"'\]\)；;，,]+)   # DOI 本体
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 参考文献编号：行首 1 / 2 / 26 这类
LEADING_INDEX_RE = re.compile(r"^\s*(?P<idx>\d{1,4})\s+")


def extract_index_to_doi_from_docx(docx_path: Path) -> Dict[int, str]:
    doc = Document(str(docx_path))
    mapping: Dict[int, str] = {}

    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue

        m_idx = LEADING_INDEX_RE.match(text)
        if not m_idx:
            continue

        idx = int(m_idx.group("idx"))

        m_doi = DOI_RE.search(text)
        if not m_doi:
            # 有些 style 会把 DOI 放到下一行（同一条文献拆段），
            # 这里先跳过；后面可以用“合并段落”的增强版再处理
            continue

        doi = m_doi.group("doi").rstrip(".")
        mapping[idx] = doi

    return mapping


def expand_citation_token(token: str) -> List[int]:
    """
    token examples:
      "[26]" -> [26]
      "[7-9]" -> [7,8,9]
      "7" -> [7]
      "[26, 28]" -> [26,28]
    """
    t = token.strip()
    t = t.strip("[]").strip()

    if not t:
        return []

    # 支持逗号分隔
    parts = [x.strip() for x in t.split(",") if x.strip()]
    out: List[int] = []

    for part in parts:
        if "-" in part:
            a, b = [x.strip() for x in part.split("-", 1)]
            if a.isdigit() and b.isdigit():
                start, end = int(a), int(b)
                step = 1 if end >= start else -1
                out.extend(list(range(start, end + step, step)))
        else:
            if part.isdigit():
                out.append(int(part))

    return out


def replace_citations_in_obj(obj: Any, index_to_doi: Dict[int, str], missing: List[int]) -> Any:
    """
    Recursively traverse YAML-loaded structure and replace any key named 'citations'
    that is a list of strings with list of DOI strings.
    """
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "citations" and isinstance(v, list):
                doi_list: List[str] = []
                for item in v:
                    if not isinstance(item, str):
                        continue
                    for idx in expand_citation_token(item):
                        doi = index_to_doi.get(idx)
                        if doi:
                            doi_list.append(doi)
                        else:
                            missing.append(idx)
                # 去重但保留顺序
                seen = set()
                dedup = []
                for d in doi_list:
                    if d not in seen:
                        seen.add(d)
                        dedup.append(d)
                obj[k] = dedup
            else:
                obj[k] = replace_citations_in_obj(v, index_to_doi, missing)
        return obj

    if isinstance(obj, list):
        return [replace_citations_in_obj(x, index_to_doi, missing) for x in obj]

    return obj


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python map_citations_to_doi.py path/to/method.yaml path/to/references.docx [output.yaml]\n\n"
            "Example:\n"
            "  python map_citations_to_doi.py 08_manuscript/method.yaml manuscript.docx 08_manuscript/method_with_doi.yaml",
            file=sys.stderr,
        )
        sys.exit(2)

    yaml_path = Path(sys.argv[1]).expanduser().resolve()
    docx_path = Path(sys.argv[2]).expanduser().resolve()
    out_path = Path(sys.argv[3]).expanduser().resolve() if len(sys.argv) >= 4 else yaml_path.with_suffix(".with_doi.yaml")

    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX not found: {docx_path}")

    index_to_doi = extract_index_to_doi_from_docx(docx_path)
    if not index_to_doi:
        print("WARNING: No (index -> DOI) pairs extracted. Check the DOCX bibliography formatting.", file=sys.stderr)

    yaml = YAML()
    yaml.preserve_quotes = True

    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)

    missing: List[int] = []
    data2 = replace_citations_in_obj(data, index_to_doi, missing)

    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump(data2, f)

    missing_unique = sorted(set(missing))
    print(f"Extracted DOI mappings: {len(index_to_doi)}")
    print(f"Wrote: {out_path}")
    if missing_unique:
        print(f"Missing DOI for citation indices: {missing_unique}", file=sys.stderr)
        print("Tip: ensure those references in Word/EndNote output actually contain DOI, or the index order matches.", file=sys.stderr)


if __name__ == "__main__":
    main()