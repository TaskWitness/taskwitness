"""TaskWitness: an independent, sensor-grounded verification layer for Physical AI."""

__version__ = "0.2.0"

from taskwitness.api import Verdict, judge, verify_episode  # noqa: E402

__all__ = ["Verdict", "__version__", "judge", "verify_episode"]
