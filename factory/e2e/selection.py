"""Validate project-owned active coverage without knowing its test catalog."""

from datetime import datetime

from factory.e2e.execution import E2EPlanError, identifiers


def eligible_checks(report, candidates, config, policy):
    if (not isinstance(report, dict) or report.get("version") != 1
            or not isinstance(report.get("source"), str) or not report["source"].strip()):
        raise E2EPlanError("Active check selection needs an identified project source")
    try:
        checked_at = datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))
        if checked_at.tzinfo is None:
            raise ValueError("Missing timezone")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise E2EPlanError("Active check selection needs a timezone-aware checked_at") from exc
    checks = report.get("checks")
    if (not isinstance(checks, list) or any(not isinstance(item, dict)
            or not isinstance(item.get("nodeid"), str) or type(item.get("eligible")) is not bool
            or not isinstance(item.get("reason"), str) or not item["reason"].strip() for item in checks)):
        raise E2EPlanError("Project selection must explain eligibility for every candidate")
    nodes = [item["nodeid"] for item in checks]
    if len(nodes) != len(set(nodes)) or set(nodes) != set(candidates):
        raise E2EPlanError("Project selection must cover exactly the collected candidates")
    active = {item["nodeid"] for item in checks if item["eligible"]}
    required = identifiers(config.get("required_tests", []), "required_tests")
    if policy["include_smoke"]:
        required += identifiers(config.get("smoke_tests", []), "smoke_tests", required=True)
    for selector in required:
        matched = {node for node in candidates if node == selector or node.startswith(selector + "[")}
        if not matched or matched - active:
            raise E2EPlanError(f"Required check is missing or inactive: {selector}; resolve its scope explicitly")
    return [node for node in candidates if node in active]
