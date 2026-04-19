from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorReport:
    hostname: str
    generated_at: str
    checks: list[CheckResult]

    @property
    def overall_status(self) -> str:
        statuses = {check.status for check in self.checks}
        if "critical" in statuses:
            return "critical"
        if "warning" in statuses:
            return "warning"
        return "ok"
