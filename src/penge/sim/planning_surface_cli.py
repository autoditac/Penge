"""JSON CLI for the explanation-first household planning surface."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from penge.sim.planning_surface import (
    PlanningSurfaceError,
    PlanningSurfaceRequest,
    generate_planning_surface,
)

__all__ = ["main"]


def _read_stdin_json() -> object:
    text = sys.stdin.read()
    if not text.strip():
        raise PlanningSurfaceError("no JSON received on stdin")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanningSurfaceError(f"input is not valid JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="penge-sim-planning-surface",
        description="Generate an explanation-first household planning surface as JSON.",
    )
    parser.parse_args(argv)

    try:
        request = PlanningSurfaceRequest.model_validate(_read_stdin_json())
        report = generate_planning_surface(request)
    except PlanningSurfaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        print(f"error: invalid input: {details}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - last-resort CLI guard
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(report.model_dump_json())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
