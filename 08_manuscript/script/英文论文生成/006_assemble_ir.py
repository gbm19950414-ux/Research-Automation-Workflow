#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Assemble multiple section-level IR YAML files into one manuscript IR.

Default behavior (no arguments):
- Read all *.ir.yaml under 08_manuscript/IR/
- Sort by predefined section order
- Output: 08_manuscript/IR/manuscript.ir.yaml

This is a minimal assembler:
- No validation beyond basic structure
- No deduplication
- No renumbering (figures / citations handled later)
"""

from pathlib import Path
from typing import List, Dict, Any
import yaml


# =========================
# Fixed paths
# =========================

PROJECT_ROOT = Path("/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1")
MANUSCRIPT_DIR = PROJECT_ROOT / "08_manuscript"
IR_DIR = MANUSCRIPT_DIR / "IR"
OUT_PATH = IR_DIR / "manuscript.ir.yaml"


# =========================
# Section ordering (MVP)
# =========================

SECTION_ORDER = [
    "abstract",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
]


# =========================
# Utilities
# =========================

def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_ir_files(ir_dir: Path) -> List[Path]:
    files = sorted(ir_dir.glob("*.ir.yaml"))
    # Exclude the output file itself to avoid re-ingesting the assembled manuscript IR,
    # which would cause accumulation and duplication of sections.
    if OUT_PATH in files:
        files.remove(OUT_PATH)
    if not files:
        raise FileNotFoundError(f"No IR files found in {ir_dir}")
    return files


def extract_sections(ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    doc = ir.get("document", {})
    sections = doc.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("IR document.sections must be a list")
    return sections


# =========================
# Assemble logic
# =========================

def assemble_irs(ir_files: List[Path]) -> Dict[str, Any]:
    all_sections: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}

    for idx, path in enumerate(ir_files):
        ir = load_yaml(path)

        if idx == 0:
            # Use meta from the first IR
            meta = ir.get("document", {}).get("meta", {}).copy()

        sections = extract_sections(ir)

        # Exclude figure list sections from manuscript IR.
        # Figures and supplementary figures are rendered separately
        # from figures_ir.yaml / supplement_figures_ir.yaml.
        filtered_sections = [
            s for s in sections
            if s.get("id") not in {"figures", "supplement_figures"}
        ]

        all_sections.extend(filtered_sections)

    # Sort sections by predefined order; unknown sections go last
    def section_sort_key(sec: Dict[str, Any]) -> int:
        sec_id = sec.get("id", "")
        if sec_id in SECTION_ORDER:
            return SECTION_ORDER.index(sec_id)
        return len(SECTION_ORDER) + 1

    all_sections.sort(key=section_sort_key)

    manuscript_ir = {
        "ir_version": "0.1",
        "document": {
            "meta": meta,
            "sections": all_sections,
        },
    }

    return manuscript_ir


def write_ir(ir: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(ir, f, sort_keys=False, allow_unicode=True, width=1000)


# =========================
# Entry
# =========================

def main():
    print(f"[INFO] Collecting IR files from {IR_DIR}")
    ir_files = collect_ir_files(IR_DIR)

    print("[INFO] IR files:")
    for p in ir_files:
        print(f"  - {p.name}")

    manuscript_ir = assemble_irs(ir_files)

    print(f"[INFO] Writing assembled IR → {OUT_PATH}")
    write_ir(manuscript_ir, OUT_PATH)

    print(f"[OK] Assembled manuscript IR: {OUT_PATH}")


if __name__ == "__main__":
    main()