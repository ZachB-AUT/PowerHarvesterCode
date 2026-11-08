"""
This program plots a specific design and some information about it.

Saves figures/winner.png.
"""

import contextlib
import csv
import importlib.util
import io
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from line_current_stats import FEEDERS, line_currents
from plot_sweep import (
    ACCENT,
    BLUES,
    INK,
    INK_SECONDARY,
    MUTED,
    REFERENCE,
    SURFACE,
    style,
)

HERE = Path(__file__).resolve().parent
FINE_RESULTS = HERE / "femm_work" / "parameter_sweep_results_fine.csv"
FIGURES = HERE / "figures"


def load_harvester():
    spec = importlib.util.spec_from_file_location(
        "harvester_reimplementation", HERE / "harvester-reimplementation.py"
    )
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


def quiet(f, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*args, **kwargs)


if __name__ == "__main__":
    with open(FINE_RESULTS, newline="") as f:
        rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]
    w = max(rows, key=lambda r: r["power"] - r["coil_loss"])

    hr = load_harvester()
    sim = quiet(hr.harvestersim)
    sim.inner_radius, sim.outer_radius = w["inner_radius"], w["outer_radius"]
    sim.CORE_LENGTH, sim.COIL_THICKNESS = w["core_length"], w["coil_thickness"]
    sim.COIL_TURNS, sim.LINE_CURRENT = int(w["coil_turns"]), w["line_current"]
    sim.recompute_dependants()
    cached = sim.load_flux_curve()
    if cached is None:
        raise SystemExit("The winner's flux curve is not in femm_work/flux_cache")
    mmf, flux_per_mm = cached
    flux = flux_per_mm * sim.CORE_LENGTH
    r_coil = sim.coil_resistance()

    def power_at(current_rms):
        sim.LINE_CURRENT = current_rms
        return quiet(sim.simulate_circuit, mmf, flux, hr.BATTERY_VOLTAGE, r_coil)

    # The flux curve was solved up to 3x the design peak current
    i_max = mmf.max() / math.sqrt(2) * 0.95
    currents = np.arange(0.0, min(70.0, i_max), 1.0)
    powers = np.array([power_at(i)[0] if i > 0 else 0.0 for i in currents])
    i_threshold = currents[np.argmax(powers > 0)]

    # A year of Kikiwa per-feeder current, half-hourly
    feeder = np.array([a for _, _, a in line_currents()]) / FEEDERS
    p_year = np.interp(feeder, currents, powers)
    mean_power = p_year.mean()
    share_harvesting = (p_year > 0).mean()

    fig, axes = plt.subplots(2, 2, figsize=(13, 9.5), facecolor=SURFACE)
    fig.suptitle(
        f"Best design: {w['power'] * 1e3:.0f} mW at {w['line_current']:g} A ",
        # f"{w['mass'] * 1e3:.0f} g. On a real rural NZ feeder it would average "
        # f"{mean_power * 1e3:.0f} mW ({mean_power * 24:.1f} Wh a day).",
        fontsize=12,
        color=INK,
        x=0.01,
        ha="left",
    )

    # 1. Power against line current, over the measured feeder currents
    ax = axes[0, 0]
    style(
        ax,
        f"Harvests nothing below {i_threshold:g} A",
        "Line current [A rms]",
        "Delivered power [mW]",
    )
    lo, hi = np.percentile(feeder, [5, 95])
    # ax.axvspan(lo, hi, color=MUTED, alpha=0.25, linewidth=0)
    # ax.text((lo + hi) / 2, powers.max() * 1e3 * 1.02,
    #         "Kikiwa feeders, 5–95 % of the year", fontsize=8,
    #         color=INK_SECONDARY, ha="center", va="bottom")
    # ax.axvline(np.median(feeder), color=REFERENCE, linewidth=1, linestyle="--")
    # ax.text(np.median(feeder), 0, f" median {np.median(feeder):.0f} A", fontsize=8,
    #         color=INK_SECONDARY, rotation=90, va="bottom")
    ax.plot(currents, powers * 1e3, color=ACCENT, linewidth=2)
    ax.set_ylim(0, powers.max() * 1e3 * 1.12)

    ax.axvline(14, color=REFERENCE, linewidth=1, linestyle="--")

    # # 2. A year on the feeder: harvested power through the day
    # ax = axes[0, 1]
    # style(ax, f"Over a year it harvests {share_harvesting:.1%} of the time",
    #       "Hour of day", "Delivered power [mW]")
    # rows_k = line_currents()
    # hours = np.array([hh / 2 for _, hh, _ in rows_k])
    # for q, alpha in ((90, 0.18), (75, 0.3)):
    #     lo_q = [np.percentile(p_year[hours == h], 100 - q) for h in np.unique(hours)]
    #     hi_q = [np.percentile(p_year[hours == h], q) for h in np.unique(hours)]
    #     ax.fill_between(np.unique(hours), np.array(lo_q) * 1e3, np.array(hi_q) * 1e3,
    #                     color=ACCENT, alpha=alpha, linewidth=0)
    # mean_by_hour = [p_year[hours == h].mean() for h in np.unique(hours)]
    # ax.plot(np.unique(hours), np.array(mean_by_hour) * 1e3, color=ACCENT, linewidth=2,
    #         label="mean")
    # ax.set_xlim(0, 23.5)
    # ax.set_xticks(range(0, 24, 3))
    # ax.set_ylim(bottom=0)
    # ax.text(0.98, 0.95, "line: mean  ·  bands: middle 50 % and 80 %",
    #         transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK_SECONDARY)

    # 3. Waveforms over one cycle at the design current
    ax = axes[1, 0]
    _, _, _, waves = power_at(w["line_current"])
    t = (waves[:, 0] - waves[0, 0]) * 1e3
    conducting = (np.abs(waves[:, 2]) > 1e-9).mean()
    style(
        ax,
        "Cycle ",
        "Time [ms]",
        "Normalised to peak",
    )
    ax.plot(
        t,
        waves[:, 1] / np.abs(waves[:, 1]).max(),
        color=MUTED,
        linewidth=2,
        label=f"line current (peak {np.abs(waves[:, 1]).max():.0f} A)",
    )
    ax.plot(
        t,
        waves[:, 3] / np.abs(waves[:, 3]).max(),
        color=REFERENCE,
        linewidth=1.5,
        linestyle="--",
        label="core flux",
    )
    ax.plot(
        t,
        waves[:, 2] / max(np.abs(waves[:, 2]).max(), 1e-12),
        color=ACCENT,
        linewidth=2,
        label=f"coil current (peak {np.abs(waves[:, 2]).max() * 1e3:.0f} mA)",
    )
    ax.axhline(0, color=INK_SECONDARY, linewidth=0.8)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")

    # 4. Power over turns x core length for the winning core and coil
    ax = axes[1, 1]
    same = [
        r
        for r in rows
        if r["inner_radius"] == w["inner_radius"]
        and r["outer_radius"] == w["outer_radius"]
        and r["coil_thickness"] == w["coil_thickness"]
    ]
    turns = np.array(sorted({r["coil_turns"] for r in same}))
    lengths = np.array(sorted({r["core_length"] for r in same}))
    grid = np.full((len(lengths), len(turns)), np.nan)
    for r in same:
        grid[
            np.searchsorted(lengths, r["core_length"]),
            np.searchsorted(turns, r["coil_turns"]),
        ] = r["power"] * 1e3
    style(
        ax,
        f"Sweet spot: {w['coil_turns']:.0f} turns, {w['core_length']:g} mm "
        "(longer is over 1 kg)",
        "Coil turns",
        "Core length [mm]",
    )
    ax.grid(False)
    im = ax.imshow(
        grid,
        origin="lower",
        aspect="auto",
        cmap=BLUES,
        extent=(turns[0], turns[-1], lengths[0] - 0.5, lengths[-1] + 0.5),
    )
    ax.plot(
        w["coil_turns"],
        w["core_length"],
        "o",
        color=SURFACE,
        markersize=9,
        markeredgecolor=INK,
        markeredgewidth=1.5,
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.05)
    cbar.ax.tick_params(labelsize=8, colors=INK_SECONDARY)
    cbar.set_label("Delivered power [mW]", fontsize=8, color=INK_SECONDARY)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    FIGURES.mkdir(exist_ok=True)
    out = FIGURES / "winner.png"
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    print(
        f"threshold {i_threshold:g} A, mean {mean_power * 1e3:.1f} mW, "
        f"harvesting {share_harvesting:.0%} of the time, coil resistance {r_coil:.2f} ohm"
    )
