---
name: fedex-shopify-store-actions
description: Use when the user wants to perform any Shopify Admin API action (REST or GraphQL) on a store — create/update/archive/delete products (simple, variable, up to 2048 variants via GraphQL), create/cancel/delete/update orders (preset, custom, draft, with stock bypass so test orders never deduct inventory), create order plus fulfillment plus tracking in one call, bulk inventory update, bulk cleanup by tag, update shipping address, manage customers, list fulfillments/carrier services/webhooks/metafields/collections/locations, or create refunds — all via natural language. The token comes from the automation .env automatically; if the store isn't found there, ask for a token.
---

# FedEx Shopify Store Actions

Perform any Shopify Admin API action (REST or GraphQL) on a store from natural language.
Used by AI QA to set up test orders and by general store maintenance tasks.

## Auth
- Read `STORE`, `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_API_VERSION` from the automation `.env`.
- If the requested store isn't configured there, ask the user for a token before proceeding.

## Capabilities
- **Products**: create/update/archive/delete; simple, variable (up to 2048 variants via GraphQL), digital, dangerous.
- **Orders**: create (preset/custom/draft), cancel, delete, update; bypass stock so test orders
  never deduct real inventory; create order + fulfillment + tracking in one call.
- **Inventory**: bulk update across variants; bulk cleanup by tag.
- **Other**: update shipping address, manage customers, create refunds; list fulfillments,
  carrier services, webhooks, metafields, collections, locations.

## Rules
- Default test orders to stock-bypass so inventory is never wrongly deducted.
- Confirm before destructive actions (delete/cancel/refund) unless clearly authorized.
- Never run a write against a store the user didn't name.

## Output
Confirmation of the action with the resulting ids (product/order/fulfillment) and any tracking info.
