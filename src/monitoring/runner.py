from __future__ import annotations

import argparse
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

from monitoring.checks.mysql_checks import collect_mysql_health
from monitoring.checks.system_checks import (
    collect_connectivity_checks,
    collect_docker_state,
    collect_host_metrics,
    collect_netdata,
    collect_service_statuses,
    collect_top_snapshot,
)
from monitoring.config import load_config
from monitoring.discord_reporter import send_report
from monitoring.models import MonitorReport
from monitoring.scheduler import run_forever


def generate_report(config: dict) -> MonitorReport:
    hostname = config["app"].get("hostname_override") or socket.gethostname()
    zone_name = config["app"].get("timezone", "UTC")
    generated_at = datetime.now(ZoneInfo(zone_name)).isoformat()

    checks = [
        collect_host_metrics(config),
        collect_connectivity_checks(config),
        collect_mysql_health(config),
        collect_docker_state(config),
        collect_service_statuses(config),
        collect_top_snapshot(config),
        collect_netdata(config),
    ]
    return MonitorReport(hostname=hostname, generated_at=generated_at, checks=checks)


def run_once(config_path: str) -> None:
    config = load_config(config_path)
    report = generate_report(config)
    send_report(report, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VPS monitor checks and send to Discord.")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run once and exit")
    mode.add_argument("--loop", action="store_true", help="Run forever using interval_minutes")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.once:
        report = generate_report(config)
        send_report(report, config)
        return 0

    if args.loop:
        run_forever(lambda: run_once(args.config), int(config["app"].get("interval_minutes", 60)))
        return 0

    return 1
