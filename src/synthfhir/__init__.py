"""SynthFHIR — validierte, deutsch lokalisierte synthetische FHIR-R4-Testdaten.

Architektur (ADR-001): Das Sprachmodell liefert ausschließlich klinische
Inhalte als flaches Parameterobjekt. Struktur, Pflichtfelder, Datentypen,
Codes und Einheiten kommen aus deterministischem Code — aus Vorlagen und
einem festen Katalog.

WARNUNG: Alle erzeugten Daten sind synthetische Testdaten und ausdrücklich
NICHT für die klinische Nutzung bestimmt.
"""

__version__ = "0.1.0"
