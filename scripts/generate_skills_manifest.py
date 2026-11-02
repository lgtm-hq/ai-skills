#!/usr/bin/env python3
"""Compatibility entry point for ai_skills_engine.generate.skills_manifest."""

from ci.npm._engine_bootstrap import run

raise SystemExit(run("ai_skills_engine.generate.skills_manifest"))
