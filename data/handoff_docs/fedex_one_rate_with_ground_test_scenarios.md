# Test Scenarios — FedEx One Rate with Ground

*Card #4612 — Fetch and display FedEx Ground rates at checkout even when FedEx One Rate is enabled, by sending packagingType = YOUR_PACKAGING for the ground request. Cheapest applicable rate is shown at checkout. Behaviour is gated behind the per-store flag `<store>.fedex.rest.ground.with.one.rate.enabled`.*

## Feature Summary

FedEx One Rate is a flat-rate option for US domestic shipping that requires a FedEx-branded box. Because Ground services cannot be used with FedEx boxes, Ground rates were previously not fetched when One Rate was enabled. This change keeps the packaging algorithm and selected box unchanged, but in the rate API request it sets the packaging type to `YOUR_PACKAGING` so Ground rates are also fetched and shown at checkout. The cheapest applicable rate (One Rate vs Ground) is displayed to the buyer.

## Scope & References

- PR (server): bitbucket shopifyfedexapp pull-request 853
- PR (client): bitbucket shopify-fedex-web-client pull-request 177
- Feature flag: `<store>.myshopify.com.fedex.rest.ground.with.one.rate.enabled = true`
- Area: Rates at Checkout (Carrier Service / rate response), US domestic only

## Preconditions (common)

- FedEx app installed and connected with valid FedEx account credentials.
- Real-time rates at checkout enabled for the store.
- FedEx One Rate enabled in the app rate settings.
- At least one FedEx Ground service enabled in the allowed services list.
- A US origin (ship-from) address and a US domestic destination.
- Test product(s) with weight/dimensions within FedEx One Rate limits (max 50 lb).

---

## P1 — Core Functionality

### TS-01 — Ground rate appears at checkout when flag ON and One Rate enabled
**Type:** Functional / Positive · **Priority:** P1
- Precondition: flag `ground.with.one.rate.enabled = true`; One Rate enabled; a Ground service enabled.
- Steps: Add a US-domestic eligible product to cart; proceed to checkout; enter a valid US destination; observe shipping rate options.
- Expected: Both One Rate service rate(s) and a FedEx Ground rate are returned and visible at checkout. No errors in the rate response.

### TS-02 — Ground request is sent with packagingType = YOUR_PACKAGING
**Type:** Functional / Integration · **Priority:** P1
- Steps: Trigger a rate request at checkout (or via Rates Log); inspect the outbound FedEx rate request payload for the Ground service.
- Expected: For the Ground rate call, `requestedShipment.packagingType` = `YOUR_PACKAGING`. The One Rate call still uses the FedEx box packaging type. The packaging algorithm / chosen box is unchanged.

### TS-03 — Cheapest applicable rate is displayed
**Type:** Functional / Positive · **Priority:** P1
- Steps: Configure a cart where Ground is cheaper than One Rate (and a second case where One Rate is cheaper); fetch rates at checkout each time.
- Expected: The cheapest valid rate is shown each time. Rate amount displayed matches the FedEx response value; correct service label is shown.

### TS-04 — Flag OFF retains legacy behaviour (no Ground with One Rate)
**Type:** Regression / Negative · **Priority:** P1
- Precondition: flag `ground.with.one.rate.enabled = false` (or absent); One Rate enabled.
- Steps: Fetch rates at checkout for an eligible US-domestic cart.
- Expected: Only One Rate rates are returned. No Ground rate appears. Behaviour matches pre-change baseline (no regression).

### TS-05 — One Rate disabled, flag ON
**Type:** Regression · **Priority:** P1
- Precondition: One Rate disabled; flag ON.
- Steps: Fetch rates at checkout for an eligible cart.
- Expected: Normal Ground/standard rate behaviour; no One Rate rates. Flag has no adverse effect when One Rate is off.

---

## P2 — Configuration & Eligibility

### TS-06 — Flag is store-scoped
**Type:** Functional / Config · **Priority:** P2
- Steps: Enable the flag for store A only; fetch rates at checkout from store A and a separate store B (flag off).
- Expected: Store A shows Ground + One Rate; store B keeps legacy One Rate-only behaviour. No cross-store leakage.

### TS-07 — Ground service not enabled in allowed services
**Type:** Negative / Config · **Priority:** P2
- Precondition: flag ON; One Rate enabled; all Ground services disabled in settings.
- Steps: Fetch rates at checkout.
- Expected: No Ground rate shown (respects allowed-services config) even though the flag is on. Only One Rate rates appear.

### TS-08 — Multiple Ground / One Rate services enabled
**Type:** Functional · **Priority:** P2
- Steps: Enable several One Rate services and Ground/Home Delivery; fetch rates.
- Expected: All eligible enabled services return rates; the displayed/selected rate respects the cheapest-rate (or configured display) rule without duplicates.

### TS-09 — Rate markup / handling fee applied consistently
**Type:** Functional · **Priority:** P2
- Precondition: a rate adjustment / handling fee configured.
- Steps: Fetch One Rate and Ground rates at checkout.
- Expected: Markup/handling is applied to the Ground rate the same way as other rates; cheapest comparison uses post-adjustment amounts.

---

## P2 — Boundary & Eligibility Limits

### TS-10 — Weight at One Rate limit boundary (50 lb)
**Type:** Boundary · **Priority:** P2
- Steps: Test carts at just below, exactly at, and just above the One Rate weight limit.
- Expected: At/under limit One Rate returns; over the limit One Rate drops out but Ground (YOUR_PACKAGING) still returns a valid rate. Cheapest-of-available logic still holds.

### TS-11 — Oversized / dimension out of One Rate box range
**Type:** Boundary · **Priority:** P2
- Steps: Cart with dimensions exceeding FedEx box capacity.
- Expected: One Rate not offered; Ground rate still fetched and shown via YOUR_PACKAGING; no error to buyer.

### TS-12 — Multi-package / multi-box cart
**Type:** Functional · **Priority:** P2
- Steps: Cart that the packaging algorithm splits into multiple boxes.
- Expected: Packaging algorithm output is unchanged vs baseline; Ground request uses YOUR_PACKAGING per package; combined rate is correct.

---

## P3 — Non-Applicability / Guard Rails

### TS-13 — International destination
**Type:** Negative · **Priority:** P3
- Steps: Checkout with a non-US destination; flag ON.
- Expected: One Rate (US-domestic only) not offered; Ground-with-One-Rate logic does not corrupt the international rate flow; valid international rates returned.

### TS-14 — Non-US origin
**Type:** Negative · **Priority:** P3
- Steps: Configure a non-US ship-from origin; fetch rates.
- Expected: One Rate not applicable; no error introduced by the new flag path.

### TS-15 — Ineligible / zero-weight product
**Type:** Negative · **Priority:** P3
- Steps: Cart with a product missing weight or with zero weight.
- Expected: Graceful handling — fallback per existing rules; no crash, no malformed rate request.

---

## P3 — Non-Functional

### TS-16 — No duplicate / no extra latency regression
**Type:** Performance · **Priority:** P3
- Steps: Measure checkout rate-fetch time with flag ON vs OFF over several requests.
- Expected: Ground rate is fetched without breaking the checkout SLA; no duplicate FedEx API calls beyond the intended One Rate + Ground requests.

### TS-17 — FedEx API error / timeout on Ground request
**Type:** Resilience / Negative · **Priority:** P3
- Steps: Simulate Ground call failure (timeout/error) while One Rate succeeds.
- Expected: Checkout still shows the One Rate rate(s); failure is logged in Rates Log; buyer is not blocked.

### TS-18 — Rates Log accuracy
**Type:** Functional / Observability · **Priority:** P3
- Steps: Fetch rates with flag ON; open the app Rates Log for the request.
- Expected: Log shows both the One Rate and Ground (YOUR_PACKAGING) request/response; packaging types are clearly distinguishable; final displayed rate matches the chosen cheapest rate.

---

## Exit Criteria

- All P1 scenarios pass.
- No regression to legacy One Rate-only behaviour when the flag is OFF.
- Ground request verified to carry `packagingType = YOUR_PACKAGING` while the packaging algorithm/box selection is unchanged.
- Cheapest applicable rate is consistently displayed at checkout across boundary and config cases.
