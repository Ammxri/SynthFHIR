"""Erlaubt den Aufruf via `python -m synthfhir`."""

from .cli import main

raise SystemExit(main())
