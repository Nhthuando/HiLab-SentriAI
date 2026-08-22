"""Dataset materialization and fine-tuning runtime package.

Keep package imports deliberately light: ``runner`` is executed with
``python -m training.runner`` by the Node API, and importing it here causes
Python to load the module twice before it starts.
"""

from .dataset_exporter import materialize

__all__ = ["materialize"]
