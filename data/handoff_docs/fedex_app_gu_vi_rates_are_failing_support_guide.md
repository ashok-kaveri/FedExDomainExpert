# Support Guide — FedEx Release version 2.3.119d

## Release Details
- Feature Reference: Unknown
- Trello: https://trello.com/c/GQaYGZ3f/4254-fedex-app-gu-vi-rates-are-failing
- App Release: `FedEx Release version 2.3.119d`
- Approved: QA verified
- Developed by: athul prakash, Alan Thomas
- Tested by: QA Team

## Feature Summary
This change fixes a rate-request issue for shipments from the US mainland to certain US territories, specifically Guam (`GU`) and the United States Virgin Islands (`VI`). Before the fix, the app could fail during rate retrieval with the error `RATE.CUSTOMCLEARANCEDETAIL.INVALID` because the request did not include `customsClearanceDetail` when those destination types were used.

With this fix in place, the app should automatically include the required customs clearance details for GU and VI rate requests. For support teams, that means merchants should be able to fetch rates for these territory shipments without hitting the earlier validation failure during the manual shipment flow.

## Toggles & Prerequisites
- No toggle required — available automatically.
- This applies to shipments from the US mainland to US territories such as Guam (`GU`) and United States Virgin Islands (`VI`).
- The scenario is relevant during manual shipment / manual label generation when the user requests rates before generating the shipment.
- A valid Shopify order and a valid FedEx app configuration are still required before rates can be fetched successfully.

## Where to Find This in the App
- Shopify admin → `Orders` → click order row
- Shopify order page → `More Actions` → `Generate Label`
- FedEx app iframe → manual label generation page
- Manual label page → left panel → `Generate Packages` → `Get Rates`
- Optional verification path: after `Get Rates`, click `⋯` → `View Logs`

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - Guam order returns rates successfully
1. In Shopify admin, open `Orders` and select an order shipping from the US mainland to Guam.
2. On the Shopify order page, click `More Actions`.
3. Click `Generate Label`.
4. In the FedEx app iframe, use the manual label page and prepare the shipment if needed.
5. Click `Generate Packages`.
6. Click `Get Rates`.
7. Confirm the app returns available rates instead of showing the earlier customs-clearance validation failure.

### Scenario B - United States Virgin Islands order returns rates successfully
1. In Shopify admin, open an order shipping from the US mainland to United States Virgin Islands.
2. Click `More Actions`.
3. Click `Generate Label`.
4. On the manual label page, click `Generate Packages`.
5. Click `Get Rates`.
6. Confirm the app returns rates normally and does not fail with `RATE.CUSTOMCLEARANCEDETAIL.INVALID`.

### Scenario C - Rate-log verification for support investigation
1. Open a GU or VI shipment on the manual label page.
2. Click `Generate Packages`.
3. Click `Get Rates`.
4. Open the `⋯` menu and click `View Logs`.
5. Review the request and response details.
6. Confirm the rate flow succeeds instead of failing because `customsClearanceDetail` is missing.

## Expected Behaviour - What Support Should Observe
- GU and VI rate requests should complete successfully in the manual shipment flow.
- Merchants should see available rates instead of the earlier `RATE.CUSTOMCLEARANCEDETAIL.INVALID` error.
- The app should handle the required customs-clearance information automatically for these territory scenarios.
- This fix improves rate retrieval before shipment generation; support should validate the rate step first when checking this issue.

## References
- Trello card: https://trello.com/c/GQaYGZ3f/4254-fedex-app-gu-vi-rates-are-failing
- PR reference: https://bitbucket.org/xadapter-cyd/shopifyfedexapp/pull-requests/832
- Customer ticket reference: https://pluginhive.zendesk.com/agent/tickets/391374
