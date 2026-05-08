---
name: analyze-project
description: High-level project analysis. Use when asked to analyze, review, or evaluate a project's architecture, structure, and overall health.
---

# Project Analysis (Zoom Out)

Perform a high-level analysis of this project. Evaluate:

## Architecture & Design
- Overall design quality and alignment with stated objectives
- Adherence to SOLID principles and separation of concerns
- Are layers (transport, business logic, data) clearly separated?
- API/interface design—are contracts clean, consistent, and hard to misuse?
- Code complexity—is it appropriately simple or over-engineered?
- Whether it reinvents solutions that existing libraries handle well

## Maintainability
- How easily could a new developer onboard and contribute?
- Is the code self-documenting, or are complex sections unexplained?
- Consistent naming conventions and project structure
- Boundary clarity—are public vs internal APIs clearly delineated?
- Change impact—how localized is the blast radius of a typical change?
- Configuration management—is config externalized properly vs scattered/hardcoded?

## CI/CD & DevOps
- Is the build reproducible?
- Are lint, test, and deploy pipelines in place?
- Are dependencies pinned and lock files committed?

## Documentation
- README quality—does it cover setup, usage, and contribution?
- API documentation—are public interfaces documented?
- Architecture decision records (ADRs) or equivalent for key decisions

## User Experience
- Interface design and usability
- Consistency of behavior and feedback
- Accessibility considerations

## Retrospective
If starting this project today, what would you do differently?

## Output Format
Rate severity of issues as: **Critical** | **Should Fix** | **Nice to Have**

Prioritize actionable feedback over observations.
