# Example connector: Home Assistant

A connector is the piece that knows the equipment. This one uses Home Assistant as the device layer, so
the integrations already installed there (for Huawei inverters, the `huawei_solar` custom integration; for
the charger, whatever your wallbox has) do the Modbus and vendor-API work, and the connector only maps
entities to the daemon's messages and the daemon's commands to service calls.

It is an **example**, deliberately outside the `fennec` package: the package has no dependency on it, no
tests cover it, and the entity ids and service names in `config.example.json` are placeholders to be
checked against your installation (Developer tools > States and > Services in Home Assistant).

```bash
cp config.example.json config.json      # edit url, token, entity ids, services
python3 ha_connector.py config.json
```

What it does, every `poll_seconds`:

| daemon message | from Home Assistant |
|---|---|
| `battery` | SOC sensor; working-mode select (`self_consumption` when the option matches, otherwise `forced`); optional battery power, PV power and setpoint sensors (W, scaled to kW) |
| `ev` | connected binary sensor; optional charging binary sensor, SOC and charger power |
| `meter` | import and export power sensors, or one signed power sensor; optional house-load sensor |

`time` is the oldest `last_updated` among the entities that make up the observation, so a sensor that
stopped updating makes the reading look old, which is exactly what the daemon's deadlines are for.

| daemon command | service call |
|---|---|
| `set_mode self_consumption` | `select.select_option` on the working-mode entity |
| `force_charge` / `force_discharge` with `power_kw` and `minutes` | the configured services with `power` in W and `duration` in minutes |
| `hold` | forcible charge at 0 W for the duration |
| `charge on/off` | `switch.turn_on` / `switch.turn_off` on the charger switch |
| `release` | `switch.turn_on` (the charger's own default is to charge whenever plugged) |

Running it as a service on the same Pi: copy `ha_connector.py` and `config.json` to `/opt/fennec`, create a
unit similar to `deploy/fennec-rto.service` with `SupplementaryGroups=fennec` so that it can open the Unix
socket, and `After=fennec-rto.service`.
