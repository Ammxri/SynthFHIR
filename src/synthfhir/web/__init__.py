"""Die Weboberfläche des MVP.

Das Modul heißt `oberflaeche` und nicht `app`, damit `synthfhir.web.app`
eindeutig die FastAPI-Instanz bezeichnet. Hießen beide gleich, verdeckte
der Export das Modul — was das Testen der Routen unnötig erschwert.
"""

from .oberflaeche import app

__all__ = ["app"]
