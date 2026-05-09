"""Tests for :mod:`penge.sim.returns`.

Combines targeted deterministic tests (construction validation,
reproducibility, IID degenerate case) with property-based tests
(``hypothesis``) for the model-level invariants documented in
ADR-0010.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from penge.sim.returns import BootstrapReturnModel, ReturnModelError, SampledPaths

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ar1_history(
    *,
    n_months: int,
    rho: float,
    sigma: float,
    seed: int,
) -> list[Decimal]:
    """Build a synthetic AR(1) monthly log-return series.

    Used to exercise autocorrelation-preservation invariants. Decimals
    are quantised so two histories with the same parameters produce
    identical input bytes (and therefore identical ``history_hash``).
    """
    rng = np.random.default_rng(seed)
    eps = rng.standard_normal(n_months) * sigma
    out = np.empty(n_months, dtype=np.float64)
    out[0] = eps[0]
    for i in range(1, n_months):
        out[i] = rho * out[i - 1] + eps[i]
    return [Decimal(f"{x:.10f}") for x in out]


def _two_asset_history(n_months: int, seed: int) -> dict[str, list[Decimal]]:
    """Two perfectly comoving asset series — used to test cross-asset structure."""
    series = _ar1_history(n_months=n_months, rho=0.0, sigma=0.04, seed=seed)
    return {"a": list(series), "b": list(series)}


def _flat_inflation(n_months: int) -> dict[str, list[Decimal]]:
    """Constant 0.2%/month inflation; deterministic and easy to assert against."""
    return {"de": [Decimal("0.002")] * n_months, "dk": [Decimal("0.0015")] * n_months}


def _model(
    *,
    n_months: int = 240,
    block_months: int = 12,
    seed: int = 0,
    history_seed: int = 7,
) -> BootstrapReturnModel:
    return BootstrapReturnModel(
        asset_returns=_two_asset_history(n_months, history_seed),
        inflation=_flat_inflation(n_months),
        block_months=block_months,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_accepts_decimal_int_float_and_str_inputs(self) -> None:
        # The pre-validator coerces int/float/numeric-str to Decimal at
        # runtime; mypy still sees the field's declared element type as
        # ``Decimal`` so the non-Decimal entries need an explicit ignore.
        model = BootstrapReturnModel(
            asset_returns={
                "a": [Decimal("0.01")] * 12,
                "b": [0.01] * 12,  # type: ignore[list-item]  # float coerced to Decimal by validator
                "c": [1] * 12,  # type: ignore[list-item]  # int coerced to Decimal by validator
                "d": ["0.01"] * 12,  # type: ignore[list-item]  # numeric str coerced to Decimal by validator
            },
            inflation={"de": [Decimal("0.002")] * 12},
            block_months=3,
            seed=0,
        )
        assert model.history_months == 12

    def test_rejects_empty_asset_returns(self) -> None:
        # Pydantic wraps validator errors in ValidationError (a ValueError).
        with pytest.raises(ValueError, match="asset_returns must contain"):
            BootstrapReturnModel(
                asset_returns={},
                inflation={"de": [Decimal("0.0")] * 12},
            )

    def test_rejects_empty_inflation(self) -> None:
        with pytest.raises(ValueError, match="inflation must contain"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("0.0")] * 12},
                inflation={},
            )

    def test_rejects_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            BootstrapReturnModel(
                asset_returns={
                    "a": [Decimal("0.0")] * 24,
                    "b": [Decimal("0.0")] * 12,
                },
                inflation={"de": [Decimal("0.0")] * 24},
            )

    def test_rejects_short_history(self) -> None:
        with pytest.raises(ValueError, match="at least 12 months"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("0.0")] * 11},
                inflation={"de": [Decimal("0.0")] * 11},
            )

    def test_rejects_block_longer_than_history(self) -> None:
        with pytest.raises(ValueError, match=r"block_months \(60\)"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("0.0")] * 24},
                inflation={"de": [Decimal("0.0")] * 24},
                block_months=60,
            )

    def test_rejects_non_numeric_entry(self) -> None:
        with pytest.raises(ValueError, match="non-numeric"):
            BootstrapReturnModel(
                asset_returns={"a": ["nope"] * 12},  # type: ignore[list-item]
                inflation={"de": [Decimal("0.0")] * 12},
            )

    def test_rejects_block_months_below_one(self) -> None:
        # Below-one is enforced by the pydantic Field constraint, not our
        # custom validator — surface that path once.
        with pytest.raises(ValueError, match="block_months"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("0.0")] * 12},
                inflation={"de": [Decimal("0.0")] * 12},
                block_months=0,
            )

    def test_rejects_string_series(self) -> None:
        # A bare string would otherwise iterate as characters and silently
        # parse into a series of digits.
        with pytest.raises(ValueError, match="must be a non-string sequence"):
            BootstrapReturnModel(
                asset_returns={"a": "0.01"},  # type: ignore[dict-item]  # intentional misuse for validation
                inflation={"de": [Decimal("0.002")] * 12},
            )

    def test_rejects_bytes_series(self) -> None:
        with pytest.raises(ValueError, match="must be a non-string sequence"):
            BootstrapReturnModel(
                asset_returns={"a": b"\x01" * 12},  # type: ignore[dict-item]  # intentional misuse for validation
                inflation={"de": [Decimal("0.002")] * 12},
            )

    def test_rejects_nan_decimal(self) -> None:
        with pytest.raises(ValueError, match="non-finite entry"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("NaN")] + [Decimal("0.01")] * 11},
                inflation={"de": [Decimal("0.002")] * 12},
            )

    def test_rejects_infinity(self) -> None:
        with pytest.raises(ValueError, match="non-finite entry"):
            BootstrapReturnModel(
                asset_returns={"a": [Decimal("Infinity")] + [Decimal("0.01")] * 11},
                inflation={"de": [Decimal("0.002")] * 12},
            )

    def test_rejects_nan_float(self) -> None:
        with pytest.raises(ValueError, match="non-finite entry"):
            BootstrapReturnModel(
                asset_returns={"a": [float("nan")] + [0.01] * 11},  # type: ignore[dict-item]  # validator coerces float→Decimal
                inflation={"de": [Decimal("0.002")] * 12},
            )

    def test_history_hash_is_invariant_to_decimal_formatting(self) -> None:
        # Numerically-equal but textually-different inputs must hash identically.
        a = BootstrapReturnModel(
            asset_returns={"a": [Decimal("1")] * 12},
            inflation={"de": [Decimal("0.002")] * 12},
        )
        b = BootstrapReturnModel(
            asset_returns={"a": [Decimal("1.0")] * 12},
            inflation={"de": [Decimal("0.00200")] * 12},
        )
        assert a.history_hash() == b.history_hash()


# ---------------------------------------------------------------------------
# Reproducibility & shape
# ---------------------------------------------------------------------------


class TestReproducibility:
    def test_same_seed_produces_identical_arrays(self) -> None:
        model = _model(seed=42)
        a = model.sample_paths(years=10, n_paths=8)
        b = model.sample_paths(years=10, n_paths=8)
        for label in a.asset_log_returns:
            np.testing.assert_array_equal(a.asset_log_returns[label], b.asset_log_returns[label])
        for label in a.inflation_log:
            np.testing.assert_array_equal(a.inflation_log[label], b.inflation_log[label])

    def test_different_seeds_produce_different_arrays(self) -> None:
        a = _model(seed=1).sample_paths(years=10, n_paths=8)
        b = _model(seed=2).sample_paths(years=10, n_paths=8)
        # With 8*10*12 = 960 sampled month indices on a 240-long history,
        # the probability of two seeds producing identical outputs is
        # vanishingly small.
        assert not np.array_equal(a.asset_log_returns["a"], b.asset_log_returns["a"])

    def test_history_hash_is_deterministic_across_constructions(self) -> None:
        h1 = _model(history_seed=11).history_hash()
        h2 = _model(history_seed=11).history_hash()
        h3 = _model(history_seed=12).history_hash()
        assert h1 == h2
        assert h1 != h3

    def test_sampled_paths_shape(self) -> None:
        result = _model().sample_paths(years=30, n_paths=64)
        for arr in result.asset_log_returns.values():
            assert arr.shape == (64, 30)
        for arr in result.inflation_log.values():
            assert arr.shape == (64, 30)
        assert result.seed == 0
        assert result.block_months == 12

    def test_sampled_paths_metadata_round_trip(self) -> None:
        model = _model(block_months=6, seed=99)
        result = model.sample_paths(years=5, n_paths=2)
        assert isinstance(result, SampledPaths)
        assert result.seed == 99
        assert result.block_months == 6
        assert result.history_hash == model.history_hash()

    def test_sample_rejects_non_positive_years_or_paths(self) -> None:
        model = _model()
        with pytest.raises(ReturnModelError, match="years"):
            model.sample_paths(years=0, n_paths=4)
        with pytest.raises(ReturnModelError, match="n_paths"):
            model.sample_paths(years=4, n_paths=0)


# ---------------------------------------------------------------------------
# Modelling invariants
# ---------------------------------------------------------------------------


class TestCrossAssetStructure:
    def test_perfectly_comoving_assets_remain_perfectly_comoving(self) -> None:
        """The same idx is used for every asset class, so two identical
        history series must produce identical sampled paths."""
        result = _model(seed=3).sample_paths(years=20, n_paths=16)
        np.testing.assert_array_equal(result.asset_log_returns["a"], result.asset_log_returns["b"])


class TestIIDDegenerateCase:
    def test_block_months_one_yields_independent_paths(self) -> None:
        # AR(1) history with rho=0.6, sampled IID monthly. Adjacent paths
        # are drawn independently, so the cross-path correlation between
        # consecutive single-year annual sums is ~0. (This does NOT test
        # within-path lag-1 monthly autocorrelation — see
        # ``TestBlockBootstrapPreservesAutocorrelation`` for the
        # variance-based proxy of that.)
        n_months = 480
        history = _ar1_history(n_months=n_months, rho=0.6, sigma=0.04, seed=1)
        model = BootstrapReturnModel(
            asset_returns={"a": history},
            inflation=_flat_inflation(n_months),
            block_months=1,
            seed=11,
        )
        result = model.sample_paths(years=1, n_paths=2000)
        annual = result.asset_log_returns["a"][:, 0]
        ac = float(np.corrcoef(annual[:-1], annual[1:])[0, 1])
        assert abs(ac) < 0.1


class TestBlockBootstrapPreservesAutocorrelation:
    def test_long_block_inflates_annual_variance_vs_iid(self) -> None:
        """Variance-based proxy for within-block autocorrelation.

        We cannot inspect within-path monthly autocorrelation directly
        without exposing internal sequences, so we use the textbook
        identity for an annual sum of 12 months: under IID,
        ``var(annual) ≈ 12 * var(monthly)``; under positively
        autocorrelated blocks, ``var(annual) > 12 * var(monthly)``
        because months within a block move together. We compare the
        variance of one-year annual sums under ``block_months=1``
        (IID baseline) and ``block_months=24`` (long blocks) against
        the same AR(1) history; the long-block variance should
        noticeably exceed the IID variance.
        """
        n_months = 480
        history = _ar1_history(n_months=n_months, rho=0.6, sigma=0.04, seed=2)
        asset_returns = {"a": history}
        inflation = _flat_inflation(n_months)
        iid = BootstrapReturnModel(
            asset_returns=asset_returns, inflation=inflation, block_months=1, seed=5
        )
        block = BootstrapReturnModel(
            asset_returns=asset_returns, inflation=inflation, block_months=24, seed=5
        )

        n_paths = 4000
        var_iid = float(iid.sample_paths(years=1, n_paths=n_paths).asset_log_returns["a"].var())
        var_blk = float(block.sample_paths(years=1, n_paths=n_paths).asset_log_returns["a"].var())
        # Block-bootstrap variance of an annual sum should noticeably exceed
        # the IID variance for a positively autocorrelated history.
        assert var_blk > var_iid * 1.2


class TestLongRunMeanPreservation:
    @settings(
        max_examples=5,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(seed=st.integers(min_value=0, max_value=2**31 - 1))
    def test_mean_of_sampled_monthly_returns_matches_history(self, seed: int) -> None:
        # Synthetic history with a known non-zero mean.
        n_months = 240
        rng = np.random.default_rng(seed)
        raw = rng.standard_normal(n_months) * 0.04 + 0.005  # ≈0.5%/month drift
        history = [Decimal(f"{x:.10f}") for x in raw]
        hist_mean = float(np.asarray(raw).mean())

        model = BootstrapReturnModel(
            asset_returns={"a": history},
            inflation=_flat_inflation(n_months),
            block_months=6,
            seed=seed ^ 0xA5A5,
        )
        # 200 paths * 30 years * 12 = 72 000 sampled months, well over the
        # 240 distinct history months → empirical mean must approach the
        # historical mean. Annual sums divided by 12 recover monthly mean.
        result = model.sample_paths(years=30, n_paths=200)
        sampled_monthly_mean = float(result.asset_log_returns["a"].mean()) / 12.0
        assert abs(sampled_monthly_mean - hist_mean) < 0.001


class TestPropertyShapeAndDtype:
    @settings(max_examples=20, deadline=None)
    @given(
        years=st.integers(min_value=1, max_value=40),
        n_paths=st.integers(min_value=1, max_value=32),
        block_months=st.integers(min_value=1, max_value=24),
    )
    def test_shape_and_dtype_invariants(self, years: int, n_paths: int, block_months: int) -> None:
        model = _model(n_months=240, block_months=block_months, seed=years * 17 + n_paths)
        result = model.sample_paths(years=years, n_paths=n_paths)
        for arr in (*result.asset_log_returns.values(), *result.inflation_log.values()):
            assert arr.shape == (n_paths, years)
            assert arr.dtype == np.float64
        # Labels are preserved.
        assert set(result.asset_log_returns.keys()) == set(model.asset_returns.keys())
        assert set(result.inflation_log.keys()) == set(model.inflation.keys())
