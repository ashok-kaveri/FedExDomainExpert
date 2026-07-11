"""
BDD Test: Short city name (2 chars) should not cause CITY.TOO.SHORT error

Given I duplicate an order
And enter the shipping address with city = "NY" (2-char short city)
And enter the billing address with a different address, city = "NY"
And I click on More Actions
And click on Auto Label Generation
And I click on "Generate Package & Get Shipment Rate"
And I open the rate logs
Then the city field should still be included in the request
And no "CITY.TOO.SHORT" error should occur
"""
import sys
import logging
import os

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

import config  # noqa: E402
from pipeline.smart_ac_verifier import verify_test_cases, get_auto_app_url  # noqa: E402

APP_URL = "https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553"

TC_MARKDOWN = """
### TC-001: Short city name (2 chars) does not cause CITY.TOO.SHORT error in rate request

**Type:** Negative / Boundary
**Priority:** High
**Preconditions:**
- User is logged in to the FedEx app at https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553
- Store kee-fedex-qa has at least one existing fulfilled or unfulfilled order to duplicate
- A product exists in the store

**Steps:**
1. Navigate to https://admin.shopify.com/store/kee-fedex-qa/orders
2. Open order KFED1468
3. Click "More actions" dropdown and select "Duplicate"
4. On the duplicated draft order page, edit the shipping address:
   - Street: 123 Main St
   - City: NY
   - State/Province: NY
   - ZIP: 10001
   - Country: United States
5. Edit the billing address to a different address:
   - Street: 456 Broadway
   - City: NY
   - State/Province: NY
   - ZIP: 10002
   - Country: United States
6. Save the draft order and convert it to a real order (click "Create order" or "Save")
7. On the newly created order page, click "More actions"
8. Click "Auto-Generate Label" (Auto Label Generation)
9. In the FedEx app label page that opens, click "Generate Package & Get Shipment Rate" (or "Get Rates")
10. After rates appear (or request is made), navigate to Rates Log:
    - Click the "⋯" (more options) or go to the app sidebar and click "Rates Log"
    - Find the most recent rate request log entry
11. Open the rate request log and inspect the request JSON payload
12. Check whether the "city" field is present in the request body
13. Check whether the response contains any "CITY.TOO.SHORT" error code or message

**Expected Result:**
- Step 12: The request still contains the short city value (for example, "NY") in the relevant address node
- Step 13: No "CITY.TOO.SHORT" error appears in the rate log response
- The rate request completes successfully and returns available shipping rates
"""


def progress(scenario_idx: int, title: str, step: int, desc: str) -> None:
    print(f"  [TC {scenario_idx}] Step {step:>2}  {desc}")


def main() -> None:
    app_url = APP_URL

    print(f"\n{'='*70}")
    print("  BDD TEST: Short City Name — CITY.TOO.SHORT validation")
    print(f"  App URL : {app_url}")
    print(f"{'='*70}\n")
    print("  Scenario:")
    print("    Given  Duplicate an existing order")
    print("    And    Shipping address city = 'NY' (2 chars)")
    print("    And    Billing address city  = 'NY' (2 chars, different address)")
    print("    When   Auto-Generate Label → Get Rates")
    print("    Then   city field remains in request and no CITY.TOO.SHORT error appears")
    print(f"\n{'='*70}\n")

    report = verify_test_cases(
        app_url=app_url,
        test_cases_markdown=TC_MARKDOWN,
        card_name="Short city (2 chars) CITY.TOO.SHORT validation",
        card_id="short-city-bdd-test",
        qa_name="Claude BDD Runner",
        progress_cb=progress,
        auto_report_bugs=False,
    )

    print(f"\n{'='*70}")
    print("  RESULT SUMMARY")
    print(f"{'='*70}")
    for sv in report.scenarios:
        icon = {"pass": "✅", "fail": "❌", "partial": "⚠️", "qa_needed": "❓"}.get(sv.status, "?")
        print(f"\n  {icon}  [{sv.status.upper()}]  {sv.title}")
        for step in sv.steps:
            marker = "✓" if step.get("ok") else "✗"
            print(f"       {marker}  {step.get('desc', '')}")
        if sv.finding:
            print(f"\n       Finding : {sv.finding}")
        if sv.verdict:
            print(f"       Verdict : {sv.verdict}")

    print(f"\n{'='*70}")
    overall = "PASSED" if all(s.status == "pass" for s in report.scenarios) else "FAILED"
    print(f"  OVERALL: {overall}")
    print(f"{'='*70}\n")

    return 0 if all(s.status == "pass" for s in report.scenarios) else 1


if __name__ == "__main__":
    sys.exit(main())
