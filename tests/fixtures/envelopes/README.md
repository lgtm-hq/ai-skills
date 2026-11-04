# Envelope golden fixtures

Inputs for `tests/test_envelopes.py` and the TypeScript install plane (#578).

- `source/` is a synthetic publication. `core` and `extras` publish skills,
  `crew` publishes a specialist, and `other` is unexported.
- `index.json` is the real artifact builder's catalog index for `source/`, built
  with engine version `0.0.0-fixture`. A test rebuilds it and compares bytes.
- `golden/` holds the exact output of `ai-skills-engine generate` for these
  rules (`schemas/envelope-rules.v1.json`), after
  `--index index.json --output DIR`:

- `built-unfiltered`: no extra arguments.
- `built-filtered`: `--exclude fixture/extras:skill/gamma`.
- `slice-unfiltered`: `--layout slice --exclude fixture/crew:specialist/reviewer`.
- `slice-filtered`: the slice arguments plus `--exclude fixture/core:skill/beta`.

Regenerate a directory only through the generator, for example:

```sh
uv run ai-skills-engine generate --repo-root tests/fixtures/envelopes/source \
  --index tests/fixtures/envelopes/index.json \
  --output tests/fixtures/envelopes/golden/built-unfiltered
```

Slice layouts cannot carry the `crew` specialist, so repo-root generation for
`source/` fails until that package is excluded or unexported.
