---
name: analyze-tests
description: Test suite analysis. Use when asked to analyze, review, or evaluate a project's tests for quality, coverage gaps, and best practices.
---

# Test Suite Analysis

Perform a focused analysis of this project's test suite. Evaluate:

## Test Design & Quality
- Overall test structure and organization
- Adherence to testing best practices for the framework used
- Alignment with SOLID and DRY principles

## Problem Areas
- "Nothing burger" tests—tests that pass trivially or don't validate real behavior
- Missing parameterization where similar cases are tested with copy-paste
- Overly complex test code that's hard to maintain
- Large test files that should be split into logical groupings

## Test Hygiene
- Test isolation—do tests have side effects or depend on execution order?
- Flaky tests—tests that pass/fail inconsistently
- Mocking practices—appropriate use vs. over-mocking that hides real bugs
- Test naming—do names clearly describe the scenario and expected outcome?
- Setup/teardown—duplicated fixtures that should be shared
- Execution time—slow tests that could be optimized or parallelized

## Coverage Gaps
- Edge cases and failure modes not adequately tested
- Integration points lacking coverage

## Output Format
Rate severity of issues as: **Critical** | **Should Fix** | **Nice to Have**

Provide specific file/test names when identifying issues, and suggest concrete improvements.
