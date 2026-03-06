#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
visualize_argument.py

Read an argument YAML (nodes/edges/paths/narrative) and export:
  01_argument_network.html  (argument graph with evidence styling + pseudo-nested nodes via `contains`)
  02_paths.html             (each path as a horizontal chain)
  03_narrative.html         (figure flow diagram)

Usage:
  python 08_manuscript/script/论文层级/visualize_argument.py --yaml 06_figures/record/lyout_2_argument.yaml --outdir 07_results/argument_viz
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from pyvis.network import Network


# ----------------------------
# Styling maps
# ----------------------------

RELATION_COLOR = {
    # normalize promotes/activation etc.
    "promotes": "#2ca02c",
    "activation": "#2ca02c",
    "promotion": "#2ca02c",

    "inhibits": "#d62728",
    "inhibition": "#d62728",

    "requirement": "#1f77b4",

    "production": "#9467bd",
    "generation": "#9467bd",

    "state_transition": "#ff7f0e",
    "transition": "#ff7f0e",
}

# evidence → width
EVIDENCE_WIDTH = {
    "correlation": 1.5,
    "positioning": 3.0,
    "necessity": 5.0,
    "sufficiency": 5.0,
    "causal_closure": 7.0,
    # “established biology” should be visible but not dominate
    "established biology": 2.5,
    "established_biology": 2.5,
    "established": 2.5,
}

# evidence → dashed?
EVIDENCE_DASHED = {
    "established biology": True,
    "established_biology": True,
    "established": True,
}

# evidence → alpha (rgba)
EVIDENCE_ALPHA = {
    "established biology": 0.45,
    "established_biology": 0.45,
    "established": 0.45,
}


def rgba(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to rgba(r,g,b,a)."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ----------------------------
# YAML parsing
# ----------------------------

def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_nodes(data: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    node_label: Dict[str, str] = {}
    node_contains: Dict[str, List[str]] = {}

    for n in data.get("nodes", []) or []:
        nid = str(n.get("id"))
        node_label[nid] = str(n.get("label", nid))
        contains = n.get("contains", []) or []
        if isinstance(contains, str):
            contains = [contains]
        node_contains[nid] = [str(x) for x in contains]

    return node_label, node_contains


def parse_edges(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    edge_map: Dict[str, Dict[str, Any]] = {}
    for e in data.get("edges", []) or []:
        eid = str(e.get("id"))
        edge_map[eid] = e
    return edge_map


def normalize_relation(rel: str) -> str:
    r = (rel or "").strip().lower()
    if r in ("promote", "promotes", "activation", "promotion"):
        return "promotes"
    if r in ("inhibit", "inhibits", "inhibition"):
        return "inhibits"
    if r in ("require", "requires", "requirement"):
        return "requirement"
    if r in ("produce", "produces", "production", "generate", "generates", "generation"):
        return "generation"
    if r in ("state transition", "state_transition", "transition"):
        return "state_transition"
    return r or "unknown"


def normalize_evidence(ev: str) -> str:
    e = (ev or "").strip().lower()
    e = e.replace("_", " ")
    return e


# ----------------------------
# HTML exporters
# ----------------------------

def set_common_options(net: Network, physics: bool = True) -> None:
    """Set pyvis options once (avoid repeated set_options bugs)."""
    # Use vis-network options JSON
    opts = {
        "interaction": {
            "dragNodes": True,
            "dragView": True,
            "zoomView": True,
            "hover": True,
        },
        "physics": {
            "enabled": physics,
            "barnesHut": {
                "gravitationalConstant": -2000,
                "centralGravity": 0.3,
                "springLength": 180,
                "springConstant": 0.04,
                "damping": 0.09,
                "avoidOverlap": 0.2,
            },
            "minVelocity": 0.75,
        },
    }
    net.set_options(json.dumps(opts))


def export_argument_network(
    data: Dict[str, Any],
    node_label: Dict[str, str],
    node_contains: Dict[str, List[str]],
    edge_map: Dict[str, Dict[str, Any]],
    out_html: Path,
) -> None:
    net = Network(height="900px", width="100%", directed=True, bgcolor="#ffffff", notebook=False)

    # --- pseudo-nested nodes (containers) ---
    containers = {nid for nid, kids in (node_contains or {}).items() if kids}
    container_pos: Dict[str, Tuple[int, int]] = {}

    # Place containers on the left column
    x0, y0, dy = -450, -200, 260
    for idx, nid in enumerate(sorted(containers)):
        kids = node_contains.get(nid, []) or []
        size = 45 + 8 * len(kids)
        x = x0
        y = y0 + idx * dy
        container_pos[nid] = (x, y)

        net.add_node(
            nid,
            label=node_label.get(nid, nid),
            title=f"{nid} (container)\ncontains: {', '.join(kids)}",
            shape="dot",
            size=size,
            physics=False,
            fixed=True,
            x=x,
            y=y,
            color={"background": "rgba(180,180,180,0.18)", "border": "rgba(120,120,120,0.45)"},
            borderWidth=2,
        )

    # Add other nodes
    for nid in node_label.keys():
        if nid in containers:
            continue

        # If contained by a container: place around it (inside-ish)
        parent = None
        for c in containers:
            if nid in (node_contains.get(c, []) or []):
                parent = c
                break

        kwargs = dict(
            label=node_label.get(nid, nid),
            title=f"{nid}\n{node_label.get(nid, nid)}",
            shape="dot",
        )

        if parent and parent in container_pos:
            px, py = container_pos[parent]
            kids = node_contains.get(parent, []) or []
            k = max(1, len(kids))
            try:
                j = kids.index(nid)
            except ValueError:
                j = 0
            angle = (2 * math.pi) * (j / k)
            # smaller radius so it visually sits “inside” the container
            r = 70
            x = px + int(r * math.cos(angle))
            y = py + int(r * math.sin(angle))
            kwargs.update({"x": x, "y": y})

        net.add_node(nid, **kwargs)

    # Invisible containment springs (visual only)
    for c in containers:
        for kid in node_contains.get(c, []) or []:
            if kid not in node_label:
                continue
            net.add_edge(
                c, kid,
                label="",
                arrows="",
                color="rgba(0,0,0,0)",
                width=0.01,
                physics=True,
            )

    # Causal edges
    for eid, e in edge_map.items():
        u = str(e.get("from"))
        v = str(e.get("to"))
        rel = normalize_relation(str(e.get("relation", "")))
        ev = normalize_evidence(str(e.get("evidence_level", "")))

        base_color = RELATION_COLOR.get(rel, "#7f7f7f")
        alpha = EVIDENCE_ALPHA.get(ev, 1.0)
        color = rgba(base_color, alpha)

        width = float(EVIDENCE_WIDTH.get(ev, 2.5))
        dashes = bool(EVIDENCE_DASHED.get(ev, False))

        title = (
            f"{eid}\n"
            f"{node_label.get(u,u)}  ->  {node_label.get(v,v)}\n"
            f"relation: {rel}\n"
            f"evidence: {ev}\n"
        )
        if "supported_by" in e:
            sb = e.get("supported_by")
            if isinstance(sb, list):
                refs = []
                for item in sb:
                    if isinstance(item, dict) and "ref" in item:
                        refs.append(str(item["ref"]))
                    elif isinstance(item, str):
                        refs.append(item)
                if refs:
                    title += "supported_by:\n" + "\n".join(refs)

        net.add_edge(
            u, v,
            label="",   # keep graph clean
            title=title,
            color=color,
            width=width,
            arrows="to",
            dashes=dashes,
        )

    # Legend (fixed)
    net.add_node("legend_title", label="LEGEND", shape="box", x=350, y=-420, physics=False, fixed=True, color="#ffffff", font={"size": 20})
    net.add_node("legend_promotes", label="green = promotes", shape="box", x=350, y=-370, physics=False, fixed=True, color="#2ca02c")
    net.add_node("legend_inhibits", label="red = inhibits", shape="box", x=350, y=-330, physics=False, fixed=True, color="#d62728")
    net.add_node("legend_requirement", label="blue = requirement", shape="box", x=350, y=-290, physics=False, fixed=True, color="#1f77b4")
    net.add_node("legend_generation", label="purple = generation", shape="box", x=350, y=-250, physics=False, fixed=True, color="#9467bd")
    net.add_node("legend_transition", label="orange = state transition", shape="box", x=350, y=-210, physics=False, fixed=True, color="#ff7f0e")
    net.add_node("legend_corr", label="thin = correlation", shape="box", x=350, y=-160, physics=False, fixed=True)
    net.add_node("legend_pos", label="mid = positioning", shape="box", x=350, y=-120, physics=False, fixed=True)
    net.add_node("legend_nec", label="thick = necessity/sufficiency", shape="box", x=350, y=-80, physics=False, fixed=True)
    net.add_node("legend_est", label="dashed/light = established biology", shape="box", x=350, y=-40, physics=False, fixed=True)

    set_common_options(net, physics=True)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_html), open_browser=False, notebook=False)


def export_paths(
    data: Dict[str, Any],
    node_label: Dict[str, str],
    out_html: Path,
) -> None:
    net = Network(height="800px", width="100%", directed=True, bgcolor="#ffffff", notebook=False)

    paths = data.get("paths", []) or []
    if not paths:
        net.add_node("no_paths", label="No paths found in YAML", shape="box")
        set_common_options(net, physics=False)
        net.write_html(str(out_html), open_browser=False, notebook=False)
        return

    x_step = 240
    y_step = 180

    for pi, p in enumerate(paths):
        pid = str(p.get("id", f"p{pi+1}"))
        role = str(p.get("role", ""))
        nodes = [str(x) for x in (p.get("nodes", []) or [])]

        # path label node (left)
        label_id = f"{pid}__label"
        net.add_node(
            label_id,
            label=f"{pid}\n({role})",
            shape="box",
            x=-350,
            y=pi * y_step,
            physics=False,
            fixed=True,
        )

        prev = None
        for i, nid in enumerate(nodes):
            vid = f"{pid}__{nid}__{i}"
            net.add_node(
                vid,
                label=node_label.get(nid, nid),
                title=f"{nid}",
                shape="dot",
                x=i * x_step,
                y=pi * y_step,
                physics=False,
                fixed=True,
            )
            if prev is not None:
                net.add_edge(prev, vid, arrows="to", label="", width=3)
            prev = vid

    set_common_options(net, physics=False)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_html), open_browser=False, notebook=False)


def export_narrative(
    data: Dict[str, Any],
    node_label: Dict[str, str],
    edge_map: Dict[str, Dict[str, Any]],
    out_html: Path,
) -> None:
    net = Network(height="650px", width="100%", directed=True, bgcolor="#ffffff", notebook=False)

    narrative = data.get("narrative", []) or []
    if not narrative:
        net.add_node("no_narrative", label="No narrative found in YAML", shape="box")
        set_common_options(net, physics=False)
        net.write_html(str(out_html), open_browser=False, notebook=False)
        return

    x_step = 260
    y = 0

    fig_nodes: List[str] = []
    for i, item in enumerate(narrative):
        fig = item.get("figure", i + 1)
        ftype = str(item.get("type", ""))
        edges = [str(x) for x in (item.get("edges", []) or [])]

        fid = f"fig{fig}"
        fig_nodes.append(fid)

        # Build tooltip with edge details
        lines = [f"Figure {fig}  [{ftype}]"]
        lines.append("edges:")
        for eid in edges:
            e = edge_map.get(eid, {})
            u = str(e.get("from", ""))
            v = str(e.get("to", ""))
            rel = normalize_relation(str(e.get("relation", "")))
            ev = normalize_evidence(str(e.get("evidence_level", "")))
            lines.append(f"- {eid}: {node_label.get(u,u)} -> {node_label.get(v,v)} | {rel} | {ev}")
        title = "\n".join(lines)

        net.add_node(
            fid,
            label=f"Fig{fig}\n{ftype}",
            title=title,
            shape="box",
            x=i * x_step,
            y=y,
            physics=False,
            fixed=True,
        )

    for a, b in zip(fig_nodes, fig_nodes[1:]):
        net.add_edge(a, b, arrows="to", width=3)

    set_common_options(net, physics=False)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_html), open_browser=False, notebook=False)


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", required=True, help="Path to lyout_2_argument.yaml")
    ap.add_argument("--outdir", required=True, help="Output directory (e.g., 07_results/argument_viz)")
    args = ap.parse_args()

    yaml_path = Path(args.yaml).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    data = load_yaml(yaml_path)
    node_label, node_contains = parse_nodes(data)
    edge_map = parse_edges(data)

    export_argument_network(
        data=data,
        node_label=node_label,
        node_contains=node_contains,
        edge_map=edge_map,
        out_html=outdir / "01_argument_network.html",
    )
    export_paths(
        data=data,
        node_label=node_label,
        out_html=outdir / "02_paths.html",
    )
    export_narrative(
        data=data,
        node_label=node_label,
        edge_map=edge_map,
        out_html=outdir / "03_narrative.html",
    )

    print(f"[OK] Exported:\n  {outdir / '01_argument_network.html'}\n  {outdir / '02_paths.html'}\n  {outdir / '03_narrative.html'}")


if __name__ == "__main__":
    main()