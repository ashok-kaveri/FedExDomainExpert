# Support Guide — From SL: Show Migration Warning for FedEx SOAP Customers to Move to REST API [#4372]

## Release Details
- Feature Reference: Migration warning for SOAP-to-REST customers
- Trello: https://trello.com/c/JtCSlqjo
- App Release: `v2.3.118p`
- Approved: Unknown
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This change introduces a visible in-app warning for merchants who are still using a FedEx SOAP-based account and need to move to REST. The goal is to make the migration requirement clear before SOAP sunset causes shipping disruption.

When the warning is working correctly, a SOAP-configured merchant should see a message explaining that they must migrate their account to REST. The warning should guide the merchant toward the correct next step instead of letting the migration risk remain hidden.

## Configuration
Message updates can be configured.

## Where to Find This in the App
- Open the FedEx app on a SOAP-configured store.
- Navigate to common app surfaces such as:
- `Settings`
- `Product Settings`
- `FAQ`
- `Rate Log`
- `Pickup`

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - SOAP-configured merchant sees the migration warning
1. Open the FedEx app on a store that is still using a SOAP account.
2. Navigate to one of the expected app pages such as `Settings`, `Product Settings`, `FAQ`, `Rate Log`, or `Pickup`.
3. Observe the current account status area.
4. Confirm a migration warning is shown.
5. Confirm the message clearly tells the merchant that they must migrate from SOAP to REST because FedEx Web Services is in sunset mode.

## Business-Safe Explanation (For Merchant-Facing Communication)
> FedEx is moving away from its older SOAP connection method, so merchants still using that setup need to migrate to REST to avoid shipping interruptions. This update makes that requirement visible inside the app and is intended to guide affected merchants to the correct migration path before shipping is impacted.


## References
- Trello card: https://trello.com/c/JtCSlqjo
- Card title: `Show Migration Warning for FedEx SOAP Customers to Move to REST API`
