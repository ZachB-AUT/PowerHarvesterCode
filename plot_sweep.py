"""
Overview figures of a parameter sweep, from femm_work/parameter_sweep_progress.csv.

    uv run python plot_sweep.py            # the most recent line current swept
    uv run python plot_sweep.py 600        # a particular line current [A rms]

Saves figures/sweep_overview_<current>A.png.
"""

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

HERE = Path(__file__).resolve().parent
PROGRESS = HERE / "femm_work" / "parameter_sweep_progress.csv"
FIGURES = HERE / "figures"

# Colours (reference palette, light mode)
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
MUTED = "#b9b8b2"  # the quiet grey for data
ACCENT = "#2a78d6"  # blue: what each title is about
REFERENCE = "#8a8984"
BLUES = LinearSegmentedColormap.from_list(
    "blue_ramp",
    ["#f2f6fc", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
)
SATURATION_T = 1.6  # [T] knee of the AK Steel M-19 DC B-H curve, where it starts to saturate


def load(line_current=None):
    with open(PROGRESS, newline="") as f:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]
    if line_current is None:
        line_current = rows[-1]["line_current"]
    rows = [r for r in rows if r["line_current"] == line_current]
    data = {k: np.array([r[k] for r in rows]) for k in rows[0]}
    data["core_thickness"] = data["outer_radius"] - data["inner_radius"]
    area = data["core_thickness"] * data["core_length"] * 1e-6  # [m^2]
    data["b_peak"] = data["phi_peak"] / area
    return line_current, data


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.set_xlabel(xlabel, fontsize=8, color=INK_SECONDARY)
    ax.set_ylabel(ylabel, fontsize=8, color=INK_SECONDARY)


def pareto(mass, power):
    """Indices of designs that no lighter design beats on power."""
    order = np.argsort(mass)
    front, best = [], -np.inf
    for i in order:
        if power[i] > best:
            front.append(i)
            best = power[i]
    return np.array(front)


def best_by(values, power):
    """Highest power at each distinct value."""
    xs = np.unique(values)
    return xs, np.array([power[values == x].max() for x in xs])


if __name__ == "__main__":
    line_current, d = load(float(sys.argv[1]) if len(sys.argv) > 1 else None)
    p_mw = d["power"] * 1e3
    unit, scale = ("W", 1e-3) if p_mw.max() >= 1000 else ("mW", 1.0)
    p = p_mw * scale
    win = int(np.argmax(p))
    winner = {k: v[win] for k, v in d.items()}
    n = len(p)

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), facecolor=SURFACE)
    fig.suptitle(
        f"{n} designs at {line_current:g} A rms. Best: {p[win]:.3g} {unit} from "
        f"{winner['mass'] * 1e3:.0f} g (core r {winner['inner_radius']:g}–"
        f"{winner['outer_radius']:g} mm, {winner['core_length']:g} mm long, "
        f"{winner['coil_turns']:.0f} turns)",
        fontsize=12, color=INK, x=0.01, ha="left",
    )

    # 1. Power against mass, with the Pareto front
    ax = axes[0, 0]
    front = pareto(d["mass"], p)
    style(ax, f"Power vs mass: the best design at each mass (blue)", "Total mass [g]",
          f"Delivered power [{unit}]")
    ax.scatter(d["mass"] * 1e3, p, s=8, color=MUTED, linewidths=0)
    # Best power available at or below each mass: a step at each improvement
    ax.plot(d["mass"][front] * 1e3, p[front], color=ACCENT, linewidth=2,
            drawstyle="steps-post")
    ax.scatter([winner["mass"] * 1e3], [p[win]], s=60, color=ACCENT,
               edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.annotate(f"{p[win]:.3g} {unit}", (winner["mass"] * 1e3, p[win]),
                xytext=(8, -12), textcoords="offset points", fontsize=8, color=INK)

    # 2. Turns: best overall at each turn count vs the winning geometry
    ax = axes[0, 1]
    xs, ys = best_by(d["coil_turns"], p)
    best_turns = xs[np.argmax(ys)]
    title = (f"Turns: more still helps at {best_turns:.0f}, the top of the range"
             if best_turns == xs.max() else f"Turns: best at {best_turns:.0f}")
    style(ax, title, "Coil turns", f"Delivered power [{unit}]")
    ax.plot(xs, ys, color=MUTED, linewidth=2, label="best of all geometries")
    same = np.ones(n, bool)
    for k in ("inner_radius", "outer_radius", "core_length", "coil_thickness"):
        same &= d[k] == winner[k]
    order = np.argsort(d["coil_turns"][same])
    ax.plot(d["coil_turns"][same][order], p[same][order], color=ACCENT, linewidth=2,
            marker="o", markersize=4, label="winning core and coil")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)

    # 3. Heatmap of best power over core inner radius x thickness
    ax = axes[0, 2]
    radii = np.unique(d["inner_radius"])
    thick = np.unique(d["core_thickness"])
    grid = np.full((len(thick), len(radii)), np.nan)
    for i, t in enumerate(thick):
        for j, r in enumerate(radii):
            sel = (d["inner_radius"] == r) & (d["core_thickness"] == t)
            if sel.any():
                grid[i, j] = p[sel].max()
    style(ax, "Best power by core shape (blank = over the mass limit)",
          "Core inner radius [mm]", "Core radial thickness [mm]")
    ax.grid(False)
    im = ax.imshow(grid, origin="lower", aspect="auto", cmap=BLUES,
                   extent=(radii[0] - 0.5, radii[-1] + 0.5, thick[0] - 0.5, thick[-1] + 0.5)
                   if len(radii) > 1 and len(thick) > 1 else None)
    if len(radii) > 1 and len(thick) > 1:
        dr = (radii[-1] - radii[0]) / (len(radii) - 1)
        dt = (thick[-1] - thick[0]) / (len(thick) - 1)
        im.set_extent((radii[0] - dr / 2, radii[-1] + dr / 2, thick[0] - dt / 2, thick[-1] + dt / 2))
    cbar = fig.colorbar(im, ax=ax, fraction=0.05)
    cbar.ax.tick_params(labelsize=8, colors=INK_SECONDARY)
    cbar.set_label(f"Best power [{unit}]", fontsize=8, color=INK_SECONDARY)

    # 4. Where the power goes: delivered vs copper loss
    ax = axes[1, 0]
    loss = d["coil_loss"] * 1e3 * scale
    style(ax, "Delivered vs coil heating (blue = best per mass)",
          f"Coil copper loss [{unit}]",
          f"Delivered power [{unit}]")
    ax.scatter(loss, p, s=8, color=MUTED, linewidths=0)
    ax.scatter(loss[front], p[front], s=14, color=ACCENT, linewidths=0)
    x_max, y_max = max(loss.max(), 1e-9) * 1.05, max(p.max(), 1e-9) * 1.08
    for eff in (0.5, 0.8, 0.95):
        slope = eff / (1 - eff)  # delivered / loss
        ax.plot([0, x_max], [0, x_max * slope], color=REFERENCE, linewidth=1, linestyle="--")
        # Label where the line leaves the plot: right edge or top edge
        if x_max * slope <= y_max:
            x, y, ha, va = x_max * 0.98, x_max * slope * 0.98, "right", "bottom"
        else:
            x, y, ha, va = y_max * 0.95 / slope, y_max * 0.95, "left", "top"
        ax.text(x, y, f" {eff:.0%} efficient", fontsize=8, color=INK_SECONDARY, ha=ha, va=va)
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, y_max)

    # 5. Saturation: peak flux density in the core
    ax = axes[1, 1]
    style(ax, "Core flux: are we saturating?", "Peak core flux density [T]",
          f"Delivered power [{unit}]")
    ax.scatter(d["b_peak"], p, s=8, color=MUTED, linewidths=0)
    ax.scatter([winner["b_peak"]], [p[win]], s=60, color=ACCENT, edgecolor=SURFACE,
               linewidth=1.5, zorder=3)
    ax.axvline(SATURATION_T, color=REFERENCE, linewidth=1, linestyle="--")
    ax.text(SATURATION_T, p.max() * 1.02, " M-19 knee", fontsize=8,
            color=INK_SECONDARY, va="bottom")
    ax.set_ylim(0, p.max() * 1.1)

    # 6. Core length
    ax = axes[1, 2]
    xs, ys = best_by(d["core_length"], p)
    best_length = xs[np.argmax(ys)]
    title = (f"Core length: longer still helps at {best_length:g} mm, the top of the range"
             if best_length == xs.max() else f"Core length: best at {best_length:g} mm (mass limit)")
    style(ax, title, "Core length along the line [mm]", f"Best delivered power [{unit}]")
    ax.plot(xs, ys, color=ACCENT, linewidth=2, marker="o", markersize=4)
    ax.set_ylim(0, ys.max() * 1.1)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    FIGURES.mkdir(exist_ok=True)
    out = FIGURES / f"sweep_overview_{line_current:g}A.png"
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
