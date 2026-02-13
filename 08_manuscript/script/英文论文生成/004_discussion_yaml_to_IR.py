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

Usage:
  python 004_discussion_yaml_to_IR.py
  python 004_discussion_yaml_to_IR.py --with-subheadings
  python 004_discussion_yaml_to_IR.py --input /path/to/discussion_outline_en.yaml --output /path/to/discussion.ir.yaml
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
    include_para_ids: Optional[List[str]] = None,
    exclude_para_ids: Optional[List[str]] = None,
    include_verdict_levels: Optional[List[str]] = None,
    max_paragraphs: Optional[int] = None,
    apply_compression_rule: bool = False,
) -> Dict[str, Any]:
    doc = outline.get("discussion_outline") or {}
    paragraphs = doc.get("paragraphs") or []

    blocks: List[Dict[str, Any]] = []

    include_id_set = set(_norm_str_list(include_para_ids)) if include_para_ids else set()
    exclude_id_set = set(_norm_str_list(exclude_para_ids)) if exclude_para_ids else set()
    include_v_set = set(_norm_str_list(include_verdict_levels)) if include_verdict_levels else set()
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
        sentences = [str(x).strip() for x in sentences if str(x).strip()]

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