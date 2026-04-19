from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from monitoring.models import CheckResult, MonitorReport

STATUS_ICON = {
    "ok": "✅",
    "warning": "⚠️",
    "critical": "🚨",
}


def _clip(value: str, limit: int = 1000) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _color_for_status(status: str) -> int:
    return {
        "ok": 0x2ECC71,
        "warning": 0xF1C40F,
        "critical": 0xE74C3C,
    }.get(status, 0x3498DB)


def _build_check_field(check: CheckResult) -> dict[str, Any]:
    icon = STATUS_ICON.get(check.status, "ℹ️")
    details_preview = json.dumps(check.details, default=str, indent=2)
    return {
        "name": f"{icon} {check.name}",
        "value": _clip(f"{check.summary}\n```json\n{_clip(details_preview, 800)}\n```", 1024),
        "inline": False,
    }


def build_single_embed_payload(report: MonitorReport, config: dict[str, Any]) -> dict[str, Any]:
    fields = []
    max_fields = int(config["discord"].get("max_fields", 20))

    for check in report.checks[:max_fields]:
        fields.append(_build_check_field(check))

    return {
        "username": config["discord"].get("username", "VPS Monitor"),
        "embeds": [
            {
                "title": f"{STATUS_ICON.get(report.overall_status, 'ℹ️')} VPS Monitor Report",
                "description": f"Host: `{report.hostname}`\nGenerated: `{report.generated_at}`",
                "color": _color_for_status(report.overall_status),
                "fields": fields,
            }
        ],
    }


def build_summary_payload(report: MonitorReport, config: dict[str, Any]) -> dict[str, Any]:
    summary_lines = [
        f"{STATUS_ICON.get(check.status, 'ℹ️')} **{check.name}**: {check.summary}"
        for check in report.checks
    ]
    description = "\n".join(summary_lines[:10])
    return {
        "username": config["discord"].get("username", "VPS Monitor"),
        "embeds": [
            {
                "title": f"{STATUS_ICON.get(report.overall_status, 'ℹ️')} VPS Monitor Summary",
                "description": _clip(
                    f"Host: `{report.hostname}`\nGenerated: `{report.generated_at}`\n\n{description}",
                    4096,
                ),
                "color": _color_for_status(report.overall_status),
            }
        ],
    }


def build_detail_payload(check: CheckResult, report: MonitorReport, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": config["discord"].get("username", "VPS Monitor"),
        "embeds": [
            {
                "title": f"{STATUS_ICON.get(check.status, 'ℹ️')} {check.name} Details",
                "description": _clip(
                    f"Host: `{report.hostname}`\nGenerated: `{report.generated_at}`\n\n{check.summary}",
                    4096,
                ),
                "color": _color_for_status(check.status),
                "fields": [_build_check_field(check)],
            }
        ],
    }


def build_payloads(report: MonitorReport, config: dict[str, Any]) -> list[dict[str, Any]]:
    discord_config = config["discord"]
    delivery_mode = discord_config.get("delivery_mode", "single_embed")
    detail_checks = set(discord_config.get("detail_checks", []))
    send_ok_detail_messages = bool(discord_config.get("send_ok_detail_messages", False))

    if delivery_mode == "single_embed":
        return [build_single_embed_payload(report, config)]

    if delivery_mode == "summary_and_alert_details":
        payloads = [build_summary_payload(report, config)]
        for check in report.checks:
            if check.name not in detail_checks:
                continue
            if check.status == "ok" and not send_ok_detail_messages:
                continue
            payloads.append(build_detail_payload(check, report, config))
        return payloads

    if delivery_mode == "split_messages":
        payloads = [build_summary_payload(report, config)]
        for check in report.checks:
            if check.name in detail_checks:
                payloads.append(build_detail_payload(check, report, config))
        return payloads

    raise ValueError(
        "Unsupported discord.delivery_mode. Use single_embed, summary_and_alert_details, or split_messages."
    )


def _send_payload(webhook_url: str, payload: dict[str, Any]) -> None:
    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


def send_report(report: MonitorReport, config: dict[str, Any]) -> None:
    webhook_url = config["discord"]["webhook_url"]
    for payload in build_payloads(report, config):
        _send_payload(webhook_url, payload)
