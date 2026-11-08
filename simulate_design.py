"""
Simulate one harvester design and print what it delivers.

    uv run python simulate_design.py <inner radius> <outer radius> <core length> \
        <coil thickness> <turns> [line current]

Lengths in mm, line current in A rms (default: LINE_CURRENT in
harvester-reimplementation.py). Example, the best 1 kg design at 25 A:

    uv run python simulate_design.py 16 32 51 8 265 25

Runs FEMM once for the core's cross-section (a few minutes), unless that
flux curve is already in femm_work/flux_cache from an earlier run or sweep.
"""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_harvester():
    """Import harvester-reimplementation.py (the hyphen stops a normal import)."""
    spec = importlib.util.spec_from_file_location(
        "harvester_reimplementation", HERE / "harvester-reimplementation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        raise SystemExit(__doc__)
    inner, outer, length, coil = (float(a) for a in sys.argv[1:5])
    turns = int(sys.argv[5])

    hr = load_harvester()
    with contextlib.redirect_stdout(io.StringIO()):
        sim = hr.harvestersim()
    sim.inner_radius, sim.outer_radius = inner, outer
    sim.CORE_LENGTH, sim.COIL_THICKNESS, sim.COIL_TURNS = length, coil, turns
    if len(sys.argv) == 7:
        sim.LINE_CURRENT = float(sys.argv[6])
    sim.recompute_dependants()

    power, coil_loss, phi_peak, _ = sim.run_simulation()
    area = (outer - inner) * length * 1e-6  # [m^2]
    mass = sim.core_mass + sim.coil_mass()
    print(f"\nDesign: core r {inner:g}-{outer:g} mm, {length:g} mm long, "
          f"{coil:g} mm coil, {turns} turns, at {sim.LINE_CURRENT:g} A rms")
    print(f"  delivered power  {power * 1e3:8.1f} mW into {hr.BATTERY_VOLTAGE:g} V")
    print(f"  coil copper loss {coil_loss * 1e3:8.1f} mW (coil {sim.coil_resistance():.2f} ohm)")
    print(f"  peak flux density {phi_peak / area:7.2f} T")
    print(f"  mass             {mass * 1e3:8.0f} g "
          f"(core {sim.core_mass * 1e3:.0f} g, copper {sim.coil_mass() * 1e3:.0f} g)")
