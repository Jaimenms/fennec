"""Tabular summaries of one or several results (pandas)."""

from __future__ import annotations

from typing import Dict, Mapping

from ..model import SmartHome
from ..results import Results


def describe(home: SmartHome) -> "pandas.DataFrame":
    """One row per asset of a house: kind, name and the main parameters."""
    import pandas as pd

    rows = []
    for asset in home.all_assets:
        row = {"asset": asset.name, "kind": asset.kind}
        for attr in ("capacity_kwh", "max_charge_kw", "max_discharge_kw", "soc_initial", "soc_min", "soc_max"):
            if hasattr(asset, attr):
                row[attr] = getattr(asset, attr)
        if hasattr(asset, "controller"):
            row["controller"] = asset.controller.describe()
        if hasattr(asset, "total_kwh"):
            row["total_kwh"] = round(asset.total_kwh, 2)
        if asset.kind == "grid":
            row["import_tariff"] = asset.import_tariff.name
            row["export_tariff"] = asset.export_tariff.name
            row["contracted_power_kw"] = asset.contracted_power_kw
        rows.append(row)
    return pd.DataFrame(rows).set_index("asset")


def energy_balance(results: Results) -> "pandas.DataFrame":
    """Total kWh injected into and absorbed from the house by every asset over the horizon."""
    import pandas as pd

    rows = []
    for name, kind in results.kinds.items():
        cols = results.data.get(name, {})
        if "energy" in cols:
            total = results.total(name, "energy")
            injected, absorbed = (total, 0.0) if kind == "pv" else (0.0, total)
        else:
            injected, absorbed = results.total(name, "energy_from"), results.total(name, "energy_to")
        rows.append(
            {
                "asset": name,
                "kind": kind,
                "to_house_kwh": round(injected, 3),
                "from_house_kwh": round(absorbed, 3),
                "cost": round(results.cost(name), 4) if "cost" in cols else 0.0,
            }
        )
    return pd.DataFrame(rows).set_index("asset")


def compare(results_by_label: Mapping[str, Results], reference: str | None = None) -> "pandas.DataFrame":
    """
    One row per scenario with status, bill (grid cost), value of the energy gained in the batteries,
    objective, import/export and commands. With ``reference`` the saving of the objective relative to that
    scenario is added; the objective is the right thing to compare because it accounts for the energy left
    in the batteries.
    """
    import pandas as pd

    rows: Dict[str, Dict[str, object]] = {}
    for label, res in results_by_label.items():
        s = res.summary()
        row = {
            "status": s["status"],
            "bill": round(s.get("grid_cost", float("nan")), 4),
            "stored_value": round(res.stored_value(), 4) if res.terminal else 0.0,
            "objective": round(s["objective"], 4) if s["objective"] is not None else None,
            "import_kwh": round(s.get("grid_import_kwh", float("nan")), 2),
            "export_kwh": round(s.get("grid_export_kwh", float("nan")), 2),
            "solve_s": s["solve_seconds"],
        }
        final = [v for k, v in s.items() if k.endswith("_final_soc")]
        if final:
            row["final_soc"] = round(sum(final) / len(final), 1)
        commands = [v for k, v in s.items() if k.endswith("_commands") and v is not None]
        if commands:
            row["commands"] = int(round(sum(commands)))
        rows[label] = row
    frame = pd.DataFrame.from_dict(rows, orient="index")
    if reference is not None and reference in frame.index:
        base = frame.loc[reference, "objective"]
        frame["saving"] = (base - frame["objective"]).round(4)
        frame["saving_pct"] = ((base - frame["objective"]) / base * 100).round(1)
    return frame
