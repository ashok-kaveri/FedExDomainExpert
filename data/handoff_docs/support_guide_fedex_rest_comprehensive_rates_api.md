# Support Guide - FedEx REST Comprehensive Rates API

## Release Details

**Feature:** FedEx app - Support Comprehensive Rates API for FedEx REST

**Trello card:** https://trello.com/c/TzjbcE6f/4410-fedex-app-support-comprehensive-rates-api-for-fedex-rest

**Status:** QA verified in Trello.

**Developed by:** Athul Prakash, based on the Trello card member returned by the project Trello workflow.

**Tested by:** QA verified on the card. A named QA member was not returned by the Trello member lookup.

## Feature Summary

This enhancement improves how the PH FedEx app handles FedEx REST rate responses when the Comprehensive Rates API is enabled. For FedEx REST accounts, the app can now work with comprehensive rate responses that may contain both negotiated account rates and published list rates. This allows the app to select the correct rate type based on the merchant's setting while still preserving delivery estimate details for the returned service.

Support should explain this in simple terms: merchants using a FedEx REST account can choose whether they want the app to use their negotiated Account Rates or the standard Published Rates when rates are fetched. The app maps those choices to FedEx REST request/response values and uses the returned rate details for rate display, label generation, and troubleshooting logs.

## Toggles & Prerequisites

The merchant must be using a FedEx REST account. This feature is not meant to change the legacy non-REST FedEx account flow.

The Rate Request Type field appears in the manual label additional or hidden services area for FedEx REST accounts. The app code shows REST-specific values of Account Rates and Published Rates for this field. For non-REST accounts, the legacy values remain separate and the REST-specific labels are not used.

The comprehensive response handling depends on the Comprehensive API path being enabled for the account or environment. When comprehensive handling is active, the app can receive both `ACCOUNT` and `LIST` rate entries in the FedEx REST response and then choose the correct entry based on the merchant's selected setting.

## Where to Find This in the App

For manual label generation, open a Shopify order in the PH FedEx app, start the manual label generation flow, and open the additional or hidden services section. For a FedEx REST account, the Rate Request Type field should show Account Rates and Published Rates.

For checkout or rate settings, support may also see the existing Display Published/Account Rates option under Settings > Rate Settings. This setting controls whether the merchant wants account or published rates shown in rating flows that use the configured account setting.

For troubleshooting, open the Rates Log entry for the related rate request. The enhanced REST log captures the service type and, when FedEx returns them, both accountRates and publishedRates values.

## Step-by-Step Walkthrough (Support / Demo)

Start with a store configured with a valid FedEx REST account. Confirm the order can reach the manual label generation page and that rates can be fetched normally.

Open the manual label generation flow for a valid order. In the additional or hidden services section, find Rate Request Type. Select Account Rates when the merchant wants the app to use negotiated contract rates from the FedEx account. Select Published Rates when the merchant wants the app to use FedEx list pricing.

Fetch rates. If the selection is Account Rates, the app maps the selection to FedEx REST `ACCOUNT`. If the selection is Published Rates, the app maps the selection to FedEx REST `LIST`. When the Comprehensive Rates API path is enabled, the rate request asks FedEx for both `LIST` and `ACCOUNT`, and the app selects the appropriate returned value for display and label flow continuation.

After rates are returned, confirm that the service list is displayed and that a valid service can still be selected for label generation. If FedEx returns delivery information, the app can show an estimated delivery date or estimated delivery days. If FedEx does not return delivery estimate fields for a valid service, the app should still show the available service and allow the flow to continue.

To troubleshoot, open the Rates Log for the rate request. The log should help support compare the service type, published rate value, and account rate value when those values are available in the FedEx response.

## Expected Behaviour - What Support Should Observe

For FedEx REST accounts, Rate Request Type should show Account Rates and Published Rates in the manual label additional or hidden services area.

Account Rates maps to the FedEx REST `ACCOUNT` rate type. Published Rates maps to the FedEx REST `LIST` rate type.

When the comprehensive response contains both account and list rates, the app should select the rate matching the merchant's chosen setting. If the selected rate type is missing, the code has fallback behavior to use the available alternate rate entry rather than failing the whole flow.

Returned services should include rate data and remain usable for label generation. Delivery estimates are shown when FedEx provides delivery date or transit-day values. Missing transit estimate fields should not block a valid rate from being shown.

Rates Log should show service information and, when available, both Published Rates and Account Rates values for REST responses.

Non-REST FedEx account behavior should remain unchanged.

## Business-Safe Explanation

Account Rates are negotiated rates tied to the merchant's FedEx account. These are often lower because they reflect the merchant's contract or account-level pricing.

Published Rates are FedEx standard list rates. These are the general carrier rates before account-specific negotiated pricing is applied.

This release helps the app handle REST responses that include both rate types. It gives merchants clearer control over whether they want negotiated or published pricing used in the app and gives support better rate-log evidence when investigating pricing questions.

## Common Questions & Troubleshooting

**Why are Account Rates and Published Rates showing the same value?**

This can happen depending on the FedEx account and response. QA noted that the test account returned the same value for both Account and List rates, so support should not assume the two values will always differ. If a merchant expects different pricing, ask them to confirm the account contract or validate the returned rate response with FedEx.

**What should support check when a merchant says the wrong rate is shown?**

First confirm whether the merchant is using a FedEx REST account. Then check whether the merchant selected Account Rates or Published Rates. Next, open the related Rates Log and compare the publishedRates and accountRates values. If FedEx returned only one rate type, the app may use the available fallback value.

**Does this guarantee both rate types are always returned by FedEx?**

No. The app can handle both values when FedEx returns them, but FedEx may return only one value depending on the account, shipment, service, and API response. The feature improves handling of the response; it does not force FedEx to return different values.

**What happens if transit time or transit days are missing?**

The app should still show the valid service and rate. Delivery estimate text is displayed only when the response provides the needed estimate fields.

**Is this for SOAP or legacy FedEx accounts?**

No. The support scenario for this card is FedEx REST. Non-REST behavior should continue as before.

## Known Limitations / Rollout Notes

QA could not fully verify a scenario where the test account returns different Account and List values because the available test account returned the same value for both.

QA also could not fully verify a List-only response for the Account Rates fallback path because the test account did not return a List-only comprehensive response. The code-level behavior includes fallback handling, but real-world confirmation depends on FedEx returning that response shape.

QA could not verify the Estimated Duties & Taxes success-rate scenario because Estimated Duties & Taxes were not returned along with the rate response. The response included `EDT.DETAILS.MISSING`, which says the harmonized code for the commodity at array index 1 is missing or invalid and estimated duties and taxes were not returned. The response also included `DUTIES.TAXES.ESTIMATED`, which says duties and taxes are estimates only and may change based on the recipient country, customs, exchange rate fluctuations, or tariff changes.

If a customer asks why rates do not differ, support should avoid saying this is an app defect without checking the FedEx response. The difference depends on FedEx account pricing and the rate data FedEx returns.

## References

- Trello card: https://trello.com/c/TzjbcE6f/4410-fedex-app-support-comprehensive-rates-api-for-fedex-rest
- Backend mapping: `server/shared/adaptors/fedexRest/fedexRestMappers.js`
- Backend rate selection and fallback: `server/shared/adaptors/fedexRest/fedexRestShipmentHelper.js`
- Backend REST request building: `server/shared/adaptors/fedexRest/fedexRestRequestBuilder.js`
- Backend rates log extraction: `server/shared/adaptors/fedexRest/fedexRestRatesLogBuilder.js`
- Frontend manual label Rate Request Type field: `src/screens/orders/details/components/HiddenServices.js`
- Frontend rates log display: `src/screens/rateslog/ratesLogDetails/components/AvailableServiceList.js`
