"""
FedEx REST API Knowledge Ingest
================================
Embeds comprehensive, structured knowledge about the FedEx REST API
into the RAG knowledge base.

Coverage:
  • Authentication (OAuth 2.0)
  • Rate API v1 — how rate requests are built, request/response schema
  • Ship API v1 — label request structure, tracking number, label data
  • Special Handles — how each special service changes the request
  • International — customs commodities, duties, invoice
  • Pickup API — schedule, cancel
  • Track API — tracking events, status codes
  • Error codes — meaning and recommended fix
  • SOAP → REST migration notes
  • App-specific conventions (how the FedEx Shopify App uses the API)

NOTE: This app has fully migrated from SOAP to REST API.
Only REST endpoints are used. SOAP endpoints are deprecated and not called.
"""
from __future__ import annotations

import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE,
    chunk_overlap=config.CHUNK_OVERLAP,
)

# ---------------------------------------------------------------------------
# Knowledge articles
# ---------------------------------------------------------------------------

_ARTICLES: list[dict] = [

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — Overview and Authentication",
        "content": """
FedEx REST API — Overview and Authentication
=============================================

IMPORTANT: The FedEx Shopify App has fully migrated from SOAP to REST API.
All API calls use REST. SOAP is no longer used. Do not reference SOAP structures.

Base URLs:
  Production: https://apis.fedex.com
  Sandbox:    https://apis-sandbox.fedex.com

Authentication — OAuth 2.0 Client Credentials:
  POST /oauth/token
  Content-Type: application/x-www-form-urlencoded
  Body: grant_type=client_credentials&client_id={API_KEY}&client_secret={API_SECRET}

  Response:
  {
    "access_token": "eyJhbGci...",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "CXS"
  }

  The access_token is used as Bearer token in all subsequent API calls.
  Token expires after 1 hour. App caches and refreshes as needed.

Required headers for all API calls:
  Authorization: Bearer {access_token}
  Content-Type: application/json
  X-locale: en_US  (optional, for response language)
  X-Customer-Transaction-Id: {uuid}  (optional, for request tracing)

Account information used in every request:
  accountNumber: { value: "{FEDEX_ACCOUNT_NUMBER}" }
  This is the FedEx billing account number, not the API key.
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx Rate API v1 — Request and Response Structure",
        "content": """
FedEx Rate API v1 — Request Structure
======================================
Endpoint: POST /rate/v1/rates/quotes

This API returns shipping rates for all eligible FedEx services
(or a specific service if serviceType is specified).

Minimal request example:
{
  "accountNumber": { "value": "123456789" },
  "requestedShipment": {
    "shipper": {
      "address": {
        "streetLines": ["123 Main St"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38103",
        "countryCode": "US"
      }
    },
    "recipient": {
      "address": {
        "streetLines": ["456 Oak Ave"],
        "city": "Los Angeles",
        "stateOrProvinceCode": "CA",
        "postalCode": "90001",
        "countryCode": "US",
        "residential": true
      }
    },
    "pickupType": "USE_SCHEDULED_PICKUP",
    "rateRequestType": ["LIST", "ACCOUNT"],
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 5.0 },
        "dimensions": { "length": 12, "width": 8, "height": 6, "units": "IN" }
      }
    ]
  }
}

Key fields in rate request:
  pickupType: DROPOFF_AT_FEDEX_LOCATION | USE_SCHEDULED_PICKUP | CONTACT_FEDEX_TO_SCHEDULE
  rateRequestType: LIST (published rates) | ACCOUNT (negotiated rates) | PREFERRED
  serviceType: (optional) FEDEX_GROUND | FEDEX_2_DAY | etc. — omit for all services
  packagingType: YOUR_PACKAGING | FEDEX_ENVELOPE | FEDEX_PAK | FEDEX_BOX | FEDEX_TUBE
                 FEDEX_SMALL_BOX | FEDEX_MEDIUM_BOX | FEDEX_LARGE_BOX | FEDEX_EXTRA_LARGE_BOX

Rate Response example:
{
  "output": {
    "rateReplyDetails": [
      {
        "serviceType": "FEDEX_GROUND",
        "serviceName": "FedEx Ground®",
        "packagingType": "YOUR_PACKAGING",
        "ratedShipmentDetails": [
          {
            "rateType": "ACCOUNT",
            "totalNetCharge": 12.50,
            "totalBaseCharge": 10.00,
            "surchargeDetail": [...]
          }
        ],
        "operationalDetail": {
          "transitTime": "THREE_DAYS",
          "deliveryTimestamp": "2024-01-15T20:00:00",
          "deliveryDay": "MON"
        }
      }
    ]
  }
}

Transit time values: ONE_DAY, TWO_DAYS, THREE_DAYS, FOUR_DAYS, FIVE_DAYS,
                    SIX_DAYS, SEVEN_DAYS, EIGHT_DAYS, NINE_DAYS, TEN_DAYS, UNKNOWN
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx Rate API — Special Services in Rate Request",
        "content": """
FedEx Rate API — Special Services that Modify Rate Requests
===========================================================

Special services are added to the requestedShipment.specialServicesRequested object.

--- DRY ICE ---
Adds dry ice surcharge to the rate. Only valid for Express services.
"specialServicesRequested": {
  "specialServiceTypes": ["DRY_ICE"],
  "dryIceWeight": {
    "units": "KG",
    "value": 0.5
  }
}
Note: dryIceWeight is per package in the rate request.
Dry ice is NOT available for FedEx Ground or FedEx Ground Economy.
The app shows a validation error if dry ice is enabled with a Ground service.

--- SATURDAY DELIVERY ---
"specialServicesRequested": {
  "specialServiceTypes": ["SATURDAY_DELIVERY"]
}
Only available for: FEDEX_PRIORITY_OVERNIGHT, FEDEX_FIRST_OVERNIGHT, FEDEX_2_DAY,
INTERNATIONAL_PRIORITY (select markets).
Adds Saturday delivery surcharge to the rate.

--- FEDEX ONE RATE ---
FedEx One Rate uses flat-rate pricing regardless of weight (up to 50 lbs).
Set packagingType to a FedEx-branded packaging type:
  FEDEX_ENVELOPE, FEDEX_PAK, FEDEX_SMALL_BOX, FEDEX_MEDIUM_BOX,
  FEDEX_LARGE_BOX, FEDEX_EXTRA_LARGE_BOX, FEDEX_TUBE, FEDEX_BOX
"specialServicesRequested": {
  "specialServiceTypes": ["FEDEX_ONE_RATE"]
}
One Rate is only available for domestic US Express services.

--- HOLD AT LOCATION ---
"specialServicesRequested": {
  "specialServiceTypes": ["HOLD_AT_LOCATION"],
  "holdAtLocationDetail": {
    "locationContactAndAddress": {
      "address": {
        "streetLines": ["1234 FedEx Way"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38103",
        "countryCode": "US"
      }
    },
    "locationType": "FEDEX_OFFICE"
  }
}
locationType values: FEDEX_OFFICE, WALGREENS, DOLLAR_GENERAL, FEDEX_ONSITE, FEDEX_SHIP_CENTER

--- DECLARED VALUE (Insurance) ---
"specialServicesRequested": {
  "specialServiceTypes": ["DECLARED_VALUE"],
  "declaredValueDetail": {
    "amount": 500.00,
    "currency": "USD"
  }
}
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx Ship API v1 — Label Request Structure",
        "content": """
FedEx Ship API v1 — Label (Shipment) Request Structure
=======================================================
Endpoint: POST /ship/v1/shipments

Creates a shipment and returns a shipping label (PDF or ZPL).

Request structure:
{
  "labelResponseOptions": "URL_ONLY",
  "requestedShipment": {
    "shipper": {
      "contact": {
        "personName": "John Doe",
        "phoneNumber": "9012634567",
        "companyName": "Acme Corp"
      },
      "address": {
        "streetLines": ["10 FedEx Pkwy", "Suite 302"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38103",
        "countryCode": "US"
      }
    },
    "recipients": [
      {
        "contact": {
          "personName": "Jane Smith",
          "phoneNumber": "5559876543"
        },
        "address": {
          "streetLines": ["456 Main St"],
          "city": "Los Angeles",
          "stateOrProvinceCode": "CA",
          "postalCode": "90001",
          "countryCode": "US",
          "residential": true
        }
      }
    ],
    "shipDatestamp": "2024-01-10",
    "serviceType": "FEDEX_GROUND",
    "packagingType": "YOUR_PACKAGING",
    "pickupType": "USE_SCHEDULED_PICKUP",
    "blockInsightVisibility": false,
    "shippingChargesPayment": {
      "paymentType": "SENDER",
      "payor": {
        "responsibleParty": {
          "accountNumber": { "value": "123456789" }
        }
      }
    },
    "labelSpecification": {
      "labelFormatType": "COMMON2D",
      "labelOrder": "SHIPPING_LABEL_FIRST",
      "labelPrintingOrientation": "TOP_EDGE_OF_TEXT_FIRST",
      "imageType": "PDF",
      "labelStockType": "PAPER_85X11_TOP_HALF_LABEL"
    },
    "requestedPackageLineItems": [
      {
        "sequenceNumber": 1,
        "weight": { "units": "LB", "value": 5.0 },
        "dimensions": { "length": 12, "width": 8, "height": 6, "units": "IN" }
      }
    ]
  },
  "accountNumber": { "value": "123456789" }
}

Label response:
{
  "output": {
    "transactionShipments": [
      {
        "masterTrackingNumber": "794622372192",
        "serviceType": "FEDEX_GROUND",
        "shipDatestamp": "2024-01-10",
        "pieceResponses": [
          {
            "trackingNumber": "794622372192",
            "packageDocuments": [
              {
                "contentType": "LABEL",
                "copiesToPrint": 1,
                "url": "https://apis.fedex.com/labels/...",
                "encodedLabel": "JVBERi0xLjQ..." (base64 if LABEL_ONLY response)
              }
            ]
          }
        ]
      }
    ]
  }
}

labelResponseOptions:
  URL_ONLY        — returns a temporary URL to download the label (preferred)
  LABEL           — returns base64-encoded label in response
  URL_AND_LABEL   — both

imageType: PDF | PNG | ZPL | EPL2 | STOCK_4_X_6 | PAPER_4X6

paymentType: SENDER | RECIPIENT | THIRD_PARTY | COLLECT
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx Ship API — Special Services in Label Request",
        "content": """
FedEx Ship API — Special Services in Label Requests
====================================================

--- DRY ICE ---
Required for: any shipment containing dry ice as refrigerant.
Only for Express services. Must declare quantity per package.

"shipmentSpecialServices": {
  "specialServiceTypes": ["DRY_ICE"],
  "dryIceDetail": {
    "totalWeight": { "units": "KG", "value": 0.5 },
    "packageCount": 1
  }
}

Also add per-package dry ice weight:
"requestedPackageLineItems": [{
  "specialServicesRequested": {
    "specialServiceTypes": ["DRY_ICE"],
    "dryIceWeight": { "units": "KG", "value": 0.5 }
  }
}]

Both shipment-level AND package-level dry ice must be set.
The app sets: dry ice weight from the user-configured "Dry Ice Weight Per Package" field.

--- SIGNATURE OPTIONS ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["SIGNATURE_OPTION"],
  "signatureOptionDetail": {
    "optionType": "NO_SIGNATURE_REQUIRED"
  }
}
optionType values:
  NO_SIGNATURE_REQUIRED        — no signature needed
  INDIRECT                     — adult or neighbor can sign
  DIRECT                       — adult at address must sign
  ADULT                        — adult 21+ must sign (required for alcohol)

--- SATURDAY DELIVERY ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["SATURDAY_DELIVERY"]
}
Only for eligible services: FEDEX_PRIORITY_OVERNIGHT, FEDEX_FIRST_OVERNIGHT, FEDEX_2_DAY.

--- ALCOHOL ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["ALCOHOL"],
  "alcoholDetail": {
    "alcoholRecipientType": "CONSUMER",
    "licenseOrPermitDetail": {
      "licenseOrPermitExpiryDate": "2025-12-31",
      "licenseOrPermitNumber": "ABC123"
    }
  }
}
alcoholRecipientType: LICENSEE (retailer-to-retailer) | CONSUMER (retailer-to-consumer)
Adult signature is required for alcohol — add ADULT signature option.

--- BATTERY (DANGEROUS GOODS) ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["DANGEROUS_GOODS"],
  "dangerousGoodsDetail": {
    "offeredException": false,
    "accessibility": "ACCESSIBLE",
    "options": ["BATTERY"],
    "batteryMaterialType": "LITHIUM_ION",
    "regulation": "IATA"
  }
}
batteryMaterialType: LITHIUM_ION | LITHIUM_METAL
Battery packing types:
  "contained in equipment" → accessibility: ACCESSIBLE
  "packed with equipment"  → accessibility: INACCESSIBLE
  Standalone batteries     → declare as hazmat

--- RETURN SHIPMENT ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["RETURN_SHIPMENT"],
  "returnShipmentDetail": {
    "returnType": "PRINT_RETURN_LABEL",
    "rma": {
      "number": "RMA12345",
      "reason": "CUSTOMER_REQUEST"
    }
  }
}
returnType: PRINT_RETURN_LABEL | EMAIL_LABEL | PENDING

--- HOLD AT LOCATION ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["HOLD_AT_LOCATION"],
  "holdAtLocationDetail": {
    "locationContactAndAddress": {
      "contact": { "personName": "FedEx Office", "phoneNumber": "9015551234" },
      "address": {
        "streetLines": ["1234 FedEx Way"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38103",
        "countryCode": "US"
      }
    },
    "locationType": "FEDEX_OFFICE"
  }
}

--- NON-STANDARD CONTAINER ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["NON_STANDARD_CONTAINER"]
}
For irregularly shaped packages.

--- DECLARED VALUE ---
"shipmentSpecialServices": {
  "specialServiceTypes": ["DECLARED_VALUE"],
  "totalDeclaredValue": { "amount": 500.00, "currency": "USD" }
}
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — International Shipments",
        "content": """
FedEx REST API — International Shipments
=========================================

International shipments require additional fields in the label request.

Customs commodities (required for every international shipment):
"customsClearanceDetail": {
  "dutiesPayment": {
    "paymentType": "SENDER",
    "payor": {
      "responsibleParty": {
        "accountNumber": { "value": "123456789" }
      }
    }
  },
  "commodities": [
    {
      "description": "Cotton T-Shirt",
      "countryOfManufacture": "US",
      "harmonizedCode": "6109.10.00",
      "name": "T-Shirt",
      "numberOfPieces": 2,
      "quantity": 2,
      "quantityUnits": "PCS",
      "unitPrice": { "amount": 25.00, "currency": "USD" },
      "customsValue": { "amount": 50.00, "currency": "USD" },
      "weight": { "units": "LB", "value": 0.5 }
    }
  ]
}

dutiesPayment types: SENDER | RECIPIENT | THIRD_PARTY | COLLECT

Terms of Sale (INCOTERMS):
  DDP  — Delivered Duty Paid (seller pays duties)
  DDU  — Delivered Duty Unpaid (buyer pays duties)
  EXW  — Ex Works
  FCA  — Free Carrier
  CPT  — Carriage Paid To
  CIP  — Carriage and Insurance Paid
  DAT  — Delivered At Terminal
  DAP  — Delivered At Place

Purpose of Shipment:
  SOLD, GIFT, SAMPLE, REPAIR_AND_RETURN, PERSONAL_EFFECTS, NOT_SOLD

Commercial Invoice — required for dutiable goods:
"internationalDocumentations": {
  "commercialInvoice": {
    "comments": ["Order #1234"],
    "freightCharge": { "amount": 12.50, "currency": "USD" },
    "taxesOrMiscellaneous": { "amount": 0, "currency": "USD" },
    "declarationStatement": "I hereby certify that the goods described...",
    "paymentTerms": "NET30",
    "purpose": "SOLD"
  }
}

Shipper TIN (Tax Identification Number) — required for some countries:
"shipperTins": [
  {
    "tinType": "FEDERAL",
    "number": "12-3456789",
    "usage": "SHIPPER_AND_IMPORTER"
  }
]
tinType: FEDERAL | STATE | PERSONAL_STATE | PERSONAL_NATIONAL | PASSPORT | BUSINESS_NATIONAL
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — Error Codes and Meanings",
        "content": """
FedEx REST API — Error Codes and Their Meanings
================================================

Error response format:
{
  "errors": [
    {
      "code": "AUTHENTICATION.AUTHENTICATION_FAILED",
      "message": "We are unable to process this request...",
      "parameterList": [
        { "key": "client_id", "value": "..." }
      ]
    }
  ]
}

AUTHENTICATION ERRORS:
  AUTHENTICATION.AUTHENTICATION_FAILED
    → API key or secret is wrong. Re-enter credentials in FedEx account settings.
    → Token may have expired. App should refresh OAuth token.

  AUTHENTICATION.NOT_AUTHORIZED
    → Account number not authorized for the requested service.
    → Check if account has freight, One Rate, or international capabilities.

VALIDATION ERRORS (400):
  INVALID.INPUT.EXCEPTION
    → One or more request fields have invalid values.
    → Check weight units, dimensions, date format (YYYY-MM-DD), country code (ISO 2-letter).

  MISSING.REQUIRED.FIELD
    → A required field is absent. Check parameterList for the field name.

  SHIPDATE.VALIDATION.FAILED
    → Ship date is in the past or too far in the future.
    → Use today's date or a date within the booking window.

RATE ERRORS:
  SERVICE.UNAVAILABLE.FOR.SHIPMENT
    → The requested service (e.g. FEDEX_2_DAY) is not available for this origin/destination.
    → Use a different service type, or remove serviceType to get all available services.

  NO.RATES.FOUND
    → FedEx returned no rates. Common causes: invalid zip code, weight=0, service not eligible.

  DRY_ICE.ONLY.VALID.FOR.EXPRESS
    → Dry ice was selected but the service is FEDEX_GROUND or FEDEX_GROUND_HOME_DELIVERY.
    → Dry ice requires an Express service.

  SATURDAY_DELIVERY.NOT.AVAILABLE
    → Saturday delivery requested but origin or destination does not support it.
    → Only FEDEX_PRIORITY_OVERNIGHT and FEDEX_2_DAY support Saturday delivery.

LABEL ERRORS:
  SHIPPER.ACCOUNT.NUMBER.REQUIRED
    → accountNumber missing from request. Always include { "value": "..." }.

  INVALID.ACCOUNT.NUMBER
    → Account number not recognized. Verify the FedEx billing account number.

  PACKAGE.TOO.HEAVY
    → Package weight exceeds service maximum (usually 150 lbs for Express, 150 lbs for Ground).

  PACKAGE.TOO.LARGE
    → Package dimensions exceed service limits. Check length+girth formula.

  MISSING.COMMODITIES
    → International shipment has no customs commodity information.
    → Add customsClearanceDetail.commodities to the request.

  ALCOHOL.REQUIRES.ADULT.SIGNATURE
    → Alcohol shipment must have signatureOptionDetail.optionType = "ADULT".

  HOLD.AT.LOCATION.ADDRESS.INVALID
    → The HAL location address could not be validated by FedEx.
    → Verify the FedEx location address is correct.

PICKUP ERRORS:
  NO.PICKUP.AVAILABLE
    → No pickup available for the requested date/time at origin.
    → Try a different date or use DROPOFF_AT_FEDEX_LOCATION.

SYSTEM ERRORS (500):
  SYSTEM.DOWNTIME
    → FedEx API is temporarily unavailable. Retry after a few minutes.

  INTERNAL.SERVER.ERROR
    → Unexpected server error. Log the X-Customer-Transaction-Id for FedEx support.
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — Pickup API",
        "content": """
FedEx Pickup API — Schedule and Cancel Pickups
===============================================
Endpoint (create): POST /pickup/v1/pickups
Endpoint (cancel): PUT  /pickup/v1/pickups/cancel

Create Pickup Request:
{
  "associatedAccountNumber": { "value": "123456789" },
  "originDetail": {
    "pickupAddressType": "ACCOUNT",
    "pickupLocation": {
      "contact": {
        "personName": "John Doe",
        "phoneNumber": "9012634567",
        "companyName": "Acme Corp"
      },
      "address": {
        "streetLines": ["10 FedEx Pkwy"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38103",
        "countryCode": "US",
        "residential": false
      }
    },
    "packageLocation": "FRONT",
    "buildingPartCode": "SUITE",
    "buildingPartDescription": "Suite 302",
    "readyDateTimestamp": "2024-01-10T14:00:00",
    "customerCloseTime": "17:00:00"
  },
  "pickupType": "ON_CALL",
  "packageCount": 3,
  "totalWeight": { "units": "LB", "value": 45.0 },
  "cargoType": "CARGO_NOT_IN_FLIGHT",
  "commodityDescription": "General merchandise",
  "expressFreightDetail": { "packingListEnclosed": false }
}

Pickup response contains:
  pickupConfirmationCode — confirmation number to show user
  location              — FedEx facility that will handle pickup

Cancel Pickup:
{
  "associatedAccountNumber": { "value": "123456789" },
  "pickupConfirmationCode": "XXXX1234",
  "scheduledDate": "2024-01-10",
  "location": "MEMA",
  "remarks": "Customer cancelled order"
}

packageLocation: FRONT | REAR | SIDE | NONE | SECURED_LOCATION
buildingPartCode: SUITE | DEPT | FLOOR | ROOM | SLOT | UNIT | WING | OTHER

readyDateTimestamp: ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
customerCloseTime: HH:MM:SS (24-hour)
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — Track API",
        "content": """
FedEx Track API — Tracking Shipments
======================================
Endpoint: POST /track/v1/trackingnumbers

Request:
{
  "includeDetailedScans": true,
  "trackingInfo": [
    {
      "trackingNumberInfo": {
        "trackingNumber": "794622372192"
      }
    }
  ]
}

Response — key fields:
{
  "output": {
    "completeTrackResults": [
      {
        "trackingNumber": "794622372192",
        "trackResults": [
          {
            "trackingNumberInfo": {
              "trackingNumber": "794622372192",
              "trackingNumberUniqueId": "...",
              "carrierCode": "FDXG"
            },
            "shipperInformation": { ... },
            "recipientInformation": { ... },
            "latestStatusDetail": {
              "code": "DL",
              "derivedCode": "DL",
              "statusByLocale": "Delivered",
              "description": "Delivered",
              "scanLocation": { "city": "Los Angeles", "stateOrProvinceCode": "CA" }
            },
            "dateAndTimes": [
              { "type": "ACTUAL_DELIVERY", "dateTime": "2024-01-12T14:23:00-08:00" },
              { "type": "ESTIMATED_DELIVERY", "dateTime": "2024-01-12T20:00:00" }
            ],
            "availableImages": [ { "type": "SIGNATURE_PROOF_OF_DELIVERY" } ],
            "packageDetails": {
              "count": 1,
              "weightAndDimensions": {
                "weight": [{ "value": "5.00", "unit": "LB" }],
                "dimensions": [{ "length": 12, "width": 8, "height": 6, "units": "IN" }]
              }
            },
            "events": [
              {
                "timestamp": "2024-01-12T14:23:00-08:00",
                "eventType": "DL",
                "eventDescription": "Delivered",
                "scanLocation": { ... }
              }
            ]
          }
        ]
      }
    ]
  }
}

Common status codes:
  OC  — Order Created (label generated, not yet picked up)
  PU  — Picked Up
  AR  — Arrived at FedEx facility
  DP  — Departed FedEx facility
  OD  — On FedEx vehicle for delivery
  DL  — Delivered
  DE  — Delivery Exception (attempt failed)
  CA  — Cancelled
  SE  — Shipment Exception (problem with shipment)
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "SOAP to REST API Migration — Key Differences",
        "content": """
FedEx SOAP to REST API Migration — Key Differences
===================================================

IMPORTANT: This FedEx Shopify App has fully migrated to REST API.
SOAP (xml-based) endpoints are no longer used. Do not reference SOAP structures.

Key differences between old SOAP and current REST:

Authentication:
  SOAP: Used Meter Number + Account Number as authentication
  REST: Uses OAuth 2.0 (API Key + Secret) → Bearer token
  MIGRATION: Meter Number is no longer required for REST auth

Rate Request:
  SOAP: RateRequest with RequestedShipment XML element
  REST: POST /rate/v1/rates/quotes with JSON body
  MIGRATION: Same logical fields, JSON keys use camelCase

Label/Shipment Request:
  SOAP: ProcessShipmentRequest XML
  REST: POST /ship/v1/shipments with JSON body
  MIGRATION: requestedPackageLineItems replaces RequestedPackageLineItems

Special Handling:
  SOAP: SpecialServicesRequested.SpecialServiceTypes array (UPPERCASE strings)
  REST: specialServicesRequested.specialServiceTypes array (UPPERCASE strings — same!)
  MIGRATION: Special service type names are the same between SOAP and REST

Dry Ice (specific):
  SOAP: DryIceWeight element under each package
  REST:
    - Shipment level: shipmentSpecialServices.dryIceDetail.totalWeight
    - Package level: requestedPackageLineItems[n].specialServicesRequested.dryIceWeight
  MIGRATION: Must set BOTH shipment-level AND package-level dry ice in REST

Response format:
  SOAP: XML with WS-* envelope, faults as XML Fault elements
  REST: JSON, errors as { "errors": [{ "code": "...", "message": "..." }] }
  MIGRATION: Error handling must parse JSON errors, not XML faults

Endpoint structure:
  SOAP: Single WSDL endpoint, different operations within
  REST: Multiple RESTful endpoints per capability
    /rate/v1/rates/quotes         (formerly RateService.wsdl)
    /ship/v1/shipments            (formerly ShipService.wsdl)
    /track/v1/trackingnumbers     (formerly TrackService.wsdl)
    /pickup/v1/pickups            (formerly PickupService.wsdl)
    /oauth/token                  (new — no SOAP equivalent)

What has NOT changed (same logic, different syntax):
  • Same FedEx service type strings (FEDEX_GROUND, FEDEX_2_DAY, etc.)
  • Same special service type strings (DRY_ICE, SATURDAY_DELIVERY, etc.)
  • Same account number billing concept
  • Same packaging type strings (YOUR_PACKAGING, FEDEX_ENVELOPE, etc.)
  • Same address structure (streetLines, city, stateOrProvinceCode, postalCode)
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "How the FedEx Shopify App Builds API Requests",
        "content": """
How the FedEx Shopify App Constructs FedEx REST API Requests
=============================================================

This describes the app's internal logic for building rate and label requests.

--- Rate Request Construction ---
Trigger: Customer at Shopify checkout requests shipping rates.

1. Shipper address: pulled from Shopify store's origin address (Settings → Locations)
2. Recipient address: the customer's Shopify checkout shipping address
3. Products: each line item's weight and dimensions (from Shopify product metafields)
4. Packaging algorithm:
   a. If volumetric weight enabled: weight = max(actual, L×W×H/139)
   b. Splits into multiple packages if total weight > Max Weight setting
   c. Stacks products if "Stack Products" enabled, else one product per package
   d. Falls back to Default Dimensions if product has no dimensions
5. Special services added to rate request based on settings:
   - Dry Ice enabled → adds DRY_ICE special service
   - One Rate enabled → sets packaging type to FedEx packaging, adds FEDEX_ONE_RATE
   - Saturday Delivery enabled → adds SATURDAY_DELIVERY
   - Hold at Location enabled → adds HOLD_AT_LOCATION with configured location
6. Rate request sent to: /rate/v1/rates/quotes
7. Response parsed: one rate option per FedEx service type enabled in settings
8. Rates displayed at checkout with service name (optionally with transit days)
9. Markup applied ($ or %) if configured per service

--- Label Request Construction ---
Trigger: Merchant clicks "Generate Label" for an order (manual or auto).

1. Same origin + destination addresses as rate request
2. Same package dimensions/weights as when rate was calculated
3. Additional label-specific fields:
   - shipper.contact: merchant store name and phone
   - recipient.contact: customer name and phone from order
   - shipDatestamp: today's date (or configured deferred date)
   - labelSpecification.imageType: PDF (default), ZPL for thermal printers
4. paymentType: SENDER (merchant pays, uses their account number)
5. Special services from label-time settings (may differ from rate-time):
   - Signature option selected by merchant in side dock
   - Dry ice weight confirmed
   - Return label if requested
   - Insurance / declared value
6. Label request sent to: /ship/v1/shipments
7. Response: tracking number saved to Shopify order, label URL stored for download
8. Order status updated to "label generated" in app UI
9. Shopify fulfillment created with tracking number (if auto-fulfill enabled)

--- Error Handling ---
If FedEx returns an error:
1. Error logged to Request Log (accessible via app UI)
2. Order status set to "error"
3. Error message shown in app UI
4. Full request/response saved for debugging
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx REST API — Label Format and Output Options",
        "content": """
FedEx Label Format and Output Options
======================================

labelSpecification fields:
  labelFormatType:         COMMON2D | LABEL_DATA_ONLY | VICS_BILL_OF_LADING
  labelOrder:              SHIPPING_LABEL_FIRST | SHIPPING_LABEL_LAST
  imageType:               PDF | PNG | ZPL | EPL2
  labelStockType:          PAPER_85X11_TOP_HALF_LABEL | PAPER_85X11_BOTTOM_HALF_LABEL
                           STOCK_4_X_6 | STOCK_4_X_6_75_CUTOUT_3_X_4_75
                           PAPER_4X6 | PAPER_4X6_LABELJET_4X8
  labelPrintingOrientation: TOP_EDGE_OF_TEXT_FIRST | BOTTOM_EDGE_OF_TEXT_FIRST
  customerSpecifiedDetail: for custom reference numbers on label

labelResponseOptions:
  URL_ONLY   → response has URL, must download label from URL (expires in 24 hours)
  LABEL      → response has base64-encoded label data
  URL_AND_LABEL → both

Reference fields that appear on the label:
  customerReferences: [
    { "customerReferenceType": "CUSTOMER_REFERENCE", "value": "Order #1234" },
    { "customerReferenceType": "P_O_NUMBER", "value": "PO-5678" },
    { "customerReferenceType": "INVOICE_NUMBER", "value": "INV-9012" }
  ]
  customerReferenceType values:
    CUSTOMER_REFERENCE | P_O_NUMBER | INVOICE_NUMBER | DEPARTMENT_NUMBER
    INTRACOUNTRY_REGULATORY_REFERENCE | SHIPPER_REFERENCE

The app puts the Shopify order ID as the CUSTOMER_REFERENCE on every label.
""",
    },

    # ------------------------------------------------------------------
    {
        "title": "FedEx App — Complete Special Services Test Matrix",
        "content": """
FedEx Shopify App — Special Services Test Matrix
=================================================
This matrix defines which special services can be combined and the expected
API behavior for each.

SERVICE: DRY ICE
  Enabled via: Settings → Additional Services → Enable Dry Ice ✓
  Config: Dry Ice Weight Per Package (lbs)
  Affects: Rate request + Label request
  API field: specialServiceTypes=['DRY_ICE'] + dryIceWeight
  Restriction: Express services ONLY (not Ground, not Ground Economy)
  Cannot combine with: Ground services
  Test scenarios:
    ✓ Dry ice + Express service → rate shows dry ice surcharge
    ✓ Dry ice + Express → label generates with DRY_ICE special handling
    ✗ Dry ice + Ground service → error or validation warning
    ✓ Dry ice weight = 0.5 kg minimum
    ✓ Multiple packages → same dry ice weight applied per package

SERVICE: SIGNATURE
  Enabled via: Settings → Additional Services → Signature Options dropdown
  Options: No Signature | Indirect | Direct | Adult
  Affects: Label request only (signature does not affect rate)
  API field: signatureOptionDetail.optionType
  Cannot combine with: N/A (stacks with all other services)
  Test scenarios:
    ✓ No Signature → no signatureOptionDetail in request
    ✓ Indirect Signature → signatureOptionDetail.optionType = INDIRECT
    ✓ Direct Signature → signatureOptionDetail.optionType = DIRECT
    ✓ Adult Signature → signatureOptionDetail.optionType = ADULT (required for alcohol)

SERVICE: SATURDAY DELIVERY
  Enabled via: Settings → Additional Services → Enable Saturday Delivery ✓
  Affects: Rate request + Label request
  API field: specialServiceTypes=['SATURDAY_DELIVERY']
  Restriction: FEDEX_PRIORITY_OVERNIGHT, FEDEX_FIRST_OVERNIGHT, FEDEX_2_DAY only
  Test scenarios:
    ✓ Saturday Delivery + Priority Overnight → surcharge in rate
    ✓ Saturday Delivery + Priority Overnight → label with Saturday delivery
    ✗ Saturday Delivery + Ground → no effect (Ground doesn't support it)

SERVICE: FEDEX ONE RATE
  Enabled via: Settings → Additional Services → Enable FedEx One Rate® ✓
  Affects: Rate request (packaging type changes)
  API field: packagingType = FEDEX_ENVELOPE | FEDEX_PAK | FEDEX_BOX etc.
             specialServiceTypes=['FEDEX_ONE_RATE']
  Restriction: Domestic US only, Express services only
  Test scenarios:
    ✓ One Rate + Envelope → flat rate pricing shown at checkout
    ✓ One Rate + Medium Box → flat rate pricing
    ✗ One Rate + international → not available
    ✓ One Rate ignores package weight (up to 50 lbs)

SERVICE: ALCOHOL
  Enabled via: Settings → Additional Services → Enable Alcohol ✓
  Per-product: Products → [product] → Alcohol toggle
  Affects: Label request
  API field: specialServiceTypes=['ALCOHOL'] + alcoholDetail
  Required: Adult Signature must also be enabled
  Test scenarios:
    ✓ Alcohol product + Adult Signature → label generates correctly
    ✗ Alcohol product + No Signature → may fail regulatory check
    ✓ alcoholRecipientType = CONSUMER for B2C orders
    ✓ alcoholRecipientType = LICENSEE for B2B orders

SERVICE: BATTERY (DANGEROUS GOODS)
  Enabled via: Products → [product] → Battery toggle
  Affects: Label request
  API field: specialServiceTypes=['DANGEROUS_GOODS'] + dangerousGoodsDetail
  Test scenarios:
    ✓ Lithium Ion battery + accessible → label with IATA/dangerous goods marking
    ✓ Lithium Metal battery + inaccessible packaging
    ✓ Standalone battery → full hazmat declaration

SERVICE: INSURANCE / DECLARED VALUE
  Enabled via: Settings → Additional Services → Enable Insurance ✓
  Affects: Label request
  API field: specialServiceTypes=['DECLARED_VALUE'] + totalDeclaredValue
  Test scenarios:
    ✓ Insurance enabled → declared value in request = configured amount
    ✓ Percentage of product → declared value = order total × percentage
    ✓ No insurance → no declaredValue in request

SERVICE: HOLD AT LOCATION
  Enabled via: Settings → Additional Services → Enable Hold at Location ✓
  Config: Location type (FedEx Office, Walgreens, Dollar General, etc.)
  Affects: Rate request + Label request
  API field: specialServiceTypes=['HOLD_AT_LOCATION'] + holdAtLocationDetail
  Test scenarios:
    ✓ HAL + FedEx Office → location detail in label request
    ✓ HAL + Walgreens → different location type
""",
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_fedex_rest_api_knowledge() -> list[Document]:
    """
    Return a list of chunked LangChain Documents covering the complete
    FedEx REST API knowledge needed for test case validation and generation.
    """
    raw_docs: list[Document] = []
    for article in _ARTICLES:
        raw_docs.append(Document(
            page_content=f"{article['title']}\n\n{article['content'].strip()}",
            metadata={
                "source": "fedex_rest_api",
                "source_type": "fedex_rest",
                "title": article["title"],
                "type": "api_knowledge",
            },
        ))

    chunked = _SPLITTER.split_documents(raw_docs)
    logger.info(
        "FedEx REST API knowledge: %d articles → %d chunks",
        len(_ARTICLES), len(chunked),
    )
    return chunked


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    docs = load_fedex_rest_api_knowledge()
    print(f"\n✅ FedEx REST API knowledge: {len(docs)} document chunks")
    for doc in docs[:3]:
        print(f"\n--- {doc.metadata.get('title', '?')} ---")
        print(doc.page_content[:300])
