"""Local mesh helpers for the photo-to-part Hermes plugin.

Hermes loads the tools inside the plugin environment, which is where trimesh
is installed. The helper scripts re-exec into that environment when they are
started with a Python that cannot import it. The tools read the paths they
are given and write STL, 3MF, PNG, and JSON. They do not open network
connections.
"""

__version__ = "0.1.7"
