"""Read TestRail coverage through the test repository's configured Python client.

Standalone so the factory can copy and digest-bind it in each fresh task snapshot.
Project integration conventions stay here, outside the generic runner and role prompts.
"""

import argparse
import configparser
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import re
import sys


class AdapterError(Exception):
    pass


def configured_client(integration_repo):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(integration_repo / "framework/configs/testrail.cfg"):
        raise AdapterError("TestRail configuration is missing relative to E2E_DIR")
    try:
        api = config["API"]
        sdk = importlib.import_module("testrail_client.testrail")
        transport = getattr(sdk, "requests", None)
        if transport is not None:
            original_get = transport.get

            def bounded_get(*args, **kwargs):
                kwargs.setdefault("timeout", 30)
                return original_get(*args, **kwargs)

            transport.get = bounded_get
        client = sdk.APIClient(api["url"])
        client.user, client.password = api["email"], api["password"]
        project = configparser.ConfigParser(interpolation=None)
        if not project.read(integration_repo / "framework/configs/config.ini"):
            raise AdapterError("TestRail project configuration is missing relative to E2E_DIR")
        scope = {"project_id": int(project["testrail"]["project_id"]), "suite_name": project["testrail"]["suite_name"]}
        return client, api["url"].rstrip("/"), scope
    except (KeyError, ImportError) as exc:
        raise AdapterError("TestRail client or credentials are missing in the configured test repository environment") from exc


def product_options(field, project_id=None):
    options = {}
    for config in field.get("configs", []):
        context = config.get("context", {})
        if project_id is not None and context and not context.get("is_global") and project_id not in context.get("project_ids", []):
            continue
        for line in config.get("options", {}).get("items", "").splitlines():
            number, name = line.split(",", 1)
            options.setdefault(int(number.strip()), set()).add(name.strip().replace(" ", ""))
    return options


def active_coverage(client, metadata, candidates, platform, scope=None):
    if not isinstance(metadata, dict) or metadata.get("version") != 1 or not isinstance(metadata.get("checks"), list):
        raise AdapterError("Missing native pytest collection metadata; collect with pytest_evidence")
    checks = metadata["checks"]
    if any(not isinstance(item, dict) or not isinstance(item.get("nodeid"), str)
           or not isinstance(item.get("markers"), list) for item in checks):
        raise AdapterError("Invalid native pytest collection metadata")
    items = {item["nodeid"]: item for item in checks}
    if len(items) != len(checks) or set(items) != set(candidates):
        raise AdapterError("TestRail candidates differ from the native collected selection")
    automated = next((item["id"] for item in client.send_get("get_case_types")
                      if item["name"].lower() == "automated"), None)
    fields = client.send_get("get_case_fields")
    flag = next((item["system_name"] for item in fields if item["name"] == platform), None)
    product = next((item for item in fields if item["name"] == "product_name"), None)
    if automated is None or flag is None or product is None:
        raise AdapterError("The project's TestRail automation, platform or product configuration is incomplete")
    suite_id = None
    if scope:
        data = client.send_get(f"get_suites/{scope['project_id']}")
        suites = []
        while True:
            page = data.get("suites", []) if isinstance(data, dict) else data
            suites.extend(item["id"] for item in page if item["name"] == scope["suite_name"])
            if not isinstance(data, dict) or not data.get("_links", {}).get("next"):
                break
            offset = data.get("offset", 0) + data.get("limit", len(page))
            if not page or offset <= data.get("offset", 0):
                raise AdapterError("Invalid TestRail suite pagination")
            data = client.send_get(f"get_suites/{scope['project_id']}&offset={offset}")
        if len(suites) != 1:
            raise AdapterError("The configured TestRail suite is missing or ambiguous")
        suite_id = suites[0]
    products = product_options(product, scope["project_id"] if scope else None)
    cases = {}
    outcomes = []
    for node in candidates:
        markers = items[node]["markers"]
        names = {item["name"] for item in markers}
        identifiers = [raw for item in markers if item["name"] == "testrail"
                       for raw in item.get("kwargs", {}).get("ids", [])]
        ids = []
        for identifier in identifiers:
            match = re.fullmatch(r"C?(\d+)", str(identifier))
            if not match:
                raise AdapterError("Invalid TestRail case identifier in collected pytest metadata")
            ids.append(int(match[1]))
        eligible = False
        reasons = []
        for case_id in dict.fromkeys(ids):
            if case_id not in cases:
                cases[case_id] = client.send_get(f"get_case/{case_id}")
            case = cases[case_id]
            if case.get("is_deleted"):
                reason = "deleted"
            elif suite_id is not None and case.get("suite_id") != suite_id:
                reason = "outside the configured project/suite"
            elif case["type_id"] != automated:
                reason = "not Automated"
            elif case.get(flag) is not True:
                reason = f"not enabled for {platform}"
            elif not names.intersection(products.get(case.get(product["system_name"]), set())):
                reason = "outside the project's product-marker selection"
            else:
                reason = f"active automated {platform} coverage"
                eligible = True
            reasons.append(f"C{case_id}: {reason}")
        outcomes.append({"nodeid": node, "eligible": eligible,
                         "reason": "; ".join(reasons) or "No TestRail case mapping in the collected test"})
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--integration-repo", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("ios", "android"), required=True)
    parser.add_argument("selectors", nargs="+")
    args = parser.parse_args()
    try:
        client, source, scope = configured_client(args.integration_repo)
        checks = active_coverage(client, json.loads(args.metadata.read_text()), args.selectors, args.platform, scope)
        args.output.write_text(json.dumps({"version": 1, "source": source,
            "checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks}, indent=2) + "\n")
    except AdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # SDK/API exceptions may contain auth values or server response bodies.
        print(f"TestRail lookup failed ({type(exc).__name__}); check the repository client configuration and access.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
