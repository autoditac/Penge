"""Entry point: ``python -m penge.tax`` invokes the tax-year CLI."""

from penge.tax.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
