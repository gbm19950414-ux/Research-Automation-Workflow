#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
004_discussion_yaml_to_IR.py

Build Discussion IR from:
  08_manuscript/yaml/discussion_outline_en.yaml

Output:
  08_manuscript/IR/discussion.ir.yaml

Design:
- Use paragraphs[*].sentences_en as source of main text.
- Join sentences into a paragraph (space-separated).
- Optionally include each D# title as a subheading block.
- If policy contains `paragraph_groups`, Discussion is assembled from ordered paragraph groups instead of raw D1–D5 order.
- In paragraph-groups mode, selectors can be full paragraphs (e.g. `D1`) or sentence ids (e.g. `D1s2`).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(obj: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True, width=1000)


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


def _split_selector(selector: str) -> Tuple[str, Optional[int]]:
    """Split a selector into base paragraph id and optional 1-based sentence index.

    Examples:
      D1    -> ("D1", None)
      D1s2  -> ("D1", 2)
    """
    s = (selector or "").strip()
    if not s:
        return "", None
    m = re.match(r"^(D\d+)(?:s(\d+))?$", s, flags=re.IGNORECASE)
    if not m:
        return s, None
    base = (m.group(1) or "").strip()
    idx = m.group(2)
    return base, (int(idx) if idx is not None else None)


def _selector_maps(values: Optional[List[str]]) -> Tuple[set, Dict[str, set]]:
    """Return (paragraph_selectors, sentence_selectors_by_pid)."""
    par_set: set = set()
    sent_map: Dict[str, set] = {}
    for raw in _norm_str_list(values):
        base, sidx = _split_selector(raw)
        if not base:
            continue
        if sidx is None:
            par_set.add(base)
        else:
            sent_map.setdefault(base, set()).add(sidx)
    return par_set, sent_map


def _sentence_units(pid: str, sentences: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Return ordered sentence units with stable sentence ids.

    Convention:
      sentences_en[0] -> <pid>s1
      sentences_en[1] -> <pid>s2
      ...
    Supports both legacy string lists and future dict-based sentence items with a
    `text` field.
    """
    units: List[Dict[str, Any]] = []
    if not isinstance(sentences, list):
        return units

    idx = 1
    for item in sentences:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            raw = item.get("text")
            if isinstance(raw, str):
                text = raw.strip()
        else:
            text = str(item).strip()

        if text:
            units.append({"sid": f"{pid}s{idx}" if pid else "", "index": idx, "text": text})
            idx += 1
    return units


def _ordered_paragraphs(outline: Dict[str, Any]) -> List[Dict[str, Any]]:
    doc = outline.get("discussion_outline") or {}
    paragraphs = doc.get("paragraphs") or []
    return [p for p in paragraphs if isinstance(p, dict)]


def _pid_lookup(outline: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for p in _ordered_paragraphs(outline):
        pid = str(p.get("id", "")).strip()
        if pid and pid not in lookup:
            lookup[pid] = p
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


def _build_group_block(
    *,
    group_name: str,
    selectors: List[str],
    lookup: Dict[str, Dict[str, Any]],
    with_subheadings: bool = False,
    exclude_pars: Optional[set] = None,
    exclude_sents: Optional[Dict[str, set]] = None,
) -> List[Dict[str, Any]]:
    """Assemble one discussion paragraph block from ordered selectors.

    Selectors can be full paragraph ids (e.g. D1) or sentence ids (e.g. D1s2).
    The final sentence order follows the selector order exactly.
    """
    exclude_pars = exclude_pars or set()
    exclude_sents = exclude_sents or {}

    sentence_texts: List[str] = []
    source_para_ids: List[str] = []
    selected_sids: List[str] = []
    title_hint: str = ""

    for raw in selectors:
        base_pid, sidx = _split_selector(raw)
        if not base_pid or base_pid in exclude_pars:
            continue
        p = lookup.get(base_pid)
        if not p:
            continue

        if not title_hint:
            title_hint = str(p.get("title_en", "")).strip()

        units = _sentence_units(base_pid, p.get("sentences_en"))
        if not units:
            legacy_para = p.get("draft_paragraph_en", "")
            units = _sentence_units(base_pid, split_sentences_fallback(legacy_para))
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
            if not txt:
                continue
            sentence_texts.append(txt)
            if u.get("sid"):
                selected_sids.append(str(u.get("sid")))
            if base_pid not in source_para_ids:
                source_para_ids.append(base_pid)

    blocks: List[Dict[str, Any]] = []
    if not sentence_texts:
        return blocks

    if with_subheadings and title_hint:
        blocks.append(
            {
                "type": "heading",
                "level": 3,
                "text": title_hint,
                "source": "discussion_outline_en.yaml",
                "paragraph_group": group_name,
                "source_para_ids": source_para_ids,
            }
        )

    blocks.append(
        {
            "type": "paragraph",
            "text": " ".join(sentence_texts).strip(),
            "source": "discussion_outline_en.yaml",
            "paragraph_group": group_name,
            "source_para_ids": source_para_ids,
            "selected_sids": selected_sids,
        }
    )
    return blocks


def load_policy(path: Path) -> Dict[str, Any]:
    """Load policy YAML; missing/invalid -> {} (preserve legacy behavior)."""
    if not path or not path.exists():
        return {}
    obj = load_yaml(path)
    return obj if isinstance(obj, dict) else {}


def find_manuscript_dir(script_path: Path) -> Path:
    """
    Expect script lives in:
      08_manuscript/script/英文论文生成/004_discussion_yaml_to_IR.py
    So manuscript_dir is 3 levels up from this file:
      script_path.parent -> 英文论文生成
      parent.parent -> script
      parent.parent.parent -> 08_manuscript
    """
    return script_path.resolve().parents[2].parents[0]  # safer read? We'll do explicit below


def manuscript_dir_from_script(script_path: Path) -> Path:
    p = script_path.resolve()
    # .../08_manuscript/script/英文论文生成/<this.py>
    # parents[0]=英文论文生成, [1]=script, [2]=08_manuscript
    return p.parents[2]


def split_sentences_fallback(paragraph: str) -> List[str]:
    """
    Fallback if legacy key draft_paragraph_en is present but sentences_en missing.
    Conservative: split on . ? ! followed by whitespace+Capital/quote or end.
    """
    s = (paragraph or "").strip()
    if not s:
        return []
    # keep punctuation
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", s)
    return [p.strip() for p in parts if p.strip()]


def build_discussion_ir(
    outline: Dict[str, Any],
    with_subheadings: bool = False,
    *,
    paragraph_groups: Optional[List[Tuple[str, List[str]]]] = None,
    include_para_ids: Optional[List[str]] = None,
    exclude_para_ids: Optional[List[str]] = None,
    include_verdict_levels: Optional[List[str]] = None,
    max_paragraphs: Optional[int] = None,
    apply_compression_rule: bool = False,
) -> Dict[str, Any]:
    doc = outline.get("discussion_outline") or {}
    paragraphs = doc.get("paragraphs") or []

    blocks: List[Dict[str, Any]] = []

    include_id_set, include_sent_map = _selector_maps(include_para_ids)
    exclude_id_set, exclude_sent_map = _selector_maps(exclude_para_ids)
    include_v_set = set(_norm_str_list(include_verdict_levels)) if include_verdict_levels else set()

    # Preferred mode: explicit paragraph assembly from paragraph_groups.
    # In this mode, structure is controlled by policy paragraph_groups, not by
    # raw source paragraph order.
    if paragraph_groups:
        lookup = _pid_lookup(outline)
        kept = 0
        for group_name, selectors in paragraph_groups:
            group_blocks = _build_group_block(
                group_name=group_name,
                selectors=selectors,
                lookup=lookup,
                with_subheadings=with_subheadings,
                exclude_pars=exclude_id_set,
                exclude_sents=exclude_sent_map,
            )
            if group_blocks:
                blocks.extend(group_blocks)
                kept += 1
                if max_paragraphs is not None and kept >= max_paragraphs:
                    break

        return {
            "ir_version": "0.1",
            "document": {
                "meta": {
                    "id": "ephb1_discussion",
                    "language": "en",
                    "title": "",
                    "authors": [],
                    "date": "",
                },
                "sections": [
                    {
                        "id": "discussion",
                        "title": "Discussion",
                        "blocks": blocks,
                    }
                ],
            },
        }

    kept = 0
    for p in paragraphs:
        pid = str(p.get("id", "")).strip()
        title_en = str(p.get("title_en", "")).strip()

        verdict_level = str(p.get("verdict_level", "")).strip()

        # Policy filters
        if include_v_set and verdict_level and (verdict_level not in include_v_set):
            continue
        if include_id_set and pid and (pid not in include_id_set):
            continue
        if exclude_id_set and pid and (pid in exclude_id_set):
            continue

        # Prefer sentences_en
        sentences = p.get("sentences_en")
        if sentences is None:
            # fallback legacy
            legacy_para = p.get("draft_paragraph_en", "")
            sentences = split_sentences_fallback(legacy_para)

        # normalize
        if not isinstance(sentences, list):
            sentences = []
        normalized_sentences: List[str] = []
        for x in sentences:
            if isinstance(x, dict):
                raw = x.get("text")
                if isinstance(raw, str) and raw.strip():
                    normalized_sentences.append(raw.strip())
            else:
                sx = str(x).strip()
                if sx:
                    normalized_sentences.append(sx)
        sentences = normalized_sentences

        if apply_compression_rule:
            cr = p.get("compression_rule") if isinstance(p.get("compression_rule"), dict) else {}
            ms = cr.get("max_sentences")
            if isinstance(ms, str) and ms.strip().isdigit():
                ms = int(ms.strip())
            if isinstance(ms, int) and ms > 0:
                sentences = sentences[:ms]

        if not sentences:
            # Skip empty paragraph entries silently
            continue

        if with_subheadings and title_en:
            blocks.append(
                {
                    "type": "heading",
                    "level": 3,
                    "text": title_en,
                    "source": "discussion_outline_en.yaml",
                    "para_id": pid,
                }
            )

        text = " ".join(sentences).strip()
        blocks.append(
            {
                "type": "paragraph",
                "text": text,
                "source": "discussion_outline_en.yaml",
                "para_id": pid,
            }
        )

        kept += 1
        if max_paragraphs is not None and kept >= max_paragraphs:
            break

    return {
        "ir_version": "0.1",
        "document": {
            "meta": {
                "id": "ephb1_discussion",
                "language": "en",
                "title": "",
                "authors": [],
                "date": "",
            },
            "sections": [
                {
                    "id": "discussion",
                    "title": "Discussion",
                    "blocks": blocks,
                }
            ],
        },
    }


def resolve_default_paths(args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    # If user passes --input/--output, respect them
    if args.input:
        in_path = Path(args.input).expanduser()
    else:
        script_path = Path(__file__).resolve()
        manuscript_dir = manuscript_dir_from_script(script_path)
        in_path = manuscript_dir / "yaml" / "discussion_outline_en.yaml"

    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        script_path = Path(__file__).resolve()
        manuscript_dir = manuscript_dir_from_script(script_path)
        out_path = manuscript_dir / "IR" / "discussion.ir.yaml"

    if args.policy:
        policy_path = Path(args.policy).expanduser()
    else:
        script_path = Path(__file__).resolve()
        manuscript_dir = manuscript_dir_from_script(script_path)
        policy_path = manuscript_dir / "yaml" / "policy_discussion.yaml"

    return in_path, out_path, policy_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Path to discussion_outline_en.yaml (default: 08_manuscript/yaml/discussion_outline_en.yaml)")
    ap.add_argument("--output", help="Path to output discussion.ir.yaml (default: 08_manuscript/IR/discussion.ir.yaml)")
    ap.add_argument("--policy", help="Path to policy_discussion.yaml (default: 08_manuscript/yaml/policy_discussion.yaml)")
    ap.add_argument("--with-subheadings", action="store_true", help="Include each D# title_en as a level-3 heading block")
    args = ap.parse_args()

    in_path, out_path, policy_path = resolve_default_paths(args)

    print(f"[INFO] Using input YAML: {in_path}")
    outline = load_yaml(in_path)

    policy = load_policy(policy_path)
    paragraph_groups = _paragraph_groups_from_policy(policy)

    include_subheadings = bool(policy.get("include_subheadings", False))
    apply_compression_rule = bool(policy.get("apply_compression_rule", False))

    filt = policy.get("filter") if isinstance(policy.get("filter"), dict) else {}
    include_para_ids = _norm_str_list(filt.get("include_para_ids"))
    exclude_para_ids = _norm_str_list(filt.get("exclude_para_ids"))
    include_verdict_levels = _norm_str_list(filt.get("include_verdict_levels"))

    max_paragraphs = filt.get("max_paragraphs")
    if isinstance(max_paragraphs, str) and max_paragraphs.strip().isdigit():
        max_paragraphs = int(max_paragraphs.strip())
    if not isinstance(max_paragraphs, int):
        max_paragraphs = None

    # CLI flag takes precedence over policy
    with_subheadings = args.with_subheadings or include_subheadings

    print(f"[INFO] Using policy YAML: {policy_path}")

    ir = build_discussion_ir(
        outline,
        with_subheadings=with_subheadings,
        paragraph_groups=paragraph_groups,
        include_para_ids=include_para_ids,
        exclude_para_ids=exclude_para_ids,
        include_verdict_levels=include_verdict_levels,
        max_paragraphs=max_paragraphs,
        apply_compression_rule=apply_compression_rule,
    )

    dump_yaml(ir, out_path)
    print(f"[OK] Wrote IR: {out_path}")


if __name__ == "__main__":
    main()