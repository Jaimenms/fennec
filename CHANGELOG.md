# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - Unreleased

A rewrite of the package around a device-agnostic core, plus a real-time optimizer daemon.

### Added

- `Asset` interface: any device adds a Pyomo block exposing `energy_from`, `energy_to` and `cost` per
  step, and optionally a scalar `terminal_cost`; `SmartHome` only writes the balance and the objective.
- Battery controllers as pluggable brand behaviour: `IdealController` (free dispatch, a benchmark) and
  `HuaweiLuna2000Controller`, whose self-consumption mode is written as complementarity conditions at
  the grid meter and proven against a rule-based simulation of the inverter; forced mode with
  continuous setpoints; command accounting with `max_commands`, `command_penalty`, `initial_mode` and
  initial setpoints.
- `Horizon` with steps of different lengths, `Horizon.rolling()` (15 min for six hours, then hourly,
  aligned to settlement boundaries), tariff averaging and simulator integration inside coarse steps.
- Terminal value of the energy left in a battery (`Battery.terminal_value`, default the cheapest import
  price of the horizon) so that plans are comparable without draining the battery; `soc_final_min` kept
  as a hard reserve.
- `ElectricVehicle` with availability from a daily trip, SOC on return, soft SOC targets, on/off or
  modulated charger, command limits and `charge_on_arrival()` as the reference profile of a dumb charger.
- `Results` with status, MIP gap, time series per asset, running and terminal costs, pandas access.
- Translation of plans into device commands (`Command`, `controller.commands()`, `vehicle.commands()`).
- Scenarios as JSON (`fennec.scenario`) and the `python -m fennec` command line.
- `fennec.utils`: `describe`, `energy_balance`, `compare`, `plot_dispatch`, `plot_comparison`,
  `plot_profiles` (optional `viz` extra with pandas and matplotlib).
- Built-in Porto house scenarios (`fennec.examples`) and four executed notebooks.
- `fennec.rto`, the real-time optimizer daemon: JSON-lines message contract with an external connector,
  per-signal deadlines with a fault state and safe commands, replanning at settlement boundaries and on
  events, MIP warm start between replans, rolling daily command budget, forecasts delivered by the
  connector or learned from the audit file, TCP / Unix socket transport, a digital twin for closed-loop
  tests.
- `deploy/`: systemd unit and Raspberry Pi installation notes. `connectors/home_assistant/`: an example
  connector outside the package.
- Test suite of 86 tests (95% line and branch coverage) and `scripts/coverage_badge.py`.

### Changed

- `SmartHome` is built from typed Python objects into a `ConcreteModel`; the `AbstractModel` with a
  nested data dictionary is gone.
- `Tariff` and `Schedule` are frozen dataclasses (`start`, `end`, `price`, `weekdays`), with
  `Tariff.flat()`, `Tariff.none()`, a timezone and a default price; the Portuguese presets live in
  `fennec.tariffs.presets`.
- Simulators take a `Horizon` (`simulate_pv_energy`, `simulate_house_load_energy`).
- `pyproject.toml`: version 0.2.0, `viz` extra, dev dependency group, `fennec` console script, pytest
  path and warning filters; `.coveragerc` targets `src/fennec`.
- README rewritten: concepts, assets, controllers, results, JSON scenarios, daemon, extension points.

### Fixed

- Self-consumption mode ignored power and SOC saturation and the model had no constraint tying the two
  mode flags, so the optimizer could leave the battery in a mode that does not exist.
- Import and export tariffs were swapped in the examples; a trailing comma turned the surplus and
  deficit series into tuples and the battery example did not load.
- The tri-hourly weekly tariff had overlapping windows (the 19:30 peak never applied) and the tri-hourly
  tariffs carried the bi-hourly name.
- The vehicle controller added the SOC target penalty at every step instead of once, shadowed its loop
  variable, and let the optimizer choose the car's energy exchanged away from home.
- The command line read `args.file` instead of `args.input`; results without a solution crashed the summary.
- Battery efficiencies defaulting to zero caused a division by zero; the last step of the horizon was
  not bounded by the SOC window.

### Removed

- `fennec/blocks/`, `fennec/models/`, `fennec/fennec.py`, `fennec/examples/example_0*.py`, the old
  study notebooks, `src/fennec/README.md`, `docs/pdfs/` and the `coverage-badge` dependency.

## [0.1.0] - 2025-04-06

Initial release.

- Pyomo `AbstractModel` of a smart home with blocks for the grid connection, fixed nodes (PV and load),
  a stationary battery with a controller (self-consumption and arbitrage modes), and an electric vehicle
  with a charging controller, solved with HiGHS through `appsi`.
- Portuguese low-voltage tariff presets (simple, bi-hourly and tri-hourly, daily and weekly cycles).
- Synthetic PV production (pysolar, clear sky) and household load simulators.
- Three runnable examples and the study notebooks that led to the formulation.

[0.2.0]: https://github.com/Jaimenms/fennec/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Jaimenms/fennec/releases/tag/v0.1.0
