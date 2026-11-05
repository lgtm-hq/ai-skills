#!/usr/bin/env bash
# Verify ai-skills.lock and rebuild every capability artifact offline from it.
#
# 1. lock --fetch fills the source cache for the committed lock only; it never
#    resolves or moves a pin, and fetched bytes must match each sourceDigest.
# 2. lock --check fails if the lock is stale or differs from a cache-only rebuild.
# 3. build rebuilds dist/artifacts/ from the lock and cache without network and
#    fails if any artifactDigest differs from the lock.

set -euo pipefail

uv run ai-skills-engine lock --fetch
uv run ai-skills-engine lock --check
uv run ai-skills-engine build
