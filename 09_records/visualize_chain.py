#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Visualize mechanistic_chain in a YAML as a directed graph.

Usage:
  python visualize_chain.py \
    /Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/09_records/组学-湿实验验证假设.yaml \
    out/chain

Outputs:
  out/chain.png
  out/chain.svg
"""

import os
import re
import sys
from typing import Dict, Any, List, Tuple

import yaml
from graphviz import Digraph


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def consensus_style(consensus: str) -> Tuple[str, str]:
    """
    Return (color, edge_style) by consensus text.
    """
    c = (consensus or "").strip().lower()

    # Strong consensus
    if any(k in c for k in ["广泛", "共识", "已验证", "well", "established"]) and "部分" not in c and "非" not in c:
        return ("#2ca02c", "solid")  # green

    # Partial consensus
    if "部分" in c or "partial" in c or "context" in c:
        return ("#ff7f0e", "solid")  # orange

    # Non-consensus / needs validation
    if any(k in c for k in ["非共识", "不确定", "需", "需要", "unknown", "not"]):
        return ("#d62728", "dashed")  # red

    # Default
    return ("#4c4c4c", "solid")


def wrap_text(s: str, width: int = 28) -> str:
    """
    Simple CJK-friendly wrapping: insert \\n every ~width chars,
    while not breaking too aggressively for short strings.
    """
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= width:
        return s
    lines = []
    i = 0
    while i < len(s):
        lines.append(s[i:i + width])
        i += width
    return "\n".join(lines)


def html_escape(s: str) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def to_html_br(s: str) -> str:
    """Convert a wrapped string with \n into HTML line breaks."""
    return html_escape(s).replace("\n", "<BR ALIGN=\"CENTER\"/>")


def build_graph(data: Dict[str, Any], title: str = "Mechanistic chain") -> Digraph:
    chain = data.get("mechanistic_chain", {})
    nodes: Dict[str, str] = chain.get("nodes", {}) or {}
    links: List[Dict[str, Any]] = chain.get("links", []) or []

    g = Digraph("mechanistic_chain", format="png")
    g.attr(
        rankdir="LR",
        fontsize="12",
        labelloc="t",
        label=title,
        fontname="Arial",
        splines="line",
        overlap="false"
    )
    g.attr(nodesep="0.8", ranksep="1.6")
    g.attr("node", shape="box", style="rounded,filled", fillcolor="#f7f7f7", color="#333333", fontname="Arial")
    g.attr(
        "edge",
        color="#4c4c4c",
        fontname="Arial",
        fontsize="10",
        labelfloat="false",
        labeldistance="1.8",
        labelangle="0"
    )

    # Add nodes (keep X->... chain layout)
    # If you want fixed order, set here:
    preferred_order = ["X", "A", "B", "C", "D", "E"]
    ordered_keys = [k for k in preferred_order if k in nodes] + [k for k in nodes.keys() if k not in preferred_order]

    for k in ordered_keys:
        label = f"{k}\n{wrap_text(nodes[k], 30)}"
        g.node(k, label=label)

    # Add edges
    for lk in links:
        src = lk.get("from")
        dst = lk.get("to")
        if not src or not dst:
            continue

        q = lk.get("question", "")
        cons = lk.get("scientific_consensus", "")
        validations = lk.get("in_this_paper_validation", []) or []
        if isinstance(validations, str):
            validations = [validations]
        expected = lk.get("expected_if_true", "")

        color, style = consensus_style(cons)

        # Build a single HTML edge label so the upper and lower blocks share the same center.
        main_lines = []
        if q:
            main_lines.append(wrap_text(q, 34))
        if cons:
            main_lines.append(wrap_text(f"[{cons}]", 34))
        main_text = "\n".join([x for x in main_lines if x]).strip()

        parts = []
        if validations:
            parts.append("Validation: " + "; ".join([
                re.sub(r"\s+", " ", v).strip() for v in validations if str(v).strip()
            ]))
        if expected:
            parts.append("Expected: " + re.sub(r"\s+", " ", str(expected)).strip())
        sub_text = wrap_text(" | ".join([p for p in parts if p]), 32) if parts else ""

        # Tooltip for interactive viewers (kept as plain text)
        tooltip = "\n".join(parts) if parts else ""

        if sub_text:
            # Use a separator row (1px gray bar) to visually split upper vs lower block.
            html_label = (
                "<<TABLE BORDER=\"0\" CELLBORDER=\"0\" CELLPADDING=\"2\" CELLSPACING=\"0\">"
                f"<TR><TD ALIGN=\"CENTER\">{to_html_br(main_text)}</TD></TR>"
                "<TR><TD HEIGHT=\"1\" BGCOLOR=\"#bdbdbd\"></TD></TR>"
                f"<TR><TD ALIGN=\"CENTER\"><FONT POINT-SIZE=\"9\">{to_html_br(sub_text)}</FONT></TD></TR>"
                "</TABLE>>"
            )
        else:
            html_label = f"<{to_html_br(main_text)}>" if main_text else ""

        g.edge(
            src,
            dst,
            label=html_label,
            color=color,
            style=style,
            penwidth="2",
            tooltip=tooltip,
            minlen="2"
        )

    # Legend (subgraph): show colored LINE samples
    with g.subgraph(name="cluster_legend") as lg:
        lg.attr(label="Legend", fontsize="11", color="#dddddd", fontname="Arial")
        lg.attr(rankdir="LR")
        lg.attr("node", shape="point", width="0.02", height="0.02", label="", color="#ffffff")

        # three rows (use invisible point nodes + a colored edge between them)
        lg.node("Lg1a")
        lg.node("Lg1b")
        lg.edge("Lg1a", "Lg1b", color="#2ca02c", style="solid", penwidth="3", label="共识强")

        lg.node("Lg2a")
        lg.node("Lg2b")
        lg.edge("Lg2a", "Lg2b", color="#ff7f0e", style="solid", penwidth="3", label="部分共识")

        lg.node("Lg3a")
        lg.node("Lg3b")
        lg.edge("Lg3a", "Lg3b", color="#d62728", style="dashed", penwidth="3", label="非共识/需验证")

        # Keep the legend compact
        lg.attr("edge", fontname="Arial", fontsize="10")

    return g


def main():
    if len(sys.argv) < 3:
        print("Usage: python visualize_chain.py <input.yaml> <output_prefix> [title]")
        print("Example: python visualize_chain.py chain.yaml out/chain \"EphB1 mechanism chain\"")
        sys.exit(1)

    in_yaml = sys.argv[1]
    out_prefix = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) >= 4 else "Mechanistic chain"

    os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)

    data = load_yaml(in_yaml)
    g = build_graph(data, title=title)

    # Render PNG
    png_path = g.render(out_prefix, format="png", cleanup=True)

    # Render SVG (better for zoom; many viewers also show tooltips)
    svg_path = g.render(out_prefix, format="svg", cleanup=True)

    print("[OK] Written:")
    print("  ", png_path)
    print("  ", svg_path)


if __name__ == "__main__":
    main()