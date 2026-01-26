#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build Results v0 (English) by assembling panel-level results_skeleton_en modules
from YAML files under 06_figures/record, using configuration embedded in paper_logic.yaml.

Minimal dependencies:
  pip install pyyaml
"""

from __future__ import annotations

import fnmatch
import os
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import yaml


# -----------------------------
# Utilities
# -----------------------------

def load_yaml(path: Path) -> Any:
    """Load YAML from `path`.

    Supports both single-document YAML and multi-document YAML streams (separated by '---').
    - If the file contains a single document, returns that object.
    - If the file contains multiple documents, returns a list of documents.

    This is important because some figure YAMLs may be exported as multi-doc streams.
    """
    with path.open("r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    if len(docs) == 1:
        return docs[0]
    return docs

def dump_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)

def matches_any(name: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)

def normalize_module_key(k: str) -> str:
    # allow lowercase keys if any
    return k.strip()

def find_first(d: Any, key: str) -> List[Any]:
    """
    Recursively find all dict nodes that contain `key`.
    Returns list of values for that key.
    """
    found = []
    if isinstance(d, dict):
        if key in d:
            found.append(d[key])
        for v in d.values():
            found.extend(find_first(v, key))
    elif isinstance(d, list):
        for it in d:
            found.extend(find_first(it, key))
    return found

def get_meta_title(y: Any, fallback: str) -> str:
    """
    Try to extract a human-friendly title from typical fields.
    """
    if isinstance(y, dict):
        meta = y.get("meta") or {}
        for k in ["figure_id", "panel_id", "id", "title", "name"]:
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # sometimes top-level has figure_id
        for k in ["figure_id", "panel_id", "id", "title", "name"]:
            v = y.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # story_role is often useful
        v = (y.get("story_role") or (y.get("meta") or {}).get("story_role"))
        if isinstance(v, str) and v.strip():
            return v.strip()

    return fallback


# -----------------------------
# Transition helpers
# -----------------------------

# ---- ID normalization helpers ----

def normalize_panel_id(s: str) -> str:
    """Normalize panel ids so paper_logic and filenames can match.

    Examples:
      - '2f' -> '2f'
      - '2a+b' / '2a,b' / '2a_b' -> '2a/b'
      - 'S4A/B' -> 's4a/b'
      - 'Figure 2f' -> '2f'
    """
    t = (s or "").strip()
    if not t:
        return ""
    t = t.strip()

    # Remove a leading 'Figure' / 'Fig.' prefix if someone put it in a panel id.
    t = re.sub(r"^\s*(figure|fig\.?)[\s_-]*", "", t, flags=re.IGNORECASE)

    # canonical separators
    t = t.replace(" ", "")
    t = t.replace("+", "/").replace(",", "/").replace("_", "/")
    t = re.sub(r"/+", "/", t)

    return t.lower()


def normalize_figure_group(s: str) -> str:
    """Normalize figure-group labels to 'Figure N' or 'Figure S#'.

    Accepts inputs like 'Figure1', 'Fig 1', '1', 'S2', 'Figure S2'.
    """
    t = (s or "").strip()
    if not t:
        return ""
    t = t.strip()

    # strip leading words
    t = re.sub(r"^\s*(figure|fig\.?)[\s_-]*", "", t, flags=re.IGNORECASE)
    t = t.replace(" ", "")

    m = re.match(r"^(s\d+)$", t, flags=re.IGNORECASE)
    if m:
        return f"Figure {m.group(1).upper()}"

    m = re.match(r"^(\d+)$", t)
    if m:
        return f"Figure {m.group(1)}"

    # If already in 'Figure X' style but with odd spacing/case, recover it.
    m = re.match(r"^(s\d+)", t, flags=re.IGNORECASE)
    if m:
        return f"Figure {m.group(1).upper()}"
    m = re.match(r"^(\d+)", t)
    if m:
        return f"Figure {m.group(1)}"

    return ""


def derive_panel_id_from_filename(fname: str) -> str:
    """Derive a canonical panel id from filenames like:

      - figure_2_f.yaml -> '2f'
      - figure_2_a+b.yaml -> '2a/b'
      - figure_1_sa.yaml -> 's1a'
      - figure_4_sa+b.yaml -> 's4a/b'

    If pattern doesn't match, return empty string.
    """
    base = Path(fname).stem
    if base.startswith("figure_"):
        base = base[len("figure_"):]

    # common form: <num>_<rest>
    m = re.match(r"^(\d+)[_](.+)$", base)
    if not m:
        return ""

    num = m.group(1)
    rest = m.group(2)

    def _clean_token(tok: str) -> str:
        """Clean a token like 'a_000'/'c_v2' -> 'a'/'c', keep alphanumerics.

        Rules:
          - Strip trailing version/index suffixes: _000, _001, _v2, v2, etc.
          - Remove remaining underscores.
        """
        t = (tok or "").strip()
        if not t:
            return ""
        # drop trailing suffixes like _000, _001, _v2, v2
        t = re.sub(r"(_v?\d+|v\d+)$", "", t, flags=re.IGNORECASE)
        t = t.replace("_", "")
        return t

    # Split by '+' (and also allow ',' as an alternative separator)
    parts = re.split(r"[+,]", rest)
    parts = [_clean_token(p) for p in parts]
    parts = [p for p in parts if p]

    # Supplementary panels are encoded as 's' + <num> + <letters/parts>
    # Examples:
    #   '1_sa'        -> 's1a'
    #   '4_sa+b'      -> 's4a/b'
    #   '3_i+j+s3_d'  -> still best-effort tokenization
    if rest.lower().startswith("s"):
        # remove the leading 's' from the first token if present
        if parts and parts[0].lower().startswith("s"):
            parts[0] = parts[0][1:]
        rest2 = "/".join([p for p in parts if p])
        return normalize_panel_id(f"s{num}{rest2}")

    # Normal panels: join parts with '/'
    rest2 = "/".join(parts)
    return normalize_panel_id(f"{num}{rest2}")

def get_panel_id(y: Any, fallback: str = "") -> str:
    """Return a stable panel/figure identifier used in paper_logic transitions.

    Preference order:
      - meta.figure_id (e.g., "1a")
      - meta.figure (e.g., "4a/b")
      - top-level figure_id / figure
      - fallback
    """
    if isinstance(y, dict):
        meta = y.get("meta") or {}
        for k in ["figure_id", "figure", "panel_id", "id", "name", "title"]:
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return normalize_panel_id(v.strip())
        for k in ["figure_id", "figure", "panel_id", "id", "name", "title"]:
            v = y.get(k)
            if isinstance(v, str) and v.strip():
                return normalize_panel_id(v.strip())
    return normalize_panel_id((fallback or "").strip())


# ---- Figure group assignment helper ----
def get_figure_group(y: Any, panel_id: str) -> str:
    """Return the figure-group label used for between_figures matching.

    Prefer explicit figure group labels from YAML (meta.figure or top-level figure).
    This avoids mis-grouping supplementary panel ids like 's4c' as 'Figure S4'
    when they should belong to a main figure group (e.g., meta.figure: 'Figure 4').
    """
    if isinstance(y, dict):
        meta = y.get("meta") or {}
        # Prefer explicit figure group label from YAML
        for k in ["figure", "figure_group"]:
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                fg = normalize_figure_group(v.strip())
                if fg:
                    return fg
        for k in ["figure", "figure_group"]:
            v = y.get(k)
            if isinstance(v, str) and v.strip():
                fg = normalize_figure_group(v.strip())
                if fg:
                    return fg
    # Fallback: derive from panel id
    return figure_group_label(panel_id)


def figure_group_label(panel_id: str) -> str:
    """Map a panel_id like '4a/b' -> 'Figure 4' for between_figures matching."""
    s = normalize_panel_id(panel_id)
    if not s:
        return ""
    m = re.match(r"^(s\d+)", s, flags=re.IGNORECASE)
    if m:
        return f"Figure {m.group(1).upper()}"
    m = re.match(r"^(\d+)", s)
    if m:
        return f"Figure {m.group(1)}"
    return ""


def build_transition_maps(
    logic: Dict[str, Any]
) -> Tuple[Dict[Tuple[str, str], Dict[str, str]], Dict[Tuple[str, str], Dict[str, str]]]:
    """Return (panel_map, figure_map).

    This function is intentionally *robust to where transitions live* in paper_logic.yaml.

    Why: in your `paper_logic.yaml`, transitions may appear:
      - at the top level (e.g., section_transitions), and/or
      - nested under each figure entry (e.g., figures[].panel_transitions), and/or
      - duplicated in multiple places.

    We therefore *search recursively* for all `panel_transitions` and `section_transitions`
    blocks and merge them.

    Keys:
      - panel_map: (from_panel_id, to_panel_id) using `between_panels`
      - figure_map: (from_figure_group, to_figure_group) using `between_figures`

    Values: dict with 'en' and 'cn' (if provided).
    """

    panel_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    fig_map: Dict[Tuple[str, str], Dict[str, str]] = {}

    # ---- panel transitions (between_panels) ----
    # Collect ALL occurrences of `panel_transitions` anywhere in the YAML.
    panel_blocks = find_first(logic, "panel_transitions")
    for pt in panel_blocks:
        if not isinstance(pt, dict):
            continue
        for it in (pt.get("between_panels") or []):
            if not isinstance(it, dict):
                continue
            a = normalize_panel_id((it.get("from") or "").strip())
            b = normalize_panel_id((it.get("to") or "").strip())
            if a and b:
                # later definitions can override earlier ones (useful when you revise)
                panel_map[(a, b)] = {
                    "en": (it.get("en") or "").strip(),
                    "cn": (it.get("cn") or "").strip(),
                }

    # ---- figure transitions (between_figures) ----
    # Collect ALL occurrences of `section_transitions` anywhere in the YAML.
    section_blocks = find_first(logic, "section_transitions")
    for st in section_blocks:
        if not isinstance(st, dict):
            continue
        for it in (st.get("between_figures") or []):
            if not isinstance(it, dict):
                continue
            a = normalize_figure_group((it.get("from") or "").strip())
            b = normalize_figure_group((it.get("to") or "").strip())
            if a and b:
                fig_map[(a, b)] = {
                    "en": (it.get("en") or "").strip(),
                    "cn": (it.get("cn") or "").strip(),
                }

    # ALSO support `between_figures` living anywhere (without a `section_transitions` wrapper).
    direct_between_figures = find_first(logic, "between_figures")
    for lst in direct_between_figures:
        if not isinstance(lst, list):
            continue
        for it in lst:
            if not isinstance(it, dict):
                continue
            a = normalize_figure_group((it.get("from") or "").strip())
            b = normalize_figure_group((it.get("to") or "").strip())
            if a and b:
                fig_map[(a, b)] = {
                    "en": (it.get("en") or "").strip(),
                    "cn": (it.get("cn") or "").strip(),
                }

    return panel_map, fig_map


def render_transition(en_text: str, cn_text: str, primary: str = "en") -> str:
    """Render a bilingual transition blockquote.

    Order is controlled by `primary` ("en" or "cn").
    """
    en = " ".join((en_text or "").strip().split())
    cn = " ".join((cn_text or "").strip().split())
    if not en and not cn:
        return ""

    if primary == "cn":
        first, second = (cn, en)
        first_label, second_label = ("转场", "Transition")
    else:
        first, second = (en, cn)
        first_label, second_label = ("Transition", "转场")

    lines: List[str] = []
    if first:
        lines.append(f"> **{first_label}:** {first}")
    if second:
        lines.append(f"> **{second_label}:** {second}")
    return "\n".join(lines)

def extract_panels(y: Any, source_name: str) -> List[Dict[str, Any]]:
    """
    Extract panel-like units from a figure YAML.
    Strategy:
      - Find all 'results_skeleton_en' blocks (can be one or multiple).
      - For each, read panel_level / results_logic_type / modules.
    """
    blocks = find_first(y, "results_skeleton_en")
    panels: List[Dict[str, Any]] = []
    for idx, b in enumerate(blocks):
        if not isinstance(b, dict):
            continue
        panel_level = b.get("panel_level")
        logic_type = b.get("results_logic_type")
        modules = b.get("modules") or {}
        if not isinstance(modules, dict):
            modules = {}

        panels.append({
            "panel_key": f"{source_name}::block{idx+1}",
            "panel_level": panel_level if isinstance(panel_level, str) else "",
            "results_logic_type": logic_type if isinstance(logic_type, str) else "",
            "modules": modules,
        })
    return panels

def pick_modules(panel_level: str, logic_type: str, cfg: Dict[str, Any]) -> List[str]:
    rules = cfg.get("module_rules", {}) or {}
    panel_level = (panel_level or "").strip()

    if panel_level == "framework":
        return list((rules.get("framework", {}) or {}).get("include_modules", []) or [])

    # results
    by_logic = (rules.get("results_by_logic_type", {}) or {})
    if logic_type and logic_type in by_logic:
        return list((by_logic.get(logic_type, {}) or {}).get("include_modules", []) or [])

    return list((rules.get("results_default", {}) or {}).get("include_modules", []) or [])

def render_block(block: Dict[str, Any], include_keys: List[str], primary: str = "en") -> str:
    """Render modules as bilingual bullets (EN+CN).

    For each module, output the primary language as the main bullet, and the other
    language as an indented sub-bullet when available.
    """
    modules = block.get("modules") or {}
    if not isinstance(modules, dict):
        return ""

    other = "cn" if primary == "en" else "en"

    lines: List[str] = []
    for mk in include_keys:
        mk = (mk or "").strip()
        if not mk or mk not in modules:
            continue

        node = modules.get(mk) or {}
        if not isinstance(node, dict):
            continue

        t_primary = node.get(primary, "")
        t_other = node.get(other, "")

        t_primary = t_primary.strip() if isinstance(t_primary, str) else ""
        t_other = t_other.strip() if isinstance(t_other, str) else ""

        # If primary is missing but other exists, still render.
        if not t_primary and not t_other:
            continue

        if primary == "cn":
            main = t_primary or t_other
            sub = t_other if t_primary else ""
        else:
            main = t_primary or t_other
            sub = t_other if t_primary else ""

        lines.append(f"- {main}")
        if sub:
            lines.append(f"  - {sub}")

    return "\n".join(lines).strip()

def resolve_record_dir(paper_logic_path: Path, cfg: Dict[str, Any]) -> Path:
    rd = cfg.get("record_dir")
    if isinstance(rd, str) and rd.strip():
        return Path(rd).expanduser().resolve()
    return paper_logic_path.parent.resolve()

def resolve_output_path(record_dir: Path, cfg: Dict[str, Any]) -> Path:
    out = cfg.get("output_path", "Results_v0.md")
    if not isinstance(out, str) or not out.strip():
        out = "Results_v0.md"
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = record_dir / out_path
    return out_path.resolve()


# -----------------------------
# Main build
# -----------------------------

def main() -> int:
    # Locate paper_logic.yaml
    # Priority:
    #   1) Explicit CLI argument
    #   2) Current working directory
    #   3) Directory containing this script (so running from project root still works)
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        paper_logic = Path(sys.argv[1]).expanduser().resolve()
    else:
        cwd_candidate = Path.cwd() / "paper_logic.yaml"
        script_candidate = Path(__file__).resolve().parent / "paper_logic.yaml"
        paper_logic = cwd_candidate if cwd_candidate.exists() else script_candidate

    if not paper_logic.exists():
        print(
            "ERROR: paper_logic.yaml not found.\n"
            "- Run this script from the record directory, or\n"
            "- Pass the full path to paper_logic.yaml as an argument, e.g.:\n"
            "  python build_results.py /path/to/06_figures/record/paper_logic.yaml",
            file=sys.stderr,
        )
        return 2

    logic = load_yaml(paper_logic)
    if not isinstance(logic, dict):
        print("ERROR: paper_logic.yaml did not parse into a dict.", file=sys.stderr)
        return 2

    cfg = logic.get("results_build") or {}
    if not isinstance(cfg, dict):
        print("ERROR: paper_logic.yaml.results_build must be a dict.", file=sys.stderr)
        return 2

    panel_tr_map, figure_tr_map = build_transition_maps(logic)

    record_dir = resolve_record_dir(paper_logic, cfg)
    output_path = resolve_output_path(record_dir, cfg)
    primary_lang = (cfg.get("language") or "en").strip().lower()
    if primary_lang not in ("en", "cn"):
        primary_lang = "en"
    debug_transitions = bool(cfg.get("debug_transitions", False))
    if debug_transitions:
        print(f"[DEBUG] primary_language={primary_lang}")
        print(f"[DEBUG] panel_transitions={len(panel_tr_map)} keys; figure_transitions={len(figure_tr_map)} keys")
        # show a small sample of keys to confirm normalization
        print(f"[DEBUG] sample panel keys: {list(panel_tr_map.keys())[:10]}")
        print(f"[DEBUG] sample figure keys: {list(figure_tr_map.keys())[:10]}")

    include_globs = cfg.get("include_globs", ["figure_*.yaml"]) or ["figure_*.yaml"]
    exclude_globs = cfg.get("exclude_globs", ["paper_logic.yaml"]) or []
    include_files = cfg.get("include_files", []) or []
    figure_order = cfg.get("figure_order", []) or []
    allowed_panel_levels = cfg.get("allowed_panel_levels", ["framework", "results"]) or ["framework", "results"]

    # 1) collect candidate yaml files
    candidates: List[Path] = []
    for pat in include_globs:
        candidates.extend(record_dir.glob(pat))

    # filter excludes
    filtered: List[Path] = []
    for p in candidates:
        if matches_any(p.name, exclude_globs):
            continue
        filtered.append(p)

    # if include_files provided, enforce
    if include_files:
        wanted = set(include_files)
        filtered = [p for p in filtered if p.name in wanted]

    # order: if figure_order provided, follow it; else sort by name
    if figure_order:
        order_map = {name: i for i, name in enumerate(figure_order)}
        filtered.sort(key=lambda p: order_map.get(p.name, 10**9))
    else:
        filtered.sort(key=lambda p: p.name)

    # 2) build markdown
    md: List[str] = []
    md.append("# Results v0 (auto-assembled)\n")

    for i, fpath in enumerate(filtered):
        y = load_yaml(fpath)
        fig_title = get_meta_title(y, fallback=fpath.stem)
        fname_panel_id = derive_panel_id_from_filename(fpath.name)
        curr_panel_id = get_panel_id(y, fallback=(fname_panel_id or fig_title))
        curr_fig_group = get_figure_group(y, curr_panel_id)

        next_panel_id = ""
        next_fig_group = ""
        if i + 1 < len(filtered):
            y_next = load_yaml(filtered[i + 1])
            next_fname_panel_id = derive_panel_id_from_filename(filtered[i + 1].name)
            next_panel_id = get_panel_id(y_next, fallback=(next_fname_panel_id or filtered[i + 1].stem))
            next_fig_group = get_figure_group(y_next, next_panel_id)

        if debug_transitions:
            print(
                f"[DEBUG] pair {i}: {fpath.name}({curr_panel_id}, {curr_fig_group}) -> "
                f"{(filtered[i + 1].name if i + 1 < len(filtered) else '<end>')}({next_panel_id}, {next_fig_group})"
            )

        panels = extract_panels(y, source_name=fpath.name)
        if not panels:
            continue
        if not panels and debug_transitions:
            print(f"[DEBUG] SKIP (no results_skeleton_en found): {fpath.name}")
        # figure header
        md.append(f"## {fig_title}  \n`{fpath.name}`\n")

        any_panel_written = False
        for p in panels:
            pl = (p.get("panel_level") or "").strip()
            lt = (p.get("results_logic_type") or "").strip()

            if pl and pl not in allowed_panel_levels:
                continue

            include_keys = pick_modules(pl, lt, cfg)
            body = render_block(p, include_keys, primary=primary_lang)
            if not body:
                continue

            # panel header (keep minimal; you can enrich later)
            md.append(f"### Panel block ({pl or 'unknown'}; {lt or 'unspecified'})")
            md.append(body)
            md.append("")  # blank line
            any_panel_written = True

        if not any_panel_written:
            # remove figure header if nothing output
            md = md[:-1]  # last blank line removal is tricky; keep simple
            # (Minimal behavior: just keep header; you can adjust later)

        # Insert smooth transition to the next section (panel-to-panel or figure-to-figure)
        if next_panel_id:
            transition_text = ""
            if debug_transitions:
                print("[DEBUG] attempting transition insertion...")

            # Prefer explicit panel-to-panel transitions when staying within the same figure group
            if curr_panel_id and next_panel_id and curr_fig_group and next_fig_group and curr_fig_group == next_fig_group:
                tr = panel_tr_map.get((normalize_panel_id(curr_panel_id), normalize_panel_id(next_panel_id)))
                if debug_transitions:
                    key = (normalize_panel_id(curr_panel_id), normalize_panel_id(next_panel_id))
                    print(f"[DEBUG] panel lookup key={key} hit={bool(tr)}")
                if tr:
                    transition_text = tr

            # Otherwise use figure-to-figure transitions when moving across figure groups
            if (not transition_text) and curr_fig_group and next_fig_group and curr_fig_group != next_fig_group:
                tr = figure_tr_map.get((normalize_figure_group(curr_fig_group), normalize_figure_group(next_fig_group)))
                if debug_transitions:
                    key = (normalize_figure_group(curr_fig_group), normalize_figure_group(next_fig_group))
                    print(f"[DEBUG] figure lookup key={key} hit={bool(tr)}")
                if tr:
                    transition_text = tr

            # Fallback: allow explicit panel-to-panel transitions even across figure groups
            # (useful for Fig -> FigS jumps such as 4g -> s4a/b)
            if (not transition_text) and curr_panel_id and next_panel_id:
                tr = panel_tr_map.get((normalize_panel_id(curr_panel_id), normalize_panel_id(next_panel_id)))
                if debug_transitions:
                    key = (normalize_panel_id(curr_panel_id), normalize_panel_id(next_panel_id))
                    print(f"[DEBUG] panel fallback lookup key={key} hit={bool(tr)}")
                if tr:
                    transition_text = tr

            if transition_text:
                if debug_transitions:
                    print(f"[DEBUG] inserted transition ({'panel' if curr_fig_group==next_fig_group else 'figure'})")
                md.append(
                    render_transition(
                        transition_text.get("en", ""),
                        transition_text.get("cn", ""),
                        primary=primary_lang,
                    )
                )
                md.append("")
            elif debug_transitions:
                print("[DEBUG] no transition inserted for this pair")

        md.append("---\n")

    final_text = "\n".join(md).strip() + "\n"
    dump_text(output_path, final_text)
    print(f"[OK] Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())