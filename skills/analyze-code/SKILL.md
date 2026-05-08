---
name: analyze-code
description: Code-level quality analysis. Use when asked to review code for smells, security issues, implementation quality, or test coverage.
---

# Code Analysis (Zoom In)

Perform a code-level quality analysis of this project. Evaluate:

## Implementation Quality
- Best practices adherence for the language/framework used
- Scalability and performance considerations
- Error handling—are failures handled gracefully and consistently?
- Resource management—are connections, file handles, streams properly closed?
- Concurrency/async correctness—race conditions, deadlocks, proper cleanup
- Type safety—is the type system leveraged well or worked around with `any`/casts?
- Dependency health—outdated, redundant, or vulnerable dependencies
- Logging/observability—can issues be diagnosed in production?

## Code Smells
- Long methods/functions that do too much
- God classes or modules with too many responsibilities
- Feature envy—code that uses another module's data more than its own
- Primitive obsession—overuse of primitives instead of domain types
- Shotgun surgery—a single change requiring edits across many files
- Dead code, unreachable branches, or unused imports/variables
- Deeply nested conditionals or callbacks
- Magic numbers and hardcoded strings that should be constants
- Duplicated logic that violates DRY
- Inappropriate intimacy—modules tightly coupled to each other's internals

## Security Best Practices
- OWASP Top 10 exposure: injection (SQL, command, XSS), broken auth, SSRF, etc.
- Secrets management—no hardcoded credentials, tokens, or API keys in source
- Input validation and sanitization at system boundaries
- Proper use of cryptography—no weak algorithms, correct key/IV handling
- Dependency vulnerabilities—known CVEs in direct or transitive dependencies
- Least privilege—are permissions, scopes, and roles appropriately scoped?
- Secure defaults—are features opt-in safe (e.g., CORS, CSP, cookie flags)?
- Sensitive data handling—PII/secrets not leaked in logs, errors, or responses

## Testing
- Test quality—flag any "nothing burger" tests that don't meaningfully validate behavior
- Use of parameterization where appropriate
- Coverage of edge cases and failure modes
- Are tests isolated and deterministic?
- Do tests cover the right layer (unit vs integration vs e2e)?

## Output Format
Rate severity of issues as: **Critical** | **Should Fix** | **Nice to Have**

Prioritize actionable feedback over observations.
