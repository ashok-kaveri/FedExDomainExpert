"""
Run IOR BDD test case via the AI QA Agent (headed Playwright browser).
"""
import sys
import logging
import os

# Ensure project root on path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

import config  # noqa: E402  — must follow sys.path insert
from pipeline.smart_ac_verifier import verify_test_cases, get_auto_app_url  # noqa: E402

TC_MARKDOWN = """
### TC-001: importerOfRecord field is sent correctly in FedEx API shipment request

**Type:** Positive
**Priority:** High
**Preconditions:** PH FedEx app is accessible. An Additional Account with IOR (Importer of Record) enabled is configured in app settings with valid merchant name, address, and account number. Order 1222 exists in Shopify.

**Steps:**
1. Log into the PH FedEx Shopify app
2. Navigate to Shipping > Orders and select order 1222
3. Click "Create Label" and select the IOR-enabled Additional Account
4. Complete the label creation form
5. Click "Generate Label"
6. Open browser DevTools Network tab and locate the FedEx REST API request to https://apis-sandbox.fedex.com/ship/v1/shipments
7. Inspect the request payload JSON body
8. Verify the payload contains the field key "importerOfRecord" (not "importedOfRecord")
9. Verify the "importerOfRecord" object contains merchant name, address, and account number from Additional Account settings
10. Verify the FedEx API returns HTTP 200 or 201 response code
11. Verify no field-rejection error appears in the response body
"""

def progress(scenario_idx: int, title: str, step: int, desc: str) -> None:
    print(f"  [TC {scenario_idx}] Step {step:>2}  {desc}")


def main() -> None:
    app_url = get_auto_app_url()
    if not app_url:
        print("ERROR: Could not detect app URL from automation .env — set STORE there.")
        sys.exit(1)

    print(f"\n{'='*70}")
    print("  BDD TEST: IOR — importerOfRecord field validation")
    print(f"  App URL : {app_url}")
    print(f"{'='*70}\n")

    report = verify_test_cases(
        app_url=app_url,
        test_cases_markdown=TC_MARKDOWN,
        card_name="IOR importerOfRecord field validation",
        card_id="ior-bdd-test",
        qa_name="Claude BDD Runner",
        progress_cb=progress,
        auto_report_bugs=False,
    )

    print(f"\n{'='*70}")
    print("  RESULT SUMMARY")
    print(f"{'='*70}")
    for sv in report.scenarios:
        icon = {"pass": "✅", "fail": "❌", "partial": "⚠️", "qa_needed": "❓"}.get(sv.status, "?")
        print(f"\n  {icon}  [{sv.status.upper()}] {sv.title}")
        for step in sv.steps:
            marker = "✓" if step.get("ok") else "✗"
            print(f"       {marker}  {step.get('desc', '')}")
        if sv.finding:
            print(f"\n       Finding: {sv.finding}")

    print(f"\n{'='*70}")
    overall = "PASSED" if all(s.status == "pass" for s in report.scenarios) else "FAILED"
    print(f"  OVERALL: {overall}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
