"""Helpers for notebooks and reports: tables (pandas) and figures (matplotlib). Both are optional deps."""

from .report import compare, energy_balance, describe
from .plotting import plot_dispatch, plot_comparison, plot_profiles

__all__ = ["compare", "energy_balance", "describe", "plot_dispatch", "plot_comparison", "plot_profiles"]
