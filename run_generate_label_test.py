"""
BDD Test: Generate Label via Actions > Generate Label
Given I am logged in to the app with url https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553
And I create a new order
WHEN I click Actions > Generate Label
THEN Label should be generated
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
from pipeline.smart_ac_verifier import verify_test_cases  # noqa: E402

TC_MARKDOWN = """
### TC-001: Generate Label via Actions > Generate Label on a new order

**Type:** Positive
**Priority:** High
**Preconditions:** User is logged in to the FedEx app at https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553. Store kee-fedex-qa has at least one product available.

**Steps:**
1. Navigate to https://admin.shopify.com/store/kee-fedex-qa/orders
2. Click "Create order" button
3. In the order creation page, search for any product and add it to the order
4. Click "Save" to create the order
5. On the newly created order page, click "More actions" dropdown button
6. Click "Generate Label" from the dropdown
7. In the FedEx app Generate Label page, click "Get Rates"
8. Select the first available shipping service
9. Click "Generate Label" button
10. Wait for label generation to complete and observe the result

**Expected Result:** Label is successfully generated. The Order Summary page shows a "Label generated" status badge and tracking number is visible.
"""

APP_URL = "https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553"
CARD_NAME = "BDD: Generate Label via Actions > Generate Label"


def main():
    log = logging.getLogger("generate_label_test")
    log.info("=" * 60)
    log.info("BDD TEST: Generate Label via Actions > Generate Label")
    log.info("=" * 60)
    log.info("Given: Logged in to %s", APP_URL)
    log.info("And:   Creating a new order")
    log.info("When:  Clicking Actions > Generate Label")
    log.info("Then:  Label should be generated")
    log.info("=" * 60)

    report = verify_test_cases(
        app_url=APP_URL,
        test_cases_markdown=TC_MARKDOWN,
        card_name=CARD_NAME,
        card_id="bdd-generate-label",
    )

    log.info("\n%s", "=" * 60)
    log.info("TEST RESULTS")
    log.info("=" * 60)

    for scenario in report.scenarios:
        icon = {"pass": "✅ PASS", "fail": "❌ FAIL", "partial": "⚠️  PARTIAL"}.get(
            scenario.status, f"⏭  {scenario.status.upper()}"
        )
        log.info("%s", icon)
        log.info("Scenario: %s", scenario.scenario[:120])
        log.info("Finding:  %s", scenario.verdict or "(no finding)")
        if scenario.evidence_notes:
            for note in scenario.evidence_notes:
                log.info("Evidence: %s", note)

    log.info("=" * 60)
    log.info("Passed: %d  |  Failed: %d", report.passed, report.failed)
    overall = report.failed == 0 and report.passed > 0
    log.info("OVERALL: %s", "✅ PASSED" if overall else "❌ FAILED")
    log.info("=" * 60)

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
