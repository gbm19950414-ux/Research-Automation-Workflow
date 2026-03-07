#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

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
        https?://doi\.org[:/]            # https://doi.org:  or https://doi.org/
        |
        doi\s*[:：]\s*                   # doi:
    )
    (?P<doi>10\.\d{4,9}/[^\s<>"'\]；;，,]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 参考文献编号：行首 1 / 2 / 26 这类
LEADING_INDEX_RE = re.compile(r"^\s*(?P<idx>\d{1,4})\s+")

# 用于识别 YAML 中已经存在的 DOI（完整或不完整前缀）
DOI_LIKE_RE = re.compile(r"^(10\.\d{4,9}/\S+)$", re.IGNORECASE)
DOI_PREFIX_RE = re.compile(r'^(10\.\d{4,9}/[^\s<>{}\[\]"\']+)$', re.IGNORECASE)


def extract_index_to_doi_from_docx(docx_path: Path) -> Dict[int, str]:
    """Extract bibliography index -> DOI from a DOCX file.

    More robust than paragraph-only extraction:
    - starts a new reference block when a paragraph begins with an index
    - appends following non-index paragraphs to the same block
    - searches DOI across the full block text
    """
    doc = Document(str(docx_path))
    mapping: Dict[int, str] = {}

    current_idx: Optional[int] = None
    current_lines: List[str] = []

    def _flush_block() -> None:
        nonlocal current_idx, current_lines, mapping
        if current_idx is None:
            current_lines = []
            return
        block_text = " ".join([x.strip() for x in current_lines if isinstance(x, str) and x.strip()])
        if not block_text:
            current_idx = None
            current_lines = []
            return

        m_doi = DOI_RE.search(block_text)
        if m_doi:
            doi = normalize_doi_text(m_doi.group("doi"))
            mapping[current_idx] = doi

        current_idx = None
        current_lines = []

    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue

        m_idx = LEADING_INDEX_RE.match(text)
        if m_idx:
            # new reference entry begins; flush previous block first
            _flush_block()
            current_idx = int(m_idx.group("idx"))
            current_lines = [text]
        else:
            # continuation line of current reference entry
            if current_idx is not None:
                current_lines.append(text)

    # flush last block
    _flush_block()
    return mapping


def normalize_doi_text(s: str) -> str:
    """Normalize DOI-like text for comparison.

    - strip whitespace
    - remove leading DOI URL / doi: prefix if present
    - strip trailing punctuation commonly introduced by export/typing
    - lowercase for stable matching
    """
    t = (s or "").strip()
    t = re.sub(r"^https?://(?:dx\.)?doi\.org[:/]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^doi\s*[:：]\s*", "", t, flags=re.IGNORECASE)
    t = t.strip().rstrip(".;,，；])}")
    return t.lower()


def complete_doi_prefix(doi_prefix: str, index_to_doi: Dict[int, str]) -> Optional[str]:
    """Repair an incomplete DOI prefix by matching against DOCX-extracted full DOIs.

    Matching strategy:
    1) normalized exact match
    2) unique full DOI starting with the normalized prefix
    3) unique full DOI whose punctuation-stripped form starts with the punctuation-stripped prefix

    Returns a full DOI if and only if there is a unique match.
    """
    prefix = normalize_doi_text(doi_prefix)
    if not prefix.startswith("10."):
        return None

    # exact match first
    exact_matches: List[str] = []
    for doi in index_to_doi.values():
        full = normalize_doi_text(doi)
        if full == prefix:
            exact_matches.append(full)
    if len(set(exact_matches)) == 1 and exact_matches:
        return exact_matches[0]

    # direct prefix match
    matches: List[str] = []
    for doi in index_to_doi.values():
        full = normalize_doi_text(doi)
        if full.startswith(prefix):
            matches.append(full)

    uniq = []
    seen = set()
    for m in matches:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    if len(uniq) == 1:
        return uniq[0]

    # punctuation-insensitive fallback, useful for truncated strings like
    # 10.1016/s0140-6736(19  -> 10.1016/s0140-6736(19)32989-7
    def _strip_punct(s: str) -> str:
        return re.sub(r"[^a-z0-9./]", "", s.lower())

    stripped_prefix = _strip_punct(prefix)
    if not stripped_prefix.startswith("10."):
        return None

    fuzzy_matches: List[str] = []
    for doi in index_to_doi.values():
        full = normalize_doi_text(doi)
        if _strip_punct(full).startswith(stripped_prefix):
            fuzzy_matches.append(full)

    uniq_fuzzy = []
    seen_fuzzy = set()
    for m in fuzzy_matches:
        if m not in seen_fuzzy:
            seen_fuzzy.add(m)
            uniq_fuzzy.append(m)

    if len(uniq_fuzzy) == 1:
        return uniq_fuzzy[0]
    return None


def resolve_citation_item(item: str, index_to_doi: Dict[int, str], missing: List[int], repaired: List[str]) -> List[str]:
    """Resolve one YAML citations item into DOI strings.

    Supported inputs:
      - reference indices: "[26]", "[7-9]", "7"
      - full DOI already present: "10.1038/nature15514"
      - incomplete DOI prefix: "10.1016/s0140-6736(19"
    """
    out: List[str] = []
    raw = (item or "").strip()
    if not raw:
        return out

    # 1) 尝试按编号引用解析
    idxs = expand_citation_token(raw)
    if idxs:
        for idx in idxs:
            doi = index_to_doi.get(idx)
            if doi:
                out.append(normalize_doi_text(doi))
            else:
                missing.append(idx)
        return out

    # 2) 如果已经是 DOI-like 文本，则尝试直接保留 / 修复
    norm = normalize_doi_text(raw)
    if norm.startswith("10."):
        # 2a) 与 DOCX 中完整 DOI 精确一致
        for doi in index_to_doi.values():
            full = normalize_doi_text(doi)
            if norm == full:
                out.append(full)
                return out

        # 2b) 不完整 DOI 前缀：尝试修复为完整 DOI
        repaired_doi = complete_doi_prefix(norm, index_to_doi)
        if repaired_doi:
            if repaired_doi != norm:
                repaired.append(f"{raw} -> {repaired_doi}")
            out.append(repaired_doi)
            return out

        # 2c) 如果 raw 本身包含 doi URL / doi: 前缀，也尝试再次修复
        raw_repaired = complete_doi_prefix(raw, index_to_doi)
        if raw_repaired:
            if normalize_doi_text(raw_repaired) != norm:
                repaired.append(f"{raw} -> {raw_repaired}")
            out.append(normalize_doi_text(raw_repaired))
            return out

        # 2d) 无法修复时，原样保留规范化后的 DOI-like 值，避免数据丢失
        out.append(norm)
        return out

    # 3) 其他无法识别的字符串：原样忽略（保持与旧行为一致）
    return out


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


def replace_citations_in_obj(obj: Any, index_to_doi: Dict[int, str], missing: List[int], repaired: List[str]) -> Any:
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
                    doi_list.extend(resolve_citation_item(item, index_to_doi, missing, repaired))

                # 去重但保留顺序
                seen = set()
                dedup = []
                for d in doi_list:
                    if d not in seen:
                        seen.add(d)
                        dedup.append(d)
                obj[k] = dedup
            else:
                obj[k] = replace_citations_in_obj(v, index_to_doi, missing, repaired)
        return obj

    if isinstance(obj, list):
        return [replace_citations_in_obj(x, index_to_doi, missing, repaired) for x in obj]

    return obj


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python map_citations_to_doi.py path/to/method.yaml path/to/references.docx [output.yaml]\n\n"
            "Example:\n"
            "  python map_citations_to_doi.py 08_manuscript/method.yaml manuscript.docx 08_manuscript/method_with_doi.yaml"
            "\nAlso repairs incomplete DOI prefixes already present in YAML citations by matching against the DOCX bibliography when possible.",
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
    repaired: List[str] = []
    data2 = replace_citations_in_obj(data, index_to_doi, missing, repaired)

    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump(data2, f)

    missing_unique = sorted(set(missing))
    print(f"Extracted DOI mappings: {len(index_to_doi)}")
    if index_to_doi:
        preview = list(index_to_doi.items())[:10]
        print("DOCX extraction preview:")
        for idx, doi in preview:
            print(f"  [{idx}] {doi}")
    print(f"Wrote: {out_path}")
    if repaired:
        print(f"Repaired incomplete DOI prefixes: {len(repaired)}")
        for line in repaired:
            print(f"  {line}")

    if missing_unique:
        print(f"Missing DOI for citation indices: {missing_unique}", file=sys.stderr)
        print("Tip: ensure those references in Word/EndNote output actually contain DOI, or the index order matches.", file=sys.stderr)


if __name__ == "__main__":
    main()