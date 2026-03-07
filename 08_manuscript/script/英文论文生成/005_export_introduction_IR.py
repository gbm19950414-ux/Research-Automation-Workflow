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
- paragraph_groups: {name: {include: [str]}}  # primary paragraph assembly source; values may be paragraph ids, sentence ids, or field selectors like 1.1.2.p3.bridge
- filter.include_pids: [str]  # legacy fallback when paragraph_groups is absent
- filter.exclude_pids: [str]  # exclude paragraph ids or sentence ids using the same syntax

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
- If `paragraph_groups` is present in policy_introduction.yaml, it is used as the primary source of sentence selection and paragraph assembly.
- If `paragraph_groups` is absent, legacy defaults apply (include all non-hypotheses paragraphs, optionally filtered by include/exclude selectors).
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
        "paragraph_groups": {},
        "filter": {"include_pids": [], "exclude_pids": []},
    }
    if not path or not path.exists():
        return defaults
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        return defaults
    # merge shallow
    out = dict(defaults)
    out.update({k: raw.get(k) for k in ["mode", "include_subheadings", "keep_hypotheses", "paragraph_groups"] if k in raw})
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


def _split_selector(selector: str) -> Tuple[str, Optional[int], Optional[str]]:
    """Split a selector into paragraph pid, optional 1-based sentence index,
    and optional field selector.

    Supported forms:
      1.1.3.p3         -> ("1.1.3.p3", None, None)
      1.1.3.p3s2       -> ("1.1.3.p3", 2, None)
      1.1.2.p3.bridge  -> ("1.1.2.p3", None, "bridge")
      1.1.2.p3.topic   -> ("1.1.2.p3", None, "topic")
    """
    s = (selector or "").strip()
    if not s:
        return "", None, None

    # field selectors: <pid>.<field>
    m_field = re.match(r"^(.*?\.p\d+)\.(bridge|topic)$", s)
    if m_field:
        return m_field.group(1).strip(), None, m_field.group(2)

    # sentence selectors: <pid>sN
    m_sent = re.match(r"^(.*?)(?:s(\d+))?$", s)
    if not m_sent:
        return s, None, None

    base = (m_sent.group(1) or "").strip()
    idx = m_sent.group(2)
    return base, (int(idx) if idx is not None else None), None

def _sentence_units(pid: str, topic_sentence: Optional[str], sentences: Optional[List[str]]) -> List[Dict[str, Any]]:
    """Return ordered sentence units with stable sentence ids.

    Conventions:
      - If `topic_sentence` exists, it is sentence 1 and `sentences[0]` becomes sentence 2.
      - If `topic_sentence` is absent, `sentences[0]` is sentence 1.
    """
    units: List[Dict[str, Any]] = []
    next_idx = 1

    if isinstance(topic_sentence, str) and topic_sentence.strip():
        units.append({"sid": f"{pid}s{next_idx}" if pid else "", "index": next_idx, "text": topic_sentence.strip()})
        next_idx += 1

    if isinstance(sentences, list):
        for s in sentences:
            if isinstance(s, str) and s.strip():
                units.append({"sid": f"{pid}s{next_idx}" if pid else "", "index": next_idx, "text": s.strip()})
                next_idx += 1

    return units


def _selector_maps(values: Optional[List[str]]) -> Tuple[set, Dict[str, set]]:
    """Return (paragraph_selectors, sentence_selectors_by_pid)."""
    par_set: set = set()
    sent_map: Dict[str, set] = {}
    for raw in _norm_str_list(values):
        base, sidx, field = _split_selector(raw)
        if not base or field is not None:
            continue
        if sidx is None:
            par_set.add(base)
        else:
            sent_map.setdefault(base, set()).add(sidx)
    return par_set, sent_map


def _ordered_blocks(data: Dict[str, Any], *, keep_hypotheses: bool = False) -> List[Tuple[Optional[str], Dict[str, Any]]]:
    """Return blocks in source order, optionally excluding hypotheses paragraphs."""
    blocks = _iter_blocks(data)
    out: List[Tuple[Optional[str], Dict[str, Any]]] = []
    for heading, p in blocks:
        if (not keep_hypotheses) and ("hypotheses" in p):
            continue
        out.append((heading, p))
    return out


def _pid_lookup(data: Dict[str, Any], *, keep_hypotheses: bool = False) -> Dict[str, Tuple[Optional[str], Dict[str, Any]]]:
    """Map pid -> (heading, paragraph_dict). First occurrence wins."""
    lookup: Dict[str, Tuple[Optional[str], Dict[str, Any]]] = {}
    for heading, p in _ordered_blocks(data, keep_hypotheses=keep_hypotheses):
        pid = p.get("pid") if isinstance(p.get("pid"), str) else ""
        pid = pid.strip() if pid else ""
        if pid and pid not in lookup:
            lookup[pid] = (heading, p)
    return lookup


def _paragraph_groups_from_policy(policy: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
    """Return ordered paragraph groups as [(group_name, selectors), ...]."""
    pg = policy.get("paragraph_groups") if isinstance(policy.get("paragraph_groups"), dict) else {}
    out: List[Tuple[str, List[str]]] = []
    for name, spec in pg.items():
        if not isinstance(spec, dict):
            continue
        selectors = _norm_str_list(spec.get("include"))
        if selectors:
            out.append((str(name), selectors))
    return out

def _field_text_from_paragraph(p: Dict[str, Any], field: str) -> str:
    """Resolve special paragraph fields addressable from paragraph_groups.

    Supported fields:
      - bridge -> paragraph bridge sentence
      - topic  -> topic_sentence
    """
    if field == "bridge":
        v = p.get("bridge")
        return v.strip() if isinstance(v, str) and v.strip() else ""
    if field == "topic":
        v = p.get("topic_sentence")
        return v.strip() if isinstance(v, str) and v.strip() else ""
    return ""

def _citations_for_sentence(p: Dict[str, Any], pid: str, sidx: int) -> List[str]:
    """Resolve sentence-level citations.

    Supported forms:
      citations:
        "1.1.3.p3s2": ["[4]", "10.xxxx/..."]
        "s2": ["[4]"]
        "2": ["[4]"]

      sentence_citations:
        ...same key patterns as above...

      topic_citations: [...]   # applies to topic_sentence when present

      sentence_citations_list:
        - ["[1]"]    # sentence 1 under the final assembled paragraph
        - ["[2]"]    # sentence 2
    """
    out: List[str] = []
    full_sid = f"{pid}s{sidx}" if pid else ""
    local_sid = f"s{sidx}"
    num_sid = str(sidx)

    def _extend_from_mapping(obj: Any) -> None:
        nonlocal out
        if not isinstance(obj, dict):
            return
        for key in (full_sid, local_sid, num_sid):
            vals = obj.get(key)
            if isinstance(vals, str):
                vals = [vals]
            if isinstance(vals, list):
                out.extend([v.strip() for v in vals if isinstance(v, str) and v.strip()])

    # citations can now be either paragraph-level list or sentence-level mapping
    _extend_from_mapping(p.get("citations"))
    _extend_from_mapping(p.get("sentence_citations"))

    if sidx == 1:
        vals = p.get("topic_citations")
        if isinstance(vals, str):
            vals = [vals]
        if isinstance(vals, list):
            out.extend([v.strip() for v in vals if isinstance(v, str) and v.strip()])

    vals = p.get("sentence_citations_list")
    if isinstance(vals, list):
        idx0 = sidx - 1
        if 0 <= idx0 < len(vals):
            entry = vals[idx0]
            if isinstance(entry, str):
                entry = [entry]
            if isinstance(entry, list):
                out.extend([v.strip() for v in entry if isinstance(v, str) and v.strip()])

    # de-duplicate while preserving order
    seen = set()
    uniq: List[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _format_paragraph(parts: List[str]) -> str:
    return _normalize_space(" ".join([p.strip() for p in parts if isinstance(p, str) and p.strip()]))


def _append_citations(par_text: str, citations: Optional[List[str]]) -> str:
    """Append citations at paragraph end.

    Supports two input formats in YAML:
      1) Bracket indices: [1], [7-9], [1,2]  -> appended verbatim (legacy)
      2) DOI strings: 10.xxxx/..., doi:10.xxxx/..., https://doi.org/10.xxxx/... -> appended as {doi:...}

    If a citation token already appears in the paragraph text, it will not be duplicated.
    """
    if not citations or not isinstance(citations, list):
        return par_text

    doi_pat = re.compile(r"10\.\d{4,9}/[^\s<>\"'\]；;，,]+", re.IGNORECASE)

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


def _build_group_block(
    *,
    group_name: str,
    selectors: List[str],
    lookup: Dict[str, Tuple[Optional[str], Dict[str, Any]]],
    exclude_pars: set,
    exclude_sents: Dict[str, set],
) -> Optional[Dict[str, Any]]:
    """Assemble one paragraph block from ordered selectors.

    Selectors can be paragraph ids (e.g. 1.1.3.p3) or sentence ids (e.g. 1.1.3.p3s2).
    Sentence order follows the selector order in the group.
    """
    sentence_texts: List[str] = []
    selected_sids: List[str] = []
    selected_pids: List[str] = []
    heading_hint: Optional[str] = None

    for raw in selectors:
        base_pid, sidx, field = _split_selector(raw)
        if not base_pid or base_pid in exclude_pars:
            continue
        hit = lookup.get(base_pid)
        if not hit:
            continue
        heading, p = hit
        if heading_hint is None and heading:
            heading_hint = heading
        # special field selectors like <pid>.bridge or <pid>.topic
        if field is not None:
            txt = _field_text_from_paragraph(p, field)
            if txt:
                sentence_texts.append(txt)
                selected_sids.append(f"{base_pid}.{field}")
                if base_pid and base_pid not in selected_pids:
                    selected_pids.append(base_pid)
            continue
        units = _sentence_units(base_pid, p.get("topic_sentence"), p.get("sentences"))
        if not units:
            continue

        if sidx is None:
            picked = list(units)
        else:
            picked = [u for u in units if int(u.get("index") or 0) == sidx]

        if base_pid in exclude_sents:
            banned = exclude_sents.get(base_pid, set())
            picked = [u for u in picked if int(u.get("index") or 0) not in banned]

        for u in picked:
            txt = (u.get("text") or "").strip()
            idx = int(u.get("index") or 0)
            txt = _append_citations(txt, _citations_for_sentence(p, base_pid, idx))
            if txt:
                sentence_texts.append(txt)
                if u.get("sid"):
                    selected_sids.append(str(u.get("sid")))
                if base_pid and base_pid not in selected_pids:
                    selected_pids.append(base_pid)

    if not sentence_texts:
        return None

    blk: Dict[str, Any] = {
        "type": "paragraph",
        "text": _format_paragraph(sentence_texts),
        "paragraph_group": group_name,
    }
    if heading_hint:
        blk["section_heading"] = heading_hint
    if selected_pids:
        blk["source_pids"] = selected_pids
    if selected_sids:
        blk["selected_sids"] = selected_sids
    return blk


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


def build_introduction_ir(data: Dict[str, Any], *, keep_hypotheses: bool = False, paragraph_groups: Optional[List[Tuple[str, List[str]]]] = None, include_pids: Optional[List[str]] = None, exclude_pids: Optional[List[str]] = None) -> Dict[str, Any]:
    out_blocks: List[Dict[str, Any]] = []

    include_pars, include_sents = _selector_maps(include_pids)
    exclude_pars, exclude_sents = _selector_maps(exclude_pids)

    # Preferred mode: explicit paragraph assembly from paragraph_groups
    if paragraph_groups:
        lookup = _pid_lookup(data, keep_hypotheses=keep_hypotheses)
        for group_name, selectors in paragraph_groups:
            blk = _build_group_block(
                group_name=group_name,
                selectors=selectors,
                lookup=lookup,
                exclude_pars=exclude_pars,
                exclude_sents=exclude_sents,
            )
            if blk:
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

    blocks = _iter_blocks(data)
    last_heading: Optional[str] = None
    for heading, p in blocks:
        if (not keep_hypotheses) and ("hypotheses" in p):
            continue

        pid = p.get("pid") if isinstance(p.get("pid"), str) else ""
        pid = pid.strip() if pid else ""

        if pid and pid in exclude_pars:
            continue

        units = _sentence_units(pid, p.get("topic_sentence"), p.get("sentences"))
        if not units:
            continue

        # include logic
        if include_pars or include_sents:
            if pid and pid in include_pars:
                selected_units = list(units)
            elif pid and pid in include_sents:
                wanted = include_sents.get(pid, set())
                selected_units = [u for u in units if u.get("index") in wanted]
            else:
                continue
        else:
            selected_units = list(units)

        # exclude sentence-level selectors
        if pid and pid in exclude_sents:
            banned = exclude_sents.get(pid, set())
            selected_units = [u for u in selected_units if u.get("index") not in banned]

        if not selected_units:
            continue

        # sentence-level citations are attached inline to the selected sentence text.
        # Sentence numbering follows the assembled paragraph order:
        # topic_sentence = s1 when present; otherwise sentences[0] = s1.
        sentence_texts: List[str] = []
        for u in selected_units:
            txt = (u.get("text") or "").strip()
            sidx = int(u.get("index") or 0)
            txt = _append_citations(txt, _citations_for_sentence(p, pid, sidx))
            sentence_texts.append(txt)

        par_text = _format_paragraph(sentence_texts)

        # paragraph-level citations are appended only when present as a list
        # and only when the full paragraph is retained.
        par_citations = p.get("citations") if isinstance(p.get("citations"), list) else None
        full_paragraph_selected = len(selected_units) == len(units)
        if full_paragraph_selected:
            par_text = _append_citations(par_text, par_citations)

        meta: Dict[str, Any] = {}
        if pid:
            meta["pid"] = pid
            meta["selected_sids"] = [u.get("sid") for u in selected_units if u.get("sid")]
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
    paragraph_groups = _paragraph_groups_from_policy(policy)

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
        paragraph_groups=paragraph_groups,
        include_pids=include_pids,
        exclude_pids=exclude_pids,
    )
    ir_out = manuscript_dir / "IR" / "introduction.ir.yaml"
    _dump_yaml(ir, ir_out)
    print(f"OK: wrote IR {ir_out}")


if __name__ == "__main__":
    main()