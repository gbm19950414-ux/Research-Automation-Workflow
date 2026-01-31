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
from typing import Any, Dict, List, Optional

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
) -> Dict[str, Any]:
    doc = outline.get("discussion_outline") or {}
    paragraphs = doc.get("paragraphs") or []

    blocks: List[Dict[str, Any]] = []

    for p in paragraphs:
        pid = str(p.get("id", "")).strip()
        title_en = str(p.get("title_en", "")).strip()

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


def resolve_default_paths(args: argparse.Namespace) -> tuple[Path, Path]:
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

    return in_path, out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Path to discussion_outline_en.yaml (default: 08_manuscript/yaml/discussion_outline_en.yaml)")
    ap.add_argument("--output", help="Path to output discussion.ir.yaml (default: 08_manuscript/IR/discussion.ir.yaml)")
    ap.add_argument("--with-subheadings", action="store_true", help="Include each D# title_en as a level-3 heading block")
    args = ap.parse_args()

    in_path, out_path = resolve_default_paths(args)

    print(f"[INFO] Using input YAML: {in_path}")
    outline = load_yaml(in_path)

    ir = build_discussion_ir(outline, with_subheadings=args.with_subheadings)

    dump_yaml(ir, out_path)
    print(f"[OK] Wrote IR: {out_path}")


if __name__ == "__main__":
    main()