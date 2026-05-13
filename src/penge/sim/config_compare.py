"""Side-by-side comparison of N deterministic ``CashflowConfig`` projections.

This module answers the question *"how do these N alternative cashflow
configurations compare on key summary metrics?"* — for example,
*Coast FIRE (stop contributions after 10 years)* vs. *pay full 20 years*.

It is distinct from :mod:`penge.sim.scenario`, which models stochastic
*mutator* scenarios (house purchase, work reduction) layered on top of a
single baseline Monte-Carlo run.  This module operates purely on
deterministic :func:`penge.sim.cashflow.project` outputs, with no
randomness and no shared baseline — each scenario is its own labelled
:class:`~penge.sim.cashflow.CashflowConfig`.

Public API
----------
- :class:`ConfigComparisonResult` — projection + summary metrics for one labelled config
- :class:`ConfigComparison` — ordered tuple of results
- :func:`compare_configs` — projects each labelled config and assembles the comparison
- :exc:`ConfigCompareError` — raised on invalid inputs

Closes #127.
"""

from __future__ import annotations

from decimal import Decimal

import pydantic

from penge.sim.cashflow import CashflowConfig, CashflowProjection, project

__all__ = [
    "ConfigCompareError",
    "ConfigComparison",
    "ConfigComparisonResult",
    "compare_configs",
]


class ConfigCompareError(Exception):
    """Raised when the inputs to :func:`compare_configs` are invalid."""


class ConfigComparisonResult(pydantic.BaseModel):
    """Projection of one labelled :class:`CashflowConfig` plus summary metrics.

    All metric dictionaries are keyed by entity identifier and contain EUR
    amounts as :class:`~decimal.Decimal` values.

    Args:
        label: Human-readable scenario label (must be unique within a
            :class:`ConfigComparison`).
        config: The :class:`CashflowConfig` that was projected.
        projection: The full :class:`CashflowProjection` produced by
            :func:`penge.sim.cashflow.project`.
        end_balance_eur: Per-entity ``cumulative_pension_eur`` at the final
            projected year.  Reflects total pension entitlement accrued
            over the projection horizon (gross, pre-tax).
        total_contributions_eur: Per-entity sum of ``liquid_contribution_eur``
            across all projected years (own contributions to the liquid
            portfolio, gross of taxes).
        total_liquid_eur: Currently equal to ``total_contributions_eur`` —
            both summarise the gross liquid contribution stream.  Retained
            as a separate field for API stability so that, once a tax-aware
            liquid balance projection is integrated (see
            :mod:`penge.sim.liquid`), this can diverge to expose the
            after-tax balance without breaking callers.  Treat the two
            fields as semantically distinct even when the values match.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    config: CashflowConfig
    projection: CashflowProjection
    end_balance_eur: dict[str, Decimal]
    total_contributions_eur: dict[str, Decimal]
    total_liquid_eur: dict[str, Decimal]


class ConfigComparison(pydantic.BaseModel):
    """Ordered side-by-side comparison of N :class:`ConfigComparisonResult` items.

    The first result is conventionally the baseline; subsequent results are
    alternatives.  Order is preserved from the call to
    :func:`compare_configs`.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    results: tuple[ConfigComparisonResult, ...]

    def labels(self) -> list[str]:
        """Return the labels in declared order."""
        return [r.label for r in self.results]

    def by_label(self, label: str) -> ConfigComparisonResult:
        """Return the result for *label* or raise :class:`KeyError`."""
        for r in self.results:
            if r.label == label:
                return r
        raise KeyError(label)

    def diff_end_balance_eur(self, baseline_label: str, other_label: str) -> dict[str, Decimal]:
        """Per-entity ``other.end_balance - baseline.end_balance``.

        Entities present in only one side are treated as having a zero
        balance on the other side.
        """
        base = self.by_label(baseline_label).end_balance_eur
        other = self.by_label(other_label).end_balance_eur
        entities = set(base) | set(other)
        return {e: other.get(e, Decimal("0")) - base.get(e, Decimal("0")) for e in sorted(entities)}


def _summarize(projection: CashflowProjection) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Compute (end_balance_per_entity, total_contributions_per_entity)."""
    end_balance: dict[str, Decimal] = {}
    total_contrib: dict[str, Decimal] = {}

    if not projection.flows:
        return end_balance, total_contrib

    final_year = max(f.year for f in projection.flows)
    for flow in projection.flows:
        total_contrib[flow.entity] = (
            total_contrib.get(flow.entity, Decimal("0")) + flow.liquid_contribution_eur
        )
        if flow.year == final_year:
            end_balance[flow.entity] = flow.cumulative_pension_eur

    return end_balance, total_contrib


def compare_configs(
    *scenarios: tuple[str, CashflowConfig],
) -> ConfigComparison:
    """Project each ``(label, config)`` pair and assemble a comparison.

    Args:
        *scenarios: One or more ``(label, CashflowConfig)`` tuples.  Labels
            must be unique and non-empty.  A single scenario is accepted
            (the result is a one-element comparison), but the function is
            most useful with two or more scenarios where ``diff_*`` helpers
            actually carry information.

    Returns:
        A :class:`ConfigComparison` preserving input order.

    Raises:
        ConfigCompareError: if no scenarios are passed, a label is empty,
            or labels collide.
    """
    if not scenarios:
        raise ConfigCompareError("compare_configs requires at least one scenario")

    seen: set[str] = set()
    for label, _ in scenarios:
        if not label:
            raise ConfigCompareError("scenario label must be non-empty")
        if label in seen:
            raise ConfigCompareError(f"duplicate scenario label: {label!r}")
        seen.add(label)

    results: list[ConfigComparisonResult] = []
    for label, config in scenarios:
        projection = project(config)
        end_balance, total_contrib = _summarize(projection)
        results.append(
            ConfigComparisonResult(
                label=label,
                config=config,
                projection=projection,
                end_balance_eur=end_balance,
                total_contributions_eur=total_contrib,
                total_liquid_eur=total_contrib,
            )
        )

    return ConfigComparison(results=tuple(results))
