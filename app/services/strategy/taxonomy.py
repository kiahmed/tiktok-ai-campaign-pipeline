"""Controlled vocabulary for creative strategy.

Keeping hook types and angles to a fixed taxonomy is what makes "overused" and
"high-performing" computable: the system can count, rank, exclude and explore
across a known set instead of free-text labels that never line up.
"""
from __future__ import annotations

# How the first 1-2 seconds grab attention.
HOOK_TYPES: list[str] = [
    "question",          # "Ever notice your part line getting wider?"
    "shock_stat",        # "I lost 40% of my hair in 3 months."
    "before_after",      # "Day 1 vs Day 90."
    "pov",               # "POV: you finally found something that works."
    "testimonial",       # "My hairdresser asked what I changed."
    "problem_callout",   # "If your hair is thinning, watch this."
    "pattern_interrupt", # "Stop scrolling and look at this."
]

# The persuasive frame of the whole script.
ANGLES: list[str] = [
    "social_proof",       # everyone's using it / reviews
    "transformation",     # the visible result
    "problem_agitate",    # twist the pain before relief
    "ingredient_focus",   # why the formula works
    "founder_story",      # authentic origin / mission
    "scarcity",           # limited / selling out
    "myth_bust",          # "you don't need X, you need Y"
    "comparison",         # vs the thing they're using now
    "routine_simplicity", # how easy it is to use
]
