"""Historical block-bootstrap return / inflation model.

See ADR-0010 for the modelling rationale. In short:

- Annual asset returns and inflation are produced by sampling contiguous
  blocks of ``block_months`` real months from a joint monthly history,
  concatenating until the target horizon is reached, and summing each
  consecutive 12 monthly log returns into an annual log return.
- A single sequence of month indices is drawn per path and applied to
  every asset class and inflation series, which preserves the empirical
  cross-asset and inflation/return correlation within each block.
- ``block_months = 1`` reduces to an IID monthly bootstrap.

The public contract is intentionally narrow: the model holds an immutable
config (validated at construction via Pydantic) and exposes a single
:meth:`BootstrapReturnModel.sample_paths` method. Numeric work is done in
``float64`` inside the kernel; the Decimal inputs at the config boundary
are documented at ADR-0010 and at the relevant fields below.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReturnModelError(ValueError):
    """Raised when the return-model configuration or a sampling request is invalid."""


_MONTHS_PER_YEAR = 12

# Public input shape: any mapping of label -> sequence of Decimals. The
# pre-validator additionally coerces ``int``/``float``/numeric ``str`` for
# convenience at the YAML / hand-written-config boundary.
_HistoryInput = Mapping[str, Sequence[Decimal]]
_History = dict[str, tuple[Decimal, ...]]


@dataclass(frozen=True, slots=True)
class SampledPaths:
    """Output of :meth:`BootstrapReturnModel.sample_paths`.

    Attributes:
        asset_log_returns: Per-asset-class array of annual log returns,
            shape ``(n_paths, years)``.
        inflation_log: Per-country array of annual log inflation, same
            shape as ``asset_log_returns``.
        seed: The RNG seed used to produce these paths. Re-running with
            the same seed and the same model config reproduces the
            arrays bit-for-bit.
        block_months: The block length used during sampling.
        history_hash: SHA-256 of the canonicalised input history. Two
            models with identical histories share the same hash; any
            change to a single number changes it.
    """

    asset_log_returns: dict[str, np.ndarray] = field()
    inflation_log: dict[str, np.ndarray] = field()
    seed: int = field()
    block_months: int = field()
    history_hash: str = field()


class BootstrapReturnModel(BaseModel):
    """Block-bootstrap return / inflation model (ADR-0010, issue #26).

    The model is reproducible: ``BootstrapReturnModel(...).sample_paths(
    years=Y, n_paths=N)`` returns identical arrays across runs given the
    same ``seed``, ``block_months``, and input history.

    Inputs are monthly *log* returns / *log* inflation as Decimal
    sequences, so that exact rationals from the ingestion layer survive
    config validation. Internally the kernel converts to ``float64``
    once at the start of :meth:`sample_paths`; this is the documented
    boundary between the audit-grade Decimal layer (amounts, FX,
    statutory rates) and the numeric simulation layer (log returns are
    dimensionless ratios).

    Args:
        asset_returns: Mapping from asset-class label (e.g.
            ``"msci_world_eur"``) to its monthly log-return history.
        inflation: Mapping from country label (e.g. ``"de"``, ``"dk"``)
            to its monthly log-inflation history.
        block_months: Length of each contiguous block, in months.
            ``1`` reduces the model to an IID monthly bootstrap. Must
            satisfy ``1 <= block_months <= T`` where ``T`` is the
            shared length of all input series.
        seed: Seed for ``numpy.random.default_rng``. Defaults to ``0``.
    """

    asset_returns: _HistoryInput
    inflation: _HistoryInput
    block_months: int = Field(default=12, ge=1)
    seed: int = 0

    model_config = ConfigDict(frozen=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @field_validator("asset_returns", "inflation", mode="before")
    @classmethod
    def _coerce_history(cls, value: object) -> _History:
        """Coerce dict-of-iterables-of-numbers to dict-of-tuple-of-Decimal.

        Accepts inputs where values are any non-string iterable of numbers
        (``Decimal``, ``int``, ``float``, or numeric strings) so that
        both YAML-configured callers and tests can write naturally.
        Rejects ``str``/``bytes`` series eagerly: a single string would
        otherwise iterate as characters and silently parse into a series
        of digits. Rejects non-finite values (NaN/Infinity) to keep
        them out of the NumPy kernel where they would silently
        contaminate every sampled path.
        """
        if not isinstance(value, Mapping):
            raise ReturnModelError(
                f"history must be a mapping of label -> sequence, got {type(value).__name__}"
            )
        out: _History = {}
        for label, raw in value.items():
            if not isinstance(label, str):
                raise ReturnModelError(
                    f"history label must be a string, got {type(label).__name__}"
                )
            if isinstance(raw, str | bytes | bytearray):
                raise ReturnModelError(
                    f"history series '{label}' must be a non-string sequence, "
                    f"got {type(raw).__name__}"
                )
            try:
                series = tuple(Decimal(str(x)) for x in raw)
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise ReturnModelError(
                    f"history series '{label}' contains a non-numeric entry"
                ) from exc
            for entry in series:
                if not entry.is_finite():
                    raise ReturnModelError(
                        f"history series '{label}' contains a non-finite entry ({entry})"
                    )
            out[label] = series
        return out

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if not self.asset_returns:
            raise ReturnModelError("asset_returns must contain at least one series")
        if not self.inflation:
            raise ReturnModelError("inflation must contain at least one series")

        lengths = {len(s) for s in self.asset_returns.values()} | {
            len(s) for s in self.inflation.values()
        }
        if len(lengths) != 1:
            raise ReturnModelError(
                f"all history series must share the same length, got lengths {sorted(lengths)}"
            )
        (history_len,) = lengths
        if history_len < _MONTHS_PER_YEAR:
            raise ReturnModelError(
                f"history must contain at least {_MONTHS_PER_YEAR} months, got {history_len}"
            )
        if self.block_months > history_len:
            raise ReturnModelError(
                f"block_months ({self.block_months}) must be <= history length ({history_len})"
            )
        return self

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def history_months(self) -> int:
        """Shared length of every input history series."""
        return len(next(iter(self.asset_returns.values())))

    def history_hash(self) -> str:
        """Stable SHA-256 of the canonicalised input history.

        Stable across Python invocations: keys are sorted and Decimals
        are normalised via :py:meth:`Decimal.normalize` before being
        serialised, so numerically-equal but textually-different inputs
        (``Decimal("1")`` vs ``Decimal("1.0")``) hash identically. The
        hash changes iff a numeric value, label, or series length
        changes.
        """
        hasher = hashlib.sha256()
        for kind, series_dict in (
            ("asset_returns", self.asset_returns),
            ("inflation", self.inflation),
        ):
            hasher.update(kind.encode("utf-8"))
            hasher.update(b"\x00")
            for label in sorted(series_dict.keys()):
                hasher.update(label.encode("utf-8"))
                hasher.update(b"\x00")
                for value in series_dict[label]:
                    hasher.update(str(value.normalize()).encode("utf-8"))
                    hasher.update(b"\x00")
                hasher.update(b"\x01")
        return hasher.hexdigest()

    def sample_paths(self, *, years: int, n_paths: int) -> SampledPaths:
        """Sample ``n_paths`` joint paths of length ``years``.

        Args:
            years: Number of annual rows per path. Must be ``>= 1``.
            n_paths: Number of independent paths. Must be ``>= 1``.

        Returns:
            A :class:`SampledPaths` whose arrays have shape
            ``(n_paths, years)``.

        Raises:
            ReturnModelError: If ``years`` or ``n_paths`` is below 1.
        """
        if years < 1:
            raise ReturnModelError(f"years must be >= 1, got {years}")
        if n_paths < 1:
            raise ReturnModelError(f"n_paths must be >= 1, got {n_paths}")

        history_len = self.history_months
        block_months = self.block_months
        months_needed = years * _MONTHS_PER_YEAR
        n_blocks = (months_needed + block_months - 1) // block_months

        rng = np.random.default_rng(self.seed)
        # Each block start is a uniform draw in [0, history_len - block_months].
        # +1 because the upper bound of np.random.Generator.integers is exclusive.
        starts = rng.integers(
            low=0,
            high=history_len - block_months + 1,
            size=(n_paths, n_blocks),
        )
        offsets = np.arange(block_months)
        # Broadcast: per (path, block), generate the consecutive month indices.
        idx = starts[:, :, None] + offsets[None, None, :]
        idx = idx.reshape(n_paths, n_blocks * block_months)[:, :months_needed]

        return SampledPaths(
            asset_log_returns=self._sample_series(self.asset_returns, idx, years),
            inflation_log=self._sample_series(self.inflation, idx, years),
            seed=self.seed,
            block_months=block_months,
            history_hash=self.history_hash(),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _sample_series(
        history: Mapping[str, Sequence[Decimal]],
        idx: np.ndarray,
        years: int,
    ) -> dict[str, np.ndarray]:
        """Slice each series with ``idx`` and aggregate to annual log returns."""
        n_paths = idx.shape[0]
        out: dict[str, np.ndarray] = {}
        for label, series in history.items():
            arr = np.fromiter((float(d) for d in series), dtype=np.float64, count=len(series))
            monthly = arr[idx]  # (n_paths, years * months_per_year)
            annual = monthly.reshape(n_paths, years, _MONTHS_PER_YEAR).sum(axis=2)
            out[label] = annual
        return out
