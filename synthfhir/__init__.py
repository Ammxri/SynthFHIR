"""SynthFHIR – Phase-0-Validierungs-Spike.

Zweck: Vergleich zweier Architekturvarianten für die Erzeugung synthetischer
FHIR-R4-Ressourcen (Variante A: LLM erzeugt FHIR direkt, Variante B: LLM
erzeugt nur Parameter, deterministischer Code baut FHIR aus Vorlagen).

Der Code ist bewusst Wegwerf-Code mit Erkenntniswert: optimiert auf
Nachvollziehbarkeit und Messbarkeit, nicht auf Wiederverwendbarkeit.

WARNUNG: Alle erzeugten Daten sind synthetische Testdaten und ausdrücklich
NICHT für die klinische Nutzung bestimmt.
"""

__version__ = "0.1.0"
