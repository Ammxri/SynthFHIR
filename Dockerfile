# Betriebsabbild der Weboberflaeche.
#
# Bewusst schlank: Das Produkt spricht im Betrieb nicht mit HAPI (ADR-002),
# es braucht also weder Java noch einen zweiten Dienst. Die Validierung zur
# Laufzeit erledigen die Pydantic-Modelle von fhir.resources.
FROM python:3.13-slim

# Kein .pyc-Muell, Ausgabe sofort im Log statt gepuffert.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Erst die Abhaengigkeiten, dann der Code: So bleibt die Abhaengigkeits-
# schicht im Cache, solange sich pyproject.toml nicht aendert.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Nicht als root laufen.
RUN useradd --create-home --uid 10001 synthfhir
USER synthfhir

# Der Anbieter gibt den Port ueber die Umgebung vor; 8000 ist die
# Rueckfallebene fuer den lokalen Start.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn synthfhir.web:app --host 0.0.0.0 --port ${PORT}"]
