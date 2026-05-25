---
name: stand-py
description: Python >= 3.11 coding standards. Use when writing Python code. Requires type hints, return types, Google-style docstrings, trailing commas, explicit kwargs, StrEnum with auto(), dataclasses, pytest-style tests.
---

# Python Code Standards

Standards for Python code (>= 3.11).

## Runtime

- All Python code should be run with `uv`

## PEP Compliance

- PEP 604: Use union types as `X | Y` (not `Union[X, Y]`)
- PEP 673: Use `Self` type for self-referential types

## Required Elements

- Type hints on ALL function parameters
- Return types on ALL functions
- Docstrings in Google Style Guide format for:
  - Modules
  - Classes
  - Functions/methods

## Docstring Format (Google Style)

```python
def function_with_docstring(
    param1: str,
    param2: int,
) -> bool:
    """Short description of function.

    Longer description if needed.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When something is wrong.
    """
```

## Design Patterns

- Use `dataclasses` for structured records with fixed fields and named attributes
- Use `collections.defaultdict` for dynamic key-value aggregation with automatic
  defaults
- Choose based on the use case: typed record-like object (`dataclass`) vs map with
  default values (`defaultdict`)
- Each dataclass should be in a separate file
- String Enums should use `StrEnum` with `auto()`
- Use `auto()` with all Enums where it makes sense

## Formatting Rules

- More than 1 arg/param requires a trailing comma:

  ```python
  # Good
  def foo(bar: str, baz: int,) -> None:

  # Bad
  def foo(bar: str, baz: int) -> None:
  ```

- Be explicit with function calls when more than 1 arg:

  ```python
  # Good
  foo(bar=bar, baz=baz)

  # Bad
  foo(bar, baz)
  ```

- Single arg can be positional:

  ```python
  # OK
  foo(bar)
  ```

## Linting

See `/lint` for linting and formatting workflow.

## Ignoring Issues

See `/lint` for ignore policy (Rules section).

Additional Python-specific note: docstrings are required even for tests — no
exceptions.

## Testing (Pytest)

- NEVER use unittest style or test classes
- Use pytest-style test functions only
- Leverage `conftest.py` for shared fixtures
- Use fixtures for reusable setup/teardown
- Use `@pytest.mark.parametrize` to reduce duplication

```python
# WRONG
class TestFoo(unittest.TestCase):
    def test_bar(self):
        ...

# CORRECT
def test_foo_bar() -> None:
    """Verify foo handles bar correctly."""
    ...
```

### Wiring vs. Behavior

A test that asserts `field == "literal"` where `"literal"` is also defined in source
code is duplication, and produces silent drift the moment either side changes.

- **Wiring tests** (does X read from canonical Y) — source from the constant. Better
  still, ask whether the test is just restating the constant's value; if so, delete it.
  The codegen / source-of-truth machinery is what guarantees that wiring, not a
  per-consumer assertion.
- **Behavior tests** (does X meet a fixed external contract — protocol versions, public
  API shapes, business rules) — hardcode the literal. The literal _is_ the contract.
- **Fixture data and parser inputs** are not wiring — keep those literal. They represent
  the world being modeled, not internal state.

Parametrize IDs should describe the case under test (`attr=min_version`), never encode
mutable data values (`min_version_is_0.43.0`) — IDs that change with every dependency
bump are a smell.

### Parametrize ID Hygiene

```python
# WRONG — id encodes the data, churns on every bump
ids=["min_version_is_0.43.0"]

# CORRECT — id names the case
ids=["attr=min_version"]
```
