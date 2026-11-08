"""
Sweep of light designs (roughly 100-500 g), which the coarse and fine sweeps
barely covered: the coarse sweep stopped at 200 turns, too few for a small
core to reach the battery voltage, and the fine sweep only covered cores of
45 mm and longer.

Small cores and short lengths, with turns reaching far past the coarse cap.
FEMM runs once per (inner radius, core thickness, coil thickness); length and
turns only need the fast circuit simulation.

    make SCRIPT=light_sweep.py

or in parallel slices with sweep_worker.py (phase "light"). Results go to
femm_work/parameter_sweep_results_light.csv. Progress is shared with the other
sweeps, so designs already simulated are not redone.
"""

import importlib.util
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

LIGHT = {
    "inner_radius": np.array([12.0, 16.0, 20.0, 24.0]),
    "core_thickness": np.array([4.0, 6.0, 8.0, 10.0, 12.0, 14.0]),
    "core_length": np.arange(5.0, 45.0, 1.0),
    "coil_thickness": np.array([2.0, 4.0, 6.0, 8.0]),
    "coil_turns": range(25, 2001, 25),
}
# Heavier designs are covered by the coarse and fine sweeps
LIGHT_MAX_MASS = 0.6  # [kg]


def load_harvester():
    """Import harvester-reimplementation.py (the hyphen stops a normal import)."""
    spec = importlib.util.spec_from_file_location(
        "harvester_reimplementation", HERE / "harvester-reimplementation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    hr = load_harvester()
    hr.MAX_MASS = LIGHT_MAX_MASS
    hr.run_sweep(
        inner_radii=LIGHT["inner_radius"],
        core_thicknesses=LIGHT["core_thickness"],
        core_lengths=LIGHT["core_length"],
        coil_thicknesses=LIGHT["coil_thickness"],
        coil_turns=LIGHT["coil_turns"],
        results_file="parameter_sweep_results_light.csv",
    )
