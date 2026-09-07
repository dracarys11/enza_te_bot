"""WING exploration helpers (Phase A: HOME observation only).

This package is read-only orchestration for human-in-the-loop exploration.
It must never import or invoke executor, ActionBoundary, or any input
injection; `test_explore_home` guards that boundary statically.
"""
