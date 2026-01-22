#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import textwrap
from typing import Any, Dict, List

import yaml
from graphviz import Digraph


def wrap(s: str, width: int = 36) -> str:
    s = s or ""
    return "\n".join(textwrap.wrap(s, width=width, break_long_words=False))


def safe_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def slugify(s: str) -> str:
    import re
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = re.sub(r'_+', '_', s)
    s = s.strip('_')
    return s


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def mk_pipeline_graph(data: Dict[str, Any], out_prefix: str, title: str = None):
    pipeline = data.get("pipeline", {})
    runs = data.get("runs", [])

    g = Digraph("pipeline", format="svg")
    # Global style
    g.attr(rankdir="LR", splines="ortho", nodesep="0.35", ranksep="0.65")
    g.attr("graph", fontname="Helvetica")
    g.attr("node", fontname="Helvetica", shape="box", style="rounded", fontsize="10")
    g.attr("edge", fontname="Helvetica", arrowsize="0.7")

    assay_nodes: Dict[str, str] = {}
    branch_to_assay_edges: List[tuple] = []

    # Root node
    pname = pipeline.get("name", "pipeline")
    pver = pipeline.get("version", "")
    root_label = f"{pname}\n{pver}".strip()
    if title:
        root_label = f"{title}\n{root_label}"
    root_id = "ROOT"
    g.node(root_id, label=wrap(root_label, 44), shape="box", style="rounded,bold", fontsize="12")

    # For layout: keep runs in same rank? (not necessary)
    # Create run subgraphs
    for i, run in enumerate(runs, start=1):
        run_id = run.get("run_id", f"RUN{i:02d}")
        goal = run.get("goal", "")
        shared = run.get("shared_condition", run.get("shared_condition", ""))

        run_node = f"RUN__{run_id}"
        run_label = f"{run_id}\n{wrap(goal, 44)}"
        if shared:
            run_label += f"\n—\n共享条件：{wrap(shared, 44)}"

        g.node(run_node, label=run_label, shape="box", style="rounded,bold")

        # Edge from root to run
        g.edge(root_id, run_node)

        branches = safe_list(run.get("branches"))
        # Make a subgraph cluster for run branches
        with g.subgraph(name=f"cluster_{run_id}") as c:
            c.attr(label=run_id, fontsize="12", fontname="Helvetica", style="rounded")
            c.attr("node", fontsize="10")

            # Put run node inside cluster for clarity
            c.node(run_node)

            for b in branches:
                bid = b.get("branch_id", "branch")
                sample_type = b.get("sample_type", "")
                assay = b.get("assay", "")
                purpose = b.get("purpose", "")
                linked = safe_list(b.get("linked_EVs"))

                bnode = f"BR__{run_id}__{bid}"
                lines = [bid]
                meta = []
                if sample_type:
                    meta.append(f"样品：{sample_type}")
                if assay:
                    meta.append(f"检测：{assay}")
                if meta:
                    lines.append(" / ".join(meta))
                if linked:
                    lines.append(f"EV: {', '.join(linked)}")
                if purpose:
                    lines.append(wrap(purpose, 44))

                c.node(bnode, label="\n".join(lines))

                # Connect run -> branch
                c.edge(run_node, bnode)

                if assay:
                    assay_node_id = f"ASSAY__{slugify(assay)}"
                    if assay not in assay_nodes:
                        g.node(assay_node_id, label=f"assay:\n{assay}")
                        assay_nodes[assay] = assay_node_id
                    branch_to_assay_edges.append((bnode, assay_node_id))

    with g.subgraph(name="cluster__assay_column") as ac:
        ac.attr(rank="same")
        for assay_node_id in assay_nodes.values():
            ac.node(assay_node_id)

    for branch_node_id, assay_node_id in branch_to_assay_edges:
        g.edge(branch_node_id, assay_node_id, arrowhead="vee")

    # Render
    out_dir = os.path.dirname(os.path.abspath(out_prefix))
    if out_dir:
        ensure_dir(out_dir)

    # Render SVG first
    g.format = "svg"
    svg_path = g.render(filename=out_prefix, cleanup=True)  # outputs <prefix>.svg

    # Export additional formats by switching g.format
    for fmt in ("png", "pdf"):
        g.format = fmt
        g.render(filename=out_prefix, cleanup=True)

    # Restore format (optional, but keeps object state consistent)
    g.format = "svg"
    return svg_path


def main():
    if len(sys.argv) < 3:
        print("Usage: python visualize_pipeline.py <pipeline.yaml> <out_prefix> [title]")
        print("Example: python visualize_pipeline.py 组学假设验证pipeline.yaml out/pipeline_vis \"FigureX Pipeline\"")
        sys.exit(1)

    yaml_path = sys.argv[1]
    out_prefix = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) >= 4 else None

    data = load_yaml(yaml_path)
    mk_pipeline_graph(data, out_prefix, title=title)
    print(f"[OK] Wrote: {out_prefix}.svg / .png / .pdf")


if __name__ == "__main__":
    main()