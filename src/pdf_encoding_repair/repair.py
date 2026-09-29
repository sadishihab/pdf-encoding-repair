"""Repair text runs corrupted by a constant character-code offset.

Some PDF fonts ship a ToUnicode/CMap that decodes text with every character
shifted by a constant code offset from its real value. For example,
"Filter cartridge" comes out as ")LOWHU\\x03FDUWULGJH" (every character
shifted by -29; add 29 back to repair). Different documents use different
offsets, so the offset is inferred per run rather than hardcoded.

Detection signal: real body text never contains raw control characters
(codepoints < 32, excluding tab/newline/CR). Corrupted runs do -- the shift
lands their space character in the control range -- which is both how a run
is flagged as corrupted and a strong, near-exact clue to the offset itself
(that control byte should decode to an ASCII space, 0x20).

Offset inference combines two signals:
  1. Exact candidates from any control characters present (candidate = 32 -
     ord(control_char)).
  2. A brute-force sweep as a fallback for a corrupted run that happens not
     to contain its space substitute (e.g. a single word with no space).

A candidate offset is only accepted if the shifted text clears three
independent, no-dictionary-required bars (see `_passes_gates`):
  - almost entirely letters and spaces (a wrong offset reliably produces
    control characters or other symbol noise);
  - a plausible English letter-frequency profile (average log-likelihood of
    each letter under standard English letter frequencies);
  - at least a little real common-word content (catches the case where a
    short random string's letter frequencies look plausible by chance but it
    contains no recognizable words).
Requiring all three (not a single blended score) is what correctly rejects a
run that mixes already-clean text with a corrupted suffix -- shifting the
whole run by any single offset corrupts the clean part, which reliably fails
the noise gate for every candidate, so the run is left untouched rather than
"fixed" into something worse.

Token-level repair handles that mixed case. A line like "14 or 1' or O1" never
gets whole-run repaired, because "or" is already clean English. But "14",
"1'" and "O1" are themselves corrupted, just too short for word matching or
letter-frequency scoring to judge on their own. `infer_dominant_offset`
first confirms, from the many already-repaired lines in a document, which
single offset the document uses (only proceeding if one offset clearly
dominates -- token-level repair never runs on an offset guessed from a
single short token). `repair_line_tokens` then re-scans lines that whole-run
repair skipped, token by token, against that one already-trusted offset.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Standard English letter frequencies (percent). Used for a classical
# cipher-breaking-style average log-likelihood score -- no dictionary needed.
_ENGLISH_LETTER_FREQ_PERCENT = {
    "e": 12.70,
    "t": 9.06,
    "a": 8.17,
    "o": 7.51,
    "i": 6.97,
    "n": 6.75,
    "s": 6.33,
    "h": 6.09,
    "r": 5.99,
    "d": 4.25,
    "l": 4.03,
    "c": 2.78,
    "u": 2.76,
    "m": 2.41,
    "w": 2.36,
    "f": 2.23,
    "g": 2.02,
    "y": 1.97,
    "p": 1.93,
    "b": 1.29,
    "v": 0.98,
    "k": 0.77,
    "j": 0.15,
    "x": 0.15,
    "q": 0.10,
    "z": 0.07,
}
_LOG_FREQ = {c: math.log(f / 100) for c, f in _ENGLISH_LETTER_FREQ_PERCENT.items()}
_LOG_FREQ_FLOOR = math.log(0.01 / 100)

# A small set of very common short English words, used only to confirm a
# candidate decoding contains real words -- not a real dictionary.
_COMMON_WORDS = frozenset(
    """
    the and to of a in is you for on not with your it or if this be will
    are at call check water door power test time before installed filter
    cartridge install reinstall turn off that into from after service
    dryer washer may can has have make sure system error code press
    button dispenser drying rack solution cause possible problem replace
    clean light display control unit section page instructions when
    where what how does do did been being was were start pause stop reset
    long short high low open close blocked restricted damaged normal
    airflow circuit avoid check remove using used run runs multiple more
    less than out about above below every each other than only very
    """.split()
)

_IGNORED_CONTROL_CHARS = {"\t", "\n", "\r"}

MIN_RUN_LENGTH = 6
_OFFSET_SWEEP = range(-40, 41)

# Hard acceptance gates: a wrong offset applied to a corrupted run, or any
# offset applied to short/random noise, reliably fails at least one of these.
_MAX_NOISE_RATIO = 0.10
_MIN_LETTER_FREQ_SCORE = -3.0
_MIN_COMMON_WORD_SCORE = 4


@dataclass
class RepairResult:
    """Result of attempting to repair one text run.

    `text` is the repaired text when `was_repaired` is True, otherwise the
    original, untouched input. `confidence` (0.0-1.0) is only meaningful
    when `was_repaired` is True -- callers can use it to flag low-confidence
    repairs rather than trusting every accepted repair equally.
    """

    text: str
    was_repaired: bool
    offset: int | None = None
    confidence: float = 0.0


def _has_stray_control_char(text: str) -> bool:
    return any(ord(c) < 32 and c not in _IGNORED_CONTROL_CHARS for c in text)


def _vowel_ratio(text: str) -> float:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c in "aeiou") / len(letters)


def is_suspicious_run(text: str) -> bool:
    """Best-effort, no-dictionary-required check that a run looks corrupted.

    Primary signal: a stray control character. Fallback signal (for a
    corrupted run that never happens to include its space substitute): real
    English text has a letter-level vowel ratio roughly between 0.28 and
    0.60; text shifted by an arbitrary constant essentially never does.
    """
    stripped = text.strip()
    if len(stripped) < MIN_RUN_LENGTH:
        return False
    if _has_stray_control_char(text):
        return True
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < MIN_RUN_LENGTH:
        return False
    return not (0.28 <= _vowel_ratio(stripped) <= 0.60)


def _shift(text: str, offset: int) -> str:
    def shift_char(c: str) -> str:
        code = ord(c) + offset
        return chr(code) if 0 <= code < 0x110000 else c

    return "".join(shift_char(c) for c in text)


def _noise_ratio(text: str) -> float:
    """Fraction of characters that are neither a letter nor a space."""
    if not text:
        return 1.0
    bad = sum(1 for c in text if not (c.isalpha() or c == " "))
    return bad / len(text)


def _letter_freq_score(text: str) -> float:
    """Average log-likelihood of this text's letters under English letter
    frequencies. Near -2.9 for real English; noticeably lower once wrong or
    random letters pull in rare-letter penalties."""
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return _LOG_FREQ_FLOOR
    return sum(_LOG_FREQ.get(c, _LOG_FREQ_FLOOR) for c in letters) / len(letters)


_SUBSTRING_MIN_WORD_LEN = 4


def _exact_word_matches(text: str) -> set[str]:
    tokens = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    return {w for w in _COMMON_WORDS if w in tokens}


def _common_word_score(text: str) -> int:
    """Length-weighted count of common-word matches.

    Matches as whitespace-delimited tokens (the normal case) *and* as plain
    substrings for words of 4+ letters. The substring check matters because
    some corrupted runs have no space character at all in the source PDF --
    inter-word spacing comes from glyph positioning, not an actual space
    glyph -- so a correctly-decoded run like "press start button" can come
    out run-on as "pressstartbutton" with no token boundaries for a
    whitespace-based match to find.
    """
    lowered = text.lower()
    matched = _exact_word_matches(text)
    matched |= {w for w in _COMMON_WORDS if len(w) >= _SUBSTRING_MIN_WORD_LEN and w in lowered}
    return sum(len(w) for w in matched)


# An exact (not merely substring) match of at least this length, or enough
# cumulative word-match evidence, is treated as strong-enough independent
# evidence to waive the letter-frequency gate -- see _passes_gates.
_EXACT_MATCH_BYPASS_MIN_LEN = 5
_WORD_SCORE_BYPASS = _MIN_COMMON_WORD_SCORE * 2


def _passes_gates(text: str) -> bool:
    if _noise_ratio(text) > _MAX_NOISE_RATIO:
        return False
    word_score = _common_word_score(text)
    if word_score < _MIN_COMMON_WORD_SCORE:
        return False
    if _letter_freq_score(text) >= _MIN_LETTER_FREQ_SCORE:
        return True
    # A short run has high-variance average letter-frequency (few letters to
    # average over) and can dip below the general threshold even when it's
    # genuinely correct -- e.g. "Problem" alone scores -3.24, just under the
    # -3.0 bar, purely because of its particular letters. Strong word-match
    # evidence -- either one long exact word, or enough smaller matches
    # adding up -- is trusted enough on its own to accept the text anyway.
    if word_score >= _WORD_SCORE_BYPASS:
        return True
    return any(len(w) >= _EXACT_MATCH_BYPASS_MIN_LEN for w in _exact_word_matches(text))


def _confidence(text: str) -> float:
    word_score = _common_word_score(text)
    lf_score = _letter_freq_score(text)
    word_component = min(1.0, word_score / 20)
    lf_component = max(0.0, min(1.0, (lf_score - _MIN_LETTER_FREQ_SCORE) / 1.0))
    return round(min(1.0, 0.4 + 0.4 * word_component + 0.2 * lf_component), 3)


def _candidate_offsets(text: str) -> list[int]:
    from_control_chars = {32 - ord(c) for c in text if ord(c) < 32 and c not in _IGNORED_CONTROL_CHARS}
    return sorted((from_control_chars | set(_OFFSET_SWEEP)) - {0})


def repair_run(text: str) -> RepairResult:
    """Attempt to repair one text run.

    Returns the original text unchanged (was_repaired=False) unless a
    candidate offset produces text that clears all three acceptance gates
    (see module docstring) *and* is a genuine improvement over the
    unshifted text. The latter check matters because an offset of exactly
    +/-32 merely swaps letter case (ASCII 'a'-'A' are 32 apart) -- since
    every score here is case-insensitive, such an offset can look like a
    "winning" candidate purely by re-labeling already-clean text (e.g.
    'system' -> 'SYSTEM') without fixing anything. So: if the unshifted
    text already clears the gates itself, a competing offset only wins by
    strictly beating its word-match score, not merely tying it.
    """
    if not is_suspicious_run(text):
        return RepairResult(text=text, was_repaired=False)

    baseline_passes = _passes_gates(text)
    baseline_word_score = _common_word_score(text) if baseline_passes else -1

    best_offset: int | None = None
    best_shifted = text
    best_word_score = baseline_word_score

    for offset in _candidate_offsets(text):
        shifted = _shift(text, offset)
        if not _passes_gates(shifted):
            continue
        word_score = _common_word_score(shifted)
        if word_score > best_word_score:
            best_word_score = word_score
            best_offset = offset
            best_shifted = shifted

    if best_offset is None:
        return RepairResult(text=text, was_repaired=False)

    return RepairResult(
        text=best_shifted,
        was_repaired=True,
        offset=best_offset,
        confidence=_confidence(best_shifted),
    )


# --- document-level dominant offset + token-level repair -------------------

# A document's offset only "clearly dominates" if at least this many lines
# were confidently repaired at it, and it accounts for at least this share of
# every repair in the document -- both required so a handful of repairs (or a
# near-even split across two offsets) never triggers token-level repair on a
# guess.
_MIN_REPAIRS_FOR_DOMINANT_OFFSET = 5
_MIN_DOMINANT_SHARE = 0.8

_TRAILING_PUNCT = ".,;:!?"
_CONTRACTION_SUFFIXES = ("'t", "'s", "'re", "'ll", "'ve", "'d", "'m")
# NOTE: '(' and ')' were tried as strong-signal symbols and dropped:
# parentheses sit directly next to digits/letters constantly in ordinary
# text -- unit conversions ("14 in. (35.6 cm)"), list markers ("(1)"),
# abbreviations ("(SD)") -- and treating that adjacency as strong evidence
# produced dozens of false positives on ordinary numbers. '&' and "'" next
# to a letter/digit are far rarer outside this exact corruption.
_STRONG_SYMBOL_ADJACENCY_RE = re.compile(r"[A-Za-z0-9][&']|[&'][A-Za-z0-9]")
_WEAK_TOKEN_MAX_LEN = 4


@dataclass
class DominantOffset:
    """The single offset that clearly dominates a document's run-level
    repairs, with the evidence behind that call."""

    offset: int
    count: int
    total_repaired: int
    share: float


@dataclass
class TokenRepair:
    """One token-level repair applied by repair_line_tokens."""

    original: str
    repaired: str
    confidence: float


def infer_dominant_offset(offsets: list[int]) -> DominantOffset | None:
    """Given the offsets of every confidently run-level-repaired line in a
    document, return the one offset that clearly dominates -- or None if
    there isn't enough evidence, or no single offset clearly wins."""
    if len(offsets) < _MIN_REPAIRS_FOR_DOMINANT_OFFSET:
        return None

    counts: dict[int, int] = {}
    for offset in offsets:
        counts[offset] = counts.get(offset, 0) + 1
    best_offset, best_count = max(counts.items(), key=lambda item: item[1])
    share = best_count / len(offsets)
    if share < _MIN_DOMINANT_SHARE:
        return None

    return DominantOffset(offset=best_offset, count=best_count, total_repaired=len(offsets), share=share)


def _strip_trailing_punct(token: str) -> tuple[str, str]:
    core = token.rstrip(_TRAILING_PUNCT)
    return core, token[len(core) :]


def _looks_like_contraction(core: str) -> bool:
    lowered = core.lower()
    return "'" in core and any(lowered.endswith(suffix) for suffix in _CONTRACTION_SUFFIXES)


def _token_has_strong_signal(token: str) -> bool:
    """Strong evidence a token is corrupted, valid on its own without needing
    a corrupted sibling in the same line: a stray control character, or a
    letter/digit sitting directly next to & or ' -- normal English
    essentially never does this outside a contraction like "don't"."""
    if not token:
        return False
    if _has_stray_control_char(token):
        return True
    core, _ = _strip_trailing_punct(token)
    if not core or _looks_like_contraction(core):
        return False
    return bool(_STRONG_SYMBOL_ADJACENCY_RE.search(core))


def _token_has_weak_signal(token: str) -> bool:
    """Weaker evidence, only trusted when a strong-signal sibling is present
    on the same line (see repair_line_tokens): a short token that mixes
    letters and digits, or is a bare short number -- either digits landing on
    letters under a shift, which is this cipher's signature, but also
    exactly what an ordinary short quantity ("5", "24") looks like, hence the
    sibling requirement."""
    core, _ = _strip_trailing_punct(token)
    if not core or core.isalpha() or not core.isalnum():
        return False
    return len(core) <= _WEAK_TOKEN_MAX_LEN and any(c.isdigit() for c in core)


def _repair_token(token: str, dominant_offset: int) -> tuple[str, float] | None:
    core, suffix = _strip_trailing_punct(token)
    if not core:
        return None
    shifted_core = _shift(core, dominant_offset)
    if not shifted_core or shifted_core == core or _has_stray_control_char(shifted_core):
        return None

    if shifted_core.isalnum():
        # The signature effect of this cipher: digits/symbols/control chars
        # land on ordinary letters-and-digits under the document's one
        # known offset -- e.g. "14" -> "PS", or "U&\x12" (a control
        # character directly follows, no space) -> "tE1". Deliberately
        # isalnum(), not isalpha(): short codes with a trailing digit
        # ("tE1", "tE2") are legitimate targets. Short tokens (<=2 chars)
        # get a lower confidence -- less evidence per token.
        confidence = 0.5 if len(core) <= 2 else 0.65
        return shifted_core + suffix, confidence

    if _has_stray_control_char(core) and shifted_core.lower() in _COMMON_WORDS:
        return shifted_core + suffix, 0.8

    return None


def repair_line_tokens(
    text: str, dominant_offset: int, *, allow_weak_signal: bool = True
) -> tuple[str, list[TokenRepair]]:
    """Second-pass, token-level repair for a line that whole-run repair left
    untouched (typically because it mixes already-clean words with a
    corrupted token, which fails repair_run's noise gate for every offset).

    Only ever applied against the document's already-established dominant
    offset (see infer_dominant_offset) -- this function never searches for an
    offset itself.

    A token with a strong corruption signal (a stray control character, or a
    letter/digit adjacent to & or ') is always a candidate. A token with only
    a weak signal (a short digit-bearing token like "14") is a candidate only
    when the line also holds a strong-signal token.

    allow_weak_signal=False disables the weak-signal path entirely. Pass it
    when the surrounding content is not code-like (e.g. prose or data
    tables): weak-signal repair can turn real measurements into
    plausible-looking wrong numbers, since a genuinely corrupted word can
    sit on the very same row as an uncorrupted number. Strong-signal tokens
    are independent evidence on their own and are still repaired.
    """
    parts = re.split(r"(\s+)", text)
    token_positions = range(0, len(parts), 2)

    any_strong_signal = any(_token_has_strong_signal(parts[i]) for i in token_positions)

    repairs: list[TokenRepair] = []
    for i in token_positions:
        token = parts[i]
        if not token:
            continue
        is_candidate = _token_has_strong_signal(token) or (
            allow_weak_signal and any_strong_signal and _token_has_weak_signal(token)
        )
        if not is_candidate:
            continue

        result = _repair_token(token, dominant_offset)
        if result is None:
            continue
        repaired_token, confidence = result
        repairs.append(TokenRepair(original=token, repaired=repaired_token, confidence=confidence))
        parts[i] = repaired_token

    return "".join(parts), repairs
