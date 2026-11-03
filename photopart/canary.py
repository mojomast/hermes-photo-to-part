"""Canary string embedded in eval files.

A git install of this repository still copies ``evals/`` (see the README).
The scorer and the ``post_tool_call`` hook treat a transcript or a tool
argument that contains this string as a leak. The string is not a secret.
"""

EVAL_CANARY = "p2p-canary-7f3a9c2e-6b14-4d88-a1e0-9c5d2f8b4a17"
