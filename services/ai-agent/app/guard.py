"""
LLM Guard integration for ChemCrow2.

Uses lightweight scanners only (no ML model downloads):
- Input:  BanSubstrings — blocks known prompt injection phrases
- Output: BanSubstrings — blocks known sensitive output patterns
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_input_scanners: list[Any] | None = None
_output_scanners: list[Any] | None = None

# Phrases that indicate prompt injection / jailbreak attempts
_INPUT_BAN = [
    "ignore previous instructions",
    "ignore all previous",
    "disregard your instructions",
    "you are now",
    "pretend you are",
    "act as if",
    "forget your rules",
    "bypass your",
    "jailbreak",
    "DAN mode",
]

# Topics we never want in output
_OUTPUT_BAN = [
    "I cannot assist",
]


def _get_input_scanners() -> list[Any]:
    global _input_scanners
    if _input_scanners is None:
        from llm_guard.input_scanners import BanSubstrings
        _input_scanners = [
            BanSubstrings(substrings=_INPUT_BAN, match_type="str", case_sensitive=False),
        ]
        logger.info("LLM Guard input scanners initialised")
    return _input_scanners


def _get_output_scanners() -> list[Any]:
    global _output_scanners
    if _output_scanners is None:
        from llm_guard.output_scanners import BanSubstrings
        _output_scanners = [
            BanSubstrings(substrings=_OUTPUT_BAN, match_type="str", case_sensitive=False),
        ]
        logger.info("LLM Guard output scanners initialised")
    return _output_scanners


def scan_input(text: str) -> tuple[str, list[str]]:
    """
    Scan user input. Returns sanitized text and list of failed scanner names.
    """
    try:
        from llm_guard import scan_prompt
        sanitized, is_valid, _ = scan_prompt(_get_input_scanners(), text)
        failed = [name for name, ok in is_valid.items() if not ok]
        return sanitized, failed
    except Exception:
        logger.exception("LLM Guard input scan failed — skipping")
        return text, []


def scan_output(prompt: str, response: str) -> tuple[str, list[str]]:
    """
    Scan LLM output. Returns sanitized text and list of failed scanner names.
    """
    try:
        from llm_guard import scan_output as _scan_output
        sanitized, is_valid, _ = _scan_output(_get_output_scanners(), prompt, response)
        failed = [name for name, ok in is_valid.items() if not ok]
        return sanitized, failed
    except Exception:
        logger.exception("LLM Guard output scan failed — skipping")
        return response, []
