"""docs-drift: Hermes plugin entry point. The implementation lives in ``docsdrift/``."""

from .docsdrift.hermes_plugin import register

__all__ = ["register"]
