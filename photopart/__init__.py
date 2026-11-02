"""Local mesh helpers for the photo-to-part Hermes plugin.

The plugin process itself only registers a skill. These modules run when an
agent or a person executes the helper scripts. They read the files they are
given and write STL, 3MF, PNG, and JSON. They do not open network connections.
"""

__version__ = "0.1.0"
