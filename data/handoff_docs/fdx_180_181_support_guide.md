# Support Guide — From SL: FDX-180 — Saturday Ship Date Auto-Advance When Saturday Pickup Disabled [#387523]

## Release Details
- Feature Reference: `FDX-180`
- Trello: https://trello.com/c/EqW4fwrU/4473-from-sl-fdx-180-saturday-ship-date-auto-advance-when-saturday-pickup-disabled-387523
- App Release: `v2.3.120`
- Approved: QA verified
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This change corrects forward-label ship-date behavior when a store does not allow Saturday pickup. Before this fix, the app could calculate a future ship date, land on Saturday, and still send that Saturday ship date in the FedEx REST label request.

With the fix in place, the app should keep the existing buffer-day calculation, then check the final result. If the final ship date lands on Saturday or Sunday while Saturday pickup is disabled, support should expect the app to move the shipment date to the next working day instead of leaving it on the weekend.

## Toggles & Prerequisites
- No separate feature flag is confirmed in the card details.
- The store's Saturday Pickup setting must be disabled to see the main corrected behavior.
- The `Ship after N days` setting is part of the scenario and should be included in validation when buffer days are used.
- Return-label behavior is not part of this change.

## Where to Find This in the App
- `Settings` where the store controls Saturday pickup and shipment timing behavior
- Forward label-generation flow for orders
- Rate log or request/response evidence where the final `shipDatestamp` can be reviewed

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - Saturday pickup disabled and the computed date lands on Saturday
1. Open a store where Saturday pickup is disabled.
2. Use a forward-shipment order that will calculate to a Saturday ship date.
3. Generate the label.
4. Review the generated shipment date or request evidence.
5. Confirm the app advances the final ship date to the next working day instead of leaving it on Saturday.

### Scenario B - Buffer days still calculate normally
1. Configure a store with `Ship after 1 day` or another buffer-day value.
2. Start from a day where the buffer calculation would land on Saturday.
3. Generate the label.
4. Confirm buffer-day logic is still applied first.
5. Confirm only the final weekend result is moved forward when Saturday pickup is disabled.

### Scenario C - Saturday pickup enabled preserves Saturday behavior
1. Open a comparable store where Saturday pickup is enabled.
2. Generate a label for an order that resolves to a Saturday ship date.
3. Confirm the Saturday date is preserved and not auto-advanced.

## Expected Behaviour - What Support Should Observe
- Forward labels should not send a Saturday ship date when Saturday pickup is disabled.
- Buffer-day logic should remain intact and should not skip Saturday during the buffer calculation itself.
- The adjustment should happen only after the final ship date is calculated.
- Checkout rate behavior should remain unchanged because the card analysis says that path was already protected.
- Return-label behavior should remain unchanged.

## Business-Safe Explanation (For Merchant-Facing Communication)
> We corrected how the app chooses the final ship date when Saturday pickup is not allowed. If the calculated ship date lands on a weekend, the app now moves it to the next working day so merchants are less likely to run into avoidable label-date issues.

## Common Questions & Troubleshooting
**Q: Why did the ship date move to Monday instead of staying on Saturday?**  
If Saturday pickup is disabled for the store, that is the expected result when the final calculated date lands on Saturday.

**Q: Does this change alter how buffer days are counted?**  
No. The QA note says buffer-day calculation should stay as it is. The app should only adjust the final result if it lands on the weekend.

**Q: Does this affect return labels?**  
The card analysis says return labels are outside this path, so support should treat this as a forward-label change.

**Q: What should support verify if a merchant still reports a Saturday ship date?**  
Check whether Saturday pickup is actually disabled for that store, then inspect the request or rate-log evidence for the final `shipDatestamp`.

## Known Limitations / Rollout Notes
- No confirmed release-wide toggle is documented in the card details.
- The strongest verification method is request or rate-log evidence, not only the visible date on screen.
- The card analysis specifically calls out the forward-shipment REST path; SOAP behavior was marked as unaffected.

## References
- Trello card: https://trello.com/c/EqW4fwrU/4473-from-sl-fdx-180-saturday-ship-date-auto-advance-when-saturday-pickup-disabled-387523
- Related StoryLab card: https://trello.com/c/XhuIYli2
- PR reference: https://bitbucket.org/xadapter-cyd/shopifyfedexapp/pull-requests/829

---

# Support Guide — From SL: FDX-181 — Fix county field missing for Ireland FedEx REST registration [#391193]

## Release Details
- Feature Reference: `FDX-181`
- Trello: https://trello.com/c/WLxQRCZE/4474-from-sl-fdx-181-fix-county-field-missing-for-ireland-fedex-rest-registration-391193
- App Release: Unknown
- Approved: QA verified
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This change fixes FedEx REST account registration for merchants in Ireland. Before the fix, the registration form did not show an Ireland county selector, so the app could submit an empty state or county value and FedEx would reject the registration request.

With the fix in place, the Ireland registration flow should show the county field and send the correct county code in the registration request. This removes a setup blocker for Ireland merchants who could not complete FedEx REST registration from the app.

## Toggles & Prerequisites
- No feature toggle is indicated in the card details.
- This applies to FedEx REST account registration for Ireland (`IE`).
- The merchant must be registering or editing a FedEx REST account in the app's account settings.
- QA notes indicate Dublin was verified with the app's current expected code value of `D`.

## Where to Find This in the App
- `Settings > Accounts`
- FedEx REST account registration or account-edit flow
- Country selector and county/state dropdown for Ireland

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - Ireland shows a county dropdown
1. Open the FedEx app and go to `Settings > Accounts`.
2. Start a FedEx REST account registration flow, or open the editable account form if that path is used.
3. Select `Ireland` as the country.
4. Confirm a county dropdown appears.

### Scenario B - Dublin submits the correct code
1. In the Ireland registration form, choose `Dublin`.
2. Complete the remaining required registration fields.
3. Submit the registration request.
4. Confirm the request succeeds without failing because of a missing county/state field.
5. If request evidence is available, confirm the app sends the Dublin code value that QA verified for the current dropdown mapping.

### Scenario C - Additional county spot-check
1. Repeat the flow with another Ireland county such as `Galway`.
2. Confirm the county can be selected from the dropdown.
3. Confirm the registration flow continues normally without the empty-county issue.

## Expected Behaviour - What Support Should Observe
- Ireland should no longer behave like a country with no county/state selection.
- The county dropdown should appear when Ireland is selected.
- Registration should no longer fail because the county/state field is blank for Ireland.
- Dublin should map to the app's currently verified code value during registration.

## Business-Safe Explanation (For Merchant-Facing Communication)
> We fixed an account-setup issue for Ireland merchants using FedEx REST registration. The registration form now captures the Ireland county information properly so merchants can complete setup without being blocked by a missing county field.

## Common Questions & Troubleshooting
**Q: Why was FedEx registration failing for Ireland before this fix?**  
The card says the form was not surfacing the Ireland county field, so the registration request could be sent with an empty county or state value.

**Q: What should support check first if an Ireland merchant still cannot register?**  
Confirm the merchant is on the FedEx REST registration flow, verify that the country is set to Ireland, and make sure the county dropdown is visible and selected before submission.

**Q: Should support expect a county dropdown for every country?**  
No. This fix is specifically about Ireland because its county handling was missing in the registration form mapping.

**Q: What code should Dublin use?**  
The latest QA comment on the Trello card says Dublin was verified with the current app value of `D`. Support should follow the live app mapping and current QA evidence rather than older draft wording.

## Known Limitations / Rollout Notes
- The card provides a client-side fix path only; no server-side rollout steps are described.
- The card history includes an earlier note that questioned a `DN` value, but the later QA verification comment says Dublin was confirmed as `D`.
- Support may want to spot-check Galway as noted in the card comment if a merchant reports another Ireland county issue.

## References
- Trello card: https://trello.com/c/WLxQRCZE/4474-from-sl-fdx-181-fix-county-field-missing-for-ireland-fedex-rest-registration-391193
- Related StoryLab card: https://trello.com/c/qPLKluXU
- PR reference: https://bitbucket.org/xadapter-cyd/shopify-fedex-web-client/pull-requests/165
