"""The link to the GFX Engine: one copy for every part of SCC Broadcast
Engine, in scc_shared/enginelink.py (make changes there). This name stays so
the HUD's code (from .enginelink import EngineLink, ...) works as it did."""

import sys

from scc_shared import enginelink as _shared

sys.modules[__name__] = _shared
