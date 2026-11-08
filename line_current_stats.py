"""
Line current on rural New Zealand 11 kV feeders, from metered grid data.

Reads the Electricity Authority's half-hourly grid export data for a grid exit
point (GXP) that supplies rural 11 kV feeders directly, converts the energy in
each half-hour to a line current, and prints its distribution. See
references.md for the source and the caveats.

    uv run python line_current_stats.py
"""

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

DATA_FILE = (
    Path(__file__).resolve().parent / "data" / "grid_export_KIK_MCH_2025-10_2026-09.csv"
)
POC = "KIK0111"  # Kikiwa, Network Tasman: rural, supplied directly at 11 kV
FEEDERS = 3  # outgoing 11 kV feeders at Kikiwa (Network Tasman AMP, 3.1.4)
LINE_VOLTAGE = 11e3  # [V] line to line
POWER_FACTOR = 0.95  # assumed


def line_currents(poc=POC):
    """Return a list of (date, half-hour index, total GXP current [A])."""
    rows = []
    with open(DATA_FILE) as f:
        for row in csv.DictReader(f):
            if row["POC"] != poc or row["Flow_Direction"] != "X":
                continue
            for tp in range(1, 49):
                kwh = row.get(f"TP{tp}")
                if not kwh:
                    continue
                watts = float(kwh) * 2 * 1e3  # kWh per half hour -> W
                amps = watts / (math.sqrt(3) * LINE_VOLTAGE * POWER_FACTOR)
                rows.append((row["Trading_Date"], tp - 1, amps))
    return rows


def percentile(sorted_values, p):
    return sorted_values[int(p * (len(sorted_values) - 1))]


if __name__ == "__main__":
    rows = line_currents()
    total = sorted(a for _, _, a in rows)
    print(f"{POC}: {len(total)} half-hours, pf {POWER_FACTOR}, {FEEDERS} feeders")
    print(f"{'':>16s} {'GXP [A]':>9s} {'per feeder [A]':>15s}")
    for name, p in (("5th percentile", 0.05), ("median", 0.5),
                    ("99th percentile", 0.99), ("maximum", 1.0)):
        value = percentile(total, p)
        print(f"{name:>16s} {value:9.0f} {value / FEEDERS:15.0f}")

    by_hour = defaultdict(list)
    by_month = defaultdict(list)
    for date, half_hour, amps in rows:
        by_hour[half_hour // 2].append(amps / FEEDERS)
        by_month[date[:7]].append(amps / FEEDERS)
    print("\nMean per-feeder current by hour of day [A]:")
    print("  " + "  ".join(f"{h:02d}h {statistics.mean(by_hour[h]):.0f}"
                           for h in range(0, 24, 2)))
    print("Mean per-feeder current by month [A]:")
    print("  " + "  ".join(f"{m} {statistics.mean(v):.0f}"
                           for m, v in sorted(by_month.items())))
