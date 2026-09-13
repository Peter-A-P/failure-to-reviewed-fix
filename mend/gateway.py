"""Model access: the four roles, the different-vendor rule, and the per-issue cap.

Every model call in this package goes through the portfolio gateway (project 04), for the
ledger row, the telemetry span and the spend cap. Nothing here talks to a vendor.

Three things this module exists to make true rather than to assert in a document:

- The reviewer resolves to a different provider than the fixer. The roles are aliases in
  config/mend.routes.yaml, so the pairing is configuration and a change to it is a commit;
  check_roles() reads the resolved providers back and refuses a same-vendor pairing, and
  tests/test_roles.py runs it against the shipped configuration.
- A spend cap per issue is enforced before the first call. The gateway checks its per-run
  cap pre-call against run_id, so mend passes the issue id as run_id and nothing else.
  That is the whole mechanism: one issue is one run, and a cap that binds is a cap the
  gateway refuses at, having made no request.
- The four roles are named, not chosen at the call site. Localisation is the cheap model,
  drafting and review the mid-tier ones (PLAN.md section 2.6), and a caller asking for a
  model by name would put that decision in a prompt file where nobody reviews it.

The boundary import is deferred into the functions that need it so that the offline half
of this package (capture, clustering, routing, metrics) imports and tests without the
gateway installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported for types only
    from boundary import Gateway

# The ledger's project column, and the key into the gateway's caps.yaml.
PROJECT = "self-healing-production-ai"

# PLAN.md section 2.6. USD, and enforced by the gateway rather than by this package: a cap
# a caller could forget to pass is not a cap. The value here is what the shipped caps file
# must agree with, and tests/test_roles.py asserts that it does.
PER_ISSUE_CAP_USD = 1.00


class Role(StrEnum):
    """What a call is for. Each maps to one alias in the routes file."""

    LOCALISER = "mend-localiser"
    TESTER = "mend-tester"
    FIXER = "mend-fixer"
    REVIEWER = "mend-reviewer"


@dataclass(frozen=True, slots=True)
class RoleResolution:
    """What a role points at right now, as the gateway resolves it."""

    role: Role
    alias: str
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.role.name.lower()}: {self.alias} -> {self.provider}/{self.model}"


class SameVendorConfiguration(Exception):
    """The fixer and the reviewer resolve to the same provider.

    Raised at configuration time, before any issue is processed, because a run that
    discovers this at the review hop has already spent money on every hop before it.
    """


def resolve_roles(gateway: Gateway) -> dict[Role, RoleResolution]:
    """Ask the gateway what each role currently points at.

    Uses Gateway.resolve, which answers without making a call, so this is free and can run
    at start-up and be printed into the run log. A run that cannot say which models it
    used is a run whose numbers mean nothing.
    """
    out: dict[Role, RoleResolution] = {}
    for role in Role:
        ref = gateway.resolve(role.value)
        out[role] = RoleResolution(
            role=role,
            alias=role.value,
            provider=ref.provider,
            model=ref.model,
        )
    return out


def check_roles(resolutions: dict[Role, RoleResolution]) -> None:
    """Refuse a configuration where the reviewer shares a vendor with the fixer.

    This is the check the plan calls a configuration test. It runs here as well as in the
    test suite because a route can be changed after the tests ran: the routes file is
    configuration, and configuration is edited between releases.
    """
    fixer = resolutions[Role.FIXER]
    reviewer = resolutions[Role.REVIEWER]
    if fixer.provider == reviewer.provider:
        raise SameVendorConfiguration(
            f"the fixer alias {fixer.alias} and the reviewer alias {reviewer.alias} both "
            f"resolve to provider {fixer.provider}; the reviewer must be a different "
            "vendor (PLAN.md section 2.4)"
        )


def open_gateway(
    config_path: Path,
    *,
    raw_store: Path | None = None,
    ledger_path: Path | None = None,
    env: str | None = None,
) -> Gateway:
    """Open the portfolio gateway for this project, and check the roles before returning.

    Checked here rather than by the caller so that there is no way to obtain a gateway
    from this package that has not had the different-vendor rule applied to it.
    """
    from boundary import Gateway as _Gateway

    gateway = _Gateway.from_config(
        config_path,
        project=PROJECT,
        ledger_path=ledger_path,
        raw_store=raw_store,
        env=env,
    )
    try:
        check_roles(resolve_roles(gateway))
    except Exception:
        gateway.close()
        raise
    return gateway


def call(
    gateway: Gateway,
    role: Role,
    *,
    issue_id: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    max_tokens: int = 4096,
    temperature: float | None = None,
) -> Any:
    """One model call, on behalf of one issue.

    issue_id becomes the gateway's run_id, which is what the per-issue cap is measured
    against. It is a required keyword argument with no default for exactly that reason:
    an uncapped call should be impossible to make by forgetting something.
    """
    from boundary import ChatRequest

    if not issue_id:
        raise ValueError("every call must name the issue it is for, so the cap can bind")

    request = ChatRequest(
        model=role.value,
        messages=messages,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return gateway.chat(request, purpose=f"mend-{role.name.lower()}", run_id=issue_id)
