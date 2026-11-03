"""Offline dependency-aware capability selection and explain surface."""

from ai_skills_engine.selection.deny import deny_matches
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.selection.rules import select
from ai_skills_engine.selection.scope import SelectionScope

__all__ = ["SelectionResult", "SelectionScope", "deny_matches", "select"]
