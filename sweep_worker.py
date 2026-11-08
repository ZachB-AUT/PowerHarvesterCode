"""
Run one slice of a parameter sweep on a private FEMM copy, so several slices
can run in parallel (FEMM itself uses one core).

A slice is one inner radius and one core thickness; the other parameters span
the whole sweep. Results go to femm_work/workers/<name>/parameter_sweep_progress.csv,
seeded from the main progress file so finished designs are not redone.
merge_workers() appends them back into the main progress file, after which the
normal sweep resumes and finds those designs done.

    uv run python sweep_worker.py coarse <inner radius> <core thickness> [coil thicknesses...]
    uv run python sweep_worker.py fine <inner radius> <core thickness> [coil thicknesses...]
    uv run python sweep_worker.py light <inner radius> <core thickness> [coil thicknesses...]
    uv run python sweep_worker.py merge
    uv run python sweep_worker.py slices <coarse|fine|light>   # list the slices

run_parallel.sh does all of this for a whole sweep.
"""

import csv
import functools
import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MAIN_WORK = HERE / "femm_work"
MAIN_PROGRESS = MAIN_WORK / "parameter_sweep_progress.csv"
WORKERS = MAIN_WORK / "workers"
FEMM_SOURCE = Path.home() / ".wine/drive_c/femm42/bin"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sweep_ranges(phase):
    """The full ranges of the coarse, fine or light sweep."""
    if phase == "light":
        return load("light_sweep", "light_sweep.py").LIGHT
    fs = load("fine_sweep", "fine_sweep.py")
    if phase == "coarse":
        ranges = {}
        for name, (first, last, step) in fs.COARSE.items():
            if name == "coil_turns":
                ranges[name] = range(int(first), int(last) + 1, int(step))
            else:
                ranges[name] = np.arange(first, last + step / 2, step)
        return ranges
    winner = fs.best_coarse_design(fs.coarse_results_file())
    return {name: fs.fine_range(name, winner[name]) for name in fs.COARSE}


def run_slice(phase, inner_radius, core_thickness, coil_thicknesses=None):
    """One slice; optionally only some coil thicknesses, to split a slow slice."""
    name = f"{phase}_r{inner_radius:g}_t{core_thickness:g}"
    # A helper on part of a slice starts from what the whole slice has done
    seed = WORKERS / name / "parameter_sweep_progress.csv"
    if not seed.exists():
        seed = MAIN_PROGRESS
    if coil_thicknesses:
        name += "_c" + "-".join(f"{c:g}" for c in coil_thicknesses)
    work = WORKERS / name
    work.mkdir(parents=True, exist_ok=True)
    progress = work / "parameter_sweep_progress.csv"
    if not progress.exists() and seed.exists():
        shutil.copy(seed, progress)

    femm_copy = Path.home() / f".wine/drive_c/femm42_{name}/bin"
    if not (femm_copy / "femm.exe").exists():
        shutil.copytree(FEMM_SOURCE, femm_copy)

    hr = load("harvester_reimplementation", "harvester-reimplementation.py")
    hr.femm.openfemm = functools.partial(hr.femm.openfemm, femmpath=str(femm_copy))
    hr.WORK_DIR = work
    if phase == "light":
        hr.MAX_MASS = load("light_sweep", "light_sweep.py").LIGHT_MAX_MASS

    ranges = sweep_ranges(phase)
    hr.run_sweep(
        inner_radii=[inner_radius],
        core_thicknesses=[core_thickness],
        core_lengths=ranges["core_length"],
        coil_thicknesses=coil_thicknesses or ranges["coil_thickness"],
        coil_turns=ranges["coil_turns"],
        results_file="slice_results.csv",
    )


def merge_workers():
    """Append worker results that the main progress file does not have yet."""
    hr = load("harvester_reimplementation", "harvester-reimplementation.py")
    known = {hr.sweep_key(r) for r in hr.load_progress(MAIN_PROGRESS)}
    added = 0
    for progress in sorted(WORKERS.glob("*/parameter_sweep_progress.csv")):
        with open(progress, newline="") as f:
            for row in csv.DictReader(f):
                key = hr.sweep_key({k: float(v) for k, v in row.items()})
                if key not in known:
                    hr.save_progress(MAIN_PROGRESS, row)
                    known.add(key)
                    added += 1
    print(f"> merged {added} new results into {MAIN_PROGRESS}")


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        merge_workers()
    elif sys.argv[1] == "slices":
        ranges = sweep_ranges(sys.argv[2])
        for r in ranges["inner_radius"]:
            for t in ranges["core_thickness"]:
                print(f"{r:g} {t:g}")
    else:
        coils = [float(c) for c in sys.argv[4:]]
        run_slice(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), coils or None)
