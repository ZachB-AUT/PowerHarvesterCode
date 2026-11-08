import csv
import hashlib
import json
import math
import os
import time
from pathlib import Path

import femm
import matplotlib.pyplot as plt
import numpy as np

# Constants:
LINE_FREQUENCY = 50.0  # Hz
CONDUCTOR_DIAMETER = 7.0  # mm
CORE_MATERIAL = "M-19 Steel"

MAX_MASS = 1  # kg

COPPER_RESISTIVITY = 2.1e-8  # [ohm m] copper at ~80 C

M19_STEEL_DENSITY = 7650.0  # [kg/m^3]
COPPER_DENSITY = 8960.0  # [kg/m^3]
FILL_FACTOR = 0.5  # fraction of the coil space that is actually copper

# Core loss, apparently this is usually about 1W per kg per tesla^2 at 50Hz.
# Stays under 2 until about 2T, so I think 1 is safe ish
# https://www.researchgate.net/figure/The-loss-curves-for-M19-at-several-values-of-frequency-versus-magnetic-flux-density_fig1_277501783
CORE_LOSS_W_PER_KG_PER_T2 = 1.0

# Volts. This is somewhat arbitrary, but lower voltages here let smaller cores
# produce non-zero power, as the EMF has to get over this for it to conduct at
# all.
BATTERY_VOLTAGE = 5

DIODE_DROP = 0.5  # [V] per diode, for a schottky diode.

VACUUM_PERMITTIVITY = 8.8541878128e-12  # [F/m]

# ----------------------------------------------------------------
# FEMM directories
# ----------------------------------------------------------------
# Where FEMM writes its files. FEMM runs inside Wine
WORK_DIR = Path(__file__).resolve().parent / "femm_work"
PLOT_FILE = Path(__file__).resolve().parent / "figure.png"
# FEMM flux curves, shared by every sweep process (see flux_cache_file)
FLUX_CACHE_DIR = Path(__file__).resolve().parent / "femm_work" / "flux_cache"


def wine_path(path: Path) -> str:
    """
    A helper function to show tell wine where to find a linux path.
    """
    return "Z:" + str(path.resolve())


# AI Usage declaration, this function was written by Claude Opus 5.5.
def callfemm_wine(command):
    """
    Replacement for pyFEMM's callfemm on Linux/Wine.

    FEMM can create ofile.txt a moment before it writes the reply into it.
    pyFEMM reads that empty file as the reply, so every later command picks
    up the previous command's answer, and eventually a command is lost and
    pyFEMM waits forever. So wait until the whole reply has been written
    before reading it.

    THIS FUNCTION WAS WRITTEN BY AN LLM.
    """
    with open(femm.ifile, "w") as f:
        f.write("flput(" + command + ")")

    while True:
        try:
            with open(femm.ofile) as f:
                reply = f.read()
        except FileNotFoundError:
            reply = ""
        # An error reply has no newline; it ends with an unescaped '")'.
        if reply.endswith("\n") or (
            reply.startswith("error(")
            and reply.endswith('")')
            and not reply.endswith('\\")')
        ):
            break
        time.sleep(femm.sleeptime)
    os.unlink(femm.ofile)

    # Same parsing as pyFEMM
    reply = reply.strip()
    reply = (
        reply.replace("[ ", "[").replace(" ]", "]").replace(" ", ",").replace("I", "1j")
    )
    if len(reply) == 0:
        result = []
    elif reply[0] == "e":
        raise Exception(reply.replace(",", " ").replace("1j", "I"))
    else:
        result = eval(reply)
    if len(result) == 1:
        result = result[0]
    return result


if os.name != "nt":
    femm.callfemm = callfemm_wine


class harvestersim:
    """
        Power harvester simulation.
    """
    def __init__(self):
        # ----------------------------------------------------------------
        # DESIGN PARAMETERS
        # ----------------------------------------------------------------
        self.n_turns = 100

        self.COIL_TURNS = 50.0  # Number of turns in the coil
        self.COIL_THICKNESS = (
            3.0  # thickness of the winding on each side of the core, mm
        )
        self.INSULATION_THICKNESS = (
            0.5  # thickess of the bobbin wall between the coil and the steel
        )

        self.coil_span_deg = 60  # Number of degrees spanned by the coil

        self.CORE_LENGTH = 10.0  # Length of the core, in mm. Also called "L"

        self.CLEARANCE_MM = (
            5.0  # minimum distance between conductor surface and the coil
        )

        self.CORE_GAP = 0.1  # mm

        self.inner_radius = 10.0
        self.outer_radius = 20.0

        self.core_thickness = self.outer_radius - self.inner_radius  # mm

        self.LINE_CURRENT = 25  # Amps

        self.core_mass = (
            M19_STEEL_DENSITY
            * self.CORE_LENGTH
            * 1e-3
            * math.pi
            * ((self.outer_radius * 1e-3) ** 2 - (self.inner_radius * 1e-3) ** 2)
        )

        self.simulation_cache = {}

        print("> Simulator Initialized.")

    def set_line_current(self, current):
        self.LINE_CURRENT = current

    def recompute_dependants(self):
        self.core_thickness = self.outer_radius - self.inner_radius  # mm

        self.core_mass = (
            M19_STEEL_DENSITY
            * self.CORE_LENGTH
            * 1e-3
            * math.pi
            * ((self.outer_radius * 1e-3) ** 2 - (self.inner_radius * 1e-3) ** 2)
        )

    def build_model(self):
        """
        Construct a FEMM simulation for the current model.
        """

        femm.openfemm(1)  # start FEMM minimised
        femm.newdocument(0)  # Magnetics problem

        femm.mi_probdef(
            0,  # Static frequency
            "millimeters",  # units mm
            "planar",  # Planar problem
            1e-8,  # Precision of 1e-8
            self.CORE_LENGTH,  # depth is CORE_LENGTH along the line
            30,  # Minimum mesh angle 30 degrees
        )

        # Load materials into simulation
        femm.mi_getmaterial("Air")
        femm.mi_getmaterial("Copper")
        # femm.mi_getmaterial("Aluminium, 1100") femm.mi_getmaterial(CORE_MATERIAL)

        # Create two circuits, one for the line, and one for the coil
        femm.mi_addcircprop("Line", 0, 1)
        femm.mi_addcircprop("Coil", 0, 1)

        conductor_radius = CONDUCTOR_DIAMETER / 2

        # Draw the conductor
        femm.mi_drawarc(conductor_radius, 0, -conductor_radius, 0, 180, 5)
        femm.mi_drawarc(-conductor_radius, 0, conductor_radius, 0, 180, 5)

        conductor_r_mm = CONDUCTOR_DIAMETER / 2
        # Working outwards from the centre of the line:
        #   conductor -> clearance -> inner coil layer -> insulation -> STEEL
        #   -> insulation -> outer coil layer
        core_inner_r_mm = (
            conductor_r_mm
            + self.CLEARANCE_MM
            + self.COIL_THICKNESS
            + self.INSULATION_THICKNESS
        )
        core_outer_r_mm = core_inner_r_mm + self.core_thickness

        # Cross-section of the steel that the magnetic flux flows through [m^2]
        core_area = (self.core_thickness * 1e-3) * (self.CORE_LENGTH * 1e-3)

        half_gap = self.CORE_GAP / 2

        y_in = math.sqrt(self.inner_radius**2 - half_gap**2)
        y_out = math.sqrt(self.outer_radius**2 - half_gap**2)
        #
        # Angle swept by each half's arc (slightly 180 degrees, because of the cut)
        arc_in = 180 - 2 * math.degrees(math.asin(half_gap / self.inner_radius))
        arc_out = 180 - 2 * math.degrees(math.asin(half_gap / self.outer_radius))

        # Right half (x > 0).
        # FEMM draws arcs counter-clockwise from the first point to the second,
        # so go from bottom to top.
        femm.mi_drawarc(half_gap, -y_in, half_gap, y_in, arc_in, 1)
        femm.mi_drawarc(half_gap, -y_out, half_gap, y_out, arc_out, 1)
        femm.mi_drawline(half_gap, y_in, half_gap, y_out)  # top cut face
        femm.mi_drawline(half_gap, -y_in, half_gap, -y_out)  # bottom cut face

        # Left half, convesely, go from top to bottom.
        femm.mi_drawarc(-half_gap, y_in, -half_gap, -y_in, arc_in, 1)
        femm.mi_drawarc(-half_gap, y_out, -half_gap, -y_out, arc_out, 1)
        femm.mi_drawline(-half_gap, y_in, -half_gap, y_out)
        femm.mi_drawline(-half_gap, -y_in, -half_gap, -y_out)

        # Close the ends of each gap strip so it becomes its own small region;
        # that lets us give the gap its own (very fine) mesh size.
        for s in (1, -1):  # s = +1 top gap, s = -1 bottom gap
            femm.mi_drawline(-half_gap, s * y_in, half_gap, s * y_in)
            femm.mi_drawline(-half_gap, s * y_out, half_gap, s * y_out)

        # DRAW THE COIL
        half_span = self.coil_span_deg / 2
        coil_in_outer = (
            self.inner_radius - self.INSULATION_THICKNESS
        )  # inner band hugs the inside of the ring
        coil_in_inner = coil_in_outer - self.COIL_THICKNESS
        coil_out_inner = (
            self.outer_radius + self.INSULATION_THICKNESS
        )  # outer band hugs the outside
        coil_out_outer = coil_out_inner + self.COIL_THICKNESS
        for r1, r2 in (
            (coil_in_inner, coil_in_outer),
            (coil_out_inner, coil_out_outer),
        ):
            femm.mi_drawarc(
                *self.polar(r1, -half_span),
                *self.polar(r1, half_span),
                self.coil_span_deg,
                1,
            )
            femm.mi_drawarc(
                *self.polar(r2, -half_span),
                *self.polar(r2, half_span),
                self.coil_span_deg,
                1,
            )
            femm.mi_drawline(*self.polar(r1, half_span), *self.polar(r2, half_span))
            femm.mi_drawline(*self.polar(r1, -half_span), *self.polar(r2, -half_span))

        # This is the distance around the coil we want to have a fine mesh
        fine_r = coil_out_outer + 10
        femm.mi_drawarc(fine_r, 0, -fine_r, 0, 180, 2)
        femm.mi_drawarc(-fine_r, 0, fine_r, 0, 180, 2)
        boundary_r = 3 * fine_r

        # Past that, just treat everything as open air.
        femm.mi_makeABC(7, boundary_r, 0, 0, 0)

        # LABEL REGIONS

        core_middle_r = (
            self.inner_radius + self.outer_radius
        ) / 2  # Distance from the center of the system to the middle of the core
        core_mesh = self.core_thickness / 12  # at least 12 points inside the core

        # Label the central conductor
        self.label_region(
            0,
            0,
            "Copper",  # The conductor we have been given is made of aluminium
            CONDUCTOR_DIAMETER / 10,  # At least 10 points inside the conductor.
            circuit="Line",  # Its part of its own circuit
            turns=1,  # Acts as a single turn primary.
        )

        # Label the air
        self.label_region(
            -(conductor_r_mm + self.inner_radius) / 2,
            0,  # left side, between the conductor and the core, clear of the coil
            "Air",
            1.0,
            # Its not part of a circuit so we dont need a circuit or turns parameter.
        )

        # Right side of the core
        self.label_region(core_middle_r, 0, CORE_MATERIAL, core_mesh)
        # Left side of the core
        self.label_region(-core_middle_r, 0, CORE_MATERIAL, core_mesh)

        # Labelling the air in between the gaps of the sides of the core. We are using a finer mesh here to increase accuracy.

        self.label_region(
            0,
            core_middle_r,  # Top gap
            "Air",
            self.CORE_GAP / 4,
        )
        self.label_region(
            0,
            -core_middle_r,  # Bottom gap
            "Air",
            self.CORE_GAP / 4,
        )

        # Label coil regions
        self.label_region(
            coil_in_inner + self.COIL_THICKNESS / 2,
            0,
            "Air",  # Kind of a hack. For now we dont care about there being current through here, we care about the flux linkage.
            # Therefore, we set this as air (so there is no current)
            # And make this a single turn coil
            # We then multiply the flux linkage by the number of turns later
            circuit="Coil",
            mesh_size_mm=self.COIL_THICKNESS / 3,
            turns=1,  # outgoing side of the turn
        )

        self.label_region(
            coil_out_inner + self.COIL_THICKNESS / 2,
            0,
            "Air",
            circuit="Coil",
            mesh_size_mm=self.COIL_THICKNESS / 3,
            turns=-1,  # return side of the turn
        )

        self.label_region(-(coil_out_outer + fine_r) / 2, 0, "Air", 2.0)  # near air
        self.label_region(-(fine_r + boundary_r) / 2, 0, "Air", 0)  # far air

        print("> Model Constructed.")

        print("> Harvester mass:")
        print(f"    Core: {self.core_mass:.2f} kg")
        print(f"    Coil: {self.coil_mass():.2f} kg")

        # Save to file
        femm.mi_saveas(wine_path(WORK_DIR / "harvester_simple.fem"))

    def flux_per_turn(self, net_ampere_turns):
        """
        Solve the model and return the flux through one coil turn [Wb].

        Use net_ampere_turns instead of just amps because FEMM gives back flux linkage. The flux linkage of a single turn coil is just the flux through the coil, which we can scale later.
        """

        print("> Solving for flux...")

        femm.mi_modifycircprop("Line", 1, net_ampere_turns)  # 1 = set current

        for _attempt in range(3):  # Sometimes FEMM is annoying.
            femm.mi_analyze(1)  # mesh and solve (1 = keep FEMM window minimised)
            femm.mi_loadsolution()  # open the result in FEMM's postprocessor
            # Returns [current, voltage, flux linkage]. A 1-turn coil's flux
            # linkage is the flux through one turn.
            result = femm.mo_getcircuitproperties("Coil")
            femm.mo_close()
            if len(result) == 3:
                return abs(result[2])
            # Under Wine, pyFEMM occasionally reads an empty reply; just retry.
        raise RuntimeError("FEMM did not return a result")

    def compute_flux_curve(self):
        """
        Compute the flux curve.

        We use a geometric scale because the curve is steep at low flux, but
        flattens out as the steel goes closer to saturation.
        """

        peak_line_current = 1.4142135624 * self.LINE_CURRENT

        # magnetomotive force, measured in ampere-turns.
        mmf = np.geomspace(0.5, 3 * peak_line_current, 20)

        # Magnetic flux
        flux = np.array([self.flux_per_turn(f) for f in mmf])

        # Add (0,0) (i.e. zero current, zero flux)
        mmf = np.concatenate([-mmf[::-1], [0.0], mmf])
        flux = np.concatenate([-flux[::-1], [0.0], flux]) / self.CORE_LENGTH

        print("> Flux and MMF curves computed.")
        return mmf, flux

    def label_region(self, x, y, material, mesh_size_mm, circuit="<None>", turns=0):
        """
        This helper function helps to label the regions of the system with their material and mesh size.

        Given a point (x,y) inside a CLOSED region it will apply material, mesh size, and circuit to it.

        Material affects its material properties, mesh size affects the precision in that region, and circuit influences how that region is connected electrically to others.
        """
        femm.mi_addblocklabel(x, y)
        femm.mi_selectlabel(x, y)
        auto_mesh = 1 if mesh_size_mm == 0 else 0
        # arguments: material, automesh, meshsize, circuit, magnet direction, group number, number of turns
        femm.mi_setblockprop(material, auto_mesh, mesh_size_mm, circuit, 0, 0, turns)
        femm.mi_clearselected()

    def coil_geometry(self):
        """
        Return mean turn length [m], copper area per turn [m^2], and volume [m^3].
        """
        # A turn goes through the planar model depth twice, and crosses the
        # radial core thickness twice. Convert the resulting length from mm.
        mean_turn_length = (
            2 * self.CORE_LENGTH + 2 * (self.outer_radius - self.inner_radius)
        ) * 1e-3

        # The winding window is the annular sector occupied by one side of the
        # coil. Its copper area is shared by all turns.
        r_out = (self.inner_radius - self.INSULATION_THICKNESS) * 1e-3
        r_in = r_out - self.COIL_THICKNESS * 1e-3
        winding_window_area = (
            math.radians(self.coil_span_deg) / 2 * (r_out**2 - r_in**2)
        )
        copper_area_per_turn = FILL_FACTOR * winding_window_area / self.COIL_TURNS

        total_wire_length = self.COIL_TURNS * mean_turn_length
        copper_volume = total_wire_length * copper_area_per_turn
        return mean_turn_length, copper_area_per_turn, copper_volume

    def coil_resistance(self):
        mean_turn_length, wire_area, _ = self.coil_geometry()
        total_wire_length = self.COIL_TURNS * mean_turn_length
        return COPPER_RESISTIVITY * total_wire_length / wire_area

    def coil_mass(self):
        _, _, copper_volume = self.coil_geometry()
        return COPPER_DENSITY * copper_volume

    def simulate_circuit(
        self, mmf_curve, flux_curve, v_out, coil_resistance, cycles=3, steps=6000
    ):
        print("> Beginning circuit simulation...")

        dt = 1 / LINE_FREQUENCY * (cycles / steps)  # time step in seconds
        omega = 2 * math.pi * LINE_FREQUENCY

        peak_line_current = math.sqrt(2) * self.LINE_CURRENT

        phi = 0.0
        coil_current = 0.0
        delivered_energy = 0.0
        coil_loss = 0.0
        phi_peak = 0.0

        waves = []

        # Only measure from the first step of the last cycle
        # We do this to make sure the system has reached a steady state before we start measuring.
        first_measured_step = (steps / cycles) * (cycles - 1)

        for step in range(1, steps + 1):
            t = step * dt
            line_current = peak_line_current * math.sin(omega * t)

            # Free flux through the coil
            free_flux = np.interp(line_current, mmf_curve, flux_curve)

            threshold_voltage = (
                v_out + 2 * DIODE_DROP + coil_resistance * abs(coil_current)
            )

            max_possible_flux_change = threshold_voltage / self.COIL_TURNS * dt

            if abs(free_flux - phi) <= max_possible_flux_change:
                phi = free_flux
                coil_current = 0
            else:
                # Rectifier turns on
                phi += math.copysign(max_possible_flux_change, free_flux - phi)
                net_mmf = np.interp(phi, flux_curve, mmf_curve)
                coil_current = (line_current - net_mmf) / self.COIL_TURNS

            if step > first_measured_step:
                delivered_energy += v_out * abs(coil_current) * dt
                coil_loss += coil_resistance * abs(coil_current) ** 2 * dt
                phi_peak = max(phi_peak, phi)
                waves.append((t, line_current, coil_current, phi))

        period = 1 / LINE_FREQUENCY

        print("> Circuit Simulation Complete.")

        return delivered_energy / period, coil_loss / period, phi_peak, np.array(waves)

    def polar(self, r, angle_deg):
        """
        Helper function for polar coordinates
        (x, y) of a point at radius r and angle angle_deg (0 = along +x).
        """
        a = math.radians(angle_deg)
        return r * math.cos(a), r * math.sin(a)

    def flux_cache_file(self):
        """
        Disk cache file for this geometry's flux curve.

        Named by everything that changes the FEMM model, so a killed or
        restarted sweep (or another process) reuses curves instead of
        re-solving them. CORE_LENGTH is left out: the curve is per mm.

        THIS FUNCTION WAS WRITTEN BY AN LLM
        """
        inputs = {
            "inner_radius": self.inner_radius,
            "outer_radius": self.outer_radius,
            "coil_thickness": self.COIL_THICKNESS,
            "line_current": self.LINE_CURRENT,
            "core_gap": self.CORE_GAP,
            "insulation_thickness": self.INSULATION_THICKNESS,
            "coil_span_deg": self.coil_span_deg,
            "conductor_diameter": CONDUCTOR_DIAMETER,
            "core_material": CORE_MATERIAL,
        }
        # 25 and 25.0 must name the same file
        inputs = {
            k: v if isinstance(v, str) else float(v) for k, v in inputs.items()
        }
        digest = hashlib.sha1(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        return FLUX_CACHE_DIR / f"{digest[:16]}.json", inputs

    def load_flux_curve(self):
        """
        Load the flux curve from cache.

        THIS FUNCTION WAS WRITTEN BY AN LLM
        """
        path, _ = self.flux_cache_file()
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return np.array(data["mmf"]), np.array(data["flux_per_mm"])

    def save_flux_curve(self, mmf, flux_per_mm):
        """
        Save flux curve to cache

        THIS FUNCTION WAS WRITTEN BY AN LLM
        """
        path, inputs = self.flux_cache_file()
        FLUX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(
            {"inputs": inputs, "mmf": mmf.tolist(), "flux_per_mm": flux_per_mm.tolist()}
        ))
        os.replace(tmp, path)  # atomic, so a killed process never leaves half a file

    def run_simulation(self):
        # make the working directory if it doesnt already exist
        WORK_DIR.mkdir(exist_ok=True)

        key = (
            self.inner_radius,
            self.outer_radius,
            self.COIL_THICKNESS,
            self.LINE_CURRENT,
        )

        if key not in self.simulation_cache:
            cached = self.load_flux_curve()
            if cached is None:
                try:
                    self.build_model()
                    cached = self.compute_flux_curve()
                finally:
                    femm.closefemm()
                self.save_flux_curve(*cached)
            self.simulation_cache[key] = cached

        mmf_curve, flux_curve_per_mm = self.simulation_cache[key]
        flux_curve = flux_curve_per_mm * self.CORE_LENGTH

        power, coil_loss, phi_peak, waves = self.simulate_circuit(
            mmf_curve, flux_curve, BATTERY_VOLTAGE, self.coil_resistance()
        )

        return power, coil_loss, phi_peak, waves


def sweep_key(result):
    """
    The parameters that define a unique sweep result.

    Technically this model could be made more accurate by computing different
    numbers of turns and different core lengths directly, because the results
    are very close to just scaling with those two, we dont recompute the flux
    curve for them.

    This function takes a result, and computes the key for it. This is then used
    to check if an equivalent cross section has already been computed, and if so
    we just grab that flux curve instead of recomputing it.

    This is a compromise I am willing to make if it means speeding up the simulation by a factor of like 20.
    """
    return tuple(
        round(float(result[column]), 6)
        for column in (
            "inner_radius",
            "outer_radius",
            "core_length",
            "coil_thickness",
            "coil_turns",
            "line_current",
            "core_gap",
            "battery_voltage",
        )
    )


def load_progress(progress_file):
    """
    Results already saved by an earlier (perhaps interrupted) sweep.

    THIS FUNCTION WAS WRITTEN BY AN LLM
    """
    if not progress_file.exists():
        return []
    with open(progress_file, newline="") as f:
        return [
            {name: float(value) for name, value in row.items()}
            for row in csv.DictReader(f)
        ]


def save_progress(progress_file, result):
    """
    Append one result and force it to disk, so a crash loses at most one.

    THIS FUNCTION WAS WRITTEN BY AN LLM
    """
    new_file = not progress_file.exists()
    with open(progress_file, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(result))
        if new_file:
            writer.writeheader()
        writer.writerow(result)
        f.flush()
        os.fsync(f.fileno())


def run_sweep(
    inner_radii,
    core_thicknesses,
    core_lengths,
    coil_thicknesses,
    coil_turns,
    results_file="parameter_sweep_results.csv",
):
    """
    Simulate every feasible combination of the given ranges.
    """
    simulator = harvestersim()
    WORK_DIR.mkdir(exist_ok=True)

    # Every simulated design is appended here as soon as it finishes. Re-running
    # the sweep skips designs already in this file for the same line current,
    # gap and battery voltage. Delete it to start from scratch, e.g. after
    # changing the core material or diode drop.
    progress_file = WORK_DIR / "parameter_sweep_progress.csv"
    saved_results = load_progress(progress_file)

    best_design = None
    best_power = -math.inf
    results = []

    # Designs that do not fit around the conductor or exceed the configured
    # mass limit are discarded.
    minimum_inner_radius = (
        CONDUCTOR_DIAMETER / 2 + simulator.CLEARANCE_MM + simulator.INSULATION_THICKNESS
    )
    candidate_geometries = []

    for inner_radius in inner_radii:
        if inner_radius <= minimum_inner_radius:
            continue

        for core_thickness in core_thicknesses:
            for core_length in core_lengths:
                for coil_thickness in coil_thicknesses:
                    # Four nested for loops. Are you starting to see why this takes so long?

                    if (
                        coil_thickness + simulator.INSULATION_THICKNESS
                        >= inner_radius - CONDUCTOR_DIAMETER / 2
                    ):
                        continue

                    for turns in coil_turns:
                        # We are now five nested for loops deep. In python.
                        simulator.inner_radius = float(inner_radius)
                        simulator.outer_radius = float(inner_radius + core_thickness)
                        simulator.CORE_LENGTH = float(core_length)
                        simulator.COIL_THICKNESS = float(coil_thickness)
                        simulator.COIL_TURNS = turns
                        simulator.recompute_dependants()

                        total_mass = simulator.core_mass + simulator.coil_mass()
                        if total_mass <= MAX_MASS:
                            candidate_geometries.append(
                                (
                                    float(inner_radius),
                                    float(core_thickness),
                                    float(core_length),
                                    float(coil_thickness),
                                    turns,
                                    total_mass,
                                )
                            )

    total_candidates = len(candidate_geometries)
    print(f"> {total_candidates} feasible candidate geometries")

    # Pick up results saved by an earlier run with the same operating point
    operating_point = {
        "line_current": simulator.LINE_CURRENT,
        "core_gap": simulator.CORE_GAP,
        "battery_voltage": BATTERY_VOLTAGE,
    }
    done = {}

    for result in saved_results:
        if all(result[k] == v for k, v in operating_point.items()):
            done[sweep_key(result)] = result
    if done:
        print(f"> Resuming: {len(done)} designs already saved in {progress_file}")

    for count, candidate in enumerate(candidate_geometries, start=1):
        (
            inner_radius,
            core_thickness,
            core_length,
            coil_thickness,
            turns,
            total_mass,
        ) = candidate

        print(
            f"\r> Simulating candidate {count}/{total_candidates} "
            f"({count / total_candidates:.1%})",
            end="",
            flush=True,
        )

        geometry = {
            "inner_radius": inner_radius,
            "outer_radius": inner_radius + core_thickness,
            "core_length": core_length,
            "coil_thickness": coil_thickness,
            "coil_turns": turns,
        }
        saved = done.get(sweep_key(geometry | operating_point))
        if saved is not None:
            result = saved
        else:
            simulator.inner_radius = inner_radius
            simulator.outer_radius = inner_radius + core_thickness
            simulator.CORE_LENGTH = core_length
            simulator.COIL_THICKNESS = coil_thickness
            simulator.COIL_TURNS = turns
            simulator.recompute_dependants()

            try:
                power, coil_loss, phi_peak, _ = simulator.run_simulation()
            except (RuntimeError, ValueError) as error:
                print(f"\n> Skipping failed design: {error}")
                continue

            result = {
                "power": power,
                "coil_loss": coil_loss,
                "phi_peak": phi_peak,
                "mass": total_mass,
                **geometry,
                **operating_point,
            }
            save_progress(progress_file, result)

        power = result["power"]
        results.append(result)

        if power > best_power:
            best_power = power
            best_design = result
            print(f"\n> New best design: {best_design}")

    if best_design is None:
        raise RuntimeError("No feasible design was found below the mass limit")

    print(f"\nHighest-power design below {MAX_MASS:.3g} kg:")
    for name, value in best_design.items():
        print(f"    {name}: {value}")

    results.sort(key=lambda result: result["power"], reverse=True)
    with open(WORK_DIR / results_file, "w") as output:
        columns = list(results[0])
        output.write(",".join(columns) + "\n")
        for result in results:
            output.write(",".join(str(result[column]) for column in columns) + "\n")

    return best_design


if __name__ == "__main__":
    # Sweep core and winding dimensions.
    # This *does* work. However it takes ~10 hours to run.
    # This is less true if you keep inner_radii and core_thicknesses small, as
    # the simulation time for an individual core scales exponentially with the
    # area of the core cross section, but for anything actually useful they have
    # to be somewhat big.
    run_sweep(
        inner_radii=np.arange(20.0, 30.0, 4.0),
        core_thicknesses=np.arange(10.0, 36.0, 4.0),
        core_lengths=np.arange(5.0, 60.0, 5.0),
        coil_thicknesses=np.arange(1.0, 10.0, 1.0),
        coil_turns=range(25, 201, 25),
    )
