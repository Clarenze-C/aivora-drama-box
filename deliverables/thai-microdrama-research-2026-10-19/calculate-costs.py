"""Reproduce the proposal's scenario arithmetic; this is not measured cost data.

Run with python3 calculate-costs.py. Only cost-scenarios.csv is overwritten.
Source prices checked 2026-10-19:
https://platform.minimax.io/docs/pricing/overview
All labor, retry, trimming, services and setup inputs are planning assumptions.
H3 output distribution rights must be resolved independently of these calculations.
"""
from pathlib import Path
from decimal import Decimal as D
import csv

FINISHED_MINUTES = D(4)
EPISODES = D(10)
# name, takes, trim factor, $/sec, prep h/rate, edit h/rate,
# Thai h/rate, ops h/rate, variable services, shared tools, reserve, setup
SCENARIOS = [
    ("low", "1.5", "1.2", ".08", 2, 20, 4, 20, 2, 25, 1, 20, 12, 10, ".10", 300),
    ("base", "3", "1.3", ".08", 5, 30, 10, 30, 3, 35, 2, 30, 30, 20, ".15", 900),
    ("high", "5", "1.5", ".13", 10, 45, 20, 45, 5, 50, 4, 45, 75, 45, ".25", 2500),
]


def calculate():
    rows = []
    for row in SCENARIOS:
        name, takes, trim, rate, ph, pr, eh, er, th, tr, oh, op, var, tools, reserve, setup = row
        generated = FINISHED_MINUTES * 60 * D(takes) * D(trim)
        video = generated * D(rate)
        labor = D(ph * pr + eh * er + th * tr + oh * op)
        episode = (video + labor + D(var + tools)) * (1 + D(reserve))
        rows.append({
            "scenario": name,
            "finished_minutes": str(FINISHED_MINUTES),
            "attempt_multiplier": takes,
            "duration_factor": trim,
            "output_usd_per_second": rate,
            "generated_seconds": str(generated),
            "video_usd": str(video),
            "labor_hours": ph + eh + th + oh,
            "labor_usd": str(labor),
            "variable_services_usd": var,
            "shared_tools_per_episode_usd": tools,
            "contingency_fraction": reserve,
            "episode_usd": f"{episode:.2f}",
            "finished_minute_usd": f"{episode / FINISHED_MINUTES:.2f}",
            "setup_usd": setup,
            "season_10_episodes_usd": f"{episode * EPISODES + D(setup):.2f}",
            "service_only_usd_excluding_labor_setup": f"{(video + D(var + tools)) * (1 + D(reserve)):.2f}",
        })
    return rows


if __name__ == "__main__":
    rows = calculate()
    target = Path(__file__).with_name("cost-scenarios.csv")
    with target.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(f"{row['scenario']}: ${row['episode_usd']}/episode; ${row['season_10_episodes_usd']}/10-episode season")
