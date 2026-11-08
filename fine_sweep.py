"""
Finer parameter sweep around the best design of a coarse sweep.

Reads the coarse sweep's results (femm_work/parameter_sweep_results_coarse.csv
if you saved a copy there, otherwise femm_work/parameter_sweep_results.csv),
takes the highest-power design, and sweeps a finer grid around it, spanning one
coarse step either side. Where the winner sits on the edge of the coarse range,
the fine grid reaches further past that edge (EDGE_STEPS), in case the optimum
lies outside it.

FEMM runs once per (inner radius, outer radius, coil thickness), so those three
get half the coarse step. Core length and turns only need the fast circuit
simulation, so they get much finer steps.

    make SCRIPT=fine_sweep.py

Results go to femm_work/parameter_sweep_results_fine.csv. Progress is shared
with the coarse sweep, so designs on both grids are not simulated twice.
"""

import csv
import importlib.util
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# The coarse grid in harvester-reimplementation.py: (first, last, step)
COARSE = {
    "inner_radius": (20.0, 28.0, 4.0),
    "core_thickness": (10.0, 34.0, 4.0),
    "core_length": (5.0, 55.0, 5.0),
    "coil_thickness": (1.0, 9.0, 1.0),
    "coil_turns": (25, 200, 25),
}
# Fine step as a fraction of the coarse step
FINE_FRACTION = {
    "inner_radius": 1 / 2,  # FEMM
    "core_thickness": 1 / 2,  # FEMM
    "coil_thickness": 1 / 2,  # FEMM
    "core_length": 1 / 5,  # circuit only
    "coil_turns": 1 / 5,  # circuit only
}
# How many coarse steps past the coarse range to reach when the winner sits on
# its edge. Length and turns only cost circuit simulations (~25 ms each), so
# they can reach much further than the three that need new FEMM solves (a
# large core takes ~35 min per FEMM geometry at 25 A). At 25 A the coarse best
# was voltage limited at the 200-turn cap, hence the long reach in turns.
EDGE_STEPS = {
    "inner_radius": 1,
    "core_thickness": 1,
    "coil_thickness": 1,
    "core_length": 4,
    "coil_turns": 32,
}
# Smallest sensible value of each
MINIMUM = {
    "inner_radius": 10.0,
    "core_thickness": 1.0,
    "core_length": 1.0,
    "coil_thickness": 0.5,
    "coil_turns": 5,
}


def load_harvester():
    """Import harvester-reimplementation.py (the hyphen stops a normal import)."""
    spec = importlib.util.spec_from_file_location(
        "harvester_reimplementation", HERE / "harvester-reimplementation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coarse_results_file():
    """The coarse sweep's results: a saved copy if there is one, else the latest sweep's."""
    work = HERE / "femm_work"
    saved = work / "parameter_sweep_results_coarse.csv"
    return saved if saved.exists() else work / "parameter_sweep_results.csv"


def best_coarse_design(results_file):
    with open(results_file, newline="") as f:
        best = max(csv.DictReader(f), key=lambda row: float(row["power"]))
    design = {name: float(value) for name, value in best.items()}
    design["core_thickness"] = design["outer_radius"] - design["inner_radius"]
    return design


def fine_range(name, centre):
    """Values for one parameter around the coarse winner."""
    first, last, step = COARSE[name]
    below = EDGE_STEPS[name] * step if np.isclose(centre, first) else step
    above = EDGE_STEPS[name] * step if np.isclose(centre, last) else step
    fine_step = step * FINE_FRACTION[name]
    low = max(centre - below, MINIMUM[name])
    values = np.arange(low, centre + above + fine_step / 2, fine_step)
    if name == "coil_turns":
        return range(int(values[0]), int(values[-1]) + 1, int(fine_step))
    return np.round(values, 6)


if __name__ == "__main__":
    coarse_file = coarse_results_file()
    if len(sys.argv) > 1:
        coarse_file = Path(sys.argv[1])
    winner = best_coarse_design(coarse_file)
    print(f"> Coarse winner ({coarse_file.name}): {winner['power']:.3f} W")

    ranges = {name: fine_range(name, winner[name]) for name in COARSE}
    for name, values in ranges.items():
        values = list(values)
        print(f"    {name}: {values[0]:g} .. {values[-1]:g}, {len(values)} values")

    hr = load_harvester()
    hr.run_sweep(
        inner_radii=ranges["inner_radius"],
        core_thicknesses=ranges["core_thickness"],
        core_lengths=ranges["core_length"],
        coil_thicknesses=ranges["coil_thickness"],
        coil_turns=ranges["coil_turns"],
        results_file="parameter_sweep_results_fine.csv",
    )
