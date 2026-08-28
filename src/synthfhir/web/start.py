"""Startbefehl für die Entwicklung.

Im Betrieb startet der Hosting-Anbieter uvicorn direkt:
    uvicorn synthfhir.web:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    import uvicorn

    uvicorn.run(
        "synthfhir.web:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("SYNTHFHIR_RELOAD", "").strip() in ("1", "true"),
    )


if __name__ == "__main__":
    main()
