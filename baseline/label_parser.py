# label_parser.py

import re
from typing import Optional

OFFICIAL_LABELS = [
    "Supported",
    "Refuted",
    "Not Enough Evidence",
    "Conflicting Evidence/Cherrypicking",  # evaluator spelling, no hyphen
]

LABEL_ALIASES: dict[str, str] = {
    "supported": "Supported",
    "refuted": "Refuted",
    "not enough evidence": "Not Enough Evidence",
    "insufficient evidence": "Not Enough Evidence",
    "not enough info": "Not Enough Evidence",
    "not enough information": "Not Enough Evidence",
    "conflicting evidence/cherrypicking": "Conflicting Evidence/Cherrypicking",
    "conflicting evidence/cherry-picking": "Conflicting Evidence/Cherrypicking",
    "conflicting evidence / cherrypicking": "Conflicting Evidence/Cherrypicking",
    "conflicting evidence / cherry-picking": "Conflicting Evidence/Cherrypicking",
    "conflicting evidence": "Conflicting Evidence/Cherrypicking",
    "cherry-picking": "Conflicting Evidence/Cherrypicking",
    "cherrypicking": "Conflicting Evidence/Cherrypicking",
}

_SORTED_ALIASES = sorted(LABEL_ALIASES.keys(), key=len, reverse=True)

BINARY_LABELS = ["Supported", "Refuted"]


def _normalize(text: str, labels: list[str] = OFFICIAL_LABELS) -> Optional[str]:
    aliases = {a: t for a, t in LABEL_ALIASES.items() if t in labels}
    sorted_aliases = sorted(aliases.keys(), key=len, reverse=True)
    cleaned = text.strip().lower()
    if cleaned in aliases:
        return aliases[cleaned]
    for alias in sorted_aliases:
        if alias in cleaned:
            return aliases[alias]
    return None


def parse_label(raw_output: str, labels: list[str] = OFFICIAL_LABELS) -> tuple[Optional[str], bool]:
    """
    Extract the veracity label from the model's raw text output.

    Strategy (first success wins):
      1. Backtick-enclosed single-line spans, tried last-to-first.
         WHY [^`\\n]+ (not [^`]+): the prompt has no code blocks now, but
         keeping newlines excluded is a safety net — valid labels are always
         single-line, so cross-line matches are never correct.
      2. Full-text substring scan as fallback.

    `labels` restricts which of OFFICIAL_LABELS are accepted (default: all 4).
    Pass BINARY_LABELS to reject NEI/Conflicting matches outright rather than
    silently normalizing an off-list answer onto one of the allowed labels.

    Returns (label_or_None, parse_success).
    """
    # Strategy 1: backtick spans, reversed so the final verdict is tried first
    for candidate in reversed(re.findall(r"`([^`\n]+)`", raw_output)):
        label = _normalize(candidate, labels)
        if label is not None:
            return label, True

    # Strategy 2: full-text fallback (model forgot backticks)
    label = _normalize(raw_output, labels)
    if label is not None:
        return label, True

    return None, False
