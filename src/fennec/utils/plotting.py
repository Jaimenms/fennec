"""
Figures for notebooks and reports (matplotlib).

Colors follow the entity, never the rank: the grid is always blue/orange, PV yellow, load violet, battery
aqua/magenta, EV green. Marks are thin, axes recessive, one y-axis per panel.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..results import Results

# Reference categorical palette (validated for color-vision deficiency on a light surface).
PALETTE = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
    "violet": "#6250d6",
    "red": "#e34948",
}
COLORS = {
    "import": PALETTE["blue"],
    "export": PALETTE["orange"],
    "pv": PALETTE["yellow"],
    "load": PALETTE["violet"],
    "charge": PALETTE["aqua"],
    "discharge": PALETTE["magenta"],
    "ev": PALETTE["green"],
    "soc": PALETTE["blue"],
    "cost": PALETTE["red"],
    "band": "#d9d9d6",  # mode / availability shading
    "grid": "#e6e6e3",
    "ink": "#52514e",
}


def _style(ax, ylabel: str, title: Optional[str] = None) -> None:
    ax.set_ylabel(ylabel, color=COLORS["ink"])
    if title:
        ax.set_title(title, loc="left", fontsize=10, color=COLORS["ink"])
    ax.grid(True, axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.grid(False, axis="x")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["ink"], labelsize=8)
    ax.margins(x=0)


def _legend(ax) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if len(labels) >= 2:
        ax.legend(loc="upper left", frameon=False, fontsize=8, ncol=len(labels))


def _band(ax, times, flags: Sequence[Optional[float]], label: str) -> None:
    """Shade the steps where ``flags`` is 1 (mode on, car away, ...)."""
    import matplotlib.dates as mdates

    step = times[1] - times[0] if len(times) > 1 else None
    start = None
    for i, flag in enumerate(list(flags) + [0]):
        on = flag is not None and flag > 0.5
        if on and start is None:
            start = times[i]
        if not on and start is not None:
            end = times[i] if i < len(times) else times[-1] + step
            ax.axvspan(mdates.date2num(start), mdates.date2num(end), color=COLORS["band"], alpha=0.6, lw=0, zorder=0)
            start = None
    ax.plot([], [], color=COLORS["band"], lw=6, label=label)


def _commands(ax, times, flags: Sequence[Optional[float]]) -> None:
    """A tick near the top of the panel at every step where a command is sent to the device."""
    from matplotlib.transforms import blended_transform_factory

    marks = [t for t, c in zip(times, flags) if c is not None and c > 0.5]
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    ax.plot(
        marks,
        [0.93] * len(marks),
        ls="none",
        marker="v",
        ms=6,
        color=COLORS["ink"],
        transform=trans,
        label=f"command ({len(marks)})",
        clip_on=False,
    )


def _steps(ax, times, values, label, color, **kw):
    clean = [float("nan") if v is None else v for v in values]
    ax.step(times, clean, where="post", lw=1.8, color=color, label=label, **kw)


def plot_profiles(results: Results, ax=None):
    """PV production and load, the two fixed inputs."""
    import matplotlib.pyplot as plt

    ax = ax or plt.subplots(figsize=(11, 2.6))[1]
    times = results.horizon.timestamps
    for name in results.assets("pv"):
        _steps(ax, times, results.column(name, "energy"), f"{name} (PV)", COLORS["pv"])
    for name in results.assets("load"):
        _steps(ax, times, results.column(name, "energy"), f"{name} (load)", COLORS["load"])
    _style(ax, "kWh / step", "PV production and load")
    _legend(ax)
    return ax


def plot_dispatch(results: Results, title: Optional[str] = None, show_prices: bool = True):
    """
    One panel per piece of the house, sharing the time axis: prices, PV and load, grid exchange, then
    SOC and power for every battery (with the self-consumption mode shaded) and every EV (with the
    time away shaded), and the cumulative cost at the bottom.
    """
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    batteries, evs, grids = results.assets("battery"), results.assets("ev"), results.assets("grid")
    n_panels = (1 if show_prices else 0) + 2 + 2 * len(batteries) + 2 * len(evs) + 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(11, 2.0 * n_panels), sharex=True, layout="constrained")
    axes = list(axes)
    times = results.horizon.timestamps
    grid = grids[0] if grids else None
    k = 0

    if show_prices and grid:
        ax = axes[k]
        k += 1
        _steps(ax, times, results.column(grid, "import_price"), "import", COLORS["import"])
        _steps(ax, times, results.column(grid, "export_price"), "export", COLORS["export"])
        _style(ax, "EUR / kWh", "Tariffs")
        _legend(ax)

    plot_profiles(results, axes[k])
    k += 1

    if grid:
        ax = axes[k]
        k += 1
        imp = results.column(grid, "energy_from")
        exp = [-(v or 0.0) for v in results.column(grid, "energy_to")]
        _steps(ax, times, imp, "import", COLORS["import"])
        _steps(ax, times, exp, "export (negative)", COLORS["export"])
        ax.axhline(0, color=COLORS["grid"], lw=0.8)
        _style(ax, "kWh / step", "Grid exchange")
        _legend(ax)

    for name in batteries:
        cols = results.data[name]
        ax = axes[k]
        k += 1
        if "self_consumption" in cols:
            _band(ax, times, cols["self_consumption"], "self-consumption mode")
        _steps(ax, times, cols["soc"], "SOC", COLORS["soc"])
        ax.set_ylim(0, 105)
        _style(ax, "SOC %", f"{name}: state of charge")
        _legend(ax)

        ax = axes[k]
        k += 1
        if "self_consumption" in cols:
            _band(ax, times, cols["self_consumption"], "self-consumption mode")
        _steps(ax, times, cols["energy_to"], "charge", COLORS["charge"])
        _steps(ax, times, [-(v or 0.0) for v in cols["energy_from"]], "discharge (negative)", COLORS["discharge"])
        if "command" in cols:
            _commands(ax, times, cols["command"])
        ax.axhline(0, color=COLORS["grid"], lw=0.8)
        _style(ax, "kWh / step", f"{name}: charge and discharge")
        _legend(ax)

    for name in evs:
        cols = results.data[name]
        away = [0.0 if p else 1.0 for p in cols["plugged"]]
        ax = axes[k]
        k += 1
        _band(ax, times, away, "away")
        _steps(ax, times, cols["soc"], "SOC", COLORS["ev"])
        ax.set_ylim(0, 105)
        _style(ax, "SOC %", f"{name}: state of charge")
        _legend(ax)

        ax = axes[k]
        k += 1
        _band(ax, times, away, "away")
        _steps(ax, times, cols["energy_to"], "charging", COLORS["ev"])
        _commands(ax, times, cols["command"])
        _style(ax, "kWh / step", f"{name}: charging")
        _legend(ax)

    ax = axes[k]
    total, cumulative = 0.0, []
    costs = results.column(grid, "cost") if grid else [0.0] * len(times)
    for c in costs:
        total += c or 0.0
        cumulative.append(total)
    _steps(ax, times, cumulative, "cumulative grid cost", COLORS["cost"])
    ax.annotate(f"{total:.2f} EUR", (times[-1], total), ha="right", va="bottom", fontsize=9, color=COLORS["ink"])
    _style(ax, "EUR", "Cumulative grid cost")

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz=results.horizon.start.tzinfo))
    axes[-1].xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 6)))
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=COLORS["ink"])
    return fig


def plot_comparison(results_by_label: Mapping[str, Results], reference: Optional[str] = None):
    """
    Objective per scenario as horizontal bars (bill minus the value of the energy left in the batteries,
    plus penalties), with the value and the saving against ``reference`` written next to each bar.
    """
    import matplotlib.pyplot as plt

    labels = list(results_by_label)
    costs = [results_by_label[l].objective or 0.0 for l in labels]
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(labels) + 1.2))
    bars = ax.barh(labels[::-1], costs[::-1], color=PALETTE["blue"], height=0.55)
    for bar, cost, label in zip(bars, costs[::-1], labels[::-1]):
        text = f"{cost:.2f} EUR"
        if reference is not None and reference in results_by_label:
            base = results_by_label[reference].objective or 0.0
            if base:
                text += f"  ({(base - cost) / base * 100:+.1f}%)" if label != reference else "  (reference)"
        ax.annotate(
            text,
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=COLORS["ink"],
        )
    ax.set_xlim(0, max(costs) * 1.35 if costs else 1)
    _style(ax, "", "Cost over the horizon (bill net of the energy left in the batteries)")
    ax.grid(True, axis="x", color=COLORS["grid"], linewidth=0.8)
    ax.grid(False, axis="y")
    ax.set_xlabel("EUR", color=COLORS["ink"])
    fig.tight_layout()
    return fig
