"""Observation vocabulary shared by derived understanding and spatial evidence."""

from typing import Literal

ObservationModality = Literal[
    "event_observed",
    "character_statement",
    "belief",
    "hypothesis",
    "author_plan",
    "figurative",
    "unclear",
]
