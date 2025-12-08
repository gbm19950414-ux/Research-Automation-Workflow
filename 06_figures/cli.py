# CLI entry placeholder
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command line interface for building figures
"""

import argparse
from engine.render import render_one

def main():
    parser = argparse.ArgumentParser(description="Build figures in Nature style")
    parser.add_argument("build", help="build figure(s)", nargs='?')
    parser.add_argument("--fig", required=True, help="Path to YAML config in figs/")
    parser.add_argument("--style", default="style", help="Path to style folder")
    parser.add_argument("--out", default="out", help="Output folder")
    args = parser.parse_args()

    render_one(args.fig, args.style, args.out)

if __name__ == "__main__":
    main()