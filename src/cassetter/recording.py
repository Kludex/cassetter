from __future__ import annotations

import enum


class RecordMode(enum.Enum):
    """Controls how cassette recording/playback behaves."""

    NONE = enum.auto()
    """Never record - only replay from existing cassettes. Raises if no match found."""

    NEW_EPISODES = enum.auto()
    """Replay existing interactions. Record new ones that don't match."""

    ALL = enum.auto()
    """Record all interactions, overwriting any existing cassette."""

    ONCE = enum.auto()
    """Record if cassette doesn't exist. Replay if it does."""

    REWRITE = enum.auto()
    """Delete the cassette up front, then record everything. A run that records nothing leaves no file."""

    @classmethod
    def from_str(cls, value: str) -> RecordMode:
        mapping = {
            "none": cls.NONE,
            "new_episodes": cls.NEW_EPISODES,
            "all": cls.ALL,
            "once": cls.ONCE,
            "rewrite": cls.REWRITE,
        }
        normalized = value.lower().replace("-", "_")
        if normalized not in mapping:
            raise ValueError(f"unknown record mode: {value!r}, expected one of {list(mapping)}")
        return mapping[normalized]
