class GaudiError(Exception):
    """Expected, user-facing failure. CLI prints the message and exits non-zero."""


class ShipError(GaudiError):
    """Map would ship in an artifact or Docker context."""
