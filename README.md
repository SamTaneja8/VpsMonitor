# VPS Discord Monitor

Config-driven monitoring scripts for VPS infrastructure, MySQL health, network checks, Docker state, and service status. Reports are sent to Discord through a webhook and can run:

- once, for GitHub Actions or cron
- in a loop, for a long-running Docker container

## Discord delivery modes

The reporter supports three config-driven output modes:

- `single_embed`: one Discord embed with all checks
- `summary_and_alert_details`: one summary embed, plus detail embeds only for warning or critical checks
- `split_messages`: one summary embed, plus detail embeds for every configured check

Example `single_embed` flow:

```text
Message 1
✅ VPS Monitor Report
- VPS Infra: CPU 32.4% | RAM 61.2% | Disk 48.1% | Uptime 132.5h
- Connectivity: All connectivity checks passed
- MySQL: Alive=True | Conn 78/100 (78.0%) | Lag 12
- Docker: 4 container(s) reported
- systemctl: Inactive: netdata
```

Example `summary_and_alert_details` flow:

```text
Message 1
⚠️ VPS Monitor Summary
- VPS Infra: OK
- Connectivity: OK
- MySQL: warning
- Docker: OK
- systemctl: warning

Message 2
⚠️ MySQL Details
Alive=True | Conn 78/100 (78.0%) | Lag 12

Message 3
⚠️ systemctl Details
Inactive: netdata
```

Example `split_messages` flow:

```text
Message 1
✅ VPS Monitor Summary

Message 2
✅ VPS Infra Details

Message 3
✅ Connectivity Details

Message 4
⚠️ MySQL Details
```

## What it checks

- CPU utilization
- RAM usage
- Disk space and sampled disk I/O
- Uptime and optional TCP/ICMP style connectivity checks
- MySQL availability and process presence
- Connection usage
- Slow query count
- InnoDB buffer pool usage
- Replication lag
- Docker container inventory
- `systemctl` status for configured services
- `top` snapshot
- Optional Netdata endpoint probe
- Custom MySQL queries

## Quick start

1. Copy [`config/config.example.yml`](/Users/samtaneja/Documents/Codex/2026-04-19-can-you-build-a-script-set/config/config.example.yml) to `config/config.yml`.
2. Fill in the Discord webhook, MySQL credentials, service names, hosts to ping, and any custom SQL.
3. Run locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python3 main.py --config config/config.yml --once
```

4. Or build/run in Docker:

```bash
docker build -t vps-discord-monitor .
docker run --rm \
  -v "$(pwd)/config:/app/config:ro" \
  --network host \
  vps-discord-monitor \
  python main.py --config /app/config/config.yml --once
```

Helper wrappers are included in [`scripts/run_once.sh`](/Users/samtaneja/Documents/Codex/2026-04-19-can-you-build-a-script-set/scripts/run_once.sh) and [`scripts/run_loop.sh`](/Users/samtaneja/Documents/Codex/2026-04-19-can-you-build-a-script-set/scripts/run_loop.sh).

## Build and install

### Option 1: Install directly on the VPS

1. Install system packages you may need:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip procps
```

2. Clone the repository onto the VPS.
3. Create a virtual environment and install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Create the live config:

```bash
cp config/config.example.yml config/config.yml
```

5. Export secrets or place them in the runner environment:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export MYSQL_USER="monitor_user"
export MYSQL_PASSWORD="secret"
```

6. Test a single run:

```bash
PYTHONPATH=src python3 main.py --config config/config.yml --once
```

### Option 2: Build and run with Docker on the VPS

1. Install Docker on the VPS.
2. Build the image:

```bash
docker build -t vps-discord-monitor .
```

3. Copy the sample config and adjust it:

```bash
cp config/config.example.yml config/config.yml
```

4. Run a one-off test:

```bash
docker run --rm \
  --network host \
  -e DISCORD_WEBHOOK_URL \
  -e MYSQL_USER \
  -e MYSQL_PASSWORD \
  -v "$(pwd)/config:/app/config:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  vps-discord-monitor \
  python main.py --config /app/config/config.yml --once
```

5. Run continuously:

```bash
docker compose up -d --build
```

### Option 3: Use a self-hosted GitHub Actions runner on the VPS

1. In GitHub, open your repository settings and create a Linux self-hosted runner.
2. On the VPS, follow GitHub’s runner install steps for the generated date and token GitHub gives you.
3. Install any local dependencies the checks need:
   Docker if you want Docker inspection
   MySQL client access if your MySQL server is local or reachable
   `systemd` access if you want `systemctl` checks
4. Put your secrets into the repository or organization:
   `DISCORD_WEBHOOK_URL`
   `MYSQL_USER`
   `MYSQL_PASSWORD`
5. Commit your `config/config.yml` strategy.
   Recommended: commit a non-secret config file and keep secrets in GitHub Actions secrets or runner environment variables.
6. Use [`.github/workflows/monitor.yml`](/Users/samtaneja/Documents/Codex/2026-04-19-can-you-build-a-script-set/.github/workflows/monitor.yml) to run every hour on that VPS-hosted runner.

## Recommended deployment choice

For your use case, I recommend:

- self-hosted GitHub Actions runner on the VPS
- direct Python execution on the VPS for the most accurate host metrics
- Docker packaging as a rebuild/redeployment option if the VPS changes later

That gives you the cleanest monitoring path now and still keeps the project portable.

## GitHub Actions note

If you want GitHub Actions to collect **local VPS metrics**, the job must run:

- on a self-hosted runner installed on the VPS, or
- by SSH-ing into the VPS and running the container/script remotely

A GitHub-hosted runner cannot directly inspect another VPS host's CPU, disk, systemd, or Docker state.

An example self-hosted workflow is included in [`.github/workflows/monitor.yml`](/Users/samtaneja/Documents/Codex/2026-04-19-can-you-build-a-script-set/.github/workflows/monitor.yml).

If you later need central orchestration across multiple servers, an SSH-based workflow can be added alongside the self-hosted runner pattern.

## Docker compatibility note

The image is useful for packaging and repeatable deployment, but **host-level metrics are most accurate when the script runs on the VPS host itself**. A plain container usually sees container-scoped CPU, memory, process, and service data.

Use one of these patterns:

- best fidelity: run `python main.py --once` directly on the VPS from a self-hosted GitHub Actions runner
- portable packaging: use the Docker image as the delivery artifact, but invoke it on the VPS with access to the host network and any sockets/files you need, such as `/var/run/docker.sock`

If you want fully host-aware metrics from inside Docker, we can add a second pass that reads mounted host `/proc` and filesystem data explicitly.

## Config model

All adjustable parameters live in YAML:

- schedule interval
- Discord webhook and username
- Discord delivery mode and detail policy
- warning thresholds
- ping targets
- services to inspect
- Docker toggle
- Netdata endpoint
- MySQL settings
- custom SQL queries

## Security

- Prefer secrets injection for passwords and webhooks.
- The sample config supports `${ENV_VAR}` interpolation.
- Mount config read-only in Docker.
- Use a limited-permission MySQL monitoring user for custom queries.
