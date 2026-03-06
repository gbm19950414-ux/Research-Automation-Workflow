#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
从 lyout_2_argument.yaml 读取 nodes/edges，构建有向图，枚举 start->end 所有简单路径，
并导出：
1) interactive HTML 网状图（pyvis）
2) paths.tsv 路径清单（按分数排序）
3) paths.md（便于你直接看/复制到 argument_paths）

用法示例：
  python build_argument_paths.py \
    --yaml "/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/record/lyout_2_argument.yaml" \
    --start n1 --end n2 --max-hops 6 \
    --outdir "./_argument_viz"

依赖：
  pip install pyyaml networkx pyvis pandas
  # 支持 evidence_level: established_biology / established biology / existence
"""

import argparse
import os
from pathlib import Path
import yaml
import networkx as nx
import pandas as pd
from pyvis.network import Network

# 证据等级 → 强度分数（用于排序/筛选，不代表论文里要写的“强度词”）

EVIDENCE_SCORE = {
    # weakest → strongest (used only for ranking paths)
    "correlation": 1,
    "positioning": 2,
    # established / consensus biology used as bridging edges in the argument graph
    "established_biology": 2,
    "established biology": 2,  #在路径选择（主轴排序）时，共识边的存在价值主要是“连通/桥接”，不是“加分”
    "existence": 2,
    "necessity": 3,
    "sufficiency": 3,
    "causal_closure": 4,
}

# Visual encoding for graph edges
# - Color encodes relation type
# - Width encodes evidence strength
RELATION_COLOR = {
    # positive / activation
    "promotes": "#2ca02c",
    "activation": "#2ca02c",
    "activate": "#2ca02c",
    "positive": "#2ca02c",
    "promotion": "#2ca02c",

    # negative / inhibition
    "inhibits": "#d62728",
    "inhibition": "#d62728",
    "inhibit": "#d62728",
    "negative": "#d62728",

    # requirement (necessary condition)
    "requires": "#1f77b4",
    "requirement": "#1f77b4",

    # production / generation
    "generates": "#9467bd",
    "generation": "#9467bd",
    "produces": "#9467bd",
    "production": "#9467bd",

    # state transition
    "state_transition": "#ff7f0e",
    "state transition": "#ff7f0e",
    "transition": "#ff7f0e",
}

EVIDENCE_WIDTH = {
    # weakest → strongest (visual thickness only)
    "correlation": 1,
    "positioning": 2,
    "established_biology": 2,
    "established biology": 2,
    "existence": 2,
    "necessity": 4,
    "sufficiency": 4,
    "causal_closure": 6,
}

# Evidence levels that should be visually de-emphasized (background bridging edges)
BRIDGING_EVIDENCE = {"established_biology", "established biology", "existence"}

def _norm_key(s: str) -> str:
    return (s or "").strip().lower().replace("-", "_")

def edge_color(relation: str) -> str:
    return RELATION_COLOR.get(_norm_key(relation), "#7f7f7f")

def edge_width(evidence_level: str) -> int:
    return int(EVIDENCE_WIDTH.get(_norm_key(evidence_level), 1))

def edge_is_bridging(evidence_level: str) -> bool:
    return _norm_key(evidence_level) in { _norm_key(x) for x in BRIDGING_EVIDENCE }

def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def build_graph(data: dict) -> tuple[nx.DiGraph, dict, dict]:
    """
    返回：
      G: networkx DiGraph
      nodes: node_id -> label
      edges: edge_id -> edge_dict（含 from/to/evidence_level/relation/robustness 等）
    """
    nodes_list = data.get("nodes", [])
    edges_list = data.get("edges", [])

    node_label = {}
    for n in nodes_list:
        nid = n["id"]
        label = n.get("label") or n.get("label_cn") or nid
        node_label[nid] = label

    edge_map = {}
    G = nx.DiGraph()
    for nid, label in node_label.items():
        G.add_node(nid, label=label)

    for e in edges_list:
        eid = e["id"]
        src = e["from"]
        dst = e["to"]
        evidence_level = (e.get("evidence_level") or "").strip()
        relation = (e.get("relation") or "").strip()
        robustness = (e.get("robustness") or "").strip()

        score = EVIDENCE_SCORE.get(evidence_level, 0)

        edge_map[eid] = {
            "id": eid,
            "from": src,
            "to": dst,
            "evidence_level": evidence_level,
            "relation": relation,
            "robustness": robustness,
            "score": score,
            "supported_by": e.get("supported_by", []),
            "condition": e.get("condition", []),
        }

        # 用 (src, dst, key=eid) 的方式保存，便于同一对节点多条边
        # networkx 的 DiGraph 只能存一条边；这里用 edge_id 作为属性，允许覆盖不冲突（同对节点多边可改 MultiDiGraph）
        if G.has_edge(src, dst):
            # 如果你确实存在同一对节点多条边，建议改成 MultiDiGraph
            # 这里先把 edge_id 们聚合
            prev = G.edges[src, dst].get("edge_ids", [])
            prev.append(eid)
            G.edges[src, dst]["edge_ids"] = prev
        else:
            G.add_edge(src, dst, edge_ids=[eid])

    return G, node_label, edge_map

def enumerate_paths(G: nx.DiGraph, start: str, end: str, max_hops: int) -> list[list[str]]:
    """
    返回 node_id 路径列表（简单路径，不重复节点）
    """
    # cutoff 是“节点数-1”的最大边数
    cutoff = max_hops
    return list(nx.all_simple_paths(G, source=start, target=end, cutoff=cutoff))

def choose_edge_id_for_step(edge_ids: list[str], edge_map: dict) -> str:
    """
    同一对节点可能映射到多个 edge_id（你未来可能会出现）。
    默认选择证据分数更高的那条（也可改成保留全部）。
    """
    best = None
    best_score = -1
    for eid in edge_ids:
        s = edge_map.get(eid, {}).get("score", 0)
        if s > best_score:
            best_score = s
            best = eid
    return best or edge_ids[0]

def score_path(G: nx.DiGraph, path_nodes: list[str], edge_map: dict) -> dict:
    """
    给一条路径打分：
      - total_score: 每步 edge score 求和
      - bottleneck: 最弱一条边的 score
      - edge_ids: 该路径对应的 edge_id 列表（每一步选一条最强边）
    """
    edge_ids = []
    scores = []
    relations = []
    evidences = []

    for i in range(len(path_nodes) - 1):
        u = path_nodes[i]
        v = path_nodes[i + 1]
        edge_ids_uv = G.edges[u, v].get("edge_ids", [])
        eid = choose_edge_id_for_step(edge_ids_uv, edge_map)
        edge_ids.append(eid)
        s = edge_map[eid]["score"]
        scores.append(s)
        relations.append(edge_map[eid].get("relation", ""))
        evidences.append(edge_map[eid].get("evidence_level", ""))

    total = sum(scores) if scores else 0
    bottleneck = min(scores) if scores else 0

    return {
        "edge_ids": edge_ids,
        "scores": scores,
        "relations": relations,
        "evidences": evidences,
        "total_score": total,
        "bottleneck": bottleneck,
        "hops": len(path_nodes) - 1,
    }

def export_pyvis(G: nx.DiGraph, node_label: dict, edge_map: dict, out_html: Path):
    net = Network(height="750px", width="100%", directed=True, bgcolor="#ffffff")

    # nodes
    for nid in G.nodes():
        label = node_label.get(nid, nid)
        net.add_node(nid, label=label, title=nid)
    # ---- Legend ----
    net.add_node("legend_title", label="LEGEND", shape="box",
                x=-900, y=-450, physics=False, fixed=True,
                color="#ffffff", font={"size":20})

    net.add_node("legend_promote", label="green = promotes / activation",
                shape="box", x=-900, y=-400, physics=False, fixed=True,
                color="#2ca02c")

    net.add_node("legend_inhibit", label="red = inhibition",
                shape="box", x=-900, y=-360, physics=False, fixed=True,
                color="#d62728")

    net.add_node("legend_requirement", label="blue = requirement",
                shape="box", x=-900, y=-320, physics=False, fixed=True,
                color="#1f77b4")

    net.add_node("legend_generation", label="purple = generation",
                shape="box", x=-900, y=-280, physics=False, fixed=True,
                color="#9467bd")

    net.add_node("legend_transition", label="orange = state transition",
                shape="box", x=-900, y=-240, physics=False, fixed=True,
                color="#ff7f0e")

    net.add_node("legend_corr", label="thin edge = correlation",
                shape="box", x=-900, y=-180, physics=False, fixed=True)

    net.add_node("legend_pos", label="medium edge = positioning / established",
                shape="box", x=-900, y=-140, physics=False, fixed=True)

    net.add_node("legend_nec", label="thick edge = necessity / sufficiency",
                shape="box", x=-900, y=-100, physics=False, fixed=True)

    net.add_node("legend_closure", label="very thick = causal closure",
                shape="box", x=-900, y=-60, physics=False, fixed=True)
    # edges（若同一对节点有多条 edge_id，这里显示“最强那条”的标签）
    for u, v, attrs in G.edges(data=True):
        edge_ids = attrs.get("edge_ids", [])
        if not edge_ids:
            continue
        eid = choose_edge_id_for_step(edge_ids, edge_map)
        e = edge_map[eid]
        relation = e.get("relation", "")
        evidence_level = e.get("evidence_level", "")

        # Remove edge label text for clarity; keep details in hover tooltip.
        title = f"{eid}\nrelation: {relation}\nevidence: {evidence_level}"

        color = edge_color(relation)
        width = edge_width(evidence_level)

        # De-emphasize bridging/established edges (still visible, but lighter)
        if edge_is_bridging(evidence_level):
            net.add_edge(u, v, label="", title=title, color=color, width=width, arrows="to", opacity=0.35, dashes=True)
        else:
            net.add_edge(u, v, label="", title=title, color=color, width=width, arrows="to")

    # Enable physics (spring-like layout) for the whole graph.
    # Legend nodes are fixed (physics=False), so they won't be affected.
    net.toggle_physics(True)
    net.barnes_hut(gravity=-2000, central_gravity=0.3, spring_length=180, spring_strength=0.04, damping=0.09)
    net.write_html(str(out_html), open_browser=False, notebook=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", required=True, help="lyout_2_argument.yaml 路径")
    ap.add_argument("--start", required=True, help="起点 node id，如 n1")
    ap.add_argument("--end", required=True, help="终点 node id，如 n2")
    ap.add_argument("--max-hops", type=int, default=6, help="最大边数（路径长度上限）")
    ap.add_argument("--outdir", default="./_argument_viz", help="输出目录")
    args = ap.parse_args()

    yaml_path = Path(args.yaml).expanduser()
    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    data = load_yaml(yaml_path)
    G, node_label, edge_map = build_graph(data)

    if args.start not in G.nodes:
        raise SystemExit(f"start node not found: {args.start}")
    if args.end not in G.nodes:
        raise SystemExit(f"end node not found: {args.end}")

    paths = enumerate_paths(G, args.start, args.end, args.max_hops)

    rows = []
    for idx, p in enumerate(paths, start=1):
        sc = score_path(G, p, edge_map)
        rows.append({
            "path_id": f"p{idx}",
            "start": args.start,
            "end": args.end,
            "nodes": " -> ".join(p),
            "node_labels": " -> ".join([node_label.get(n, n) for n in p]),
            "edges": ", ".join(sc["edge_ids"]),
            "relations": ", ".join(sc["relations"]),
            "evidences": ", ".join(sc["evidences"]),
            "total_score": sc["total_score"],
            "bottleneck": sc["bottleneck"],
            "hops": sc["hops"],
        })

    df = pd.DataFrame(rows)
    if len(df) == 0:
        print("No paths found. Try increasing --max-hops or check graph connectivity.")
    else:
        df = df.sort_values(by=["total_score", "bottleneck", "hops"], ascending=[False, False, True])

    # 1) paths.tsv
    tsv_path = outdir / "paths.tsv"
    df.to_csv(tsv_path, sep="\t", index=False, encoding="utf-8")

    # 2) paths.md（生成 argument_paths 草案）
    md_path = outdir / "paths.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write(f"# Paths from {args.start} to {args.end}\n\n")
        if len(df) == 0:
            f.write("No paths found.\n")
        else:
            for _, r in df.iterrows():
                f.write(f"## {r['path_id']}  score={r['total_score']}  bottleneck={r['bottleneck']}  hops={r['hops']}\n")
                f.write(f"- nodes: {r['node_labels']}\n")
                f.write(f"- edges: {r['edges']}\n")
                f.write(f"- evidences: {r['evidences']}\n")
                f.write("\n")
            f.write("\n## YAML snippet (candidate argument_paths)\n\n")
            f.write("```yaml\n")
            for _, r in df.iterrows():
                node_ids = [n.strip() for n in r["nodes"].split("->")]
                edge_ids = [e.strip() for e in r["edges"].split(",")]
                f.write(f"- id: {r['path_id']}\n")
                f.write(f"  start: {args.start}\n")
                f.write(f"  end: {args.end}\n")
                f.write(f"  nodes: [{', '.join(node_ids)}]\n")
                f.write(f"  edges: [{', '.join(edge_ids)}]\n")
                f.write("\n")
            f.write("```\n")

    # 3) graph.html（交互网状图）
    html_path = outdir / "graph.html"
    export_pyvis(G, node_label, edge_map, html_path)

    print(f"[OK] Wrote: {tsv_path}")
    print(f"[OK] Wrote: {md_path}")
    print(f"[OK] Wrote: {html_path}")

if __name__ == "__main__":
    main()