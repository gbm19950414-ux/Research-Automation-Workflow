# render module placeholder
# engine/render.py
from .figlib import boxplot
import yaml
import matplotlib.pyplot as plt
from pathlib import Path
from .registry import PLOTTERS

def render_one(fig_yaml, style_dir, out_dir):
    with open(fig_yaml, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    base_name = Path(fig_yaml).stem

    # 加载并合并样式配置
    style = {}
    style_dir = Path(style_dir)
    for name in ["rcparams.yaml", "layout.yaml", "export.yaml", "palette.yaml"]:
        p = style_dir / name
        if p.exists():
            with open(p, "r", encoding="utf-8") as sf:
                s = yaml.safe_load(sf) or {}
                for k, v in s.items():
                    if k in style and isinstance(style[k], dict) and isinstance(v, dict):
                        style[k].update(v)
                    else:
                        style[k] = v
    # 应用全局 rcParams
    plt.rcParams.update(style.get("rcparams", {}))

    for panel in spec["panels"]:
        typ = panel["type"]
        plotter = PLOTTERS[typ]

        use_constrained = spec.get("constrained_layout", False) or panel.get("constrained_layout", False)
        size_cfg = spec.get("size", {}) or panel.get("size", {})
        if size_cfg:
            w = size_cfg.get("width_mm")
            h = size_cfg.get("high_mm") or size_cfg.get("height_mm")
            if w and h:
                fig, ax = plt.subplots(figsize=(w/25.4, h/25.4), constrained_layout=use_constrained)
            else:
                fig, ax = plt.subplots(constrained_layout=use_constrained)
        else:
            fig, ax = plt.subplots(constrained_layout=use_constrained)

        plotter(ax, panel, style)

        out_name = f"{base_name}_{panel.get('id', 'panel')}.pdf"
        out_path = Path(out_dir) / out_name
        fig.savefig(out_path)
        plt.close(fig)
        print(f"✅ 已生成: {out_path}")