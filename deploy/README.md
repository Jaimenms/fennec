# Deploying the daemon on a Raspberry Pi

Tested layout: 64-bit Raspberry Pi OS (Bookworm), Python 3.12 from the distribution, the package in a
virtual environment under `/opt/fennec`, configuration in `/etc/fennec`, state in `/var/lib/fennec`, the
socket in `/run/fennec`. `highspy` ships ARM64 wheels, so nothing is compiled.

```bash
# 1. system packages and a dedicated user
sudo apt-get install -y python3-venv python3-pip
sudo useradd --system --home /var/lib/fennec --shell /usr/sbin/nologin fennec
sudo install -d -o fennec -g fennec -m 0750 /var/lib/fennec
sudo install -d -m 0755 /etc/fennec /opt/fennec

# 2. the package (from a wheel built with `poetry build`, or straight from the repository)
sudo python3 -m venv /opt/fennec/venv
sudo /opt/fennec/venv/bin/pip install --upgrade pip
sudo /opt/fennec/venv/bin/pip install fennec-*.whl          # or: pip install git+https://github.com/Jaimenms/fennec

# 3. configuration: start from the example and edit the house, the deadlines and the limits
sudo cp docs/examples/rto-config.json /etc/fennec/rto.json

# 4. the service
sudo cp deploy/fennec-rto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fennec-rto
systemctl status fennec-rto
journalctl -u fennec-rto -f
```

The connector runs as its own service, in the `fennec` group so that it can open `/run/fennec/rto.sock`
(`SupplementaryGroups=fennec` in its unit). `connectors/home_assistant/` is an example.

## Day-to-day

- **Status**: every message the daemon writes to the socket is also in the audit file; `tail -f
  /var/lib/fennec/audit.jsonl | grep '"kind": "health"'` shows the health transitions.
- **Audit rotation**: the file grows by roughly 1 MB per day with 5-minute reports. Rotate it with
  `logrotate` (`copytruncate`, weekly, keep 8) or let the learner window do the pruning: the daemon only
  reads the last `learning.days` days at start-up.
- **Configuration changes**: `systemctl restart fennec-rto`. The daemon rebuilds the learned forecasts from
  the audit, so a restart costs a few seconds and no knowledge.
- **Solver time**: keep `solver.time_limit` below the settlement period (15 minutes). A solve that hits the
  limit returns the best plan found, with its gap in the plan message.
- **Clock**: the daemon trusts the system clock for deadlines and settlement boundaries. Keep `systemd-timesyncd`
  enabled; a Pi without a real-time clock starts with the wrong time until NTP answers, and the first
  readings would look stale.
