"""LatticeD v2 — parallel architecture.

See V2_ARCHITECTURE.md at the repo root for the why and the layer map.

Brief: the 1.5B model is one component (the narrator) in an agent that
does knowledge, perception, reasoning, generation, verification, and
reflection as separate layers. Built parallel to v1; v1 keeps serving
real traffic until the v2 A/B gate is met.
"""
__all__ = ["kstore"]
