from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import psutil

from monitoring.models import CheckResult


def _run_command(command: list[str], timeout: int = 10) -> tuple[bool, str]:
    if not shutil.which(command[0]):
        return False, f"{command[0]} not installed"
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)

    output = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode != 0:
        return False, output or f"exit={completed.returncode}"
    return True, output


def collect_host_metrics(config: dict[str, Any]) -> CheckResult:
    thresholds = config["app"]["thresholds"]
    sample_seconds = config["app"].get("sample_seconds", {}).get("disk_io", 2)
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()

    disk_details: dict[str, Any] = {}
    worst_disk_percent = 0.0
    for path in config["system"].get("disk_paths", ["/"]):
        usage = psutil.disk_usage(path)
        disk_details[path] = {
            "used_percent": round(usage.percent, 2),
            "free_gb": round(usage.free / 1024**3, 2),
            "total_gb": round(usage.total / 1024**3, 2),
        }
        worst_disk_percent = max(worst_disk_percent, usage.percent)

    io_before = psutil.disk_io_counters()
    time.sleep(max(sample_seconds, 1))
    io_after = psutil.disk_io_counters()
    read_mb_s = 0.0
    write_mb_s = 0.0
    if io_before and io_after:
        read_mb_s = round(
            (io_after.read_bytes - io_before.read_bytes) / sample_seconds / 1024**2, 2
        )
        write_mb_s = round(
            (io_after.write_bytes - io_before.write_bytes) / sample_seconds / 1024**2, 2
        )

    uptime_seconds = int(time.time() - boot_time)
    uptime_hours = round(uptime_seconds / 3600, 2)

    status = "ok"
    if (
        cpu_percent >= thresholds["cpu_warn_percent"]
        or memory.percent >= thresholds["memory_warn_percent"]
        or worst_disk_percent >= thresholds["disk_warn_percent"]
    ):
        status = "warning"

    summary = (
        f"CPU {cpu_percent:.1f}% | RAM {memory.percent:.1f}% | "
        f"Disk {worst_disk_percent:.1f}% | Uptime {uptime_hours}h"
    )
    return CheckResult(
        name="VPS Infra",
        status=status,
        summary=summary,
        details={
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(memory.percent, 2),
            "memory_used_gb": round(memory.used / 1024**3, 2),
            "memory_total_gb": round(memory.total / 1024**3, 2),
            "disk": disk_details,
            "disk_io_read_mb_s": read_mb_s,
            "disk_io_write_mb_s": write_mb_s,
            "uptime_hours": uptime_hours,
        },
    )


def collect_connectivity_checks(config: dict[str, Any]) -> CheckResult:
    targets = config["system"].get("ping_targets", [])
    failures: list[str] = []
    outcomes: list[dict[str, Any]] = []

    for target in targets:
        host = target["host"]
        port = int(target.get("port", 80))
        timeout_seconds = int(target.get("timeout_seconds", 2))
        started = time.perf_counter()
        ok = False
        error = ""
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                ok = True
        except OSError as exc:
            error = str(exc)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        outcomes.append(
            {
                "name": target["name"],
                "host": host,
                "port": port,
                "ok": ok,
                "latency_ms": elapsed_ms,
                "error": error,
            }
        )
        if not ok:
            failures.append(target["name"])

    status = "critical" if failures else "ok"
    summary = "All connectivity checks passed" if not failures else f"Failed: {', '.join(failures)}"
    return CheckResult(
        name="Connectivity",
        status=status,
        summary=summary,
        details={"targets": outcomes},
    )


def collect_docker_state(config: dict[str, Any]) -> CheckResult:
    docker_config = config["system"].get("docker", {})
    if not docker_config.get("enabled", False):
        return CheckResult("Docker", "ok", "Docker checks disabled", {})

    command = ["docker", "ps"]
    if docker_config.get("include_all", False):
        command.append("-a")
    command.extend(["--format", "{{.Names}}|{{.Status}}|{{.Image}}"])
    ok, output = _run_command(command)
    if not ok:
        return CheckResult("Docker", "warning", f"Unable to inspect Docker: {output}", {})

    containers = []
    for line in output.splitlines():
        if not line.strip():
            continue
        name, status, image = (line.split("|", 2) + ["", ""])[:3]
        containers.append({"name": name, "status": status, "image": image})

    summary = f"{len(containers)} container(s) reported"
    return CheckResult("Docker", "ok", summary, {"containers": containers})


def collect_service_statuses(config: dict[str, Any]) -> CheckResult:
    services = config["system"].get("services", [])
    results = []
    degraded = []

    for service in services:
        ok, output = _run_command(["systemctl", "is-active", service], timeout=5)
        state = output.strip() if output else "unknown"
        is_ok = ok and state == "active"
        if not is_ok:
            degraded.append(service)
        results.append({"service": service, "state": state})

    status = "warning" if degraded else "ok"
    summary = "All configured services active" if not degraded else f"Inactive: {', '.join(degraded)}"
    return CheckResult("systemctl", status, summary, {"services": results})


def collect_top_snapshot(config: dict[str, Any]) -> CheckResult:
    if not config["system"].get("enable_top_snapshot", True):
        return CheckResult("top", "ok", "Top snapshot disabled", {})

    line_count = int(config["system"].get("top_lines", 15))
    ok, output = _run_command(["top", "-b", "-n", "1"], timeout=10)
    if not ok:
        return CheckResult("top", "warning", f"Unable to read top: {output}", {})

    lines = output.splitlines()[:line_count]
    return CheckResult("top", "ok", "Captured top snapshot", {"lines": lines})


def collect_netdata(config: dict[str, Any]) -> CheckResult:
    netdata = config["system"].get("netdata", {})
    if not netdata.get("enabled", False):
        return CheckResult("Netdata", "ok", "Netdata probe disabled", {})

    url = netdata["url"]
    timeout = int(netdata.get("timeout_seconds", 3))
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return CheckResult("Netdata", "warning", f"Netdata probe failed: {exc}", {})

    version = payload.get("version", "unknown")
    return CheckResult("Netdata", "ok", f"Netdata reachable (version {version})", payload)
