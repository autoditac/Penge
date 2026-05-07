"""ECB daily reference FX rates loader.

Source: European Central Bank ``eurofxref`` XML feed. EUR is always the base
currency; the feed publishes one row per quote currency per business day.

- ``eurofxref-daily.xml``: latest business day only (small, ~1KB).
- ``eurofxref-hist-90d.xml``: trailing 90 days.
- ``eurofxref-hist.xml``: full history since 1999 (~5MB).

The loader is pure-stdlib for the network/XML side (``urllib`` +
``xml.etree``); the database side uses SQLAlchemy core for an idempotent
``INSERT ... ON CONFLICT DO UPDATE`` against the ``fx_rate`` table.

Public API (see ``loader`` submodule):

- ``fetch(feed)`` — return raw bytes for one of the three feeds.
- ``parse(xml_bytes)`` — yield ``ParsedRate`` records (no IO).
- ``upsert(engine, rates)`` — write to ``fx_rate``, returning a count.
- ``run(feed, engine)`` — convenience: fetch + parse + upsert.
"""

from .loader import (
    Feed,
    ParsedRate,
    fetch,
    parse,
    run,
    upsert,
)

__all__ = ["Feed", "ParsedRate", "fetch", "parse", "run", "upsert"]
