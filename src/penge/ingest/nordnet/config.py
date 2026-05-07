"""Account → entity mapping config loader.

Real exports contain account numbers but no owner identity, so the
loader reads a YAML file mapping each Nordnet `kontonummer` to the
local `entity` name and the canonical account kind. A sample file
is committed at `config/nordnet-accounts.example.yaml`; the real
file (`config/nordnet-accounts.yaml`) is gitignored.

YAML shape:

```yaml
accounts:
  - number: "60109543"
    entity: "Rouven"
    kind: aktiedepot
    currency: DKK
    name: "Aktiedepot"
```
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from penge.ingest.nordnet.constants import ACCOUNT_KINDS


class AccountConfig(BaseModel):
    """One Nordnet account entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    entity: str
    kind: str
    currency: str = "DKK"
    name: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind_is_known(cls, v: str) -> str:
        if v not in ACCOUNT_KINDS:
            raise ValueError(f"unknown account.kind {v!r}; expected one of {sorted(ACCOUNT_KINDS)}")
        return v

    @field_validator("currency")
    @classmethod
    def _currency_is_iso4217_ish(cls, v: str) -> str:
        if len(v) != 3 or not v.isalpha() or not v.isupper():
            raise ValueError(f"currency must be a 3-letter ISO code, got {v!r}")
        return v


class AccountsConfig(BaseModel):
    """Top-level config object — list of `AccountConfig` entries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounts: tuple[AccountConfig, ...] = Field(default_factory=tuple)

    def by_number(self, number: str) -> AccountConfig | None:
        """Look up an account by its Nordnet kontonummer.

        Returns ``None`` if not configured. Callers wanting a hard
        error should raise :class:`UnknownAccountError` instead.
        """

        for entry in self.accounts:
            if entry.number == number:
                return entry
        return None

    @field_validator("accounts")
    @classmethod
    def _no_duplicate_numbers(cls, v: tuple[AccountConfig, ...]) -> tuple[AccountConfig, ...]:
        seen: set[str] = set()
        for entry in v:
            if entry.number in seen:
                raise ValueError(f"duplicate account number {entry.number!r}")
            seen.add(entry.number)
        return v


def load_accounts_config(path: str | Path) -> AccountsConfig:
    """Read and validate the accounts YAML file.

    Raises :class:`ValueError` for malformed YAML and Pydantic
    `ValidationError` for shape violations.
    """

    raw = Path(path).read_text(encoding="utf-8")
    data: Any = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping, got {type(data).__name__}")
    return AccountsConfig.model_validate(data)
