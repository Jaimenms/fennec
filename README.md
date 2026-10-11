# Fennec

![Logo](docs/imgs/logo-small.png)

Fennec schedules the flexible assets of a house (today: stationary batteries and electric vehicles; next:
heat pumps, water heaters, air conditioners) to minimise the electricity bill over a horizon of a few days,
**subject to what the real equipment lets you command**.

That last part is what makes Fennec different from a textbook battery optimizer. A Huawei inverter in
self-consumption mode does not take a power setpoint: it follows its own rule, and the only things you can
change are the operating mode and a handful of forced charge/discharge commands. Fennec models the device
physics once and lets a *controller* object describe each brand's modes and commands, so the optimizer only
produces plans that the equipment can execute.

The optimization is a mixed-integer linear program built with [Pyomo](https://www.pyomo.org/) and solved with
[HiGHS](https://highs.dev/).

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Concepts](#concepts)
- [Assets](#assets)
- [Battery controllers](#battery-controllers)
- [Results and figures](#results-and-figures)
- [Scenarios as JSON and the command line](#scenarios-as-json-and-the-command-line)
- [Real-time optimizer: the daemon](#real-time-optimizer-the-daemon)
- [Extending Fennec](#extending-fennec)
- [Project layout](#project-layout)
- [Development](#development)

## Installation

Fennec needs Python 3.12 or newer. HiGHS ships as a wheel (`highspy`), so there is nothing to compile.

```bash
pip install fennec            # core: pyomo, highspy, pysolar
pip install "fennec[viz]"     # plus pandas and matplotlib for tables and figures
```

From a clone of the repository:

```bash
poetry install --all-extras
```

## Quick start

```python
from datetime import datetime, timezone

from fennec import Horizon, SmartHome, Grid, PVProduction, Load, Battery, HuaweiLuna2000Controller
from fennec.tariffs import import_bi_daily_tariff, export_none_tariff
from fennec.simulators import simulate_pv_energy, simulate_house_load_energy

# 36 hours at 15-minute resolution
horizon = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=1.5)

# inputs: one kWh value per step (here from the built-in simulators; use your own forecasts in practice)
pv = simulate_pv_energy(horizon, area_m2=25, efficiency=0.2, latitude=41.21, longitude=-8.61)
load = simulate_house_load_energy(horizon, area_m2=100, residents=4, longitude=-8.61)

home = SmartHome(
    horizon,
    grid=Grid(import_tariff=import_bi_daily_tariff, export_tariff=export_none_tariff, contracted_power_kw=6.9),
    assets=[
        PVProduction("pv", energy=pv),
        Load("house", energy=load),
        Battery(
            "battery",
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            soc_initial=50, soc_min=10, soc_max=100,
            controller=HuaweiLuna2000Controller(max_commands=4, command_penalty=0.01),
        ),
    ],
)

results = home.solve(time_limit=60)
print(results.summary())
# {'status': 'optimal', 'objective': 5.56, 'grid_cost': 5.51, 'battery_stored_value': -0.03, 'battery_commands': 3.0, ...}

frame = results.frame("battery")   # pandas DataFrame: soc, energy_to, energy_from, self_consumption, command, ...
```

The same scenario is available as `fennec.examples.huawei_battery()`, and the notebooks in `notebooks/` walk
through it step by step.

## Concepts

**Horizon.** `Horizon(start, steps, delta_t)` is a time grid; steps need not be equal:
`Horizon.rolling(now, fine=15 min, fine_hours=6, coarse=1 h, total_hours=36)` runs at 15 minutes for the
next six hours and hourly afterwards, which cuts the number of binaries by two thirds for a rolling
optimizer. Every quantity in the model is an *energy in kWh exchanged during a step*;
`horizon.energy(power_kw, t)` converts a power into the kWh of step `t`, tariffs are averaged inside a
coarse step, and the simulators integrate the power inside each step. Helpers such as
`horizon.within("22:00", "06:00")` and `horizon.first_steps_at("08:00")` turn clock times into step indexes.

**Asset.** Anything that exchanges energy with the house. Each asset adds a block to the Pyomo model exposing,
per step, `energy_from[t]` (kWh injected into the house), `energy_to[t]` (kWh absorbed) and `cost[t]`. The
grid is an asset like the others.

**SmartHome.** A grid plus a list of assets. It writes one constraint and one objective:

```
sum(energy_from[t]) == sum(energy_to[t])      for every step t
minimise sum(cost[t]) over all assets and steps
```

Everything else (SOC dynamics, operating modes, command limits, soft targets) lives inside the assets.

**Controller.** For devices whose behaviour depends on the brand, the physics lives in the asset and the
behaviour in a controller object. `Battery(..., controller=HuaweiLuna2000Controller(...))` is a battery that
behaves like a Huawei; `Battery(..., controller=IdealController())` is the same battery with perfect control,
a benchmark that no real inverter reaches.

**End of the horizon.** A block may also add a scalar `terminal_cost` to the objective for the state the device
is left in. Batteries use it to value the energy they still hold (see `terminal_value` below), otherwise the
optimizer would drain them before the end of the horizon because stored energy is worth nothing to it.

**Results.** `solve()` returns a `Results` with the status, the objective, the MIP gap and one table of time
series per asset. `results.cost()` is the running cost, `results.terminal_cost()` the end-of-horizon terms, and
`results.objective` their sum. A time limit returns the best plan found with its gap; an infeasible problem
returns `status == "infeasible"` and no series.

**Commands.** A plan is energies per step; equipment takes instructions. `controller.commands(results,
battery)` and `vehicle.commands(results)` turn runs of consecutive steps with the same intent into
`Command` objects in the device's own vocabulary (`set_mode self_consumption`, `force_charge 3 kW for 45
min`, `charge on`). Fennec never sends them anywhere: that is the connector's job (see the daemon below).

## Assets

### `Grid`

```python
Grid(import_tariff, export_tariff=Tariff.none(), contracted_power_kw=6.9, export_power_kw=None, settled=None)
```

Import is limited by the contracted power, export by `export_power_kw` (default: the contracted power).
Tariffs are `fennec.tariffs.Tariff` objects: time-of-use prices by clock time and weekday (`Tariff.flat(0.2)`,
`Tariff.none()`, or the Portuguese presets `import_simple_tariff`, `import_bi_daily_tariff`,
`import_tri_daily_tariff`, `import_bi_weekly_tariff`, `import_tri_weekly_tariff`). Importing and exporting in
the same step is forbidden with a binary only when some step has an export price at least as high as the import
price (`settled=None`); force it with `settled=True`.

### `PVProduction` and `Load`

Fixed profiles: `PVProduction("pv", energy=[...])` injects, `Load("house", energy=[...])` absorbs, one kWh per
step, no decisions. Any inflexible device is a `Load`.

### `Battery`

```python
Battery(name, capacity_kwh, max_charge_kw, max_discharge_kw,
        soc_initial=50, soc_min=0, soc_max=100,
        charge_efficiency=0.95, discharge_efficiency=0.95,
        controller=IdealController(), soc_required={}, soc_final_min=None,
        terminal_value="min_import_price")
```

`soc[t]` is the state of charge (%) at the start of step `t`, `soc_end[t]` at its end, and both stay inside
`[soc_min, soc_max]` (the Huawei "end-of-discharge SOC" and "charge cutoff SOC"). Charging and discharging never
happen in the same step. `soc_required` maps steps to minimum SOCs (a reserve before an outage) and
`soc_final_min` is a hard minimum at the end of the horizon.

`terminal_value` prices the energy left in the battery at the end of the horizon: the objective receives
`-price * (usable kWh at the end - usable kWh at the start)`, where usable kWh is what the battery can deliver
above `soc_min` after the discharge efficiency. Draining the battery is therefore paid for, filling it is
credited, and a plan that ends where it started has an objective equal to its bill. The price can be a number
(currency per kWh), `"min_import_price"` (the default: the cheapest import price of the horizon, which makes
buying energy at that price to store it neutral and never rewards hoarding), `"mean_import_price"`, or `None`
to disable the valuation. `results.stored_value("battery")` reports the value gained over the horizon.

### `ElectricVehicle`

```python
plugged, returns = ElectricVehicle.daily_trip(horizon, leave="08:30", back="18:00", soc_on_return=40)
ElectricVehicle("car", capacity_kwh=40, max_charge_kw=3.7, plugged=plugged,
                soc_initial=40, soc_on_return=returns,
                soc_target={t: 80 for t in horizon.first_steps_at("08:00")}, target_penalty=0.5,
                modulated=False, max_commands=6, command_penalty=0.001)
```

The car charges only while `plugged[t]` is true; while it is away its SOC is not tracked, and on return it is set
to `soc_on_return[t]`. `soc_target` is a *soft* constraint: missing percentage points cost `target_penalty` each,
so an unreachable target does not make the problem infeasible. The charger is on/off at full power unless
`modulated=True`. Every change of the charger setpoint is a command. `charge_on_arrival()` returns the profile
of a dumb charger, the natural reference to measure the saving of optimizing the car.

## Battery controllers

### `IdealController`

No restrictions, no cost. Use it as the lower bound: the difference between the ideal and a brand controller is
what the brand's restrictions cost.

### `HuaweiLuna2000Controller`

```python
HuaweiLuna2000Controller(max_commands=100, command_penalty=0.0, mode="optimize", initial_mode=None)
```

Models a SUN2000 hybrid inverter with LUNA2000 batteries. At every step the inverter is in one of two modes:

- **Self consumption.** The inverter runs its own greedy rule and the optimizer has no say on the power: PV
  surplus charges the battery and load deficit is covered by the battery, each saturated by the power limit and
  by the SOC window. Writing that rule with `min()` operators would be non-linear, so Fennec writes it as
  complementarity conditions measured at the grid meter, which is what the inverter sees:
  the battery never charges while the house imports and never discharges while it exports; the house only
  imports if the discharge is saturated (power limit, or battery empty at the end of the step); the house only
  exports if the charge is saturated (power limit, or battery full at the end of the step). The unit tests check
  that, with the mode pinned to self consumption, the MILP reproduces a step-by-step simulation of the rule
  exactly.
- **Forced.** The charge and discharge setpoints (fraction of the power limit) are decision variables, as with a
  forcible charge/discharge command. Grid charging is allowed.

Any change of mode or of a setpoint between consecutive steps is one **command**, limited by `max_commands` and
penalised by `command_penalty`. Both default to "unlimited and free", which lets the solver toggle setpoints at no
cost when it makes no difference to the bill; set a small penalty (0.001) to get tidy plans. `mode="self_consumption"` reproduces the inverter left alone, `mode="forced"` a
fully commanded battery, and `initial_mode` tells the optimizer which mode the inverter is in before the first
step so that changing it counts as a command.

Known simplifications: the forced branch is a free dispatch within the limits (a real forcible charge holds one
power for a duration, and TOU windows behave differently), and the SOC saturation is evaluated at the end of each
step. Because the energy left in the battery is valued (see `terminal_value`), an inverter left alone and an
optimized schedule are compared on the same footing even when they end at different SOCs.

## Results and figures

```python
results.status, results.objective, results.gap, results.solve_seconds
results.summary()                      # headline numbers
results.column("battery", "soc")       # one list per asset column
results.frame()                        # pandas, all assets, "<asset>.<column>" columns
results.frame("grid")                  # pandas, one asset
```

With the `viz` extra, `fennec.utils` has the helpers used by the notebooks:

```python
from fennec.utils import describe, energy_balance, compare, plot_dispatch, plot_comparison, plot_profiles

describe(home)                         # one row per asset with its parameters
energy_balance(results)                # kWh injected / absorbed and cost per asset
compare({"baseline": r0, "battery": r1}, reference="baseline")   # bill, stored value, objective, saving
plot_dispatch(results, title="...")    # prices, PV and load, grid, SOC and power per asset, cumulative cost
plot_comparison({"baseline": r0, "battery": r1}, reference="baseline")
```

The notebooks in `notebooks/` are executed and show the figures:

| Notebook | What it shows |
|---|---|
| `01_house_baseline.ipynb` | the house without flexible assets, the inputs and the reference cost |
| `02_huawei_battery.ipynb` | inverter alone vs optimized vs ideal, and how many commands are worth sending |
| `03_electric_vehicle.ipynb` | an EV with a daily trip against a charger that charges on arrival |
| `04_battery_and_vehicle.ipynb` | both assets together |

## Scenarios as JSON and the command line

A scenario can be a plain dictionary (see `fennec.scenario` for the full format):

```json
{
  "horizon": {"start": "2025-03-22T00:00:00+00:00", "days": 1.5, "step_minutes": 15},
  "grid": {"contracted_power_kw": 6.9, "import_tariff": "bi_daily", "export_tariff": "none"},
  "assets": [
    {"type": "pv", "name": "pv",
     "simulate": {"area_m2": 25, "efficiency": 0.2, "latitude": 41.21, "longitude": -8.61}},
    {"type": "load", "name": "house", "simulate": {"area_m2": 100, "residents": 4, "longitude": -8.61}},
    {"type": "battery", "name": "battery", "capacity_kwh": 10, "max_charge_kw": 5, "max_discharge_kw": 5,
     "soc_initial": 50, "soc_min": 10, "terminal_value": "min_import_price",
     "controller": {"type": "huawei", "max_commands": 4, "command_penalty": 0.01}},
    {"type": "ev", "name": "car", "capacity_kwh": 40, "max_charge_kw": 3.7,
     "daily_trip": {"leave": "08:30", "back": "18:00", "soc_on_return": 40},
     "soc_target": {"08:00": 80}, "max_commands": 6, "command_penalty": 0.001}
  ],
  "solver": {"time_limit": 60}
}
```

```bash
python -m fennec scenario.json --output results.json --plot results.png
python -m fennec --example huawei_battery          # one of the built-in scenarios
fennec --help                                      # same entry point after `poetry install`
```

`results.json` holds the summary and every time series; `fennec.scenario.smart_home_from_dict` and
`results_to_dict` are the functions behind it, for use from a web service or a scheduler.

## Real-time optimizer: the daemon

`fennec.rto` turns the optimizer into a service for an edge computer (a Raspberry Pi is enough, see below).
It re-plans every settlement period on a rolling horizon from what the house reports, sends the first
commands of the plan, and refuses to decide when its information is too old.

**It talks to nobody but a connector.** The daemon contains no integration with inverters, chargers or
meters. An external connector, written by whoever knows the equipment, opens a socket, writes observations
as JSON lines and reads commands back. The contract is in `fennec/rto/messages.py`:

```
->  {"type": "battery", "time": "2025-03-22T18:03:00+00:00", "soc": 47.3, "mode": "self_consumption",
     "setpoint_kw": 0.0, "power_kw": -1.2, "pv_kw": 0.0}                              (last three optional)
->  {"type": "ev", "time": "...", "plugged": true, "soc": 40, "charging": true, "power_kw": 3.7,
     "expected_departure": "..."}                                                      (all but plugged optional)
->  {"type": "meter", "time": "...", "import_kw": 1.1, "export_kw": 0.0, "load_kw": 2.3}      (load optional)
->  {"type": "forecast", "time": "...", "signal": "pv", "start": "...", "step_minutes": 15, "values_kwh": [...]}
->  {"type": "control", "action": "replan" | "pause" | "resume"}
<-  {"type": "command", "device": "battery", "action": "force_charge", "power_kw": 3.0, "minutes": 45, ...}
<-  {"type": "command", "device": "car", "action": "charge", "on": true, ...}
<-  {"type": "status", "health": "running", "reason": null, "stale": [], "last_plan": {...}, ...}
<-  {"type": "plan", "summary": {...}, "commands": {...}}
<-  {"type": "error", "error": "..."}      (a bad message is answered, never fatal)
```

`time` is when the value was measured, so a reading delivered late is as old as it really is. The optional
fields make the plans and the forecasts better: the setpoint and charger state in force let the optimizer
count a change from them as a command, and the measured powers feed the learned forecasts.

**Deadlines and the fault state.** Every signal has a maximum age in the configuration. When a *required*
signal (by default the battery and the car) is older than its deadline, or was never received, the daemon
enters `fault`: it sends each device its safe command once (`set_mode self_consumption` to the battery,
`release` to the charger, i.e. "do what you do on your own"), stops planning, and reports the stale signals
in every status message. As soon as the signal is fresh again it re-plans immediately and re-sends the
commands. An *optional* signal (meter, forecasts) that goes stale only marks the loop `degraded`; a plan that
fails (infeasible, no solution in time) also sends the safe commands and retries after `retry_s`. The
connector can `pause` and `resume` the daemon.

| health | meaning |
|---|---|
| `starting` | waiting for the first reading of every required signal |
| `running` | planning at every settlement boundary and on events |
| `degraded` | planning, but an optional signal is stale or the last plan failed |
| `fault` | a required signal missed its deadline: safe commands sent, no planning |
| `paused` | told to pause by the connector |

**When it plans.** At every settlement boundary (15 minutes by default, the horizon starts at the period that
is running), when the car is plugged in or out, when a forecast arrives, on request, and on recovery from a
fault; events are debounced. Commands are only sent when the intent changes, except timed commands
(`force_charge`, `force_discharge`, `hold`, `set_power`), which are renewed before they expire. Every solve
starts from the previous plan shifted in time (a MIP warm start): HiGHS turns it into a feasible incumbent
at once, so a solve that hits the time limit still returns at least the previous plan adapted to the new
state. It does not shorten the proof of optimality on these problems, so the horizon settings remain the
lever for solve time.

**Daily command budget.** `limits` in the configuration caps the commands actually sent to each device over a
rolling 24 hours. The budget that is left is handed to the optimizer as its `max_commands`, so the plan
itself respects it: with a budget of zero the inverter is left in its current mode and setpoint (which is
why the connector should report `setpoint_kw` and `charging`) and the daemon only watches.

**Learned forecasts.** With `learning.enabled` the daemon rebuilds, from the last `learning.days` of the
audit file, a PV factor per hour of the day (production reported by the inverter over the clear-sky model)
and a load profile per 15-minute slot for weekdays and weekends (from `load_kw` when the meter measures it,
otherwise from the balance of the reported powers). After `learning.min_days` of data these replace the
configured fallback profiles; forecasts sent by the connector still take precedence. The status message
reports how many days of data the learner holds.

**Running it.**

```bash
python -m fennec.rto docs/examples/rto-config.json --tcp 127.0.0.1:7777      # or --unix /run/fennec.sock
```

The configuration (see `docs/examples/rto-config.json` and `fennec/rto/config.py`) holds the house in the
same format as a scenario, the fallback forecasts used when the connector sends none (clear-sky PV scaled by
a factor, a load profile by hour of day), the horizon, the deadlines, the re-planning settings, the solver
limits and the audit file. The audit is a JSON lines file with every observation, plan, command and health
change, which is what you replay to understand a day.

**Testing without hardware.** `fennec.rto.Twin` is a digital twin of the house that plays the connector: it
applies the daemon's commands to a simulated plant (the inverter's self-consumption rule, forced charge and
discharge, an on/off charger, a car that leaves and comes back) and produces the observations, optionally
delivered late. `tests/unit/test_rto.py` runs the closed loop for a simulated evening with delayed readings
and checks that the loop stays healthy, and that a late required signal trips the fault state and recovers.
The engine itself takes the clock as an argument, so every state transition is tested deterministically.

**On a Raspberry Pi.** HiGHS is effectively single-threaded on these models, so only single-core speed
matters. With the rolling horizon (6 h at 15 min, then hourly) the Porto house with battery and car has
~500 binaries and solves in about a second on a laptop; expect ten to twenty seconds on a Pi 4, well inside
a 15-minute period. `deploy/` has a `systemd` unit and the installation steps for 64-bit Raspberry Pi OS;
keep `solver.time_limit` below the period so that a slow solve returns the best plan found instead of
blocking the loop.

**Connectors.** `connectors/home_assistant/` is an example connector that uses Home Assistant as the device
layer: it polls the entities of your integrations, sends the observations, and turns the daemon's commands
into service calls. It lives outside the package on purpose: Fennec has no dependency on it and the entity
and service names are placeholders to be checked against your installation.

## Extending Fennec

**A new device** (heat pump, water heater, air conditioner, pool pump...): subclass `fennec.assets.Asset`,
declare the parameters as dataclass fields, implement `validate()` and `build(ctx)`. The block you return must
expose `energy_from[t]`, `energy_to[t]` and `cost[t]`; the house takes care of the balance and the objective. A
thermal device looks like a battery whose "SOC" is a temperature: `Battery` is a good template. Override
`extract()` to report extra columns, and set the class attribute `kind` so results and figures recognise it.

**A new battery brand**: subclass `fennec.controllers.BatteryController` and implement `build(block, battery,
ctx)`. The block already has `energy_to`, `energy_from`, `soc`, `soc_end` and the SOC dynamics; add the brand's
mode variables, the constraints that tie the energies to those modes, the command accounting and `block.cost`.
`HuaweiLuna2000Controller` is the reference implementation, and `tests/unit/test_huawei.py` shows how to prove a
controller against a rule-based simulation of the device.

**A new tariff**: `Tariff(name, prices={...}, schedules=[Schedule("08:00", "22:00", "peak", weekdays=(0,1,2,3,4)), ...])`.

**Real data**: replace the simulators by your forecasts. Any list with one kWh value per step works, so a
`pandas.Series` resampled to the horizon's step is enough.

## Project layout

```
src/fennec/
├── horizon.py          Horizon: the time grid and clock-time helpers
├── model.py            SmartHome: balance, objective, solve
├── results.py          Results: status, series per asset, pandas access
├── scenario.py         dict / JSON <-> SmartHome, results_to_dict
├── commands.py         Command: a run of steps translated into a device instruction
├── cli.py              python -m fennec
├── rto/                the daemon: messages, state and deadlines, planner, engine, learning, transport, twin
├── assets/             Asset base class, Grid, PVProduction, Load, Battery, ElectricVehicle
├── controllers/        BatteryController base, IdealController, HuaweiLuna2000Controller
├── tariffs/            Tariff, Schedule and the Portuguese presets
├── simulators/         synthetic PV and household load
├── examples/           the Porto house scenarios used by notebooks, tests and the CLI
└── utils/              report tables and matplotlib figures (optional extra)
notebooks/              executed studies, one per scenario
tests/unit/             pytest suite (HiGHS runs in the tests; they take a few seconds)
docs/                   images and docs/examples/rto-config.json
deploy/                 systemd unit and Raspberry Pi installation notes
connectors/             example connectors (not part of the package)
scripts/                coverage badge generator
```

## Development

```bash
poetry install --all-extras
poetry run pytest                      # unit tests
poetry run black src tests             # formatting (line length 120)
poetry run coverage run -m pytest && poetry run python scripts/coverage_badge.py   # updates docs/imgs/coverage.svg
poetry run jupyter notebook            # the notebooks expect to run from notebooks/
```

Changes between versions are listed in [CHANGELOG.md](CHANGELOG.md).

To re-execute the notebooks in place:

```bash
cd notebooks && poetry run jupyter nbconvert --to notebook --execute --inplace *.ipynb
```

Model sizes and solve times for the built-in scenarios (144 steps, Apple Silicon, HiGHS, 0.1 % gap):

| Scenario | Binaries | Solve |
|---|---|---|
| baseline | 0 | < 0.1 s |
| huawei_battery | ~1000 | ~10 s |
| electric_vehicle | ~240 | < 0.1 s |
| battery_and_vehicle | ~1250 | ~12 s |

Longer horizons or several batteries grow the number of binaries linearly; raise `time_limit` and accept the
reported gap, or lower the resolution to 30 minutes.
