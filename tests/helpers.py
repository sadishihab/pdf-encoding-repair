"""Shared helpers. Every test string is built here from known English text."""

from __future__ import annotations


def corrupt(text: str, offset: int) -> str:
    """Shift every character by -offset, mirroring how the corruption encodes
    text (repair then needs to find +offset to undo it)."""
    return "".join(chr(ord(c) - offset) for c in text)


CLEAN_SENTENCES = [
    "The unit will shut off when the timer has run out.",
    "QUICK REFERENCE TIPS",
    "Press and hold the START button for three seconds.",
    "system",
    "MAIN SWITCH",
]

# Known plain-English sentences (each clears every gate once repaired).
PLAIN_LINES = [
    "Turn off the power before you start the service.",
    "Check the filter and replace it if it is blocked.",
    "Press the button to reset the system after the error.",
    "Remove the rack and clean the door with water.",
    "Call for service if the problem is not solved.",
    "Make sure the light is on before you run the test.",
    "Open the door and check the display for a code.",
]
