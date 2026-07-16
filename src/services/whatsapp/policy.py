from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


PolicyMode = Literal["warn", "enforce", "off"]


@dataclass
class PolicyDecision:
    allowed: bool
    mode: PolicyMode
    reason: str | None = None
    requires_template: bool = False


class WhatsAppPolicy:
    """Minimal outbound policy gate for free-form WhatsApp replies."""

    def __init__(
        self,
        mode: PolicyMode = "warn",
        customer_service_window_hours: int = 24,
    ) -> None:
        self._mode = mode
        self._customer_service_window_hours = customer_service_window_hours

    def evaluate_freeform_send(
        self,
        last_customer_message_at: datetime | None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        if self._mode == "off":
            return PolicyDecision(allowed=True, mode=self._mode)

        if not last_customer_message_at:
            return self._decision_for_violation("no_customer_service_window")

        current_time = now or datetime.now(timezone.utc)
        if last_customer_message_at.tzinfo is None:
            last_customer_message_at = last_customer_message_at.replace(tzinfo=timezone.utc)

        age = current_time - last_customer_message_at
        allowed_window = timedelta(hours=self._customer_service_window_hours)
        if age <= allowed_window:
            return PolicyDecision(allowed=True, mode=self._mode)

        return self._decision_for_violation("outside_customer_service_window")

    def _decision_for_violation(self, reason: str) -> PolicyDecision:
        if self._mode == "warn":
            return PolicyDecision(
                allowed=True,
                mode=self._mode,
                reason=reason,
                requires_template=True,
            )

        return PolicyDecision(
            allowed=False,
            mode=self._mode,
            reason=reason,
            requires_template=True,
        )
