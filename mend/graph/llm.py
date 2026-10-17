"""The one interface the hops use to ask a model anything.

The hops depend on ModelClient, not on the gateway, for the same reason the rails live in
a plain state machine: the wiring is then tested on every commit with scripted replies,
and the only code that needs keys, a network and money is GatewayClient, which is a thin
adapter over mend.gateway.call.

Two failure types, and the hops treat both the same way: they stop the issue and say why.
BudgetExhausted is the per-issue cap binding, which is the cap working, not an error.
ModelCallFailed is a call that came back without usable text after the gateway's own
retry. Neither is a RailViolation; those are never caught.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from mend.gateway import Role, call, open_gateway

if TYPE_CHECKING:  # pragma: no cover - imported for types only
    from boundary import Gateway


class HopFailed(Exception):
    """A hop could not get what it needed from a model. The issue stops; the run goes on."""


class BudgetExhausted(HopFailed):
    """The gateway refused the call before making it: the per-issue cap would be passed."""


class ModelCallFailed(HopFailed):
    """The call was made and did not return usable text."""


@dataclass(frozen=True, slots=True)
class Reply:
    """What came back, and enough about the call to account for it.

    provider is what the gateway actually routed to, read off the response rather than
    the configuration, so the different-vendor check at the review hop compares what
    happened rather than what was intended.
    """

    text: str
    provider: str
    model: str
    cost_usd: float | None = None
    latency_ms: float = 0.0
    cached: bool = False


@dataclass(frozen=True, slots=True)
class HopRecord:
    """One model call, for the per-hop minutes and cost in PLAN.md section 1."""

    hop: str
    role: str
    provider: str
    model: str
    cost_usd: float | None
    latency_ms: float
    cached: bool


class ModelClient(Protocol):
    """Ask one role one question on behalf of one issue."""

    def ask(
        self,
        role: Role,
        *,
        issue_id: str,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> Reply: ...


@dataclass
class GatewayClient:
    """ModelClient over the portfolio gateway. Every call is ledgered and capped there.

    Opened through mend.gateway.open_gateway, so a client that exists has had the
    different-vendor rule checked against what the gateway resolves.
    """

    gateway: Gateway
    # None sends no temperature at all. Reasoning models refuse any value but their
    # default, and the reviewer is one; a fixed temperature is a per-role decision for
    # the validation run, not a default here.
    temperature: float | None = None

    @classmethod
    def open(cls, config_path: Path, *, env: str | None = None) -> GatewayClient:
        return cls(gateway=open_gateway(config_path, env=env))

    def close(self) -> None:
        self.gateway.close()

    def ask(
        self,
        role: Role,
        *,
        issue_id: str,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> Reply:
        from boundary import BoundaryError, SpendCapExceeded

        started = time.monotonic()
        try:
            response = call(
                self.gateway,
                role,
                issue_id=issue_id,
                messages=[{"role": "user", "content": prompt}],
                system=system,
                max_tokens=max_tokens,
                temperature=self.temperature,
            )
        except SpendCapExceeded as exc:
            raise BudgetExhausted(str(exc)) from exc
        except BoundaryError as exc:
            raise ModelCallFailed(f"{role.name.lower()}: {exc}") from exc

        if not response.ok or not response.text:
            raise ModelCallFailed(
                f"{role.name.lower()}: status {response.status}, "
                f"finish reason {response.finish_reason}, no text"
            )
        provider, _, model = response.model_requested.partition("/")
        return Reply(
            text=response.text,
            provider=response.provider or provider,
            model=response.model_returned or model,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms or (time.monotonic() - started) * 1000,
            cached=response.cached,
        )
