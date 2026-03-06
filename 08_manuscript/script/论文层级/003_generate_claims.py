#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
generate_claims.py

Auto-generate a draft claim layer from:
- edges: {id, from, to, relation, evidence_level, ...}
- narrative: [{figure, type, edges:[...]}]

Writes a new top-level key `claims:` back to YAML (or output to a new file).

Usage:
python 08_manuscript/script/论文层级/003_generate_claims.py \
  --yaml /Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/record/lyout_2_argument.yaml \
  --templates /Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/08_manuscript/script/论文层级/templates.yaml \
  --out /Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/record/lyout_2_argument.with_claims.yaml

If --out is omitted, it will create: <yaml>.with_claims.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import yaml

TEMPLATES: Dict[str, Any] = {}


def load_yaml(p: Path) -> Dict[str, Any]:
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(p: Path, data: Dict[str, Any]) -> None:
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )


def norm(s: str) -> str:
    return (s or "").strip()


# --- Helper functions for safe template rendering and evidence key normalization ---

def normalize_evidence_key(ev: str) -> str:
    e = (ev or "").lower().replace("_", " ").strip()
    if e == "causal closure":
        return "causal_closure"
    if e == "established biology":
        return "established_biology"
    return e.replace(" ", "_")
def normalize_relation_key(rel: str) -> str:
    """Normalize relation tokens to match keys in templates.yaml."""
    r = (rel or "").lower().strip()
    alias = {
        "promotes": "promote",
        "promote": "promote",
        "activation": "promote",
        "promotion": "promote",
        "activates": "promote",

        "inhibits": "inhibition",
        "inhibit": "inhibition",
        "inhibition": "inhibition",

        "requires": "requirement",
        "require": "requirement",
        "requirement": "requirement",

        "generates": "generation",
        "generate": "generation",
        "produces": "generation",
        "produce": "generation",
        "production": "generation",
        "generation": "generation",

        "state transition": "state_transition",
        "state_transition": "state_transition",
        "transition": "state_transition",
    }
    if r in alias:
        return alias[r]
    if r.endswith("s"):
        return r[:-1]
    return r


def parse_perturbation(v: Any) -> str:
    """Return normalized perturbation type string (e.g., knockout) or empty."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, dict):
        t = v.get("type") or v.get("kind") or v.get("name")
        return str(t or "").strip().lower()
    return ""


def gene_from_basal_label(label: str) -> str:
    s = (label or "").strip()
    for suf in [" basal state", " base state", " basal", " base"]:
        if s.lower().endswith(suf):
            return s[: -len(suf)].strip()
    return s


def is_subject_knockout(subj_id: str, edge_ids: List[str], edge_map: Dict[str, Dict[str, Any]]) -> bool:
    """True if any edge from subj_id declares perturbation knockout."""
    for eid in edge_ids:
        e = edge_map.get(eid, {})
        if str(e.get("from", "")) != str(subj_id):
            continue
        p = parse_perturbation(e.get("perturbation"))
        if p in ("knockout", "ko"):
            return True
    return False


def invert_verb_for_knockout(rel_key: str) -> str:
    """Verb under knockout framing."""
    rk = normalize_relation_key(rel_key)
    if rk == "promote":
        return "reduces"
    if rk == "inhibition":
        return "increases"
    if rk == "requirement":
        return "impairs"
    if rk == "generation":
        return "reduces"
    if rk == "state_transition":
        return "impairs"
    return "alters"


def render_subject_and_verb(
    subj_id: str,
    subj_label: str,
    edge_ids: List[str],
    edge_map: Dict[str, Dict[str, Any]],
    relation_key: str,
    verb: str,
) -> Tuple[str, str]:
    """Return (subject_render, verb_render) with knockout-aware inversion if applicable."""
    if is_subject_knockout(subj_id, edge_ids, edge_map):
        g = gene_from_basal_label(subj_label)
        return f"{g} deficiency", invert_verb_for_knockout(relation_key)
    return subj_label, verb


# --- Step 1: Add condition extraction helper ---
def extract_condition(edge_ids: List[str], edge_map: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """
    Extract a representative biological_system and stimulus from edge conditions.
    Uses the first edge that contains the field.
    """
    system = ""
    stimulus = ""

    for eid in edge_ids:
        e = edge_map.get(eid, {})
        cond = e.get("condition", [])

        if isinstance(cond, list):
            for item in cond:
                if isinstance(item, dict):
                    if not system and ("biological system" in item or "biological_system" in item):
                        system = item.get("biological system") or item.get("biological_system") or ""
                    if not stimulus and "stimulus" in item:
                        stimulus = item.get("stimulus") or ""

    return {
        "biological_system": system,
        "stimulus": stimulus,
    }

class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_template(tpl: str, values: Dict[str, Any]) -> str:
    """Safe .format_map() that leaves unknown placeholders untouched."""
    if tpl is None:
        return ""
    try:
        return str(tpl).format_map(_SafeDict(values))
    except Exception:
        # last-resort fallback: return raw template
        return str(tpl)


def get_template(*path: str, default: Any = "") -> Any:
    """Fetch nested template value from loaded TEMPLATES."""
    cur: Any = TEMPLATES
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def strip_hedge_prefix_from_claim(claim_sentence: str) -> str:
    """Best-effort: remove common hedging prefixes and return the proposition part."""
    s = (claim_sentence or "").strip()
    if not s:
        return s

    # collect known prefixes from templates.yaml
    hedging = get_template("templates", "hedging", default={})
    prefixes: List[str] = []
    if isinstance(hedging, dict):
        for _, v in hedging.items():
            if isinstance(v, dict) and v.get("prefix"):
                prefixes.append(str(v.get("prefix")).strip())

    # Try to match a known prefix first
    for p in sorted(prefixes, key=len, reverse=True):
        if s.startswith(p):
            s = s[len(p):].lstrip(" ,")
            break

    # If we still have a leading clause with 'that', take the part after it.
    if " that " in s:
        s = s.split(" that ", 1)[1].strip()

    # Handle the 'in which' style
    if " in which " in s and s.lower().startswith("a causal role"):
        s = s.split(" in which ", 1)[1].strip()

    # Remove a leading modal like 'may'
    if s.lower().startswith("may "):
        s = s[4:].strip()

    # Remove trailing period for re-use
    if s.endswith("."):
        s = s[:-1]

    return s.strip()


def infer_claim_components(
    fig_type: str,
    edge_ids: List[str],
    edge_map: Dict[str, Dict[str, Any]],
    node_label: Dict[str, str],
) -> Dict[str, str]:
    """Infer subject/object/mediator/verb/evidence for rendering derived sentences."""
    subj_id, obj_id = choose_subject_object(edge_ids, edge_map)
    subj = node_label.get(subj_id, subj_id)
    obj = node_label.get(obj_id, obj_id)

    tos = set(str(edge_map.get(eid, {}).get("to", "")) for eid in edge_ids)
    frs = set(str(edge_map.get(eid, {}).get("from", "")) for eid in edge_ids)
    mediators = [node_label.get(n, n) for n in sorted((tos & frs) - {subj_id, obj_id}) if n]
    mediator = mediators[0] if mediators else ""

    w_ev = weakest_evidence(edge_ids, edge_map)

    rel_keys = [normalize_relation_key(str(edge_map.get(eid, {}).get("relation", ""))) for eid in edge_ids]
    rel_key = rel_keys[0] if rel_keys and all(rk == rel_keys[0] for rk in rel_keys) else "default"

    rels = [relation_en(str(edge_map.get(eid, {}).get("relation", ""))) for eid in edge_ids]
    verb = rels[0] if rels and all(r == rels[0] for r in rels) else get_template("templates", "relations", "default", "verb", default="affects")

    subj_render, verb_render = render_subject_and_verb(
        subj_id=subj_id,
        subj_label=subj,
        edge_ids=edge_ids,
        edge_map=edge_map,
        relation_key=rel_key,
        verb=verb,
    )
    verb = rels[0] if rels and all(r == rels[0] for r in rels) else get_template("templates", "relations", "default", "verb", default="affects")

    # --- Step 2: Inject condition into components ---
    cond = extract_condition(edge_ids, edge_map)

    return {
        "fig_type": (fig_type or "").strip(),
        "subject": subj_render,
        "object": obj,
        "mediator": mediator,
        "verb": verb_render,
        "relation_key": rel_key,
        "weakest_evidence_level": w_ev,
        "weakest_evidence_key": normalize_evidence_key(w_ev),
        "biological_system": cond.get("biological_system", ""),
        "stimulus": cond.get("stimulus", ""),
    }


def derive_results_strings(
    claim_sentence_en: str,
    components: Dict[str, str],
) -> Dict[str, str]:
    """Render figure_title / paragraph_opening / paragraph_summary from templates.yaml."""
    # Load templates
    title_tpl = get_template("templates", "results", "figure_title", "template", default="{subject} {verb} {object}")
    opening_tpl = get_template("templates", "results", "paragraph_opening", "template", default="To determine whether {claim_core}, we {approach}.")

    ev_key = components.get("weakest_evidence_key", "")
    summary_tpl = get_template("templates", "results", "paragraph_summary", ev_key, "template", default="Together, these data indicate that {claim}.")

    claim_core = strip_hedge_prefix_from_claim(claim_sentence_en)

    # A conservative default approach placeholder (user can override by adding 'approach' into narrative later)
    approach_default = "examined the relevant readouts"

    # --- Step 3: Pass condition variables to templates ---
    values = {
        **components,
        "claim": (claim_sentence_en or "").rstrip(),
        "claim_core": claim_core,
        "approach": approach_default,
        "biological_system": components.get("biological_system", ""),
        "stimulus": components.get("stimulus", ""),
    }

    figure_title = render_template(title_tpl, values).strip().rstrip(".")
    paragraph_opening = render_template(opening_tpl, values).strip()
    paragraph_summary = render_template(summary_tpl, values).strip()

    return {
        "figure_title": figure_title,
        "paragraph_opening": paragraph_opening,
        "paragraph_summary": paragraph_summary,
        "claim_core_en": claim_core,
    }


def get_node_label(nodes: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}
    for n in nodes or []:
        nid = str(n.get("id"))
        out[nid] = str(n.get("label", nid))
    return out


def get_edge_map(edges: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for e in edges or []:
        eid = str(e.get("id"))
        out[eid] = e
    return out




def relation_en(rel: str) -> str:
    r = normalize_relation_key(rel)
    rel_map = get_template("templates", "relations", default={})
    if isinstance(rel_map, dict) and r in rel_map:
        return rel_map[r].get("verb", r)
    default = "affects"
    if isinstance(rel_map, dict):
        default = rel_map.get("default", {}).get("verb", default)
    return default


def evidence_rank(ev: str) -> int:
    """Higher is stronger. Used to pick hedging level conservatively (min across edges)."""
    e = (ev or "").lower().replace("_", " ").strip()
    if e in ("correlation",):
        return 1
    if e in ("positioning",):
        return 2
    if e in ("necessity", "sufficiency"):
        return 3
    if e in ("causal closure", "causal_closure"):
        return 4
    # Established biology is not your new experimental support; treat as moderate and phrase explicitly.
    if e in ("established biology", "established", "established_biology"):
        return 2
    return 2


def weakest_evidence(edge_ids: List[str], edge_map: Dict[str, Dict[str, Any]]) -> str:
    """Return the weakest (most conservative) evidence_level string among the edges."""
    weakest = None
    weakest_rank = 10
    for eid in edge_ids:
        ev = str(edge_map.get(eid, {}).get("evidence_level", ""))
        r = evidence_rank(ev)
        if r < weakest_rank:
            weakest_rank = r
            weakest = ev
    return str(weakest or "")




def evidence_hedge_en(ev: str) -> str:
    e = (ev or "").lower().replace("_", " ").strip()

    hedge = (
        TEMPLATES.get("templates", {})
        .get("hedging", {})
        .get(e, {})
    )

    prefix = hedge.get("prefix", "These data indicate that")
    modal = hedge.get("modal", "")

    return prefix, modal




def summarize_edges_en(
    edge_ids: List[str],
    edge_map: Dict[str, Dict[str, Any]],
    node_label: Dict[str, str],
) -> List[str]:
    lines = []
    for eid in edge_ids:
        e = edge_map.get(eid, {})
        u = str(e.get("from", ""))
        v = str(e.get("to", ""))
        rel = relation_en(str(e.get("relation", "")))
        ev = str(e.get("evidence_level", ""))
        lines.append(f"{eid}: {node_label.get(u,u)} {rel} {node_label.get(v,v)} (evidence: {ev})")
    return lines


def choose_subject_object(
    edge_ids: List[str],
    edge_map: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    """
    Heuristic:
    - subject: most frequent 'from'
    - object : most frequent 'to'
    """
    from_count: Dict[str, int] = {}
    to_count: Dict[str, int] = {}
    for eid in edge_ids:
        e = edge_map.get(eid, {})
        u = str(e.get("from", ""))
        v = str(e.get("to", ""))
        from_count[u] = from_count.get(u, 0) + 1
        to_count[v] = to_count.get(v, 0) + 1
    subj = max(from_count.items(), key=lambda x: x[1])[0] if from_count else ""
    obj = max(to_count.items(), key=lambda x: x[1])[0] if to_count else ""
    return subj, obj




def draft_claim_text_en(
    fig_type: str,
    edge_ids: List[str],
    edge_map: Dict[str, Dict[str, Any]],
    node_label: Dict[str, str],
) -> str:
    """Conservative English templates with automatic hedging based on weakest evidence."""
    t = (fig_type or "").strip()

    subj_id, obj_id = choose_subject_object(edge_ids, edge_map)
    subj = node_label.get(subj_id, subj_id)
    obj = node_label.get(obj_id, obj_id)
    rel_keys = [normalize_relation_key(str(edge_map.get(eid, {}).get("relation", ""))) for eid in edge_ids]
    rel_key = rel_keys[0] if rel_keys and all(rk == rel_keys[0] for rk in rel_keys) else "default"
    # mediator heuristic: a node that appears as both to and from within this figure
    tos = set(str(edge_map.get(eid, {}).get("to", "")) for eid in edge_ids)
    frs = set(str(edge_map.get(eid, {}).get("from", "")) for eid in edge_ids)
    mediators = [node_label.get(n, n) for n in sorted((tos & frs) - {subj_id, obj_id}) if n]
    mediator = mediators[0] if mediators else ""

    # choose conservative hedging based on the weakest evidence among these edges
    w_ev = weakest_evidence(edge_ids, edge_map)
    prefix, modal = evidence_hedge_en(w_ev)

    # pick a representative verb from the dominant relation in the figure (fallback to affect)
    # If relations differ, default to a neutral verb.
    rels = []
    for eid in edge_ids:
        rels.append(relation_en(str(edge_map.get(eid, {}).get("relation", ""))))
    verb = rels[0] if rels and all(r == rels[0] for r in rels) else get_template("templates", "relations", "default", "verb", default="affects")

    # Knockout-aware rendering
    subj, verb = render_subject_and_verb(
        subj_id=subj_id,
        subj_label=subj,
        edge_ids=edge_ids,
        edge_map=edge_map,
        relation_key=rel_key,
        verb=verb,
    )

    # Compose by figure type
    if t == "phenotype":
        if modal == "may":
            return f"{prefix} {subj} {modal} {verb} {obj}."
        if modal in ("is required to", "is sufficient to"):
            # phenotype claims usually describe effect on phenotype; keep readable
            return f"{prefix} {subj} {verb} {obj}."
        return f"{prefix} {subj} {verb} {obj}."

    if t == "positioning":
        if subj.lower().endswith("deficiency"):
            return f"{prefix} {subj} maps to the level of {obj}."
        return f"{prefix} {subj} acts at the level of {obj}."

    if t == "mechanism_discovery":
        if mediator:
            if modal == "may":
                return f"{prefix} {subj} {modal} {verb} {obj} by influencing {mediator}."
            if modal in ("is required to", "is sufficient to"):
                return f"{prefix} {subj} {verb} {obj}, with {mediator} as a key intermediate step."
            return f"{prefix} {subj} {verb} {obj}, implicating {mediator} as a key intermediate step."
        if modal == "may":
            return f"{prefix} {subj} {modal} {verb} {obj}."
        return f"{prefix} {subj} {verb} {obj}."

    if t == "mechanism_completion":
        if mediator:
            if modal == "may":
                return f"{prefix} the regulation of {obj} by {subj} {modal} depend on {mediator}."
            if modal == "is required to":
                return f"{prefix} {mediator} is required for {subj}-dependent regulation of {obj}."
            if modal == "is sufficient to":
                return f"{prefix} {mediator} is sufficient to account for {subj}-dependent regulation of {obj}."
            return f"{prefix} the regulation of {obj} by {subj} depends on {mediator}."
        if modal == "may":
            return f"{prefix} {subj} {modal} {verb} {obj}."
        return f"{prefix} {subj} {verb} {obj}."

    if t == "upstream_regulation":
        if mediator:
            if modal == "may":
                return f"{prefix} {subj} {modal} influence {obj} through upstream signaling (e.g., {mediator})."
            return f"{prefix} {subj} influences {obj} through upstream signaling (e.g., {mediator})."
        if modal == "may":
            return f"{prefix} {subj} {modal} influence {obj} through upstream signaling."
        return f"{prefix} {subj} influences {obj} through upstream signaling."

    # fallback
    if modal == "may":
        return f"{prefix} {subj} {modal} {verb} {obj}."
    return f"{prefix} {subj} {verb} {obj}."


def build_claims(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    node_label = get_node_label(data.get("nodes", []) or [])
    edge_map = get_edge_map(data.get("edges", []) or [])
    narrative = data.get("narrative", []) or []

    claims = []
    for item in narrative:
        fig = item.get("figure")
        ftype = str(item.get("type", ""))
        edge_ids = [str(x) for x in (item.get("edges", []) or [])]
        components = infer_claim_components(ftype, edge_ids, edge_map, node_label)

        title = f"Fig{fig} {ftype}"
        claim_id = f"c_fig{fig}"

        claims.append(
            {
                "id": claim_id,
                "figure": fig,
                "type": ftype,
                "title": title,
                "weakest_evidence_level": weakest_evidence(edge_ids, edge_map),
                "text_en_draft": draft_claim_text_en(ftype, edge_ids, edge_map, node_label),
                "derived": derive_results_strings(
                    claim_sentence_en=draft_claim_text_en(ftype, edge_ids, edge_map, node_label),
                    components=components,
                ),
                "supported_by_edges": edge_ids,
                "edge_summary_en": summarize_edges_en(edge_ids, edge_map, node_label),
            }
        )

    return claims


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", required=True, help="Input lyout_2_argument.yaml")
    ap.add_argument("--out", default="", help="Output yaml path. Default: <in>.with_claims.yaml")
    ap.add_argument("--templates", required=True, help="templates.yaml path")
    args = ap.parse_args()

    in_path = Path(args.yaml).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve() if args.out else in_path.with_suffix(".with_claims.yaml")

    global TEMPLATES
    tpl_path = Path(args.templates).expanduser().resolve()
    with tpl_path.open("r", encoding="utf-8") as f:
        TEMPLATES = yaml.safe_load(f)

    data = load_yaml(in_path)
    claims = build_claims(data)

    out_obj = {
        "source_yaml": str(in_path),
        "claims": claims,
    }

    dump_yaml(out_path, out_obj)
    print(f"[OK] Wrote claims to: {out_path}")


if __name__ == "__main__":
    main()