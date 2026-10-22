"""The shipped configuration: different vendors, a per-issue cap, a price for every role.

These read the YAML in config/ directly rather than through the gateway, so that they run
without project 04 installed and without a network. The gateway's own loader is tested in
its repository; what is being tested here is this project's configuration, which is where
the design decisions in PLAN.md sections 2.4 and 2.6 actually live.

The check that runs against a real gateway is mend.gateway.check_roles, which runs at
start-up in open_gateway. The point of doing it in both places is that configuration can
be edited after the tests ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config"
# The gateway prices with the newest dated file, so that is the one the routes must match.
LATEST_PRICES = "prices/" + max(p.name for p in (CONFIG / "prices").glob("*.yaml"))


def load(name: str) -> dict[str, Any]:
    with (CONFIG / name).open(encoding="utf-8") as handle:
        data: object = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return dict(data)


@pytest.fixture(scope="module")
def routes() -> dict[str, Any]:
    section = load("mend.routes.yaml")["routes"]
    assert isinstance(section, dict)
    return dict(section)


@pytest.fixture(scope="module")
def caps() -> dict[str, Any]:
    return load("mend.caps.yaml")


def test_all_four_roles_are_configured(routes: dict[str, Any]) -> None:
    from mend.gateway import Role

    for role in Role:
        assert role.value in routes, f"{role.name} has no route"


def test_the_reviewer_is_a_different_vendor_than_the_fixer(routes: dict[str, Any]) -> None:
    """The configuration test PLAN.md section 4 asks for.

    If this fails, the adversarial review is a model checking its own vendor's work, which
    is the Rule C ablation rather than the design.
    """
    fixer = routes["mend-fixer"]["provider"]
    reviewer = routes["mend-reviewer"]["provider"]
    assert fixer != reviewer, (
        f"the fixer and the reviewer both route to {fixer}; "
        "the reviewer must be a different vendor (PLAN.md section 2.4)"
    )


def test_the_self_reviewer_is_the_fixer_and_only_the_ablation_calls_it(
    routes: dict[str, Any],
) -> None:
    """The same-vendor ablation needs the fixer's own model, and the pipeline must never
    reach it: a graph that could ask it would have a same-vendor review one edit away."""
    from pathlib import Path

    assert routes["mend-self-reviewer"] == routes["mend-fixer"]
    graph = Path(__file__).resolve().parent.parent / "mend" / "graph"
    for path in graph.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "SELF_REVIEWER" not in text and "mend-self-reviewer" not in text, path.name


def test_the_reviewer_is_a_different_model_too(routes: dict[str, Any]) -> None:
    """Weaker than the vendor rule and worth asserting separately, so a failure says which."""
    assert routes["mend-fixer"]["model"] != routes["mend-reviewer"]["model"]


def test_the_localiser_is_the_cheap_model(routes: dict[str, Any]) -> None:
    """Bounded cost (PLAN.md section 2.6): the highest-token hop runs on the small model."""
    prices = load(LATEST_PRICES)["per_million_tokens"]

    def rate(alias: str) -> float:
        route = routes[alias]
        return float(prices[route["provider"]][route["model"]]["input"])

    assert rate("mend-localiser") < rate("mend-fixer")
    assert rate("mend-localiser") < rate("mend-tester")


def test_every_role_has_a_price(routes: dict[str, Any]) -> None:
    """A model with no price is written to the ledger uncosted, and the cost table lies."""
    prices = load(LATEST_PRICES)["per_million_tokens"]
    for alias, route in routes.items():
        provider, model = route["provider"], route["model"]
        assert provider in prices, f"{alias} routes to unpriced provider {provider}"
        assert model in prices[provider], f"{alias} routes to unpriced model {model}"
        entry = prices[provider][model]
        assert entry["input"] > 0 and entry["output"] > 0


def test_the_per_issue_cap_is_enforced_and_matches_the_code(caps: dict[str, Any]) -> None:
    """One issue is one gateway run, so per_run_usd is the per-issue cap.

    The same number lives in mend.gateway.PER_ISSUE_CAP_USD, which is what the code checks
    against; a cap that exists in only one of the two places drifts from the other.
    """
    from mend.gateway import PER_ISSUE_CAP_USD, PROJECT

    project = caps["projects"][PROJECT]
    assert project["per_run_usd"] == PER_ISSUE_CAP_USD
    assert project["per_run_usd"] > 0


def test_the_default_cap_is_not_a_loophole(caps: dict[str, Any]) -> None:
    """A project name typo must not fall through to an unbounded default."""
    assert caps["default"]["per_run_usd"] <= 1.00
    assert caps["default"]["monthly_usd"] <= 10


def test_the_monthly_cap_covers_the_plan_and_no_more(caps: dict[str, Any]) -> None:
    """PLAN.md section 6 budgets US$107 of model spend. The cap leaves room for a repeat
    of the validation run and nothing like room for a runaway."""
    from mend.gateway import PROJECT

    monthly = caps["projects"][PROJECT]["monthly_usd"]
    assert 107 <= monthly <= 160


def test_the_gateway_config_points_at_this_projects_files() -> None:
    """A config that borrowed another project's routes would not carry the vendor split."""
    config = load("boundary.yaml")
    assert config["routes"] == "mend.routes.yaml"
    assert config["caps"] == "mend.caps.yaml"
    assert config["prices"] == "prices"


def test_no_secret_is_in_any_configuration_file() -> None:
    """Keys come from environment variables named in the config, never from the config."""
    config = load("boundary.yaml")
    for name, provider in config["providers"].items():
        assert "api_key" not in provider, f"{name} carries a literal key"
        if not provider.get("price_zero"):
            assert provider["api_key_env"], f"{name} names no key environment variable"

    text = (CONFIG / "boundary.yaml").read_text(encoding="utf-8")
    for marker in ("sk-", "ghp_", "github_pat_"):
        assert marker not in text


def test_retry_allows_one_retry_only() -> None:
    """PLAN.md section 6 budgets one retry per task; more would break the cost model."""
    config = load("boundary.yaml")
    assert config["retry"]["max_attempts"] == 2
