#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
from pathlib import Path


ARGUMENT_FILE = Path(
"/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/06_figures/record/lyout_2_argument.yaml"
)

OUTPUT_FILE = Path(
"/Volumes/Samsung_SSD_990_PRO_2TB_Media/EphB1/07_results/introduction_skeleton.yaml"
)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_path(data, role):

    for p in data["paths"]:
        if p.get("role") == role:
            return p

    return None


def generate_intro(data):

    main_path = find_path(data, "main_axis")
    core_path = find_path(data, "mechanism_core")
    established_path = find_path(data, "inflammasome_downstream_established")

    main_nodes = main_path["nodes"]

    regulator = main_nodes[0]
    phenotype_nodes = main_nodes[-2:]

    focus_nodes = core_path["nodes"][1:-2]

    upstream_nodes = main_nodes[1:3]

    intro = {
        "introduction": {
            "field_importance": {
                "phenotype_nodes": phenotype_nodes
            },

            "known_mechanism": {
                "path": established_path["id"]
            },

            "mechanistic_focus": {
                "nodes": focus_nodes
            },

            "knowledge_gap": {
                "upstream_nodes": upstream_nodes
            },

            "hypothesis": {
                "regulator_node": regulator,
                "mechanism_nodes": focus_nodes,
                "phenotype_nodes": phenotype_nodes
            }
        }
    }

    return intro


def main():

    data = load_yaml(ARGUMENT_FILE)

    intro_yaml = generate_intro(data)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(
            intro_yaml,
            f,
            allow_unicode=True,
            sort_keys=False
        )

    print("Introduction YAML generated:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()