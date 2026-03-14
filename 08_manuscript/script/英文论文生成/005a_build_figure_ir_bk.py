#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build an Evidence-IR YAML for figures (figure asset + figure title + stitched legends)
from:
  - 06_figures/record/paper_logic.yaml (figure_order + figure title mapping)
  - 06_figures/record/*.yaml (panel records containing figure_legend and optionally panel_overrides)
  - 06_figures/figs/figure_1.ai ... as figure sources (also tries .pdf/.png if present)

Key design goals (per our discussion):
  1) Use paper_logic.yaml.figure_order as the ONLY inclusion list
  2) Group records by YAML meta.figure (e.g., "Figure 6") rather than filename guessing
  3) Support BOTH legend schemas:
       - single-panel: top-level figure_legend with figure_legend.panel="a"
       - multi-panel: shared figure_legend + panel_overrides{a:{...}, b:{...}}
  4) Render "figure_legend" text by stitching suitable fields per panel
  5) Output a single IR YAML for later unified rendering (docx/pdf/etc.)

Usage:
  python build_figures_ir.py \
    --root /Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1 \
    --paper-logic 06_figures/record/paper_logic.yaml \
    --record-dir 06_figures/record \
    --figs-dir 06_figures/figs \
    --out 08_manuscript/IR/figures_ir.yaml
  python 005a_build_figure_ir.py --no-write-results-ir   # only write figures_ir.yaml
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Union

import yaml


# -----------------------------
# Helpers
# -----------------------------
def load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML supporting single or multi-document streams.

    If multiple documents are present (---), later documents override earlier keys.
    This prevents PyYAML ComposerError and keeps behavior deterministic.
    """
    if not path.exists():
        raise FileNotFoundError(f"YAML not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    docs = [d for d in docs if d is not None]
    if not docs:
        return {}
    if len(docs) == 1:
        return docs[0] or {}
    merged: Dict[str, Any] = {}
    for d in docs:
        if isinstance(d, dict):
            merged.update(d)
    return merged


def dump_yaml(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            obj,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )


# --- Legend policy loader ---
def load_legend_policy(path: Path) -> Dict[str, Any]:
    """Load legend policy YAML if present; return {} if missing.

    This keeps legacy behavior when no policy file is provided.
    """
    if not path or not Path(path).exists():
        return {}
    return load_yaml(Path(path))


# --- Figure-level statistics loader ---
def load_figure_level_statistics(path: Path) -> Dict[str, str]:
    """Load figure-level statistic / display note blocks keyed by figure id.

    Accepted YAML forms:
      - figure_1: "..."
      - figure_1:
          text: "..."
      - figure_1:
          block: "..."
      - Figure 1: "..."

    Returns a normalized mapping like:
      {"Figure 1": "...", "Figure 2": "..."}
    Missing files return {} to preserve legacy behavior.
    """
    if not path or not Path(path).exists():
        return {}

    raw = load_yaml(Path(path))
    out: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return out

    for k, v in raw.items():
        key = norm_space(str(k))
        m = re.fullmatch(r"figure_(\d+)", key, flags=re.IGNORECASE)
        if m:
            fig_key = f"Figure {m.group(1)}"
        else:
            m2 = re.fullmatch(r"Figure\s+(\d+)", key, flags=re.IGNORECASE)
            if m2:
                fig_key = f"Figure {m2.group(1)}"
            else:
                continue

        text = ""
        if isinstance(v, str):
            text = v
        elif isinstance(v, dict):
            text = first_nonempty(
                v.get("text"),
                v.get("block"),
                v.get("figure_level_statistics"),
                v.get("figure_level_statistics_en"),
                v.get("closing_block"),
                v.get("display_note"),
            )

        text = str(text).strip()
        if text:
            out[fig_key] = text

    return out


def append_figure_level_statistics(panel_texts: List[str], figure_level_text: str) -> str:
    """Append figure-level statistic/display-note block after panel-wise descriptions."""
    parts: List[str] = []
    for t in panel_texts:
        s = str(t).strip()
        if s:
            parts.append(s)
    stats_block = str(figure_level_text or "").strip()
    if stats_block:
        parts.append(stats_block)
    return "\n\n".join(parts).strip()


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def first_nonempty(*vals: Optional[str]) -> str:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def parse_panel_label(panel: str) -> Tuple[int, str]:
    """
    Sort key for panels.

    Priority:
      0) single-letter panels: a,b,c...
      1) multi-char like "s4c", "s3e" etc (supplement): after main panels
      2) others: last

    Within bucket:
      - main panels: alphabetical
      - supplement: natural-ish (string)
    """
    p = (panel or "").strip()
    if re.fullmatch(r"[a-z]", p):
        return (0, p)
    if re.fullmatch(r"s\d+[a-z]$", p) or p.startswith("s"):
        return (1, p)
    return (2, p)


def find_figure_asset(figs_dir: Path, figure_num: str) -> Dict[str, str]:
    """
    Return available asset paths for a figure:
      - source_ai (preferred)
      - render_pdf / render_png (if exist)
    """
    base = f"figure_{figure_num}"
    candidates = {
        "source_ai": figs_dir / f"{base}.ai",
        "render_pdf": figs_dir / f"{base}.pdf",
        "render_png": figs_dir / f"{base}.png",
        "render_svg": figs_dir / f"{base}.svg",
    }
    out: Dict[str, str] = {}
    for k, p in candidates.items():
        if p.exists():
            out[k] = str(p)
    # Always provide intended AI path even if not exists (helps QA)
    if "source_ai" not in out:
        out["source_ai"] = str(candidates["source_ai"])
    # If a variant image name exists (e.g., figure_1_画板 1.png), capture it as render_png_hint
    variant_png = find_rendered_figure_image(figs_dir, figure_num, prefer_ext=["png"]) if figure_num else None
    if variant_png and "render_png" not in out:
        out["render_png"] = variant_png
    return out


# Flexible rendered image finder for exported figure images
def find_rendered_figure_image(figs_dir: Path, figure_num: str, prefer_ext: List[str] = None) -> Optional[str]:
    """Find a rendered figure image with flexible filenames.

    Accepts names like:
      - figure_1.png
      - figure_1_画板 1.png
      - Figure 1.png
      - figure_1_v3.tif

    Returns absolute path string or None.
    """
    if not figure_num:
        return None
    prefer_ext = prefer_ext or ["png", "tif", "tiff", "jpg", "jpeg"]

    patterns = [
        f"figure_{figure_num}*.*",
        f"Figure_{figure_num}*.*",
        f"Figure {figure_num}*.*",
    ]

    candidates: List[Path] = []
    for pat in patterns:
        candidates.extend(sorted(figs_dir.glob(pat)))

    if not candidates:
        return None

    def rank(p: Path) -> Tuple[int, int]:
        ext = p.suffix.lower().lstrip(".")
        try:
            e_rank = prefer_ext.index(ext)
        except ValueError:
            e_rank = 999
        return (e_rank, len(p.name))

    candidates.sort(key=rank)
    return str(candidates[0].resolve())


# -----------------------------
# Legend rendering
# -----------------------------

def format_panel_group_label(panels: List[str]) -> str:
    """Format a merged panel label like (a,b) with stable ordering."""
    ps = [norm_space(p) for p in (panels or []) if norm_space(p)]
    ps_sorted = sorted(ps, key=parse_panel_label)
    return f"({','.join(ps_sorted)})"


def resolve_one_sentence(
    shared_legend: Dict[str, Any],
    panel_legend: Dict[str, Any],
    panel_key: str,
) -> str:
    """Resolve one_sentence_en for a panel.

    Supports:
      - string: one_sentence_en: "..."
      - dict:   one_sentence_en: {a: "...", "a,b": "..."}
      - list:   one_sentence_en: [{panels:[a,b], text:"..."}, ...]

    Panel overrides take precedence over shared legend.
    """

    def _from_obj(obj: Any) -> str:
        if obj is None:
            return ""
        # string
        if isinstance(obj, str):
            return obj
        # dict mapping
        if isinstance(obj, dict):
            # exact match
            if panel_key in obj and isinstance(obj.get(panel_key), str):
                return obj.get(panel_key) or ""
            # group keys like "a,b" or "a,b,c"
            for k, v in obj.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                ks = [norm_space(x) for x in k.split(",") if norm_space(x)]
                if panel_key in ks:
                    return v
            return ""
        # list of group specs
        if isinstance(obj, list):
            for it in obj:
                if not isinstance(it, dict):
                    continue
                panels = it.get("panels")
                text = it.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                if isinstance(panels, str):
                    ps = [norm_space(x) for x in panels.split(",") if norm_space(x)]
                elif isinstance(panels, list):
                    ps = [norm_space(str(x)) for x in panels if norm_space(str(x))]
                else:
                    ps = []
                if panel_key in ps:
                    return text
            return ""
        return ""

    # panel override first
    v1 = _from_obj(panel_legend.get("one_sentence_en"))
    if v1 and str(v1).strip():
        return str(v1).strip()
    v2 = _from_obj(shared_legend.get("one_sentence_en"))
    return str(v2).strip() if v2 else ""


def render_panel_legend(
    shared_legend: Dict[str, Any],
    panel_legend: Dict[str, Any],
    panel_key: str,
    legend_policy: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Produce a readable panel legend paragraph.

    Strategy (stable + minimally opinionated):
      - Start with (a) + one_sentence_en (prefer panel override if present, else shared)
      - If override provides displayed_targets, append as "(...)" for precision
      - Add compact method/readout facts if present:
          key_treatments/time_window, primary_readout + assay, normalization, n/test
      - Avoid discussion-y phrases; just factual fields
    """
    # Prefer panel-specific legend fields; fall back to shared
    one_sentence = norm_space(resolve_one_sentence(shared_legend, panel_legend, panel_key))

    # Optional policy: allow a short legend mode that only keeps one_sentence_en.
    # We keep this intentionally minimal and permissive: any of the following will trigger short mode:
    #   - legend_policy.mode == "short"
    #   - legend_policy.legend_mode == "short"
    #   - legend_policy.one_sentence_only == True
    lp = legend_policy or {}
    mode = (lp.get("mode") or lp.get("legend_mode") or "").strip().lower()
    one_sentence_only = bool(lp.get("one_sentence_only")) or (mode == "short")
    if one_sentence_only:
        label = lp.get("_panel_label") or f"({panel_key})"
        if one_sentence:
            sent = one_sentence.rstrip()
            if sent.endswith((".", "!", "?")):
                return f"{label} {sent}"
            return f"{label} {sent}."
        return f"{label}."

    displayed_targets = panel_legend.get("displayed_targets") or panel_legend.get("displayed_target") or []
    if isinstance(displayed_targets, str):
        displayed_targets = [displayed_targets]
    displayed_targets = [norm_space(x) for x in displayed_targets if norm_space(x)]
    target_suffix = f" ({'; '.join(displayed_targets)})" if displayed_targets else ""

    sysd = shared_legend.get("system_and_design", {}) or {}
    ro = shared_legend.get("readouts_and_assays", {}) or {}
    st = shared_legend.get("stats", {}) or {}

    # Allow panel to override any of these blocks in future
    sysd_p = panel_legend.get("system_and_design", {}) or {}
    ro_p = panel_legend.get("readouts_and_assays", {}) or {}
    st_p = panel_legend.get("stats", {}) or {}

    # Merge: panel overrides take precedence
    sysd2 = {**sysd, **sysd_p}
    ro2 = {**ro, **ro_p}
    st2 = {**st, **st_p}

    key_treat = norm_space(sysd2.get("key_treatments", ""))
    time_window = norm_space(sysd2.get("time_window", ""))
    treat_part = ""
    if key_treat and time_window:
        treat_part = f"{key_treat} {time_window}"
    else:
        treat_part = key_treat or time_window

    primary_readout = norm_space(ro2.get("primary_readout", ""))
    assay = norm_space(ro2.get("assay", ""))
    normalization = norm_space(ro2.get("normalization", ""))

    n = norm_space(st2.get("n", ""))
    test = norm_space(st2.get("test", ""))
    stats_part = ""
    if n and test:
        stats_part = f"n: {n}; stats: {test}."
    elif n:
        stats_part = f"n: {n}."
    elif test:
        stats_part = f"stats: {test}."

    pieces: List[str] = []
    # Lead
    if one_sentence:
        pieces.append(f"({panel_key}) {one_sentence}{target_suffix}.")
    else:
        pieces.append(f"({panel_key}){target_suffix}.")

    # Treatments / timing
    if treat_part:
        pieces.append(f"{treat_part}.")

    # Readout / assay
    if primary_readout and assay:
        pieces.append(f"Readout: {primary_readout} ({assay}).")
    elif primary_readout:
        pieces.append(f"Readout: {primary_readout}.")
    elif assay:
        pieces.append(f"Assay: {assay}.")

    if normalization:
        pieces.append(f"Normalization: {normalization}.")

    if stats_part:
        pieces.append(stats_part)

    extra = norm_space(panel_legend.get("extra_notes", "")) or norm_space(shared_legend.get("extra_notes", ""))
    if extra:
        # Keep as factual note; assume user wrote appropriately
        pieces.append(extra if extra.endswith(".") else extra + ".")

    return " ".join(pieces).strip()


# -----------------------------
# Extraction
# -----------------------------
@dataclass
class PanelItem:
    figure: str           # e.g., "Figure 6"
    panel: str            # e.g., "e"
    figure_id: str        # e.g., "6e" or "s4c"
    record_path: Path
    shared_legend: Dict[str, Any]
    panel_override: Dict[str, Any]  # may be empty for single-panel
    is_multi: bool


def extract_panel_items(record_path: Path) -> List[PanelItem]:
    y = load_yaml(record_path)

    meta = y.get("meta", {}) or {}
    figure = norm_space(meta.get("figure", ""))  # e.g. "Figure 6"
    figure_id = norm_space(meta.get("figure_id", ""))  # e.g. "6e" or "s4c"
    if not figure:
        # Fallback: try infer from figure_id like "6e" -> "Figure 6"
        m = re.match(r"^(\d+)", figure_id)
        if m:
            figure = f"Figure {m.group(1)}"

    # Two schema modes:
    # A) single-panel legend: y["figure_legend"]["panel"] exists
    # B) multi-panel legend: y["figure_legend"] + y["panel_overrides"]
    shared_legend = y.get("figure_legend", {}) or {}
    panel_overrides = y.get("panel_overrides", {}) or {}

    items: List[PanelItem] = []

    if panel_overrides:
        # Multi-panel record: shared legend + per panel overrides (panel labels are keys: a,b,c,... or s3e etc)
        for p_key, override in panel_overrides.items():
            p_key_s = norm_space(str(p_key))
            override_d = override or {}
            items.append(
                PanelItem(
                    figure=figure,
                    panel=p_key_s,                 # panel label inside the figure (a/b/...)
                    figure_id=figure_id or p_key_s,
                    record_path=record_path,
                    shared_legend=shared_legend,
                    panel_override=override_d,
                    is_multi=True,
                )
            )
        return items

    # Single-panel record
    panel = norm_space(str(shared_legend.get("panel", "")))  # required in your template
    if not panel:
        # fallback: try meta.figure_id tail char like "6e" -> "e"
        m = re.match(r"^\d+([a-z])$", figure_id)
        if m:
            panel = m.group(1)
        else:
            # last resort: unknown
            panel = ""

    items.append(
        PanelItem(
            figure=figure,
            panel=panel,
            figure_id=figure_id or panel,
            record_path=record_path,
            shared_legend=shared_legend,
            panel_override={},  # none
            is_multi=False,
        )
    )
    return items


def load_paper_logic_titles(paper_logic: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract mapping: "Figure 1" -> figure_title_en
    paper_logic.yaml structure varies; we support two common patterns:
      - top-level dict with keys like "Figure 1": {figure_title_en: ...}
      - list under figures: [{id:"Figure 1", figure_title_en:"..."}]
    """
    out: Dict[str, str] = {}

    # Pattern 1: direct keys
    for k, v in (paper_logic or {}).items():
        if isinstance(k, str) and k.startswith("Figure ") and isinstance(v, dict):
            title = v.get("figure_title_en") or v.get("figure_title") or v.get("figure_title_en:")
            if title:
                out[norm_space(k)] = norm_space(str(title))

    # Pattern 2: list
    figs = paper_logic.get("figures") or paper_logic.get("figure_list") or []
    if isinstance(figs, list):
        for it in figs:
            if not isinstance(it, dict):
                continue
            fid = it.get("id") or it.get("figure") or it.get("name")
            if fid and str(fid).startswith("Figure "):
                title = it.get("figure_title_en") or it.get("figure_title")
                if title:
                    out[norm_space(str(fid))] = norm_space(str(title))

    return out


# -----------------------------
# DOCX figure block builder and upsert
def build_docx_figure_blocks(figures_ir: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert figures_ir items to renderer-friendly blocks.

    Each block:
      - type: figure
      - id: 'Figure N'
      - title: figure_title_en
      - legend: stitched panel legend text (without repeating 'Figure N | title')
      - image_path: preferred render_png if exists, else omitted (renderer may still auto-locate)
    """
    blocks: List[Dict[str, Any]] = []
    for fig in figures_ir:
        fid = norm_space(str(fig.get("id", "")))
        title = norm_space(str(fig.get("figure_title_en", "")))

        # Use panel-only stitched text for legend (avoid repeating header)
        legend_lines: List[str] = []
        raw = str(fig.get("figure_legend_en", "") or "")
        raw_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        # If the first line looks like a header (starts with Figure), drop it
        if raw_lines and raw_lines[0].startswith("Figure "):
            raw_lines = raw_lines[1:]
        legend = " ".join(raw_lines).strip()

        block: Dict[str, Any] = {
            "type": "figure",
            "id": fid,
            "title": title,
            "legend": legend,
        }

        assets = fig.get("assets") or {}
        if isinstance(assets, dict):
            # Prefer render_png if present
            img = assets.get("render_png") or assets.get("render_tif") or assets.get("render_tiff")
            if img:
                block["image_path"] = str(img)
        blocks.append(block)

    return blocks


def upsert_figures_section_into_results_ir(results_ir_path: Path, figure_blocks: List[Dict[str, Any]]) -> None:
    """Insert or replace a `figures` section in results.ir.yaml.

    Keeps all existing sections; only upserts the section with id 'figures'.
    """
    results = load_yaml(results_ir_path)
    doc = results.get("document", {}) or {}
    sections = doc.get("sections", []) or []
    if not isinstance(sections, list):
        sections = []

    figures_section = {
        "id": "figures",
        "title": "Figures",
        "blocks": figure_blocks,
    }

    replaced = False
    new_sections: List[Dict[str, Any]] = []
    for s in sections:
        if isinstance(s, dict) and norm_space(str(s.get("id", ""))) == "figures":
            new_sections.append(figures_section)
            replaced = True
        else:
            new_sections.append(s)

    if not replaced:
        new_sections.append(figures_section)

    doc["sections"] = new_sections
    results["document"] = doc

    dump_yaml(results, results_ir_path)

def get_panel_belongs_to(it: PanelItem) -> str:
    """Return belongs_to tag for a panel item.

    Convention (scheme B): put `belongs_to` inside panel_overrides for multi-panel records.
    Fallbacks are supported for single-panel records.
    """
    if it.is_multi and isinstance(it.panel_override, dict):
        v = it.panel_override.get("belongs_to")
        if v is not None:
            return norm_space(str(v))
    # Fallback: allow shared legend to carry a tag (e.g., single-panel records)
    if isinstance(it.shared_legend, dict):
        v = it.shared_legend.get("belongs_to")
        if v is not None:
            return norm_space(str(v))
    return ""

# -----------------------------
# Main build
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=str, default=".", help="Project root (default: current working directory)")
    ap.add_argument("--paper-logic", type=str, default="06_figures/record/paper_logic.yaml")
    ap.add_argument("--record-dir", type=str, default="06_figures/record")
    ap.add_argument("--figs-dir", type=str, default="06_figures/figs")
    ap.add_argument("--out", type=str, default="08_manuscript/IR/figures_ir.yaml")
    ap.add_argument("--strict", action="store_true", help="Fail if any listed record is missing")
    ap.add_argument("--results-ir", type=str, default="08_manuscript/IR/results.ir.yaml", help="Target results.ir.yaml to upsert a figures section")
    ap.add_argument("--no-write-results-ir", action="store_true", help="Do NOT update results.ir.yaml (default: update)")
    ap.add_argument(
        "--legend-policy",
        type=str,
        default="08_manuscript/yaml/policy_figure_legend_main.yaml",
        help="Optional legend policy YAML (e.g., mode: short) to control stitched legend verbosity",
    )
    ap.add_argument(
        "--figure-level-statistics",
        type=str,
        default="08_manuscript/yaml/lagend_figure_level_statistic.yaml",
        help="Optional YAML containing figure-level statistics/display-note blocks keyed by figure_1 / Figure 1, etc.",
    )
    args = ap.parse_args()

    # Default to current working directory if --root is not provided
    root = Path(args.root).expanduser().resolve()
    paper_logic_path = (root / args.paper_logic).resolve()
    record_dir = (root / args.record_dir).resolve()
    figs_dir = (root / args.figs_dir).resolve()
    out_path = (root / args.out).resolve()
    legend_policy_path = (root / args.legend_policy).resolve() if args.legend_policy else None
    legend_policy = load_legend_policy(legend_policy_path) if legend_policy_path else {}
    figure_level_stats_path = (
        (root / args.figure_level_statistics).resolve() if args.figure_level_statistics else None
    )
    figure_level_statistics = (
        load_figure_level_statistics(figure_level_stats_path) if figure_level_stats_path else {}
    )

    paper_logic = load_yaml(paper_logic_path)

    # 1) Figure order = inclusion list (single source of truth)
    # Prefer top-level `figure_order`, but also support `results_build.figure_order`
    figure_order = paper_logic.get("figure_order")
    if not figure_order:
        rb = paper_logic.get("results_build", {}) or {}
        figure_order = rb.get("figure_order")
        # Fallback to results_build.include_files if user keeps the inclusion list there
        if not figure_order:
            figure_order = rb.get("include_files")
    if not isinstance(figure_order, list) or not figure_order:
        raise ValueError(
            f"paper_logic.figure_order missing or empty in: {paper_logic_path}\n"
            f"Expected: figure_order: [figure_1_a_000.yaml, figure_1_b_000.yaml, ...]"
        )

    # 2) Titles map
    figure_titles = load_paper_logic_titles(paper_logic)

    # 3) Load each listed record yaml, extract panel items
    all_panels: List[PanelItem] = []
    missing: List[str] = []
    for name in figure_order:
        rel = Path(str(name))
        # allow list entries to be full path or relative
        candidate = rel if rel.is_absolute() else (record_dir / rel)
        if not candidate.exists():
            # also try direct under record_dir by basename
            candidate2 = record_dir / rel.name
            if candidate2.exists():
                candidate = candidate2
            else:
                missing.append(str(name))
                continue

        # Only process YAML files
        if candidate.suffix.lower() not in [".yaml", ".yml"]:
            continue

        all_panels.extend(extract_panel_items(candidate))

    if missing:
        msg = "Missing record YAML(s) listed in figure_order:\n" + "\n".join(f"  - {m}" for m in missing)
        if args.strict:
            raise FileNotFoundError(msg)
        else:
            print("[WARN]", msg)

    # 4) Group by figure (e.g., "Figure 6")
    by_figure: Dict[str, List[PanelItem]] = {}
    for p in all_panels:
        fig = p.figure or "Figure ?"
        by_figure.setdefault(fig, []).append(p)

    # 5) Sort figures by numeric order from key (Figure 1..)
    def fig_sort_key(fig_name: str) -> Tuple[int, str]:
        m = re.match(r"^Figure\s+(\d+)", fig_name)
        return (int(m.group(1)) if m else 999, fig_name)

    figures_sorted = sorted(by_figure.keys(), key=fig_sort_key)

    # 6) Build output IR object
    figures_ir: List[Dict[str, Any]] = []
    for fig in figures_sorted:
        items = by_figure[fig]

        # sort panels by label
        items_sorted = sorted(items, key=lambda x: parse_panel_label(x.panel))

        # Optional policy-driven panel filtering (scheme B): route panels by `belongs_to`.
        # Example policy:
        #   panel_filter:
        #     include_belongs_to: ["F3"]
        pf = legend_policy.get("panel_filter") or {}
        include_bt = pf.get("include_belongs_to")
        exclude_bt = pf.get("exclude_belongs_to")

        if include_bt is not None:
            if isinstance(include_bt, str):
                include_set = {norm_space(include_bt)}
            elif isinstance(include_bt, list):
                include_set = {norm_space(str(x)) for x in include_bt if norm_space(str(x))}
            else:
                include_set = set()
            if include_set:
                items_sorted = [it for it in items_sorted if get_panel_belongs_to(it) in include_set]

        if exclude_bt is not None:
            if isinstance(exclude_bt, str):
                exclude_set = {norm_space(exclude_bt)}
            elif isinstance(exclude_bt, list):
                exclude_set = {norm_space(str(x)) for x in exclude_bt if norm_space(str(x))}
            else:
                exclude_set = set()
            if exclude_set:
                items_sorted = [it for it in items_sorted if get_panel_belongs_to(it) not in exclude_set]

        # If filtering removes all panels for a figure, skip emitting that figure.
        if not items_sorted:
            continue

        # determine figure number for asset lookup
        m = re.match(r"^Figure\s+(\d+)", fig)
        fig_num = m.group(1) if m else ""
        assets = find_figure_asset(figs_dir, fig_num) if fig_num else {}
        # Ensure we capture exported images with variant names (e.g., figure_1_画板 1.png)
        if fig_num:
            img_any = find_rendered_figure_image(figs_dir, fig_num)
            if img_any:
                assets.setdefault("render_png", img_any)

        fig_title = figure_titles.get(fig, "")
        # Build stitched legend text
        panel_texts: List[str] = []

        # In short mode, optionally merge panels that share the same one_sentence_en.
        lp_mode = (legend_policy.get("mode") or legend_policy.get("legend_mode") or "").strip().lower()
        short_mode = bool(legend_policy.get("one_sentence_only")) or (lp_mode == "short")
        merge_shared = bool(legend_policy.get("merge_shared_panels"))

        if short_mode and merge_shared:
            # 1) Resolve one_sentence per panel
            sent_by_panel: Dict[str, str] = {}
            shared_by_panel: Dict[str, Dict[str, Any]] = {}
            override_by_panel: Dict[str, Dict[str, Any]] = {}
            for it in items_sorted:
                p = it.panel
                shared_by_panel[p] = it.shared_legend
                override_by_panel[p] = it.panel_override if it.is_multi else it.shared_legend
                sent_by_panel[p] = norm_space(resolve_one_sentence(it.shared_legend, override_by_panel[p], p))

            # 2) Group panels by sentence (non-empty). Empty sentences stay per-panel.
            groups: Dict[str, List[str]] = {}
            empty_panels: List[str] = []
            for p, s in sent_by_panel.items():
                if s:
                    groups.setdefault(s, []).append(p)
                else:
                    empty_panels.append(p)

            # 3) Emit merged lines, ordered by first panel appearance in items_sorted
            seen: Set[str] = set()
            for it in items_sorted:
                p = it.panel
                if p in seen:
                    continue
                s = sent_by_panel.get(p, "")
                if s:
                    ps = groups.get(s, [p])
                    for pp in ps:
                        seen.add(pp)
                    label = format_panel_group_label(ps)
                    # Pass a per-call label override via a private policy key
                    lp2 = dict(legend_policy)
                    lp2["_panel_label"] = label
                    panel_texts.append(render_panel_legend(shared_by_panel[p], override_by_panel[p], p, lp2))
                else:
                    seen.add(p)
                    panel_texts.append(render_panel_legend(shared_by_panel[p], override_by_panel[p], p, legend_policy))
        else:
            # Legacy behavior: one line per panel
            for it in items_sorted:
                if it.is_multi:
                    panel_texts.append(
                        render_panel_legend(it.shared_legend, it.panel_override, it.panel, legend_policy)
                    )
                else:
                    panel_texts.append(
                        render_panel_legend(it.shared_legend, it.shared_legend, it.panel, legend_policy)
                    )

        figure_level_stats_text = figure_level_statistics.get(fig, "")
        stitched = append_figure_level_statistics(panel_texts, figure_level_stats_text)

        figures_ir.append(
            {
                "id": fig,
                "figure_title_en": fig_title,
                "assets": assets,
                "panels_included": [
                    {
                        "panel": it.panel,
                        "figure_id": it.figure_id,
                        "record": str(it.record_path),
                        "is_multi_from_record": it.is_multi,
                    }
                    for it in items_sorted
                ],
                "figure_legend_en": stitched.strip(),
            }
        )

    out_obj = {
        "meta": {
            "source": "005a_build_figure_ir.py",
            "paper_logic": str(paper_logic_path),
            "record_dir": str(record_dir),
            "figs_dir": str(figs_dir),
            "figure_level_statistics": str(figure_level_stats_path) if figure_level_stats_path else "",
        },
        "figures": figures_ir,
    }

    dump_yaml(out_obj, out_path)
    print(f"[OK] Wrote figures IR YAML: {out_path}")

    if not args.no_write_results_ir:
        results_ir_path = (root / args.results_ir).resolve()
        if not results_ir_path.exists():
            raise FileNotFoundError(f"results.ir.yaml not found for update: {results_ir_path}")
        figure_blocks = build_docx_figure_blocks(figures_ir)
        upsert_figures_section_into_results_ir(results_ir_path, figure_blocks)
        print(f"[OK] Updated results IR with figures section: {results_ir_path}")


if __name__ == "__main__":
    main()