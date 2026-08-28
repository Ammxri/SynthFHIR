"""Der Domänenkern: Katalog, Vorlagen, Identität, Referenzintegrität.

Dieser Teil enthält die Garantien des Produkts und hängt bewusst **nicht**
vom Sprachmodell, von HTTP oder von einer Web-Schicht ab. Er ist rein
deterministisch und damit vollständig testbar.
"""

from .codes import CONDITION_CODES, OBSERVATION_CODES, ConditionCode, ObservationCode
from .identity import assign_ids
from .integrity import check_resources
from .templates import Bauergebnis, baue_aus_parametern, baue_bundle

__all__ = [
    "CONDITION_CODES",
    "OBSERVATION_CODES",
    "ConditionCode",
    "ObservationCode",
    "Bauergebnis",
    "assign_ids",
    "baue_aus_parametern",
    "baue_bundle",
    "check_resources",
]
