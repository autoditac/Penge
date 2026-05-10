"""CLI entry point for the vault watcher.

Examples::

    # Foreground watch loop with metrics on :9101
    penge-vault watch ~/Nextcloud/Finance/inbox ~/Nextcloud/Finance/vault \\
        --health-port 9101

    # Drain the inbox once and exit (handy for cron / CI)
    penge-vault watch ./inbox ./vault --once

    # Override OCR languages (default: dan+deu+eng)
    penge-vault watch ./inbox ./vault --ocr-langs eng

The default ``--health-port`` is ``0`` which binds an ephemeral port and
prints it on startup. ``PENGE_VAULT_HEALTH_PORT`` is honoured as a
fallback when the flag is omitted.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from penge.ops.sentry import init_sentry
from penge.vault.ocr import DEFAULT_LANGS, OCRConfig
from penge.vault.watcher import VaultWatcher, WatcherConfig

log = logging.getLogger("penge.vault")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="penge-vault",
        description="Watch a Nextcloud-synced inbox and OCR + file documents into the vault.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="Watch INBOX and file documents into VAULT_ROOT.")
    watch.add_argument("inbox", type=Path, help="Inbox directory to watch (created if missing).")
    watch.add_argument("vault_root", type=Path, help="Vault root directory (created if missing).")
    watch.add_argument(
        "--ocr-langs",
        default=DEFAULT_LANGS,
        help=f"Tesseract --lang argument (default: {DEFAULT_LANGS}).",
    )
    watch.add_argument("--ocr-dpi", type=int, default=300, help="Rasterisation DPI (default: 300).")
    watch.add_argument(
        "--scan-interval",
        type=float,
        default=5.0,
        help="Periodic inbox re-scan interval in seconds (default: 5.0).",
    )
    watch.add_argument(
        "--stable-for",
        type=float,
        default=2.0,
        help="Wait this long for size/mtime to settle before OCR (default: 2.0s).",
    )
    watch.add_argument(
        "--health-host",
        default="127.0.0.1",
        help="Bind address for /health and /metrics (default: 127.0.0.1).",
    )
    watch.add_argument(
        "--health-port",
        type=int,
        default=int(os.environ.get("PENGE_VAULT_HEALTH_PORT", "0")),
        help="Port for /health and /metrics (default: $PENGE_VAULT_HEALTH_PORT or ephemeral).",
    )
    watch.add_argument(
        "--once",
        action="store_true",
        help="Process every file currently in the inbox and exit (no watch loop).",
    )
    watch.add_argument(
        "--classifier-config",
        type=Path,
        default=None,
        help=(
            "Path to a custom classifier YAML. Defaults to the rules bundled "
            "with the package (penge.vault.classifier_rules.yaml)."
        ),
    )
    watch.add_argument("--verbose", action="store_true", help="Enable DEBUG logging on stderr.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    init_sentry(component="vault-watcher")

    config = WatcherConfig(
        inbox=args.inbox,
        vault_root=args.vault_root,
        ocr=OCRConfig(langs=args.ocr_langs, dpi=args.ocr_dpi),
        scan_interval_s=args.scan_interval,
        stable_for_s=args.stable_for,
        health_host=args.health_host,
        health_port=args.health_port,
        classifier_config_path=args.classifier_config,
    )
    watcher = VaultWatcher(config)

    if args.once:
        results = watcher.process_inbox_once()
        for r in results:
            action = "duplicate" if r.duplicate else "filed"
            print(f"{action}\t{r.sha256[:12]}\t{r.filed_path or '-'}")
        return 0

    print(
        f"penge-vault watching inbox={config.inbox} vault={config.vault_root} "
        f"health=http://{config.health_host}:{watcher.health_port or config.health_port}/metrics",
        file=sys.stderr,
    )
    watcher.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
