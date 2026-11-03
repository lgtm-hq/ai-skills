"""Human-readable rendering of the same plan records returned as JSON."""

from ai_skills_engine.selection.model import SelectionResult


def explain(result: SelectionResult) -> str:
    """Render dispositions, namespace report and actionable dependency chains.

    Args:
        result: Complete plan, including errors.

    Returns:
        Deterministic text with no checkout-dependent paths.
    """
    lines = [
        f"{item.id} {item.state} {item.reason}"
        for item in (*result.capabilities, *result.resources)
    ]
    for role, name, owners in result.namespace:
        lines.append(f"namespace {role}/{name}: {', '.join(owners)}")
    for item in result.diagnostics:
        severity = "warning" if item.warning else "error"
        lines.append(f"{severity}[{item.code}]: {item.message}")
        if item.chain:
            lines.append("  chain: " + " -> ".join(item.chain))
        if item.cycle:
            lines.append("  cycle: " + ", ".join(item.cycle))
        lines.append("  fix: " + item.fix)
    return "\n".join(lines) + "\n"
