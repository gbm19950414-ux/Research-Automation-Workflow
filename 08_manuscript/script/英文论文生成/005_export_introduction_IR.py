#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
export_introduction_ir.py

USAGE
-----
Run without arguments from anywhere:

  python 005_export_introduction_IR.py

Expected project layout (relative to this script):

  08_manuscript/
    yaml/
      introduction_en.yaml
      policy_introduction.yaml   # optional
    IR/
      introduction.ir.yaml        # output
    script/英文论文生成/
      005_export_introduction_IR.py

What it does
------------
- Reads: 08_manuscript/yaml/introduction_en.yaml
- Reads (optional): 08_manuscript/yaml/policy_introduction.yaml
- Writes: 08_manuscript/IR/introduction.ir.yaml

Policy controls (policy_introduction.yaml)
------------------------------------------
- include_subheadings: bool   # reserved (currently not emitted in IR blocks)
- keep_hypotheses: bool       # include/exclude paragraphs containing 'hypotheses'
- filter.include_pids: [str]  # only include these paragraph pids (empty = include all)
- filter.exclude_pids: [str]  # exclude these paragraph pids

Default behavior (no policy or empty filters)
---------------------------------------------
- Output submission-ready Introduction IR:
  - Keep only the "Introduction" section and its paragraphs, in order
  - Paragraph = topic_sentence + sentences[] merged
  - Do NOT include YAML scaffolding fields: source_trace, bridge, narrative_role, etc.
  - Citations in `citations: ["[1]", ...]` or DOI strings are appended at paragraph end if missing

Notes
-----
- The script infers the 08_manuscript root as two levels above this file.
- If policy_introduction.yaml is missing, legacy defaults apply (include all non-hypotheses paragraphs).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping (dict).")
    return data


def _load_policy(path: Path) -> Dict[str, Any]:
    """Load a policy YAML. If missing, return defaults matching legacy behavior."""
    defaults: Dict[str, Any] = {
        "mode": "submission",
        "include_subheadings": False,
        "keep_hypotheses": False,
        "filter": {"include_pids": [], "exclude_pids": []},
    }
    if not path or not path.exists():
        return defaults
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        return defaults
    # merge shallow
    out = dict(defaults)
    out.update({k: raw.get(k) for k in ["mode", "include_subheadings", "keep_hypotheses"] if k in raw})
    filt = raw.get("filter")
    if isinstance(filt, dict):
        out_f = dict(defaults["filter"])
        out_f.update({k: filt.get(k) for k in ["include_pids", "exclude_pids"] if k in filt})
        out["filter"] = out_f
    return out


def _norm_str_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, str):
        x = [x]
    if not isinstance(x, list):
        return []
    out: List[str] = []
    for it in x:
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
    return out


def _dump_yaml(obj: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True, width=1000)


def _normalize_space(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return text.strip()


def _format_paragraph(topic_sentence: Optional[str], sentences: Optional[List[str]]) -> str:
    parts: List[str] = []
    if isinstance(topic_sentence, str) and topic_sentence.strip():
        parts.append(topic_sentence.strip())
    if isinstance(sentences, list):
        parts.extend([s.strip() for s in sentences if isinstance(s, str) and s.strip()])
    return _normalize_space(" ".join(parts))


def _append_citations(par_text: str, citations: Optional[List[str]]) -> str:
    """Append citations at paragraph end.

    Supports two input formats in YAML:
      1) Bracket indices: [1], [7-9], [1,2]  -> appended verbatim (legacy)
      2) DOI strings: 10.xxxx/..., doi:10.xxxx/..., https://doi.org/10.xxxx/... -> appended as {doi:...}

    If a citation token already appears in the paragraph text, it will not be duplicated.
    """
    if not citations or not isinstance(citations, list):
        return par_text

    doi_pat = re.compile(r"10\.\d{4,9}/[^\s<>\"'\]\)；;，,]+", re.IGNORECASE)

    def _to_doi_token(raw: str) -> Optional[str]:
        s = (raw or "").strip()
        if not s:
            return None

        # Legacy bracket citations
        if re.fullmatch(r"\[[0-9,\-\s]+\]", s):
            return s

        # DOI in various forms
        m = doi_pat.search(s)
        if not m:
            return None
        doi = m.group(0).rstrip(".")
        return "{doi:" + doi + "}"

    cleaned: List[str] = []
    for c in citations:
        if isinstance(c, str):
            tok = _to_doi_token(c)
            if tok:
                cleaned.append(tok)

    if not cleaned:
        return par_text

    missing = [c for c in cleaned if c not in par_text]
    if not missing:
        return par_text

    # Nature-style: citations follow the sentence-ending punctuation.
    if par_text.endswith((".", "!", "?")):
        return f"{par_text} {' '.join(missing)}"
    else:
        return f"{par_text}. {' '.join(missing)}"


def _iter_blocks(data: Dict[str, Any]) -> List[Tuple[Optional[str], Dict[str, Any]]]:
    # Accept either top-level or under manuscript:
    manuscript = data.get("manuscript", data)
    sections = manuscript.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Expected manuscript.sections to be a list.")

    blocks: List[Tuple[Optional[str], Dict[str, Any]]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        heading = sec.get("heading") if isinstance(sec.get("heading"), str) else None
        paragraphs = sec.get("paragraphs", [])
        if not isinstance(paragraphs, list):
            continue
        for p in paragraphs:
            if isinstance(p, dict):
                blocks.append((heading, p))
    return blocks


def build_introduction_ir(data: Dict[str, Any], *, keep_hypotheses: bool = False, include_pids: Optional[List[str]] = None, exclude_pids: Optional[List[str]] = None) -> Dict[str, Any]:
    blocks = _iter_blocks(data)
    out_blocks: List[Dict[str, Any]] = []

    include_set = set(_norm_str_list(include_pids)) if include_pids else set()
    exclude_set = set(_norm_str_list(exclude_pids)) if exclude_pids else set()

    last_heading: Optional[str] = None
    for heading, p in blocks:
        if (not keep_hypotheses) and ("hypotheses" in p):
            continue

        pid = p.get("pid") if isinstance(p.get("pid"), str) else ""
        pid = pid.strip() if pid else ""
        if include_set and pid and (pid not in include_set):
            continue
        if exclude_set and pid and (pid in exclude_set):
            continue

        topic_sentence = p.get("topic_sentence")
        sentences = p.get("sentences")
        par_text = _format_paragraph(topic_sentence, sentences)

        citations = p.get("citations")
        par_text = _append_citations(par_text, citations)

        if not par_text:
            continue

        meta: Dict[str, Any] = {}
        if pid:
            meta["pid"] = pid
        if heading:
            meta["section_heading"] = heading

        blk: Dict[str, Any] = {
            "type": "paragraph",
            "text": par_text,
        }
        if meta:
            blk.update(meta)
        out_blocks.append(blk)

    return {
        "ir_version": "0.1",
        "document": {
            "meta": {
                "id": "ephb1_introduction",
                "language": "en",
                "title": "",
                "authors": [],
                "date": "",
            },
            "sections": [
                {
                    "id": "introduction",
                    "title": "Introduction",
                    "blocks": out_blocks,
                }
            ],
        },
    }


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    manuscript_dir = script_dir.parents[1]  # .../08_manuscript

    # Expected layout:
    #   08_manuscript/
    #     yaml/introduction_en.yaml
    #     IR/introduction.ir.yaml   (output)
    yaml_path = manuscript_dir / "yaml" / "introduction_en.yaml"
    policy_path = manuscript_dir / "yaml" / "policy_introduction.yaml"
    policy = _load_policy(policy_path)

    include_subheadings = bool(policy.get("include_subheadings"))
    keep_hypotheses = bool(policy.get("keep_hypotheses"))
    filt = policy.get("filter") if isinstance(policy.get("filter"), dict) else {}
    include_pids = _norm_str_list(filt.get("include_pids"))
    exclude_pids = _norm_str_list(filt.get("exclude_pids"))

    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path.resolve()}")

    data = _load_yaml(yaml_path)
    ir = build_introduction_ir(
        data,
        keep_hypotheses=keep_hypotheses,
        include_pids=include_pids,
        exclude_pids=exclude_pids,
    )
    ir_out = manuscript_dir / "IR" / "introduction.ir.yaml"
    _dump_yaml(ir, ir_out)
    print(f"OK: wrote IR {ir_out}")


if __name__ == "__main__":
    main()