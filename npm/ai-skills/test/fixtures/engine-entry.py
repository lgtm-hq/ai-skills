"""Bundled-payload stand-in: run the real engine CLI found on PYTHONPATH.

The launcher tests stage this as ``engine/__main__.py`` so the TypeScript
launcher hands off to the same ``ai_skills_engine`` the pytest suite checks.
"""

import runpy

runpy.run_module("ai_skills_engine", run_name="__main__", alter_sys=True)
