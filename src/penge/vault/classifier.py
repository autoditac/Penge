"""Rule-based document classifier for the vault (issue #42).

The classifier is intentionally *boring*: a YAML file at
``config/vault-classifier.yaml`` lists regex patterns per category,
and :func:`classify` returns the highest-scoring category whose
confidence clears the configured threshold. Documents that do not
clear the threshold are routed to ``unsorted`` and bumped on the
``vault_unclassified_total`` Prometheus counter so they show up in
manual triage.

Why rules instead of ML?

* The set of categories is small (10) and stable.
* Real fixtures are scarce and synthetic ones are easy to generate.
* The decision must be *auditable* — a YAML diff is reviewable, a
  fine-tuned model is not.

A future ML classifier (issue #42 follow-up) can plug in next to this
module by exposing the same :class:`Classification` dataclass.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Bucket used when no rule fires above ``min_confidence``. Matches
#: :data:`penge.vault.filer.UNSORTED_TYPE` and the existing on-disk
#: layout from PR #107.
UNSORTED_CATEGORY = "unsorted"

#: Default location of the rules YAML, relative to the repository root.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "vault-classifier.yaml"


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one document.

    Attributes:
        category: The winning category, or :data:`UNSORTED_CATEGORY`
            if no category cleared ``min_confidence``.
        confidence: Score of the winning category in ``[0.0, 1.0]``,
            computed as ``matches / total_patterns_for_category``.
            For ``UNSORTED_CATEGORY`` this is the *best* score that
            still failed to clear the threshold (or ``0.0`` if no
            pattern matched at all).
        matched_rules: Patterns (as written in YAML) that fired for
            the winning category. Empty for ``UNSORTED_CATEGORY``
            unless a partial match was the best signal.
    """

    category: str
    confidence: float
    matched_rules: tuple[str, ...]


class _CategoryRules(BaseModel):
    """Compiled regex rules for one category."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    patterns: tuple[str, ...]
    compiled: tuple[re.Pattern[str], ...]


class ClassifierConfig(BaseModel):
    """Validated representation of ``vault-classifier.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    min_confidence: float = Field(
        default=0.33,
        gt=0.0,
        le=1.0,
        description="Minimum (matches/total) score for a category hit to win.",
    )
    rules: tuple[_CategoryRules, ...] = Field(default_factory=tuple)

    @field_validator("rules")
    @classmethod
    def _no_empty_categories(cls, v: tuple[_CategoryRules, ...]) -> tuple[_CategoryRules, ...]:
        for entry in v:
            if not entry.patterns:
                raise ValueError(f"category {entry.name!r} has no patterns")
        return v


def _compile_rules(name: str, patterns: list[str]) -> _CategoryRules:
    compiled = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    return _CategoryRules(name=name, patterns=tuple(patterns), compiled=compiled)


def load_config(path: str | Path | None = None) -> ClassifierConfig:
    """Read and validate the classifier YAML.

    Args:
        path: Optional override; defaults to :data:`DEFAULT_CONFIG_PATH`.

    Raises:
        ValueError: If the YAML shape is invalid or a regex fails to
            compile.
    """

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = config_path.read_text(encoding="utf-8")
    data: Any = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{config_path}: top-level YAML must be a mapping, got {type(data).__name__}"
        )

    categories: Any = data.get("categories", {}) or {}
    if not isinstance(categories, dict):
        raise ValueError(f"{config_path}: 'categories' must be a mapping")

    rules: list[_CategoryRules] = []
    for name, patterns in categories.items():
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ValueError(
                f"{config_path}: category {name!r} must map to a list of regex strings"
            )
        try:
            rules.append(_compile_rules(str(name), list(patterns)))
        except re.error as exc:
            raise ValueError(f"{config_path}: invalid regex in {name!r}: {exc}") from exc

    return ClassifierConfig(
        min_confidence=float(data.get("min_confidence", 0.33)),
        rules=tuple(rules),
    )


@functools.lru_cache(maxsize=1)
def _default_config() -> ClassifierConfig:
    return load_config()


def classify(text: str, *, config: ClassifierConfig | None = None) -> Classification:
    """Classify *text* into one of the configured categories.

    Args:
        text: OCR output (or any plain text) for the document. The
            classifier lowercases it once and runs every category's
            regexes against the result.
        config: Optional pre-loaded :class:`ClassifierConfig`. Defaults
            to the cached YAML at :data:`DEFAULT_CONFIG_PATH`.

    Returns:
        :class:`Classification` describing the winning category, its
        confidence, and the patterns that fired. If no category clears
        ``min_confidence``, the result's category is
        :data:`UNSORTED_CATEGORY` and ``confidence`` reports the best
        sub-threshold score.
    """

    cfg = config or _default_config()
    haystack = text.lower()

    best_score = 0.0
    best_name = UNSORTED_CATEGORY
    best_matches: tuple[str, ...] = ()

    for category in cfg.rules:
        hits: list[str] = []
        for pattern, compiled in zip(category.patterns, category.compiled, strict=True):
            if compiled.search(haystack):
                hits.append(pattern)
        if not hits:
            continue
        score = len(hits) / len(category.patterns)
        if score > best_score:
            best_score = score
            best_name = category.name
            best_matches = tuple(hits)

    if best_score < cfg.min_confidence:
        return Classification(
            category=UNSORTED_CATEGORY,
            confidence=best_score,
            matched_rules=best_matches,
        )

    return Classification(
        category=best_name,
        confidence=best_score,
        matched_rules=best_matches,
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "UNSORTED_CATEGORY",
    "Classification",
    "ClassifierConfig",
    "classify",
    "load_config",
]
