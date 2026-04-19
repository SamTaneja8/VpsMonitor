from __future__ import annotations

import time
from typing import Any

import psutil
import pymysql

from monitoring.models import CheckResult


def _connect(mysql_config: dict[str, Any]):
    return pymysql.connect(
        host=mysql_config["host"],
        port=int(mysql_config.get("port", 3306)),
        user=mysql_config["user"],
        password=mysql_config["password"],
        database=mysql_config.get("database") or None,
        connect_timeout=int(mysql_config.get("connect_timeout_seconds", 5)),
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=10,
        write_timeout=10,
        autocommit=True,
    )


def _fetch_show_variable(cursor, query: str) -> tuple[str, str]:
    cursor.execute(query)
    row = cursor.fetchone() or {}
    return str(row.get("Variable_name", "")), str(row.get("Value", ""))


def _process_running(process_hint: str) -> bool:
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if process_hint in name or process_hint in cmdline:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def collect_mysql_health(config: dict[str, Any]) -> CheckResult:
    mysql_config = config.get("mysql", {})
    if not mysql_config.get("enabled", False):
        return CheckResult("MySQL", "ok", "MySQL checks disabled", {})

    details: dict[str, Any] = {}
    status = "ok"
    started = time.perf_counter()

    process_alive = _process_running(mysql_config.get("process_name_hint", "mysqld"))
    details["process_alive"] = process_alive
    if not process_alive:
        status = "critical"

    try:
        with _connect(mysql_config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                details["alive"] = cursor.fetchone()["ok"] == 1

                _, max_connections = _fetch_show_variable(cursor, "SHOW VARIABLES LIKE 'max_connections';")
                _, threads_connected = _fetch_show_variable(
                    cursor, "SHOW STATUS LIKE 'Threads_connected';"
                )
                _, slow_queries = _fetch_show_variable(
                    cursor, "SHOW GLOBAL STATUS LIKE 'Slow_queries';"
                )
                _, innodb_pages_data = _fetch_show_variable(
                    cursor, "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_data';"
                )
                _, innodb_pages_total = _fetch_show_variable(
                    cursor, "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_total';"
                )

                max_connections_int = int(max_connections or 0)
                threads_connected_int = int(threads_connected or 0)
                connection_usage = round(
                    (threads_connected_int / max_connections_int * 100), 2
                ) if max_connections_int else 0.0

                buffer_pool_usage = 0.0
                total_pages_int = int(innodb_pages_total or 0)
                if total_pages_int:
                    buffer_pool_usage = round(
                        int(innodb_pages_data or 0) / total_pages_int * 100, 2
                    )

                details.update(
                    {
                        "max_connections": max_connections_int,
                        "threads_connected": threads_connected_int,
                        "connection_usage_percent": connection_usage,
                        "slow_queries": int(slow_queries or 0),
                        "buffer_pool_usage_percent": buffer_pool_usage,
                    }
                )

                cursor.execute("SHOW SLAVE STATUS")
                replica = cursor.fetchone()
                if not replica:
                    cursor.execute("SHOW REPLICA STATUS")
                    replica = cursor.fetchone()

                if replica:
                    lag_value = replica.get("Seconds_Behind_Master")
                    details["replication_lag_seconds"] = None if lag_value is None else int(lag_value)
                else:
                    details["replication_lag_seconds"] = "not_replica"

                custom_results = []
                for query in mysql_config.get("custom_queries", []):
                    cursor.execute(query["sql"])
                    rows = cursor.fetchall()
                    custom_results.append({"name": query["name"], "rows": rows[:5]})
                details["custom_queries"] = custom_results

    except Exception as exc:
        return CheckResult("MySQL", "critical", f"MySQL probe failed: {exc}", details)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    details["response_ms"] = elapsed_ms

    thresholds = config["app"]["thresholds"]
    if details.get("connection_usage_percent", 0) >= thresholds["mysql_connection_warn_percent"]:
        status = "warning" if status == "ok" else status

    replication_lag = details.get("replication_lag_seconds")
    if isinstance(replication_lag, int) and replication_lag >= thresholds["replication_lag_warn_seconds"]:
        status = "warning" if status == "ok" else status

    summary = (
        f"Alive={details.get('alive', False)} | "
        f"Conn {details.get('threads_connected', 0)}/{details.get('max_connections', 0)} "
        f"({details.get('connection_usage_percent', 0)}%) | "
        f"Lag {details.get('replication_lag_seconds')}"
    )
    return CheckResult("MySQL", status, summary, details)
