"""
AI QA Agent  —  Step 2b (Agentic Upgrade)
==========================================
Replaces the old screenshot-only QA Explorer with a true agentic loop:

  AC text
    │
    ▼
  1. Claude extracts each scenario
    │
    ▼  (per scenario)
  2. Query code RAG  →  automation POM + backend API + QA knowledge
     Claude knows what locators exist, what API endpoints to watch
    │
    ▼
  3. Claude plans: which app path to navigate, what to interact with
    │
    ▼  (agentic loop — up to 10 steps)
  4. Browser action  →  navigate / click / fill / scroll / observe
  5. Capture: page accessibility tree + screenshot + network calls
  6. Claude decides next action  OR  gives verdict  OR  asks QA
    │
    ▼
  ✅ pass / ❌ fail / ⚠️ partial  per scenario
    │
    ▼
  Final report  →  feeds directly into Write Automation Code

If Claude can't find a feature:
  → status = "qa_needed"
  → Dashboard shows Claude's question + QA text input
  → QA answers → re-run that scenario with the guidance injected
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import tempfile
import time
import threading
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Callable

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

_CODEBASE       = Path(config.AUTOMATION_CODEBASE_PATH) if config.AUTOMATION_CODEBASE_PATH else None
_AUTH_JSON      = _CODEBASE / "auth.json" if _CODEBASE else None
_ENV_FILE       = _CODEBASE / ".env" if _CODEBASE else None
MAX_STEPS       = 24
MIN_QA_STEP     = 12
MAX_RECOVERIES  = 2
_ANTI_BOT_ARGS  = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]
_CHALLENGE_PHRASES = [
    "connection needs to be verified",
    "let us know you",
    "verify you are human",
    "just a moment",
    "checking your browser",
]


def _extract_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return ""
    try:
        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts).strip()
    except Exception as exc:
        logger.debug("PDF text extraction failed: %s", exc)
        return ""


def _capture_document_pdf_content(viewer_url: str) -> dict:
    content: dict = {"viewer_url": viewer_url}
    try:
        parsed = urllib.parse.urlparse(viewer_url)
        qs = urllib.parse.parse_qs(parsed.query)
        document_url = ""
        for key in ("document", "url", "file"):
            vals = qs.get(key) or []
            if vals and vals[0]:
                document_url = vals[0]
                break
        if not document_url:
            if parsed.path.lower().endswith(".pdf"):
                document_url = viewer_url
            else:
                content["note"] = "Document URL not found in viewer URL"
                return content

        content["document_url"] = document_url
        with urllib.request.urlopen(document_url, timeout=30) as resp:
            pdf_bytes = resp.read()
        content["size_bytes"] = len(pdf_bytes)
        pdf_text = _extract_pdf_text_from_bytes(pdf_bytes)
        if pdf_text:
            content["pdf_text"] = pdf_text[:12000]
            content["pdf_text_preview"] = pdf_text[:4000]
            content["document_summary"] = _summarize_pdf_text(pdf_text)
        else:
            content["note"] = "PDF downloaded but text extraction unavailable or empty"
        return content
    except Exception as exc:
        logger.debug("Document capture from viewer URL failed: %s", exc)
        content["note"] = f"Document capture failed: {exc}"
        return content


def _summarize_pdf_text(pdf_text: str) -> dict[str, object]:
    text = (pdf_text or "").strip()
    lower = text.lower()
    return {
        "has_commercial_invoice_text": "commercial invoice" in lower,
        "has_packing_slip_text": "packing slip" in lower,
        "has_label_generated_codes": [code for code in ("ICE", "ALCOHOL", "ELB", "ASR", "DSR", "ISR", "SS AVXA") if code.lower() in lower],
        "mentions_purpose_of_shipment": "purpose of shipment" in lower,
        "mentions_tracking_number": "tracking" in lower or "trk#" in lower,
        "text_preview": text[:1200],
    }


def _summarize_document_bundle(bundle: dict[str, object]) -> dict[str, object]:
    summary = {
        "document_files": [],
        "has_label_pdf": False,
        "has_packing_slip_pdf": False,
        "has_commercial_invoice_pdf": False,
        "pdf_summaries": {},
    }
    for name, content in bundle.items():
        if name.startswith("_"):
            continue
        summary["document_files"].append(name)
        lname = name.lower()
        if lname.endswith(".pdf"):
            if "label" in lname:
                summary["has_label_pdf"] = True
            if "packing" in lname or "slip" in lname:
                summary["has_packing_slip_pdf"] = True
            if "invoice" in lname or "commercial" in lname:
                summary["has_commercial_invoice_pdf"] = True
        if isinstance(content, dict) and content.get("pdf_text_preview"):
            summary["pdf_summaries"][name] = {
                "has_commercial_invoice_text": content.get("has_commercial_invoice_text", False),
                "has_packing_slip_text": content.get("has_packing_slip_text", False),
                "has_label_generated_codes": content.get("has_label_generated_codes", []),
                "mentions_purpose_of_shipment": content.get("mentions_purpose_of_shipment", False),
                "text_preview": content.get("pdf_text_preview", "")[:800],
            }
    return summary


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VerificationStep:
    action: str
    description: str
    target: str = ""
    success: bool = True
    screenshot_b64: str = ""        # base64 PNG of page at this step
    network_calls: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario: str
    status: str = "pending"         # pass | fail | partial | skipped | qa_needed
    verdict: str = ""               # Claude's finding
    steps: list[VerificationStep] = field(default_factory=list)
    qa_question: str = ""           # what Claude asks QA when stuck
    bug_report: dict = field(default_factory=dict)  # result from bug_reporter.notify_devs_of_bug
    scenario_category: str = ""
    order_action: str = ""
    orchestrated: bool = False
    setup_succeeded: bool = False
    setup_url: str = ""
    setup_screenshot_b64: str = ""
    final_url: str = ""
    final_screenshot_b64: str = ""
    final_network_calls: list[str] = field(default_factory=list)
    evidence_notes: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    card_name: str
    app_url: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status in ("fail", "partial"))

    @property
    def qa_needed(self) -> "list[ScenarioResult]":
        return [s for s in self.scenarios if s.status == "qa_needed"]

    def to_automation_context(self) -> str:
        """Convert verified flows into context string for automation writer."""
        lines = [f"=== Smart AC Verification: {self.card_name} ===", f"App: {self.app_url}", ""]
        for sv in self.scenarios:
            icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(sv.status, "⏭️")
            lines.append(f"{icon} {sv.scenario}")
            for step in sv.steps:
                if step.action in ("click", "fill", "navigate") and step.target:
                    lines.append(f"   [{step.action}] '{step.target}' — {step.description}")
                if step.network_calls:
                    for nc in step.network_calls[:3]:
                        lines.append(f"   [api] {nc}")
            if sv.verdict:
                lines.append(f"   Result: {sv.verdict}")
            lines.append("")
        return "\n".join(lines)


@dataclass(frozen=True)
class ScenarioPrerequisitePlan:
    category: str
    order_action: str
    product_type: str = "simple"
    address_type: str = "default"
    requires_manual_label: bool = False
    requires_existing_label: bool = False
    label_flow: str = "manual"
    setup_steps: tuple[str, ...] = ()
    verification_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackagingRequirements:
    method: str = ""
    unit_label: str = ""
    length: str = ""
    width: str = ""
    height: str = ""
    weight: str = ""
    box_name: str = ""
    custom_box_name: str = ""
    use_volumetric: bool | None = None
    stack_products_in_boxes: bool | None = None
    additional_weight_enabled: bool | None = None
    additional_weight_mode: str = ""
    additional_weight_value: str = ""
    max_weight: str = ""


@dataclass(frozen=True)
class OrderGridRequirements:
    search_order_id: str = ""
    date_filter: str = ""
    add_filter: str = ""
    add_filter_value: str = ""
    status_filter: str = ""
    clear_all: bool = False
    status_tab: str = ""


@dataclass(frozen=True)
class ParsedTestCase:
    index: int
    tc_id: str
    title: str
    tc_type: str
    priority: str
    preconditions: str
    body: str
    execution_flow: str = "manual"

    @property
    def priority_rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}.get(self.priority.lower(), 3)

    @property
    def execution_text(self) -> str:
        parts = [f"{self.tc_id}: {self.title}"]
        if self.tc_type:
            parts.append(f"Type: {self.tc_type}")
        if self.priority:
            parts.append(f"Priority: {self.priority}")
        if self.preconditions:
            parts.append(f"Preconditions: {self.preconditions}")
        if self.body:
            parts.append(self.body)
        return "\n".join(parts)


def _build_specialized_verification_context(
    scenario: str,
    plan: ScenarioPrerequisitePlan,
    ctx: str = "",
) -> str:
    s = (scenario or "").lower()
    lines: list[str] = []

    if plan.category == "packaging_flow":
        req = _extract_packaging_requirements(f"{scenario}\n\n{ctx}")
        lines.append("=== PACKAGING VERIFICATION RULES ===")
        lines.append("This is a packaging-sensitive scenario. Prefer exact verification, not generic UI checks.")
        if req.method:
            lines.append(f"- Packing Method must align with: {req.method}")
        if req.unit_label:
            lines.append(f"- Weight/Dimension unit must align with: {req.unit_label}")
        if req.box_name:
            lines.append(f"- Carrier box expectation: {req.box_name}")
        if req.custom_box_name:
            lines.append(f"- Custom box expectation: {req.custom_box_name}")
        if req.length and req.width and req.height:
            lines.append(f"- Product dimensions expectation: {req.length} x {req.width} x {req.height}")
        if req.weight:
            lines.append(f"- Product weight expectation: {req.weight}")
        if req.max_weight:
            lines.append(f"- Max package weight expectation: {req.max_weight}")
        if req.stack_products_in_boxes is not None:
            lines.append(f"- Stack products in boxes expectation: {req.stack_products_in_boxes}")
        if req.additional_weight_enabled is not None:
            lines.append(f"- Additional weight enabled: {req.additional_weight_enabled}")
        if req.additional_weight_mode:
            lines.append(f"- Additional weight mode: {req.additional_weight_mode}")
        if req.additional_weight_value:
            lines.append(f"- Additional weight value: {req.additional_weight_value}")
        lines.append("- Packaging setup should mirror automation: save base Packing Method first, then open `more settings` for volumetric weight, stacking, max weight, carrier-box restriction, custom boxes, and additional-weight options.")
        lines.append("- Use MANUAL label flow so pre-submit logs are available when needed.")
        lines.append("- Before concluding PASS, prefer checking the in-flow logs or downloaded JSON/documents if the scenario mentions request, response, logs, rates log, documents, or print documents.")
        lines.append("- Strong verification signals for packaging:")
        lines.append("  1. Label generation completes successfully.")
        lines.append("  2. Order Summary / Shipping grid shows the expected generated-label state.")
        lines.append("  3. If View Logs is available, use action=open_view_logs and inspect Request/Response JSON for packaging-related values.")
        lines.append("  4. If Print/Download Documents is available, use action=open_print_documents or action=open_download_documents for deterministic verification.")
        if req.box_name:
            lines.append(f"- Packaging-specific check: verify logs/documents do not contradict the expected carrier box '{req.box_name}'.")
        if req.weight or (req.length and req.width and req.height):
            lines.append("- Packaging-specific check: compare visible/request values against the exact weight/dimensions above when logs or JSON are available.")

    if any(token in s for token in ("rates log", "rate log", "view logs", "request log", "response log")):
        lines.append("=== LOG VERIFICATION RULES ===")
        lines.append("- Prefer using action=open_view_logs or action=open_request_response_zip instead of relying only on page text.")
        lines.append("- For PASS, verify Request and/or Response JSON is visible and relevant to the tested order or label flow.")
        lines.append("- If the scenario expects a specific request field, weight, box, service, or packaging behavior, inspect logs for that exact value before concluding PASS.")

    if any(token in s for token in ("soldto", "sold to", "billing address", "request payload", "city.too.short")):
        lines.append("=== SOLDTO / BILLING VERIFICATION RULES ===")
        lines.append("- This scenario is about shipment request payload correctness, not only UI reachability.")
        lines.append("- If manual label flow is open, do not stop after order creation or landing on the label page.")
        lines.append("- Complete the manual label flow far enough to create the label unless the scenario explicitly says to stop before generation.")
        lines.append("- After label generation, prefer action=open_request_response_zip (More Actions → How To → Click Here) to inspect the createShipment request JSON.")
        lines.append("- Use action=open_view_logs only if the request field can be verified before final label generation; otherwise prefer the request/response ZIP.")
        lines.append("- For PASS, confirm both:")
        lines.append("  1. The label generation reaches a real success state in the app.")
        lines.append("  2. The request payload shows the expected soldTo / billing-address behavior.")
        lines.append("- For empty/short billing-address scenarios, fail the case if no label is generated and no request payload evidence is captured.")

    if any(token in s for token in ("print documents", "download document", "download documents", "commercial invoice", "packing slip")):
        lines.append("=== DOCUMENT VERIFICATION RULES ===")
        lines.append("- Prefer action=open_print_documents or action=open_download_documents after label generation, not only pre-label UI checks.")
        lines.append("- Do NOT stop at clicking 'More Actions' alone; use the deterministic document actions instead of generic menu clicking.")
        lines.append("- If a document download or viewer opens, use that as evidence and record it before concluding PASS.")
        lines.append("- Treat Print Documents and Download Documents as different evidence sources: Print Documents gives viewer/PDF text proof, Download Documents gives a physical-document bundle summary.")
        if any(token in s for token in ("commercial invoice", " ci ", " customs ", "international")):
            lines.append("- Commercial Invoice (CI) is an international-shipment artifact. Do not use a domestic US shipment when the scenario expects CI.")

    story_training = _build_story_training_context(scenario, plan, ctx)
    if story_training:
        if lines:
            lines.append(story_training)
        else:
            lines = [story_training]

    return "\n".join(lines).strip()


def _build_story_training_context(
    scenario: str,
    plan: ScenarioPrerequisitePlan,
    ctx: str = "",
) -> str:
    text = f" {(scenario or '').lower()} {(ctx or '').lower()} "
    lines: list[str] = []

    if _has_any(text, ("fdx-111", "sanitize empty billing", "city.too.short", "streetline1.empty")):
        lines.append("=== FDX-111 TRAINING ===")
        lines.append("- This is an international soldTo sanitization scenario.")
        lines.append("- Prefer an international shipment and verify the captured shipment request payload, not only UI success.")
        lines.append("- PASS requires both: label generation succeeds and soldTo omits invalid/empty billing nodes.")
        lines.append("- If the billing city is short like 'NY', confirm soldTo keeps the node but omits the city field.")
        lines.append("- If the billing address is completely empty, confirm soldTo is omitted entirely.")

    if _has_any(text, ("fdx-112", "restrict soldto", "soldto to international", "domestic shipment")):
        lines.append("=== FDX-112 TRAINING ===")
        lines.append("- This is a domestic soldTo suppression scenario.")
        lines.append("- Use a domestic shipment and prove the request payload contains no soldTo node at all.")
        lines.append("- Do not treat a generated label alone as sufficient evidence; request payload proof is required.")

    if _has_any(text, ("fdx-113", "accurate error codes", "label failure", "fedex error code", "generic error")):
        lines.append("=== FDX-113 TRAINING ===")
        lines.append("- This is a failure-state verification scenario, not a success-state label scenario.")
        lines.append("- Create or reuse a label request that fails with a real FedEx validation error.")
        lines.append("- PASS requires the UI to surface the FedEx error code/message instead of only a generic fallback.")
        lines.append("- Prefer visible error panel evidence from the label failure UI before concluding PASS.")

    if _has_any(text, ("fdx-115", "purpose of shipment", "shipment purpose override", "slgp")):
        lines.append("=== FDX-115 TRAINING ===")
        lines.append("- This is a per-order manual-label override scenario.")
        lines.append("- First establish the global International Shipping purpose setting from Settings > International Shipping Settings > more settings.")
        lines.append("- Then override the value on the SLGP/manual-label flow for the current order.")
        lines.append("- PASS requires request-side proof that the per-order override wins over the saved global default.")
        lines.append("- Prefer live request evidence first (rate logs / request payload), then confirm the same overridden value in the downloaded label-request form.")
        lines.append("- If commercial-invoice evidence is visible after generation, use it as secondary confirmation only.")

    if _has_any(text, ("fdx-164", "importer of record", "ior", "importerofrecord", "commercial invoice")):
        lines.append("=== FDX-164 TRAINING ===")
        lines.append("- This is an international customs-document scenario.")
        lines.append("- Use an account/product flow where Importer Of Record is enabled before label generation.")
        lines.append("- PASS requires request payload proof that importerOfRecord is present with the correct key spelling.")
        lines.append("- Then verify the commercial invoice/printed documents reflect the IOR details.")

    if _has_any(text, ("fdx-175", "weight sync", "stale weight", "product weight sync", "shopify weight update")):
        lines.append("=== FDX-175 TRAINING ===")
        lines.append("- This is a product-sync scenario, not a normal label-generation-first scenario.")
        lines.append("- Prefer Shopify Products and FedEx App Products verification over direct label flow.")
        lines.append("- The primary proof is that a Shopify product weight change becomes visible in the app-managed product/rate flow.")
        lines.append("- Only use label or rate generation as downstream confirmation after product sync is visible.")

    if plan.category == "checkout_rates" and _has_any(text, ("rates log", "signature", "special service")):
        lines.append("=== STOREFRONT / RATES LOG TRAINING ===")
        lines.append("- For storefront scenarios, use the latest Rates Log entry created by the current checkout as the primary evidence.")
        lines.append("- Only scan a few older rows as fallback if the latest row is stale or delayed.")

    if plan.category == "settings_or_grid" and _has_any(text, ("settings", "configuration", "save setting", "documents/label", "notifications", "print settings", "return settings", "pickup settings", "rate settings", "international shipping")):
        lines.append("=== SETTINGS TRAINING ===")
        lines.append(f"- Open the most specific settings route first: `{_settings_route_for_scenario(scenario)}`.")
        lines.append("- Use the target page heading and its primary field or toggle as the readiness proof, not only a generic Save button.")
        lines.append("- For settings persistence checks, prefer: open page -> change value -> save -> reopen same page -> verify persisted state.")
        lines.append("- For International Shipping settings, treat the Commercial Invoice more-settings surface as a distinct verification area.")
        lines.append("- Prefer the section-scoped Save button that belongs to the active settings block (Rate Settings, Print Settings, Return Settings, Return Label Settings, etc.), not the first Save button on the page.")

    if plan.category == "product_admin":
        lines.append("=== PRODUCT ADMIN TRAINING ===")
        lines.append("- First decide whether this is Shopify Products or FedEx App Products; do not mix them.")
        lines.append("- For FedEx App Products, use product search, open the product detail page, and verify the exact product control needed by the scenario.")
        lines.append("- For Shopify Products, prefer detail fields like title, price, inventory tracked, SKU, weight, tags, country of origin, and HS code as proof rather than only the page URL.")
        lines.append("- For persistence checks, use: open product -> change field -> save -> reopen or re-check the same field.")
        lines.append("- For Shopify product create/edit flows, prefer the same save sequence used by automation: set title/price/inventory/SKU/weight/customs fields -> click Save -> verify the saved product heading or reopened field values.")
        lines.append("- If the scenario is `create product`, open `Add product` first; if a specific product title is known, search it from Shopify Products and open that exact detail page before verifying fields.")

    if plan.category == "settings_or_grid" and _has_any(text, ("additional services", "dry ice", "fedex one rate", "duties and taxes in checkout rates")):
        lines.append("=== ADDITIONAL SERVICES TRAINING ===")
        lines.append("- Treat Additional Services as a settings-save flow, not only a heading check.")
        lines.append("- Preferred proof: open Settings -> scroll to the exact section -> verify the target toggle/input -> save -> confirm the section remains in the expected state after reopening.")
        lines.append("- For Dry Ice, use the checkbox, weight, and unit together; for FedEx One Rate, also ensure packaging prerequisites are not ignored.")
        lines.append("- Use the section-scoped Save button, not just the first visible Save button on the page.")
        lines.append("- For Duties and Taxes, keep International Shipping / Rate Settings nearby as contextual proof that the correct Additional Services block was used.")
        lines.append("- After verification, prefer cleanup that returns these toggles to their default disabled state so later scenarios are not polluted.")

    if plan.category == "settings_or_grid" and _has_any(text, ("order grid", "filter", "search by order", "date filter", "add filter", "clear all", "pending", "label generated")):
        lines.append("=== ORDER GRID TRAINING ===")
        lines.append("- Treat the Shipping grid filters as a structured flow, not a free-form browse.")
        lines.append("- Preferred order-grid proof: open Shipping -> open Search and filter results -> apply the named filter -> verify the table remains visible and the filter control/rows reflect the expected state.")
        lines.append("- For status filters, prefer visible row-status evidence such as `label generated` over only confirming that the radio button was clicked.")
        lines.append("- Deterministic order-grid flow should cover: search by order id, Date filter, Add filter (Name / SKU / Status), status tabs, and Clear all.")

    return "\n".join(lines).strip()


def _infer_signature_option(scenario: str) -> tuple[str, str] | None:
    s = (scenario or "").lower()
    option_map = [
        (("adult",), ("ADULT", "Adult Signature Required")),
        (("direct",), ("DIRECT", "Direct Signature Required")),
        (("indirect",), ("INDIRECT", "Indirect Signature Required")),
        (("no signature", "no_signature_required", "no-signature"), ("NO_SIGNATURE_REQUIRED", "No Signature")),
        (("service default",), ("SERVICE_DEFAULT", "Service Default")),
        (("as per the general settings", "general settings"), ("AS_PER_THE_GENERAL_SETTINGS", "As Per The General Settings")),
    ]
    for keys, resolved in option_map:
        if any(key in s for key in keys):
            return resolved
    return None


def _extract_packaging_requirements(text: str) -> PackagingRequirements:
    raw = text or ""
    s = raw.lower()

    method = ""
    _carrier_box_map = [
        (("fedex extra small box", "extra small box"), "FedEx® Extra Small Box"),
        (("fedex small box", "small box"), "FedEx® Small Box"),
        (("fedex medium box", "medium box"), "FedEx® Medium Box"),
        (("fedex large box", "large box"), "FedEx® Large Box"),
        (("fedex extra large box", "extra large box"), "FedEx® Extra Large Box"),
        (("fedex envelope", "envelope"), "FedEx® Envelope"),
        (("fedex pak", "fedex pak", " pak "), "FedEx® Pak"),
        (("fedex tube", " tube "), "FedEx® Tube"),
        (("fedex 10kg box", "10kg box"), "FedEx® 10kg Box"),
        (("fedex 25kg box", "25kg box"), "FedEx® 25kg Box"),
        (("fedex standard freight box", "standard freight box", "fedex freight box"), "FedEx® Standard Freight Box"),
        (("your packaging",), "Your Packaging"),
    ]
    box_name = ""
    for keys, label in _carrier_box_map:
        if any(key in s for key in keys):
            method = "Box Packing"
            box_name = label
            break
    if box_name:
        pass
    elif "box packing" in s or "box based" in s or "box packaging" in s:
        method = "Box Packing"
        box_name = ""
    else:
        box_name = ""
        if any(k in s for k in ("weight based", "volumetric", "packing method")):
            method = "Weight Based"

    custom_box_name = ""
    custom_box_match = re.search(r"custom box(?: named)?[:\s]+([A-Za-z0-9 _-]+)", raw, re.I)
    if custom_box_match:
        custom_box_name = custom_box_match.group(1).strip()
        if not method:
            method = "Box Packing"

    unit_label = ""
    if any(k in s for k in ("kilograms & centimeters", "kgs_cm", "kg", "kgs", "centimeters", " cm ")):
        unit_label = "Kilograms & Centimeters"
    elif any(k in s for k in ("pounds & inches", "lb", "lbs", "inches", " in ")):
        unit_label = "Pounds & Inches"

    dims_match = re.search(
        r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)",
        raw,
        re.I,
    )
    length = width = height = ""
    if dims_match:
        length, width, height = dims_match.group(1), dims_match.group(2), dims_match.group(3)

    weight = ""
    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)\b", raw, re.I)
    if weight_match:
        weight = weight_match.group(1)
        if not unit_label:
            unit_label = "Kilograms & Centimeters" if weight_match.group(2).lower().startswith("kg") else "Pounds & Inches"

    use_volumetric = None
    if "use volumetric weight" in s or "volumetric weight" in s:
        use_volumetric = True
    if "without volumetric" in s or "disable volumetric" in s or "volumetric weight off" in s:
        use_volumetric = False

    stack_products_in_boxes = None
    if any(k in s for k in ("stack enabled", "stack products in boxes", "stack products", "stacking enabled")):
        stack_products_in_boxes = True
    if any(k in s for k in ("stack disabled", "do not stack", "without stacking", "stacking disabled")):
        stack_products_in_boxes = False

    additional_weight_enabled = None
    additional_weight_mode = ""
    additional_weight_value = ""
    if "additional weight" in s:
        additional_weight_enabled = True
        if "constant" in s:
            additional_weight_mode = "Constant"
            match = re.search(r"additional weight[^.\n]*?constant[^0-9]*(\d+(?:\.\d+)?)", raw, re.I)
            if match:
                additional_weight_value = match.group(1)
        elif any(k in s for k in ("percentage", "percent", "pct")):
            additional_weight_mode = "PERCENTAGE_OF_PACKAGE_WEIGHT"
            match = re.search(r"(\d+(?:\.\d+)?)\s*%", raw, re.I)
            if not match:
                match = re.search(r"additional weight[^.\n]*?(?:percentage|percent|pct)[^0-9]*(\d+(?:\.\d+)?)", raw, re.I)
            if match:
                additional_weight_value = match.group(1)
    if any(k in s for k in ("disable additional weight", "without additional weight", "additional weight off")):
        additional_weight_enabled = False

    max_weight = ""
    max_weight_match = re.search(r"max weight[^0-9]*(\d+(?:\.\d+)?)", raw, re.I)
    if max_weight_match:
        max_weight = max_weight_match.group(1)

    return PackagingRequirements(
        method=method,
        unit_label=unit_label,
        length=length,
        width=width,
        height=height,
        weight=weight,
        box_name=box_name,
        custom_box_name=custom_box_name,
        use_volumetric=use_volumetric,
        stack_products_in_boxes=stack_products_in_boxes,
        additional_weight_enabled=additional_weight_enabled,
        additional_weight_mode=additional_weight_mode,
        additional_weight_value=additional_weight_value,
        max_weight=max_weight,
    )


def _extract_order_grid_requirements(text: str) -> OrderGridRequirements:
    raw = text or ""
    s = raw.lower()

    search_order_id = ""
    search_match = re.search(r"search by order id[^0-9#]*#?(\d+)", raw, re.I)
    if not search_match:
        search_match = re.search(r"order id[^0-9#]*#?(\d+)", raw, re.I)
    if search_match:
        search_order_id = search_match.group(1)

    date_filter = ""
    for option in ("Today", "Last 7 Days", "Last 30 Days"):
        if option.lower() in s:
            date_filter = option
            break

    add_filter = ""
    add_filter_value = ""
    for option in ("Name", "SKU", "Status"):
        if f'add filter "{option.lower()}"' in s or f"add filter {option.lower()}" in s or f'filter "{option.lower()}"' in s:
            add_filter = option
            break
    if not add_filter and "sku" in s:
        add_filter = "SKU"
    if not add_filter and "name" in s:
        add_filter = "Name"
    if not add_filter and "status" in s:
        add_filter = "Status"

    if add_filter == "Name":
        name_match = re.search(r'name[^A-Za-z0-9]*["\']?([A-Za-z0-9 _-]+)["\']?', raw, re.I)
        if name_match:
            candidate = name_match.group(1).strip()
            if candidate and candidate.lower() not in ("filter", "filters", "shows textbox and filters grid"):
                add_filter_value = candidate
    elif add_filter == "SKU":
        sku_match = re.search(r'sku[^A-Za-z0-9]*["\']?([A-Za-z0-9_-]+)["\']?', raw, re.I)
        if sku_match:
            add_filter_value = sku_match.group(1).strip()

    status_filter = ""
    for option in ("Pending", "Label Generated", "Failed", "Auto Cancelled", "User Cancelled"):
        if option.lower() in s:
            status_filter = option
            break

    status_tab = ""
    for option in ("All", "Pending", "Label Generated"):
        if re.search(rf'\btab\b.*{re.escape(option.lower())}', s) or re.search(rf'\b{re.escape(option.lower())}\b.*\btab\b', s):
            status_tab = option
            break

    clear_all = "clear all" in s

    return OrderGridRequirements(
        search_order_id=search_order_id,
        date_filter=date_filter,
        add_filter=add_filter,
        add_filter_value=add_filter_value,
        status_filter=status_filter,
        clear_all=clear_all,
        status_tab=status_tab,
    )


# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = dedent("""\
    Extract each testable scenario from the acceptance criteria below.
    Return ONLY a JSON array of concise scenario title strings. No explanation.
    Example: ["User can enable Hold at Location", "Success toast shown after Save"]

    Acceptance Criteria:
    {ac}
""")

_APP_WORKFLOW_GUIDE = dedent("""\
## FedEx Shopify App — Key Workflows

### TWO DIFFERENT PRODUCTS PAGES — DO NOT CONFUSE THEM

❶  nav_clicks: "AppProducts"  →  <app_base>/products
   PURPOSE: Edit FedEx-specific settings on an EXISTING product that is already in Shopify.
   HOW: Click a product row in the list → URL becomes <app_base>/products/<product_id>

   EXACT FIELDS on the product edit page (from live app):
   ┌─ Product Dimensions ────────────────────────────────────────────┐
   │  Length [input]  cm▼   Width [input]  cm▼   Height [input]  cm▼ │
   │  Weight [input]  lb▼                                            │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Supplementary Details ─────────────────────────────────────────┐
   │  ☐ Is Alcohol                                                   │
   │  ☐ Is Battery                                                   │
   │  ☐ Is Dry Ice Needed                                            │
   │  ☐ Is this product pre-packed?                                  │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Shipping Details ──────────────────────────────────────────────┐
   │  FedEx® Delivery Signature Options [dropdown]                   │
   │    options: "As Per The General Settings" | "No Signature" |    │
   │             "Indirect" | "Direct" | "Adult"                     │
   │  Freight Class [dropdown]  e.g. CLASS_050                       │
   │  Declared Value [input]    numeric, e.g. 10                     │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Customs Information ───────────────────────────────────────────┐
   │  Country of Manufacture [dropdown]  "Select One" default        │
   │  State of Manufacture (Use 2 digit State Code) [input]          │
   └─────────────────────────────────────────────────────────────────┘
   SAVE: "Save" button (top-right of the page) → success toast "Products Successfully Saved"
   ⚠️ There is NO "Add product" button here. You CANNOT create new products here.

❷  nav_clicks: "ShopifyProducts"  →  admin.shopify.com/store/<store>/products
   PURPOSE: Shopify's own product management — the ONLY place to ADD or create new products.
   WHAT YOU CAN DO HERE:
     - Click "Add product" button (top-right) to create a new Shopify product
     - Edit product title, price, weight, SKU, barcode, variants, HS code, tags
   ⚠️ This is NOT the FedEx app — it's the Shopify admin products page.

RULE: scenario about "dry ice / alcohol / battery / signature / dimensions on a product"
  → nav_clicks: "AppProducts"  (edit FedEx settings on existing product in the app)
RULE: scenario about "add new product / create product / product with 250 variants"
  → nav_clicks: "ShopifyProducts"  (create/edit in Shopify admin)

### All App Page URLs (direct navigation — no link clicking)
- nav_clicks: "Shipping"   → <app_base>/shopify      — All Orders grid
- nav_clicks: "PickUp"     → <app_base>/pickup       — Pickups list
- nav_clicks: "Settings"   → <app_base>/settings/0   — App Settings
- nav_clicks: "FAQ"        → <app_base>/faq
- nav_clicks: "Rates Log"  → <app_base>/rateslog     — Rate request history (no hyphen)
- nav_clicks: "Orders"     → admin.shopify.com/store/<store>/orders

### ⚠️ How to Generate a Label (CORRECT FLOW — via Shopify Orders)
Label generation does NOT happen from inside the app's Shipping page.
It happens through the Shopify admin Orders section:
1. Click "Orders" in the Shopify LEFT sidebar (not the app sidebar)
2. Click on an order ID (e.g. #1612) to open the order detail page
3. Click "More Actions" button (top-right dropdown on the order page)
4. You will see two label options:
   - "Auto-Generate Label" → automatically picks service and generates
   - "Generate Label"      → manual label generation (user picks service/package)
5. Click the desired option → the FedEx app opens inside Shopify for label creation
6. Fill in package details if prompted → click Generate/Create

### How to Cancel a Label
1. Go to Shopify Orders → click the order that has a generated label
2. Click "More Actions" → click "Cancel Label" (or open the app and cancel from there)
3. Confirm cancellation

### How to Regenerate a Label (after cancel)
1. After cancelling → order status reverts to Pending/Unfulfilled
2. Go to Shopify Orders → click the same order
3. Click "More Actions" → "Generate Label" again

### App's Own Shipping / Orders Grid (inside the app iframe)
- Click "Shipping" in the app sidebar → shows "All Orders" grid inside the iframe
- Grid columns: Order#, Label created date, Customer, Label status, Shipping Service,
  Subtotal, Shipping Cost, Packages, Products, Weight, Messages
- Tab filters: All | Pending | Label Generated
- Label statuses: "label generated" (green), "inprogress" (yellow), "failed" (red),
  "auto cancelled" (grey), "label cancelled"
- Top-right buttons on Shipping page: "Generate New Labels", "How to", "Help", "Generate Report"
  ⚠️ "Generate Report" downloads a CSV file directly (NOT a ZIP) — use action=download_file, target="Generate Report"
     The CSV contains order data: order number, label status, shipping service, tracking number, weight, etc.
     After download_file, next step context shows: filename, row_count, headers[], sample_rows[], raw_preview
- ⚠️ CLICK AN ORDER ROW to open the Order Summary page for that order (inside the app)
  → The Order Summary shows label details, Download Documents, More Actions, etc.
  → Use this to access an existing label for document verification (Strategy 2/3)
- Do NOT click "Generate New Labels" — that creates a new label across multiple orders

### Settings Navigation
- Click "Settings" in app sidebar
- Tabs: General, Packages, Additional Services, Rates, etc.
- Additional Services → Freight, Signature, Dry Ice, Hold at Location, etc.

### Label Status Values (inside app's Shipping page)
- Pending          → no label yet
- In Progress      → label being generated
- Label Generated  → label created successfully
- Failed           → label generation failed

### ⚠️ Full Verification Flow by Scenario Type

NEVER create a new order. Always use existing orders. Follow the COMPLETE flow for each scenario type:

─────────────────────────────────────────────────────────
SCENARIO GROUP A — Product-Level Special Services
(Dry Ice / Alcohol / Battery / Dangerous Goods)
─────────────────────────────────────────────────────────
Use the prerequisite order strategy for the scenario. For special-service scenarios,
the verifier should create a fresh order before browser verification starts.
order_action = create_new  (verifier creates a fresh Shopify order with a dangerous goods product BEFORE the browser opens)
nav_clicks: ["AppProducts"]  (start on the FedEx app Products page)

These require 3 steps: configure product → generate label on the fresh order → verify JSON.

STEP 1 — Enable the special service checkbox on a product (AppProducts):
  You are already on the FedEx app Products page (<app_base>/products).
  - Click the FIRST product row in the list (or search for "Test Product A")
  - The product detail page opens (fields visible: Dimensions, Supplementary Details, Shipping Details)
  - Enable ONLY the checkbox the scenario tests:
      Dry Ice   → check "Is Dry Ice Needed" → fill "Dry Ice Weight" input (in kg) → Save
      Alcohol   → check "Is Alcohol" → set "Alcohol Recipient Type" dropdown (CONSUMER or LICENSEE) → Save
      Battery   → check "Is Battery" → set "Battery Material Type" (LITHIUM_ION/LITHIUM_METAL)
                                     + "Battery Packing Type" → Save
      Dangerous → check "Is Dangerous Goods" → set option → Save
  - Click "Save" button → wait for success toast "Products Successfully Saved"
  - Note the PRODUCT ID from the URL (<app_base>/products/<product_id>) — this is the product in the fresh order

STEP 2 — Generate label on the fresh order AND verify JSON DURING generation:
  action=navigate, path="orders"  → Shopify admin Orders list
  → The fresh order just created is the MOST RECENT order at the top
  → Click on it → More Actions → "Generate Label" (use MANUAL label flow — NOT auto-generate)
    Manual flow is required to access the Rate Request Log BEFORE generating.
  → Generate Packages → Get Rates (rates appear as radio buttons)

STEP 3 — Verify request JSON via Rate Log (Strategy 4 — DURING label gen, BEFORE clicking Generate):
  ⚠️ Check JSON at THIS point — BEFORE clicking Generate Label button
  - Click ⋯ (three dots) next to "Shipping rates from account" → "View Logs"
  - Dialog opens with Request (left) and Response (right) JSON
  - Verify these fields:
      Dry Ice:   specialServiceTypes contains "DRY_ICE"
                 requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value = 0.3
                 weight unit = "KG"
      Alcohol:   specialServiceTypes contains "ALCOHOL"
                 requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType = "CONSUMER" or "LICENSEE"
      Battery:   specialServiceTypes contains "BATTERY"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].materialType = "LITHIUM_ION" or "LITHIUM_METAL"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].batteryPackingType = "CONTAINED_IN_EQUIPMENT" or "PACKED_WITH_EQUIPMENT"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].regulatorySubType = "IATA_SECTION_II"
  - Take screenshot → action=verify based on JSON values
  - Close dialog with "Close" button

STEP 4 — Generate Label + verify label status:
  → selectFirstShippingService (click first radio button service)
  → "Generate Label" button → Order Summary opens
  → Verify "label generated" badge visible

STEP 5 — Verify visual text on printed label (Strategy 5):
  → Print Documents button → switch_tab → screenshot → check for:
      Dry Ice:   "ICE" text on label
      Alcohol:   "ALCOHOL" text on label
      Battery:   "ELB" text on label   ← Note: Battery shows "ELB" NOT "BATTERY"
      Adult sig: "ASR" text on label
      Direct sig:"DSR" text on label
  → action=verify → close_tab

STEP 6 — Cleanup (reset product to default after test):
  action=navigate, path="products"
  → Find the same product → uncheck the special service checkbox → Save
  This prevents the setting from affecting other TCs in the same run.

─────────────────────────────────────────────────────────
SCENARIO GROUP B — Global App Settings
(FedEx One Rate / Packaging / Freight / Additional Services toggle)
─────────────────────────────────────────────────────────
These require 2 steps: configure global settings → generate label → verify.

STEP 1 — Configure the setting:
  App sidebar → Settings → relevant tab (Additional Services / Packaging / etc.)
  Enable the setting → Save → wait for success toast

STEP 2 — Generate label on existing unfulfilled order and verify:
  Shopify admin LEFT sidebar → Orders → Unfulfilled → first order
  → More Actions → Generate Label (or Auto-Generate) → Verify JSON / label

─────────────────────────────────────────────────────────
SCENARIO GROUP C — SideDock Options
(HAL / Signature / Insurance / COD / Duties & Taxes)
─────────────────────────────────────────────────────────
No product configuration needed. Configured DURING label generation on the SideDock.

STEP 1 — Navigate to an existing unfulfilled order:
  Shopify admin LEFT sidebar → Orders → Unfulfilled → first order
  → More Actions → "Generate Label" (NOT Auto-Generate — SideDock needs manual label flow)

STEP 2 — Configure SideDock BEFORE clicking Generate Label:
  - HAL          → Click "Hold at Location" → select location → confirm
  - Signature    → Dropdown "FedEx® Delivery Signature Options" → select type
  - Insurance    → Check "Add Third Party Insurance" → fill details → close modal
  - COD          → Check "Add COD Collect" → fill amount, TIN type, contact
  - Duties       → Set Purpose of Shipment, Terms of Sale, Duties Payment Type

STEP 3 — Generate Packages → Get Rates → select service → Generate Label → Verify JSON

─────────────────────────────────────────────────────────
SCENARIO GROUP D — No Label Needed
─────────────────────────────────────────────────────────
- "Next/Previous order navigation", "order grid", "pagination"
  → App sidebar → Shipping → All Orders → click ANY order row → use Prev/Next buttons

- "Verify existing label", "download documents", "label shows ICE/ALCOHOL/ASR text"
  → App sidebar → Shipping → Label Generated tab → click first "label generated" order

- "Return label generation"
  → App sidebar → Shipping → Label Generated tab → click first "label generated" order
  → Return packages tab → Return Packages button → Refresh Rates → select service → Generate Return Label

- "Settings only" (just verify a setting exists/is saved)
  → App sidebar → Settings → relevant tab → no order needed

- "App Shipping grid", "filter by status", "label status display"
  → App sidebar → Shipping → All Orders tab — grid IS the test target

─────────────────────────────────────────────────────────
SCENARIO GROUP E — Checkout / Rates
─────────────────────────────────────────────────────────
- "FedEx rates at checkout", "duties & taxes at checkout", "customer sees rates"
  → Storefront checkout flow ONLY (see storefront checkout section below)

- STOREFRONT CHECKOUT: Only use this when the scenario explicitly tests the checkout page
  (e.g. "Duties & Taxes visible at checkout", "FedEx rates shown at checkout", "customer sees rates").
  If the scenario is about label generation, address update, or order summary — use existing orders.

### How to Go Through Storefront Checkout (ONLY for checkout-specific scenarios)
1. In Shopify admin left sidebar, hover over "Online Store"
2. Click the 👁 eye icon → storefront opens in a NEW TAB
3. Browse products → click a product → "Add to cart"
4. Click cart icon (top right) → "Check out"
5. Fill Contact: test.user@example.com
6. Payment — test card details (Shopify Bogus Gateway):
   - Card number: 1231123123456781
   - Expiration: 01/37  |  Security code: 111
   - Name on card: Test (type "Test" — first name)
7. Billing address — use based on scenario type:
   DOMESTIC (US): First: Test, Last: User, Address: 123 Main St,
     City: Los Angeles, State: CA, ZIP: 90001, Country: United States
   INTERNATIONAL (Canada): First: Test, Last: User, Address: 111 Wellington St,
     City: Ottawa, Province: ON, ZIP: K1A 0A9, Country: Canada
   INTERNATIONAL (UK): First: Test, Last: User, Address: 221B Baker Street,
     City: London, ZIP: NW1 6XE, Country: United Kingdom
8. Complete order → new order appears at top of Shopify admin → Orders

### ⚠️ How to Update a Shipping Address in Shopify (for address update scenarios)
1. Go to Shopify admin → Orders → click the order
2. Click "Edit" button (top right of order page)  OR
   Click the shipping address section → "Edit address" link
3. Modify address fields → Save
4. The updated address is now the Shopify source of truth

### ⚠️ Product Strategy — When to Create vs Use Existing
- DEFAULT: Use an existing product from Shopify admin → Products list.
  Do NOT create a new product unless the scenario explicitly tests product creation.
- CREATE NEW: Only if the scenario says "create a product", "add a new product",
  or tests specific product attributes that no existing product has.
- For FedEx app product mapping (dimensions, signature, dry ice etc.) —
  always search for an existing product in the app's Products page.
  Use "Test Product A" or "Test Product B" as default test products.

### ⚠️ How to Create a New Product in Shopify Admin
1. In the Shopify admin LEFT sidebar click "Products"
2. Click "Add product" button (top right of the products list page)
3. Fill in the product form:
   - Title: type in the product name field (input[name="title"])
   - Price: fill the price field (input[name="price"])
   - Weight: fill the weight field (#ShippingCardWeight), select unit (kg/lb/g/oz)
   - SKU / Barcode: click the "SKU" button to expand → fill SKU and barcode fields
   - Country of origin / HS Code: click "Country of origin" button → select country → fill HS code
   - Tags: type in the tags input field → press Enter to add each tag
4. Click "Save" button (top right)
5. After saving the URL changes to /products/{id} — this is the product detail page

### ⚠️ How to Edit an Existing Product in Shopify Admin
1. In the Shopify admin LEFT sidebar click "Products"
2. Find the product → click its title link to open the product detail page
   OR use the search/filter button ("Search and filter products") to find it
3. Edit any field:
   - Title: input[name="title"]
   - Price: input[name="price"]
   - Weight: #ShippingCardWeight
   - Weight unit: select[name="weightUnit"]
   - SKU: click "SKU" button → input[name="sku"]
   - Barcode: input[name="barcode"]
   - Tags: input[name="tags"] → press Enter
   - HS Code: input[name="harmonizedSystemCode"]
   - Country of origin: button "Country of origin" → select[name="countryCodeOfOrigin"]
4. Click "Save" button to save changes  |  "Discard" to cancel

### ⚠️ How to Configure FedEx Product Settings (App's Products Page)
This is DIFFERENT from Shopify Products. This is inside the FedEx app.
1. Navigate using nav_clicks: "AppProducts" → lands at <app_base>/products
2. Find the product:
   - Click the search icon (🔍) button in the top-right of the products list
   - The search input appears with placeholder "Search by Product Name (Esc to cancel)"
   - Type the product name (e.g. "Coffee Mug", "Lithium Batteries") → press Enter
   - The matching product rows appear
3. Click the product row (bold product name text) → URL becomes <app_base>/products/<id>
4. Product detail page opens inside the iframe — configure ONLY what the scenario requires:
5. On the product detail page configure ONLY what the scenario requires:

   NORMAL product scenario (no special services mentioned):
   - Set Dimensions: Length, Width, Height + unit (cm/in/ft/mt)
   - Set Signature Option if needed: select[name="signatureOptionType"]
   - Do NOT touch Alcohol / Battery / Dry Ice / Dangerous Goods checkboxes
   - Click "Save" → expect toast "Products Successfully Saved"

   ONLY enable special service checkboxes when the scenario EXPLICITLY tests them:
   - "Is Alcohol" → enable only if scenario is about alcohol shipping
       → then set Alcohol Recipient Type: CONSUMER or LICENSEE
   - "Is Battery" → enable only if scenario is about battery shipments
       → then set Battery Material Type (LITHIUM_ION/LITHIUM_METAL) + Battery Packing Type
   - "Is Dry Ice Needed" → enable only if scenario is about dry ice
       → then fill Dry Ice Weight(kg) input
   - "Is Dangerous Goods" → enable only if scenario is about dangerous goods/hazmat
       → then set option (LIMITED_QUANTITIES_COMMODITIES / HAZARDOUS_MATERIALS / ORM_D)
   - "Is this product pre-packed?" → enable only if scenario tests pre-packed behaviour
   - Freight Class / Declared Value / Customs info → only if scenario mentions these

6. Click "Save" button (inside iframe) → success toast "Products Successfully Saved"
7. To go back to the product list: click the back navigation button (aria-label="products")

### ⚠️ Manual Label Generation — Full Flow
Manual label = user picks the FedEx service themselves.
1. Go to Shopify Orders → click an order → More Actions → "Generate Label"
   (the FedEx app opens in a new embedded page inside Shopify)
2. Inside the app (iframe), the page has TWO areas:
   LEFT SIDE — Package & Rates area:
   a. Click "Generate Packages" button → packages are auto-calculated
   b. Click "Get shipping rates" button → FedEx rates load as radio buttons
      (has retry logic — if rates fail, a "Retry" button appears; click it)
   c. Select a shipping service (click its radio button)
   RIGHT SIDE — The SideDock (ALWAYS visible, configure before generating label):
   d. Configure SideDock options as needed (see SideDock section below)
   e. Click "Generate Label" button → label is created
3. After generation the Order Summary page opens automatically

### ⚠️ Auto Label Generation — Full Flow
Auto label = FedEx app picks service and generates without user input.
1. Go to Shopify Orders → click an order → More Actions → "Auto-Generate Label"
2. Label generates automatically (no service selection needed)
3. Verify: navigate to Shipping → order shows "label generated" status
   OR the Order Summary page opens automatically

### ⚠️ The SideDock — Manual Label Options Panel (ALWAYS VISIBLE)
The SideDock is a panel on the RIGHT SIDE of the Manual Label page.
It is ALWAYS visible — no need to open or toggle it.
Settings configured here OVERRIDE any product-level or global settings.

SideDock contains (in order from top to bottom):
1. ADDRESS CLASSIFICATION
   - Dropdown: "Shipping Address Classification" (aria-label="Address classification")
   - Options: Residential, Commercial

2. SIGNATURE OPTIONS (overrides product-level signature)
   - Dropdown: aria-label="FedEx® Delivery Signature Options"
   - Options: ADULT, DIRECT, INDIRECT, NO_SIGNATURE_REQUIRED, SERVICE_DEFAULT
   - ⚠️ This overrides the product signature setting for this label only

3. HOLD AT LOCATION (HAL)
   - Button: "Hold at Location" (or "Choose Hold At Location Point")
   - Click → modal opens with location search/dropdown
   - Select HAL location code (e.g. 'HHRAA', 'FEDEX_OFFICE', 'WALGREENS')
   - Click "Yes" to confirm selection
   - Verifiable in JSON: specialServiceTypes contains "HOLD_AT_LOCATION",
     holdAtLocationDetail.locationId = selected location code
     holdAtLocationDetail.locationType = location type string

4. INSURANCE / THIRD-PARTY INSURANCE
   - Checkbox: "Add Third Party Insurance To Packages?"
   - After checking → click the Edit (pencil) icon that appears
   - Modal opens with:
     - Checkbox: "Include Third Party Insurance In Commercial Invoice?"
     - Dropdown: Liability Type (New / Used or Reconditioned)
     - Dropdown: Insurance Amount Type (Declared Value / Percentage of Product Price)
     - If Percentage selected → input: "Percentage of Product Price" (0–100)
   - Click Close button to save modal
   - Verifiable in JSON: declaredValue.amount in rate request

5. COD (CASH ON DELIVERY)
   - Checkbox: "Add COD Collect" (field: isCodRequired)
   - After checking → additional fields appear:
     - COD Amount input
     - COD TIN Type dropdown (BUSINESS_NATIONAL, BUSINESS_STATE, BUSINESS_UNION,
       PERSONAL_NATIONAL, PERSONAL_STATE)
     - TIN Number input
     - Contact: name, company name, phone number
     - Address fields: street, city, state/country, pincode
     - COD Reference Indicator

6. DUTIES & TAXES / INTERNATIONAL SETTINGS (for international shipments)
   - Purpose of Shipment dropdown: GIFT / SAMPLE / RETURN / REPAIR / OTHERS
   - Terms of Sale dropdown: CFR / CIF / CIP / EXW / FOB / FAS / DAF
   - Duties Payment Type dropdown: SENDER / RECIPIENT / THIRD_PARTY
     → If THIRD_PARTY: enter third-party account number
   - Additional Commercial Invoice Info checkbox: "Add Additional Commercial Invoice Info"
     → Fields: customs value, insurance value, customs comments, freight charge, reference

7. FREIGHT ADDITIONAL INFO (for freight scenarios)
   - Checkbox: "Add Additional Freight Info"
   - Fields: Collect Terms Type, Freight ID, Freight Packaging,
     Purchase Order Number, Delivery Instructions, Disposition Type
   - Freight contact details section

### ⚠️ How to Generate a Return Label
TWO WAYS to generate a return label:

WAY A — From Inside the App (after forward label is generated):
1. Open Order Summary page in the app (Shipping → click order with "label generated")
2. Click the "Return packages" tab (next to "Packages" tab)
3. Click "Return Packages" button → Return Label page opens
4. Enter return quantity (default 1)
5. Click "Refresh Rates" button → rates load (with retry logic, may take a moment)
6. Select a shipping service radio button
7. Click "Generate Return Label" button
8. Verify: "SUCCESS" badge appears + "Download Label" link becomes visible

WAY B — From Shopify Admin (directly from order page):
1. Go to Shopify admin → Orders → click the order
2. Click "More actions" dropdown (top-right of order page)
3. Click "Generate Return Label" (NOT "Create return label" — that is a different Shopify feature)
   Other options visible: Auto-Generate Label, Generate Label, Print Label, Create return label
4. The FedEx app opens for return label generation
5. Same steps as Way A from step 4 onwards

### ⚠️ How to View Rate Request / Label Request Logs
These logs show the EXACT JSON sent to FedEx REST API.
The app uses ONLY the FedEx REST API (no SOAP/XML — all logs are JSON).

RATE REQUEST LOG (from Manual Label page, after clicking Get Shipping Rates):
1. Complete manual label steps: Generate Packages → Get Shipping Rates (rates appear as radio buttons)
2. In the rates section, click the "⋯" (three dots / action menu) button
   next to "Shipping rates from account"
3. Click "View Logs" from the dropdown menu → dialog opens in the page (no download)
4. Dialog shows TWO sections (JSON format):
   - Left / "Request" section: JSON sent to FedEx (requestObject)
   - Right / "Response" section: JSON received from FedEx
5. Take a screenshot → read JSON values visually to verify fields:
   - requestedShipment.requestedPackageLineItems[0].dimensions → L/W/H/units
   - requestedShipment.requestedPackageLineItems[0].weight.value
   - requestedShipment.shipmentSpecialServices.specialServiceTypes → array
   - requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
   - requestedShipment.shipmentSpecialServices.holdAtLocationDetail → HAL info
6. Close dialog with "Close" button (aria-label="Close") or ✕

OTHER ACTIONS in the ⋯ menu:
- "View Address Logs" → shows address validation details
- "Download Logs" → downloads ZIP with rate request/response JSON (same format as Download Documents)

LABEL REQUEST LOG (after label is generated — via ZIP download):
→ See Strategy 2 or 3 in the Document Verification section below

### ⚠️ How to View Rate Log from App's "Rates Log" Sidebar
⚠️ CRITICAL — Rates Log ONLY shows requests from STOREFRONT CHECKOUT:
- Rates Log at <app_base>/rateslog ONLY populates when a customer places an order through the
  Shopify online store (storefront checkout) — the FedEx rates are fetched at checkout.
- API-created orders (used in most test cases) do NOT appear in Rates Log — it will be EMPTY.
- For API-created test orders: generate a label first, then use Download Documents ZIP
  (or "How To" → "Click Here" ZIP) to get both the createShipment request and label JSON.

WHEN TO USE Rates Log page:
- ONLY for scenarios that explicitly test "rates shown at checkout", "customer sees FedEx rates",
  or "duties & taxes at storefront checkout". These require a real storefront checkout flow.
- For all other "verify rate request JSON" scenarios → use Download Documents ZIP (Strategy 2)
  or How To → Click Here ZIP (Strategy 3) instead.

HOW TO USE (if scenario requires storefront checkout rates):
1. Click "Rates Log" in the app sidebar (inside the app iframe)
2. List of all rate requests: each row has order ID, date, status
3. Click a row → expands to show request/response JSON for that rate call

### ⚠️ How to Access the Order Summary Page (to view label details, download docs)
The Order Summary page (with label status, Download Documents, More Actions) is accessed in TWO ways:

WAY 1 — From the app's own Shipping / Orders grid (PREFERRED for verifying existing labels):
1. Click "Shipping" in the app sidebar → the "All Orders" grid loads inside the iframe
2. The grid shows orders with columns: Order#, Label status, Shipping Service, Packages, Products, Weight
3. Label statuses visible: "label generated" (green), "inprogress" (yellow), "failed" (red), "auto cancelled"
4. Click on any order ROW (e.g. #1559 with "label generated") → Order Summary page opens inside the app
5. The Order Summary now shows the full order details with action buttons

WAY 2 — After generating a label (app redirects here automatically):
- After completing manual or auto label generation, the app redirects to Order Summary directly
- No need to navigate back to the grid

### ⚠️ How to Verify Label and Documents — 4 Strategies

Order Summary Page buttons and elements:
- "← #XXXX" back arrow + order number at top left → back to Shipping grid
- Label status badge next to order number: "label generated" / "Pending" / "Failed"
- "Print Documents" button (standalone) → opens a NEW BROWSER TAB with the PluginHive document viewer
  The tab shows all documents: label, packing slip, commercial invoice (CI)
  ⚠️ Use: action=switch_tab → screenshot → read documents visually → action=close_tab
- "Upload Documents" button → upload custom customs docs
- "More Actions" dropdown → contains these exact items (in order):
  - "Track Order"         → opens FedEx tracking page for this shipment
  - "Download Documents"  → downloads a ZIP with physical shipping documents
                            (label PDF + packing slip PDF + CI PDF)
                            ⚠️ Does NOT contain request/response JSON
  - "Cancel Label"        → cancel the label
  - "Return Label"        → opens return label flow
  - "How To"              → opens a modal with usage instructions
                            ⚠️ THIS IS THE ONLY WAY to get request/response JSON:
                            scroll to bottom → "Need request/response Logs to contact FedEx? Click Here"
                            → downloads RequestResponse_#ORDERNAME.zip
                              (contains createShipment request JSON + response JSON)
  - "Help"                → opens help/support link

⚠️ CRITICAL DISTINCTION:
  - Print Documents      → opens NEW TAB viewer (visual only — no download)
  - Download Documents   → ZIP download with physical docs (label + slip + CI) — NO JSON
  - How To → Click Here → request/response JSON ONLY — the ONLY source for JSON field verification
- TWO TABS: "Packages" tab | "Return packages" tab
  - Packages tab: shows package info (box type badge, service badge, products, weight, price)
  - Return packages tab: shows return label if generated
- Customer panel (right side): name, email, phone
- Address panel (right side): street, city/state/zip, country
- Previous / Next buttons (top right) → navigate between orders

⚠️ PRINT DOCUMENTS FLOW (opens NEW BROWSER TAB — visual viewer, NOT a download):
1. On Order Summary, click "Print Documents" button (standalone button)
   → A NEW BROWSER TAB opens with the PluginHive document viewer
   → Tab shows: label, packing slip, commercial invoice (CI)
2. action=switch_tab   ← switch to the new tab
3. action=screenshot   ← capture visually (read label text, check docs present)
4. action=close_tab    ← return to Order Summary
⚠️ Do NOT use download_zip for Print Documents — it opens a tab, not a file download.

⚠️ DOWNLOAD DOCUMENTS FLOW (More Actions → ZIP with physical documents):
1. action=click, target="More Actions" → dropdown opens
2. action=download_zip, target="Download Documents"
   → ZIP downloaded and extracted automatically
   → Contents: label PDF + packing slip PDF + commercial invoice (CI) PDF
3. action=verify: confirm expected documents are present

⚠️ IMPORTANT:
  - Print Documents → NEW TAB viewer (visual) — NOT a ZIP download
  - Download Documents → ZIP with physical docs (label + slip + CI) — NO JSON
To get request/response JSON → ONLY via: More Actions → How To → Click Here (see Strategy 3)

STRATEGY 1 — Verify label EXISTS (for "label is generated" scenarios):
1. Navigate to Shipping → click order with "label generated" status → Order Summary opens
   OR after manual/auto label generation the page redirects to Order Summary automatically
2. Look for "label generated" status badge next to order number
3. Look for "Print Documents" and "More Actions" buttons visible
4. Take a screenshot — if "label generated" is visible, verdict = PASS

STRATEGY 2 — Verify physical documents exist (label + packing slip + CI):
Use for: "documents are generated", "label PDF exists", "packing slip present", "CI present"
STEPS:
1. action=click, target="More Actions" → action=download_zip, target="Download Documents"
   → ZIP extracted automatically — file list appears in your NEXT step context
2. Verify the expected files are present:
   - label PDF     → confirms label was generated
   - packing slip  → confirms slip is included
   - CI (commercial invoice) → confirms customs doc present (international shipments)
3. action=verify with finding based on files present → verdict = PASS/FAIL

STRATEGY 3 — Download request/response JSON via "How To" modal (THE ONLY WAY to get JSON):
⚠️ This is the ONLY way to get the createShipment request/response JSON after label generation.
Use for: signature type, special services, HAL, declared value, dimensions, dry ice, alcohol, battery, COD.
STEPS:
1. action=click, target="More Actions" → dropdown opens
2. action=click, target="How To" → modal opens
3. Scroll to bottom: find "Need request/response Logs to contact FedEx? Click Here"
4. action=download_zip, target="Click Here"
   → downloads RequestResponse_#ORDERNAME.zip
   → ZIP extracted automatically — JSON content appears in your NEXT step context
5. Read JSON fields:
   - Signature:        requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
   - Special services: requestedShipment.shipmentSpecialServices.specialServiceTypes (array)
     Values: "HOLD_AT_LOCATION", "DRY_ICE", "ALCOHOL", "BATTERY", "FEDEX_ONE_RATE"
   - HAL:              requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationId
   - Declared value:   requestedShipment.requestedPackageLineItems[0].declaredValue.amount
   - Dimensions:       requestedShipment.requestedPackageLineItems[0].dimensions
   - Weight:           requestedShipment.requestedPackageLineItems[0].weight.value
   - Dry ice weight:   requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value
   - Alcohol type:     requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType
6. action=verify with finding based on JSON values → verdict = PASS/FAIL
⚠️ "Click Here" is at the BOTTOM of the How To modal — scroll down if not visible.

STRATEGY 4 — In-page Rate Log (ONLY during Manual Label generation, BEFORE label is created):
Available ONLY on the Manual Label page after "Get Shipping Rates" is clicked.
1. Click ⋯ (three dots) next to "Shipping rates from account" → click "View Logs"
2. Dialog opens in-page (NO download) with JSON Request (left) and Response (right)
3. Screenshot → read JSON values visually → action=verify
4. Close dialog with "Close" button

STRATEGY 5 — Visual Label Check (for label content visible on printed label):
Use for: special service text codes printed ON the label itself
1. Click "Print Documents" → new tab opens with PluginHive viewer
2. action=switch_tab
3. Screenshot → read label visually for these codes:
   - Dry Ice    → "ICE" text on label
   - Alcohol    → "ALCOHOL" text on label
   - Battery    → "ELB" text on label  ← NOT "BATTERY"
   - Adult sig  → "ASR" text on label
   - Direct sig → "DSR" text on label
   - Indirect   → "ISR" text on label
   - Svc Default→ "SS AVXA" on label
4. action=verify based on what text/codes appear on label
5. action=close_tab

WHICH STRATEGY TO USE:
- "label is generated" / "label status"                      → Strategy 1
- Documents present (label PDF, packing slip, CI)            → Strategy 2 (More Actions → Download Documents ZIP)
- Request/response JSON fields (signature, dry ice, HAL etc) → Strategy 3 (How To → Click Here)
- Rate request DURING manual label (before generating)       → Strategy 4
- Visual label text codes (ICE, ALCOHOL, ELB, ASR, DSR)      → Strategy 5 (Print Documents → new tab → screenshot)

⚠️ For JSON field verification: ONLY Strategy 3 works (How To → Click Here).
   Strategy 2 (Download Documents ZIP) has physical docs ONLY — no JSON inside.
⚠️ Print Documents is NOT a download — it opens a NEW TAB viewer. Use switch_tab + screenshot + close_tab.
⚠️ For download_zip (Strategy 2): More Actions → action=download_zip, target="Download Documents".
⚠️ For download_zip (Strategy 3): click "More Actions" → click "How To" → scroll to bottom → download_zip target="Click Here".

### ⚠️ FedEx One Rate — Settings Flow
FedEx One Rate = flat-rate pricing using specific FedEx boxes.
1. Settings → Packaging section:
   - Set Packing Method to "Box Packing"
   - Click "more settings" button
   - In the box list, keep ONLY the relevant FedEx box (e.g. "FedEx® Small Box")
     (delete or uncheck all other boxes)
   - Save packaging settings
2. Settings → Additional Services section:
   - Find "FedEx One Rate®" heading
   - Check "Enable FedEx One Rate®" checkbox
   - Click Save button
   - Success toast: "Fedex One Rate® updated"
3. Generate label → verify JSON contains: specialServiceTypes array includes "FEDEX_ONE_RATE"

### ⚠️ Packaging Settings — Detailed Flow
Located in: Settings → Packaging tab
Key settings:
- Packing Method dropdown: "Weight Based" or "Box Packing"
- Weight And Dimensions Unit: lb/kg, in/cm
- "more settings" button → expands additional options:
  - Checkbox: "Use Volumetric Weight For Package Generation"
  - Checkbox: "Use Longest Side Of The Product As Package Dimensions"
  - FedEx box list with restore/remove options
  - Button: "Restore FedEx Boxes" → brings back all standard FedEx boxes
  - Button: "Add Custom Box" → modal to add custom box (Name, Length, Width, Height)
- For freight: separate "FedEx® Freight Services" section with freight-specific dimensions
- Save button → saves all packaging settings

### ⚠️ Pickup Scheduling — Full Flow
1. Navigate to Shipping (app sidebar) → All Orders grid
2. Select an order using the checkbox (left column of the grid)
3. Click "More actions" button (top of the grid, NOT the order-level More Actions)
4. Click "Request Pick Up" from the dropdown
5. Confirmation popup appears → click "Yes" button
6. Navigate to "PickUp" in the app sidebar → Pickups list loads
7. Verify the new pickup row shows:
   - Pickup number (generated ID)
   - Status: "SUCCESS"
   - Requested time (formatted as "MMM D, h:mm AM/PM", e.g. "Apr 9, 3:07 PM")
   - Orders column: contains the order ID that was selected
8. Pagination: "Page N of M" pattern — use Previous/Next buttons to navigate if needed

### ⚠️ Bulk Auto-Label Generation (multiple orders at once)
From automation: bulkAutoLabelGeneration.spec.ts
1. nav_clicks: ["Orders"] → Shopify admin Orders list
2. Click the header checkbox label (NOT the <input> — it has opacity:0) to select all orders
3. Bulk actions bar appears at top → click "Actions" button (aria-label="Actions", inside StickyBulkActions)
4. Click "Auto-Generate Labels" — it is a <a> LINK not a button: getByRole('link', {name: 'Auto-Generate Labels'})
5. Wait for URL to change away from /orders (do NOT use networkidle — Shopify has constant background XHR)
6. Verify labels generated in app Shipping → Label Generated tab

### ⚠️ Weight-Based Packing — Full Settings Flow
From automation: weightBasedPackaging.spec.ts, weightVolMPSP.spec.ts, weightMPMP.spec.ts
1. Settings → Packaging tab
2. action=select target="Packing Method" value="Weight Based"  (dropdown)
3. action=select target="Weight And Dimensions Unit" value="lb" (or "kg", "in", "cm")
4. Click "more settings" to expand advanced options
5. Optional: action=click target="Use Volumetric Weight For Package Generation" (checkbox)
6. Optional: action=click target="Use Longest Side Of The Product As Package Dimensions" (checkbox)
7. Click Save → verify success toast
8. Generate label → verify package weight/dimensions in downloaded JSON

### ⚠️ Box-Based Packing — Full Settings Flow
From automation: boxBasedVolCarrierBox.spec.ts, boxPackaging.spec.ts
1. Settings → Packaging tab
2. action=select target="Packing Method" value="Box Packing"
3. Click "more settings" → FedEx box list appears
4. To use only specific box: remove all others using their delete/remove button, keep only target box
5. Click "Restore FedEx Boxes" to bring back all standard boxes if needed
6. Click "Add Custom Box" → modal: fill Name, Length, Width, Height → Save
7. Click Save → verify success toast
8. Generate label → JSON should show box dimensions in requestedPackageLineItems[0].dimensions

### ⚠️ Product Configuration in FedEx App (AppProducts page)
From automation: products.spec.ts, addProductToConfig.spec.ts
URL: /apps/testing-553/products (navigate via AppProducts)
1. Search product: click search/filter button → placeholder "Search by Product Name (Esc to cancel)" → fill product name
2. Click the product button/row to open product detail
3. Configure package assignment, dimensions, special service flags
4. For dangerous goods: action=select target="Dangerous Goods Type" value="Dry Ice" (or Battery, Alcohol)
5. For alcohol: action=select target="Alcohol Recipient Type" value="Licensee" (or Consumer)
6. For battery: action=select target="Battery Material Type" value="Lithium Ion" (or Metal)
7. Click Save → verify success toast

### ⚠️ Products with More Than 250 Variants (Shopify admin)
From automation: shopifyProducts.spec.ts
nav_clicks: ["ShopifyProducts"] → Shopify admin Products list
1. Search for the product by name → click it to open
2. Scroll to Variants section
3. Verify variant count display or add/edit variants
4. For HS code / country of origin: scroll to Shipping section on product page
   - Fill "Harmonized System (HS) code" input
   - Select "Country/Region of origin" dropdown
5. Click Save → verify success

### ⚠️ Order Summary — Next/Previous Navigation
From automation: nextPreviousOrderNavigationFromOrderSummary.spec.ts
After a label is generated and you are on Order Summary page:
- "Previous order" button → navigates to previous order in list
- "Next order" button → navigates to next order in list
- Verify order ID changes in the URL and page heading
""")

# ── Selective workflow guide trimmer ─────────────────────────────────────────
# Splits the guide on ### headers and returns only sections relevant to the
# scenario — cuts ~40-60% of tokens per step call for focused scenarios.

# Sections always included regardless of scenario type
_WG_ALWAYS = [
    # These headers must exist in _APP_WORKFLOW_GUIDE — verified against actual content:
    "All App Page URLs",                  # Direct URL map for every nav_clicks value
    "TWO DIFFERENT PRODUCTS",             # AppProducts vs ShopifyProducts disambiguation
    "How to Generate a Label",            # Core flow: Orders → More Actions → Generate Label
    "How to Cancel a Label",
    "How to Regenerate a Label",
    "App's Own Shipping",                 # Shipping grid / Order Summary access
    "Settings Navigation",
    "Label Status Values",
    "Full Verification Flow by Scenario Type",
    "How to Access the Order Summary Page",
    "How to Verify Label and Documents",  # Download ZIP + all 5 verification strategies
]

# (keywords_in_scenario, header_substring_to_include)
_WG_CONDITIONAL: list[tuple[list[str], str]] = [
    (["checkout", "storefront", "customer sees rates", "rates at checkout"],
     "How to Go Through Storefront Checkout"),
    (["address update", "update address", "address change", "updated address",
      "after cancell", "new address", "regenerate", "re-generate",
      "shipping address"],
     "How to Update a Shipping Address"),
    (["create product", "add product", "new product", "add new product"],
     "How to Create a New Product"),
    (["edit product", "update product", "product weight", "product variant",
      "hs code", "harmonized", "country of origin", "modify product"],
     "How to Edit an Existing Product"),
    (["product strategy", "existing product", "use existing", "product"],
     "Product Strategy"),
    (["app product", "fedex product", "product config", "appproducts",
      "dry ice", "alcohol", "battery", "dangerous goods", "is dry ice",
      "is alcohol", "is battery", "hazmat", "pre-packed", "freight class",
      "declared value", "country of manufacture"],
     "How to Configure FedEx Product Settings"),
    (["dry ice", "alcohol", "battery", "dangerous goods", "hazmat"],
     "SCENARIO GROUP A"),
    (["manual label", "generate label", "create label", "label generation",
      "signature", "hal ", "hold at location", "cod ", "cash on delivery",
      "insurance", "duties", "freight", "automatically generate",
      "residential", "commercial", "address classification"],
     "Manual Label Generation"),
    (["auto-generate", "auto generate", "auto label", "automatically generate",
      "auto-generated", "without user"],
     "Auto Label Generation"),
    (["signature", "hal ", "hold at location", "cod ", "cash on delivery",
      "insurance", "duties", "freight additional", "residential", "commercial",
      "address classification", "sidedock", "side dock"],
     "The SideDock"),
    (["return label", "generate return", "return package", "return shipment"],
     "How to Generate a Return Label"),
    (["download document", "download documents", "verify label", "verify json",
      "label json", "print document", "view label", "label request json",
      "label shows", "label content", "ice on label", "alcohol on label"],
     "How to Verify Label and Documents"),
    (["rate log", "rate request", "view logs", "rates log", "api log",
      "api call", "network request", "json request", "fedex api"],
     "How to View Rate"),
    (["one rate", "fedex one rate", "flat rate", "flat-rate", "fedex box rate"],
     "FedEx One Rate"),
    # D4 — Additional services (freight, lift gate, inside delivery, call before delivery)
    (["additional service", "lift gate", "inside delivery", "call before delivery",
      "freight direct", "additional freight", "freight service", "additional options"],
     "Settings Navigation"),
    # I2 — Digital / virtual products (weightless, no shipping dimensions)
    (["digital product", "virtual product", "digital ", "virtual ", "downloadable",
      "non-physical", "no weight", "zero weight"],
     "Manual Label Generation"),
    (["packaging", "box packing", "weight based", "packing method",
      "package setting", "box setting", "fedex box"],
     "Packaging Settings"),
    (["pickup", "pick up", "schedule pickup", "request pickup",
      "pickup scheduling", "pickup request"],
     "Pickup Scheduling"),
    (["bulk", "50 orders", "select all orders", "auto-generate labels",
      "batch label", "multiple orders", "bulk label"],
     "Bulk Auto-Label"),
    (["weight based", "volumetric weight", "weight packing", "weight-based",
      "dimensional weight", "weight setting"],
     "Weight-Based Packing"),
    (["box packing", "box based", "fedex box", "custom box", "box-based",
      "box dimension"],
     "Box-Based Packing"),
    (["250 variant", "more than 250", "more than 100 variant", "high variant",
      "variant pagination", "product variant", ">250", "large variant"],
     "Products with More Than 250 Variants"),
    (["next order", "previous order", "next/previous", "order navigation",
      "navigate between orders", "prev order"],
     "Order Summary — Next/Previous"),
]


def _trim_workflow_guide(scenario: str) -> str:
    """Return only workflow guide sections relevant to this scenario."""
    s = scenario.lower()

    # Split on ### headers (keep header with its body)
    raw_sections = re.split(r"\n(?=###)", _APP_WORKFLOW_GUIDE)

    kept: list[str] = []
    for sec in raw_sections:
        sec_lower = sec.lower()

        # Always-include sections
        if any(ah.lower() in sec_lower for ah in _WG_ALWAYS):
            kept.append(sec)
            continue

        # Conditional sections
        for keywords, header_match in _WG_CONDITIONAL:
            if header_match.lower() in sec_lower:
                if any(kw in s for kw in keywords):
                    kept.append(sec)
                break  # each section matched at most once

    result = "\n".join(kept) if kept else _APP_WORKFLOW_GUIDE

    # Safety net: if result is less than 35% of full guide something went wrong — use full
    if len(result) < len(_APP_WORKFLOW_GUIDE) * 0.35:
        logger.warning("[guide] Trim too aggressive (%.0f%%) — falling back to full guide for '%s…'",
                       100 * len(result) / len(_APP_WORKFLOW_GUIDE), scenario[:50])
        return _APP_WORKFLOW_GUIDE

    saved = len(_APP_WORKFLOW_GUIDE) // 4 - len(result) // 4
    logger.debug("[guide] Trimmed workflow guide: saved ~%d tokens (%.0f%%) for scenario '%s…'",
                 saved, 100 * saved / (len(_APP_WORKFLOW_GUIDE) // 4), scenario[:50])
    return result


_DOMAIN_EXPERT_PROMPT = dedent("""\
    You are the domain expert for the PluginHive FedEx Shopify app.
    A QA engineer is about to verify this scenario in the live app.

    SCENARIO: {scenario}
    FEATURE:  {card_name}

    {preconditions_section}

    Using the domain knowledge and code context below, answer these questions
    concisely (max 200 words total):

    1. EXPECTED BEHAVIOUR — What should happen in the UI when this works correctly?
    2. API SIGNALS — What FedEx/backend API calls or request fields should appear
       (e.g. "signatureOptionType in rate request", "GET /rates with specialServices")?
    3. KEY THINGS TO CHECK — Specific UI elements, values, or network calls that
       confirm this scenario is implemented and working.

    Be specific. If the scenario mentions "Signature Type = Service Default", explain
    exactly what that option means and what changes in the request or UI.

    DOMAIN KNOWLEDGE (PluginHive docs / FedEx API):
    {domain_context}

    CODE KNOWLEDGE (automation POM / backend):
    {code_context}

    Answer in plain text — no JSON, no headings, just 3 short paragraphs.
""")

_PLAN_PROMPT = dedent("""\
    You are a QA engineer verifying a feature in the FedEx Shopify App.

    SCENARIO: {scenario}
    APP URL:  {app_url}

{app_workflow_guide}

    DOMAIN EXPERT INSIGHT (what this feature should do + what API signals to watch):
    {expert_insight}

    CODE KNOWLEDGE (automation POM patterns + backend API):
    {code_context}

    IMPORTANT: We test WEB (desktop browser) ONLY. SKIP any scenario that involves mobile
    viewports, responsive breakpoints, isMobileView, or screen widths ≤ 768 px. If the
    scenario is mobile-only, set plan = "SKIP — mobile/responsive testing is out of scope"
    and order_action = "none".
    IMPORTANT: Assume REST-only app behaviour. Do not reason about SOAP paths, SOAP settings,
    or SOAP-vs-REST branching.

    Plan how to verify this. The browser will ALWAYS start at the app home page.

    Navigation rules:
    - For label generation scenarios (generate new label) → nav_clicks: ["Orders"]  (Shopify left sidebar)
    - For verifying an EXISTING label / downloading documents → nav_clicks: ["Shipping"]
      (app sidebar → "All Orders" grid → click an order row with "label generated" status → Order Summary)
    - For app settings scenarios    → nav_clicks: ["Settings"]  (app sidebar)
    - For DRY ICE / ALCOHOL / BATTERY / DANGEROUS GOODS scenarios:
      → nav_clicks: ["AppProducts"]  AND  order_action: "create_new"
      FLOW: AppProducts (enable checkbox on product → Save) → navigate action to "orders"
            → find fresh order → generate label → Download Documents ZIP → verify JSON
      ⚠️ Must enable the checkbox FIRST before generating the label, or the special service won't appear in the request
    - For setting other FedEx options on a product (dimensions, freight class, declared value, signature)
      → nav_clicks: ["AppProducts"]  (FedEx app Products page — edits FedEx-specific fields on existing products)
      ⚠️ Cannot add/create new products here — only configure FedEx settings for existing ones
    - For adding a new product OR editing Shopify product fields (title, price, weight, SKU, variants, HS code)
      → nav_clicks: ["ShopifyProducts"]  (Shopify admin Products — the ONLY place to create/add products)
    - ONLY use these exact values in nav_clicks: "Orders", "Shipping", "Settings", "PickUp", "AppProducts", "ShopifyProducts", "FAQ", "Rates Log"
    - Each value navigates directly to its URL — no link-clicking, instant navigation
    - Do NOT put action steps, button names, or multi-step descriptions in nav_clicks
    - All interactions after navigation (clicking order rows, More Actions, download_zip, search, fill, save etc.) happen in the agentic loop

    ORDER JUDGMENT — pick order_action by matching your scenario to the table below.
    Read the scenario carefully and pick the FIRST row that matches.

    | Scenario contains ANY of these phrases                                        | order_action                    |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "cancel label", "cancel the label", "after cancellation", "address update",   |                                 |
    | "update address", "update the address", "update shipping address",            | existing_fulfilled              |
    | "updated address", "regenerate", "re-generate label",                         | existing_fulfilled              |
    | "return label", "generate return label", "download document", "verify label", |                                 |
    | "print document", "label shows", "next/previous order", "order summary nav"   |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "generate label", "create label", "auto-generate label", "manual label",      |                                 |
    | "dry ice", "alcohol", "battery", "signature required", "adult signature",      | create_new                      |
    | "hold at location", "HAL", "COD", "cash on delivery", "insurance",            |                                 |
    | "declared value", "one rate", "fedex one rate", "domestic label",             |                                 |
    | "international label", "cross-border label"                                   |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "bulk", "50 orders", "100 orders", "batch label", "select all orders",        | create_bulk                     |
    | "auto-generate labels", "bulk print", "bulk packing slip"                     |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "250 variants", "more than 250 variants", "high variant", "variant pagination"| create_product_250_variants     |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "settings", "configure", "pickup", "schedule pickup", "rates log",            | none                            |
    | "navigation", "order grid", "filter orders", "tab shows", "sidebar"           |                                 |

    When in doubt between create_new and existing_fulfilled → prefer create_new.
    When in doubt between existing_fulfilled and existing_unfulfilled → prefer existing_fulfilled.

    Respond ONLY in JSON:
    {{
      "app_path": "",
      "look_for": ["UI element or behaviour that proves this scenario is implemented"],
      "api_to_watch": ["API endpoint path fragment to watch in network calls"],
      "nav_clicks": ["e.g. Orders | Shipping | Settings | AppProducts | ShopifyProducts | PickUp | FAQ | Rates Log"],
      "plan": "one sentence: how you will verify this scenario",
      "order_action": "none" | "existing_fulfilled" | "existing_unfulfilled" | "create_new" | "create_bulk" | "create_product_250_variants"
    }}
""")

_STEP_PROMPT = dedent("""\
    You are verifying this AC scenario in the FedEx Shopify App.

    SCENARIO: {scenario}

    DOMAIN EXPERT INSIGHT (what this feature does + what to look for):
    {expert_insight}

    APP WORKFLOW GUIDE:
{app_workflow_guide}

    CURRENT PAGE: {url}
    ACCESSIBILITY TREE (what is visible):
    {ax_tree}

    NETWORK CALLS SEEN SO FAR:
    {network_calls}

    STEPS TAKEN SO FAR ({step_num}/{max_steps}):
    {steps_taken}

    CODE KNOWLEDGE:
    {code_context}

    Decide your NEXT action. Respond ONLY in JSON — no extra text:
    {{
      "action":       "click" | "fill" | "select" | "scroll" | "observe" | "navigate" | "verify" | "qa_needed" | "switch_tab" | "close_tab" | "download_zip" | "download_file" | "open_view_logs" | "open_print_documents" | "open_download_documents" | "open_request_response_zip" | "reset_order",
      "target":       "<exact element name from accessibility tree — required for click/fill/select/download_zip/download_file>",
      "value":        "<text to type (fill) OR option to select (select)>",
      "path":         "<relative path only e.g. 'shipping' or 'settings' — NEVER put a full URL here — required for navigate>",
      "description":  "one sentence: what you are doing and why",
      "verdict":      "pass | fail | partial  — ONLY when action=verify",
      "finding":      "what you observed      — ONLY when action=verify",
      "question":     "your question for QA   — ONLY when action=qa_needed",
      "order_action": "<required ONLY for reset_order — one of: existing_fulfilled | existing_unfulfilled | create_new | create_bulk>"
    }}

    Rules:
    - action=verify      → you have clear evidence to give a verdict
    - action=qa_needed   → use ONLY as a true last resort after you have:
                           1. observed the page carefully,
                           2. tried the most relevant navigation path,
                           3. used most of the step budget,
                           4. confirmed the feature is still not discoverable
    - action=reset_order → use ONLY when you discover you have the WRONG test data mid-run
                           (e.g. you need an order with a label but got an unfulfilled order, or vice versa)
                           Set "order_action" to what you actually need. The system will fetch/create the right
                           order and inject new context. Use this BEFORE wasting steps on wrong data.
                           Example: {{"action":"reset_order","order_action":"existing_fulfilled","description":"Need fulfilled order to cancel label"}}
    - action=select      → use for ANY dropdown or combobox where you need to pick an option value
                         (e.g. packing method, weight unit, signature type, alcohol type, battery type, duties terms)
                         target = dropdown label name, value = option text to select
    - action=fill      → use ONLY for free-text inputs (weight value, declared value, dimensions numbers)
    - action=click     → use for buttons, checkboxes, toggles, tabs, links — NOT for selecting dropdown options
    - action=open_view_logs           → deterministic helper for the known "View Logs" flow
    - action=open_print_documents     → deterministic helper for the standalone "Print Documents" button/tab flow
    - action=open_download_documents  → deterministic helper for More Actions → Download Documents ZIP
    - action=open_request_response_zip→ deterministic helper for More Actions → How To → Click Here ZIP
    - ONLY reference targets that literally appear in the accessibility tree above
    - Do NOT explore unrelated sections of the app
    - action=observe on first step to capture visible elements before interacting
    - Prefer observe or navigate over qa_needed when you still have reasonable recovery options

    TWO COMPLETELY DIFFERENT PRODUCTS PAGES:
    - nav_clicks "AppProducts"  →  <app_base>/products  (FedEx app inside iframe)
        USE FOR: configure FedEx settings on an existing product
        → dry ice, alcohol, battery, dimensions (L/W/H), signature option, declared value, freight class
        → click product row in list → URL becomes <app_base>/products/<id>
        → Save button is inside the iframe
        ⚠️ NO "Add product" button — cannot create products here
    - nav_clicks "ShopifyProducts"  →  admin.shopify.com/store/<store>/products  (Shopify admin)
        USE FOR: create new product, edit Shopify fields (title/price/weight/SKU/variants/HS code/barcode)
        → has "Add product" button at top-right
        ⚠️ This is NOT the FedEx app — no FedEx-specific fields here

    STRICT RULE: "dry ice / alcohol / battery / signature / dimensions on product" → AppProducts
    STRICT RULE: "add product / create product / 250 variants / product weight in Shopify" → ShopifyProducts

    Document verification rules:
    - To verify LABEL EXISTS: look for "label generated" status badge on Order Summary (Strategy 1)
    - To verify DOCUMENTS PRESENT (label PDF, packing slip, CI):
      Strategy 2: action=open_download_documents
      → ZIP with physical docs — verify files are present
      ⚠️ Print Documents is NOT a download — it opens a NEW TAB viewer (use Strategy 5 for that)
    - To verify FIELD VALUES in JSON (signature, special services, HAL, dry ice, alcohol, battery, declared value):
      Strategy 3 (ONLY option): action=open_request_response_zip
      → RequestResponse ZIP extracted → JSON visible in next step context → action=verify
    - Strategy 4 (rate log, ONLY during manual label BEFORE generating): action=open_view_logs
    - To verify TEXT ON THE LABEL ITSELF (ICE for dry ice, ALCOHOL, ASR/DSR/ISA signature codes, address):
      Strategy 5: action=open_print_documents → new tab opens at *document-viewer.pluginhive.io*
      → action=switch_tab → screenshot → read label visually → action=verify → action=close_tab
    - After download_zip: next step sees JSON in context → action=verify directly (no extra observe needed)
    - To download and verify a REPORT (CSV file): action=download_file, target="Generate Report"
      → next step context shows: filename, row_count, headers[], sample_rows[], raw_preview
      → action=verify: check expected columns exist and row_count > 0
    - download_file works for ANY direct file download (CSV, Excel) — NOT for ZIPs (use download_zip for those)
    - SideDock settings (signature, HAL, insurance, COD) OVERRIDE product/global settings for that label
""")

_SUMMARY_PROMPT = dedent("""\
    QA lead summary for feature: {card_name}

    Scenario results:
    {results}

    Write 2-3 sentences. Call out any failures or blockers for sign-off.
""")


# ── Browser helpers ───────────────────────────────────────────────────────────

def get_auto_app_url() -> str:
    """Auto-detect app URL from automation repo .env STORE value."""
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() == "STORE":
                v = v.strip().strip('"').strip("'")
                if v and not v.startswith("your-"):
                    store = v.replace(".myshopify.com", "")
                    return f"https://admin.shopify.com/store/{store}/apps/testing-553"
    return ""


def _normalize_app_base(app_url: str) -> str:
    """Return the root Shopify embedded-app URL, without an internal app route.

    The dashboard field can contain either the root app URL or a URL copied
    while already inside an app page, for example:
    /apps/testing-553/shopify. The agent needs the root /apps/testing-553
    base; route-specific navigation is resolved separately.
    """
    url = (app_url or "").strip().rstrip("/")
    match = re.match(r"^(https://admin\.shopify\.com/store/[^/]+/apps/[^/?#]+)", url)
    if match:
        return match.group(1)
    return url


def _store_from_app_base(app_base: str) -> str:
    match = re.search(r"/store/([^/]+)", app_base or "")
    return match.group(1) if match else ""


def _resolve_nav_url(app_base: str, path: str) -> str:
    """Resolve model navigation output into a safe, known destination URL.

    Claude is useful for deciding intent, but route construction must be
    deterministic. In particular, Shopify Orders is outside the embedded app;
    it must never become /apps/<app>/shopify/Orders.
    """
    base = _normalize_app_base(app_base)
    store = _store_from_app_base(base)
    raw = (path or "").strip()

    if not raw:
        return base

    # If a full app URL was copied from a routed page, reduce it to the route
    # and resolve through the same allow-list below.
    if raw.startswith("http://") or raw.startswith("https://"):
        app_match = re.match(
            r"^https://admin\.shopify\.com/store/[^/]+/apps/[^/?#]+/?(.*)$",
            raw.rstrip("/"),
        )
        if app_match:
            raw = app_match.group(1)
        else:
            return raw

    if "admin.shopify.com" in raw or "myshopify.com" in raw:
        return "https://" + raw.lstrip("/")

    if raw.startswith("store/"):
        raw = raw.split("/apps/", 1)[1] if "/apps/" in raw else raw
        if "/" in raw:
            raw = raw.split("/", 1)[1]
        else:
            raw = ""

    key = raw.strip("/").lower().replace("_", " ").replace("-", " ")
    key = re.sub(r"\s+", " ", key)

    if key in {"orders", "order", "shopify orders", "shopify order"}:
        return f"https://admin.shopify.com/store/{store}/orders"
    if key in {"shopifyproducts", "products shopify", "shopify products", "shopify product"}:
        return f"https://admin.shopify.com/store/{store}/products"

    # Bad model route seen in practice: /apps/testing-553/shopify/Orders.
    if key in {"shopify/orders", "shopify orders", "shopify/order", "shopify order"}:
        return f"https://admin.shopify.com/store/{store}/orders"

    if key in {"shipping", "shipments", "app shipping", "shopify"}:
        return f"{base}/shopify"
    if key in {"appproducts", "app products", "products", "product"}:
        return f"{base}/products"
    if key in {"settings", "setting"}:
        return f"{base}/settings/0"
    if key in {"pickup", "pick up", "pickups"}:
        return f"{base}/pickup"
    if key in {"faq", "help"}:
        return f"{base}/faq"
    if key in {"rates log", "rateslog", "rate log", "logs"}:
        return f"{base}/rateslog"

    return f"{base}/{raw.strip('/')}"


def _auth_ctx_kwargs() -> dict:
    kw: dict = {"viewport": {"width": 1400, "height": 1000}}
    if _AUTH_JSON.exists():
        try:
            json.loads(_AUTH_JSON.read_text(encoding="utf-8"))
            kw["storage_state"] = str(_AUTH_JSON)
        except Exception:
            pass
    return kw


def _ax_tree(page) -> str:
    """
    Accessibility tree as readable text.
    Captures BOTH the main Shopify page AND the FedEx app iframe so Claude can
    see elements inside the embedded app (buttons, inputs, dropdowns, etc.).
    """
    lines: list[str] = []

    def _walk(n: dict, d: int = 0, prefix: str = "") -> None:
        if d > 6 or len(lines) > 250:
            return
        role, name = n.get("role", ""), n.get("name", "")
        skip = {"generic", "none", "presentation", "document", "group", "list", "region"}
        if role and name and role not in skip:
            ln = f"{'  ' * d}{prefix}{role}: '{name}'"
            c = n.get("checked")
            if c is not None:
                ln += f" [checked={c}]"
            v = n.get("value", "")
            if v and role in ("textbox", "combobox"):
                ln += f" [value='{v[:30]}']"
            lines.append(ln)
        for ch in n.get("children", []):
            _walk(ch, d + 1, prefix)

    # 1. Main page (Shopify admin chrome — sidebar, headers)
    try:
        ax = page.accessibility.snapshot(interesting_only=True)
        if ax:
            _walk(ax)
    except Exception as e:
        lines.append(f"(main page snapshot error: {e})")

    # 2. FedEx app iframe — this is WHERE all the app UI lives.
    #    Without this, Claude is blind to buttons, dropdowns, and inputs inside the app.
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            # Only capture app-related iframes (skip Shopify analytics/tracking iframes)
            if not frame_url or ("shopify" not in frame_url and "pluginhive" not in frame_url
                                 and "apps" not in frame_url):
                continue
            try:
                frame_ax = frame.accessibility.snapshot(interesting_only=True)
                if frame_ax:
                    lines.append(f"\n--- [APP IFRAME: {frame_url[:60]}] ---")
                    _walk(frame_ax, prefix="")
                    lines.append("--- [END IFRAME] ---")
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(lines) or "(no interactive elements)"


def _screenshot(page) -> str:
    """Base64 PNG of current page — scaled to 50% to reduce token cost."""
    try:
        # scale=0.5 halves width+height → ~4× smaller file, still readable by Claude
        raw = page.screenshot(full_page=False, scale="css")
        return base64.standard_b64encode(raw).decode()
    except Exception:
        try:
            return base64.standard_b64encode(page.screenshot(full_page=False)).decode()
        except Exception:
            return ""


_NET_JS = """() =>
    performance.getEntriesByType('resource')
      .filter(e => ['xmlhttprequest','fetch'].includes(e.initiatorType))
      .slice(-40).map(e => e.name)
"""

def _network(page, endpoints: list[str]) -> list[str]:
    """
    Recent API/XHR calls matching endpoint paths.
    Checks BOTH the main page AND iframe frames so FedEx app API calls are captured.
    """
    all_entries: list[str] = []

    # Main page
    try:
        entries = page.evaluate(_NET_JS)
        all_entries.extend(entries or [])
    except Exception:
        pass

    # Iframe frames — FedEx app API calls live here (same URL filter as _ax_tree)
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            if not frame_url or ("shopify" not in frame_url and "pluginhive" not in frame_url
                                 and "apps" not in frame_url):
                continue
            try:
                entries = frame.evaluate(_NET_JS)
                all_entries.extend(entries or [])
            except Exception:
                pass
    except Exception:
        pass

    # Deduplicate
    seen: set[str] = set()
    hits: list[str] = []
    for e in all_entries:
        if e not in seen:
            seen.add(e)
            hits.append(e)

    if endpoints:
        return [e for e in hits if any(ep in e for ep in endpoints)]
    return [e for e in hits if "/api/" in e or "fedex" in e.lower() or "pluginhive" in e.lower()]


def _app_frame(page):
    return page.frame_locator('iframe[name="app-iframe"]')


def _is_stop_requested(stop_flag: "Callable[[], bool] | None" = None) -> bool:
    try:
        return bool(stop_flag and stop_flag())
    except Exception:
        return False


def _cooperative_wait(page, timeout_ms: int, stop_flag: "Callable[[], bool] | None" = None, chunk_ms: int = 250) -> bool:
    remaining = max(0, int(timeout_ms))
    while remaining > 0:
        if _is_stop_requested(stop_flag):
            return False
        step = min(chunk_ms, remaining)
        page.wait_for_timeout(step)
        remaining -= step
    return not _is_stop_requested(stop_flag)


def _do_action(page, action: dict, app_base: str, stop_flag: "Callable[[], bool] | None" = None) -> bool:
    """Execute a Claude-decided browser action. Returns True on success."""
    atype  = action.get("action", "observe")
    target = action.get("target", "").strip()
    value  = action.get("value", "")
    path   = action.get("path", "").strip("/")

    if _is_stop_requested(stop_flag):
        return False

    if atype == "navigate":
        url = _resolve_nav_url(app_base, path)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return _cooperative_wait(page, 800, stop_flag)
        except Exception:
            return False

    if atype in ("observe", "verify", "qa_needed"):
        return True

    if atype == "scroll":
        try:
            page.evaluate("window.scrollBy(0, 400)")
        except Exception:
            pass
        return True

    if atype == "switch_tab":
        # Switch to the most-recently-opened browser tab (e.g. a PDF that opened in a new tab)
        try:
            ctx = page.context
            pages = ctx.pages
            if len(pages) > 1:
                new_tab = pages[-1]   # most recently opened
                new_tab.bring_to_front()
                new_tab.wait_for_load_state("domcontentloaded", timeout=10_000)
                if _is_stop_requested(stop_flag):
                    return False
                # Mutate caller's page reference — replace the page object in the action loop
                # by swapping the page variable in the enclosing _verify_scenario scope.
                # We can't rebind the local var, so store the new page on the action dict
                # so _verify_scenario can pick it up.
                action["_new_page"] = new_tab
            return True
        except Exception as e:
            logger.debug("switch_tab failed: %s", e)
            return False

    if atype == "close_tab":
        # Close the current tab and switch back to the first (main Shopify) tab
        try:
            ctx = page.context
            if len(ctx.pages) > 1:
                page.close()
                # Re-fetch pages AFTER close so the reference is fresh
                main_page = ctx.pages[0]
                main_page.bring_to_front()
                action["_new_page"] = main_page
            return True
        except Exception as e:
            logger.debug("close_tab failed: %s", e)
            return False

    # frame is needed by download_zip, click, fill, and other handlers below
    frame = _app_frame(page)

    if atype == "open_view_logs":
        try:
            rates_menu_candidates = [
                # Match automation locator in ManualLabelPage.ts first.
                frame.locator('.Polaris-Box').filter(
                    has_text='Shipping rates from account'
                ).locator('button[aria-controls]').first,
                frame.locator('.Polaris-Box').filter(
                    has=frame.get_by_text("Shipping rates from account", exact=False)
                ).locator('button[aria-controls]').first,
                frame.locator('button[aria-controls]').filter(
                    has=frame.locator('svg')
                ).last,
            ]
            menu_opened = False
            for candidate in rates_menu_candidates:
                try:
                    if candidate.count() > 0:
                        candidate.wait_for(state="visible", timeout=8_000)
                        candidate.click(timeout=5_000)
                        menu_opened = True
                        break
                except Exception:
                    continue
            if not menu_opened and not _click_any([
                frame.get_by_role("button", name="View Logs"),
                frame.get_by_role("menuitem", name="View Logs"),
                frame.locator('button[role="menuitem"]').filter(has_text='View Logs').first,
                frame.get_by_text("View Logs", exact=False),
            ], timeout=5_000, wait_ms=2_500):
                return False
            if _is_stop_requested(stop_flag):
                return False
            log_item_candidates = [
                frame.get_by_role("menuitem", name="View Logs").first,
                frame.locator('button[role="menuitem"]').filter(has_text='View Logs').first,
                frame.locator('.Polaris-Popover').get_by_role("menuitem", name="View Logs").first,
                frame.get_by_text("View Logs", exact=False).first,
            ]
            clicked = False
            for candidate in log_item_candidates:
                try:
                    if candidate.count() > 0:
                        candidate.wait_for(state="visible", timeout=5_000)
                        candidate.click(timeout=5_000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                return False
            if _is_stop_requested(stop_flag):
                return False
            dialog = frame.get_by_role("dialog")
            dialog.first.wait_for(state="visible", timeout=10_000)
            if dialog.get_by_role("heading", name="Rates Log").count() > 0:
                dialog.get_by_role("heading", name="Rates Log").first.wait_for(state="visible", timeout=5_000)
            if _is_stop_requested(stop_flag):
                return False
            log_data = _extract_request_log_data(page)
            if log_data:
                action["_log_content"] = log_data
            return True
        except Exception:
            return False

    if atype == "open_print_documents":
        try:
            before_count = len(page.context.pages)
            clicked = _click_any([
                frame.get_by_role("button", name="Print Documents"),
                page.get_by_role("button", name="Print Documents"),
            ], timeout=5_000, wait_ms=5_000)
            if not clicked:
                return False
            deadline = time.time() + 10
            while time.time() < deadline:
                if _is_stop_requested(stop_flag):
                    return False
                pages = page.context.pages
                if len(pages) > before_count:
                    new_tab = pages[-1]
                    new_tab.bring_to_front()
                    try:
                        new_tab.wait_for_load_state("domcontentloaded", timeout=10_000)
                    except Exception:
                        pass
                    try:
                        action["_file_content"] = _capture_document_pdf_content(new_tab.url())
                    except Exception as doc_err:
                        logger.debug("Print Documents capture failed: %s", doc_err)
                    if _is_stop_requested(stop_flag):
                        return False
                    action["_new_page"] = new_tab
                    return True
                if not _cooperative_wait(page, 500, stop_flag):
                    return False
            return False
        except Exception:
            return False

    if atype == "open_download_documents":
        try:
            if not _open_app_more_actions_menu(page, wait_ms=8_000):
                return False
            if _is_stop_requested(stop_flag):
                return False
            nested = {"action": "download_zip", "target": "Download Documents"}
            ok = _do_action(page, nested, app_base, stop_flag=stop_flag)
            if ok and "_zip_content" in nested:
                action["_zip_content"] = nested["_zip_content"]
                if isinstance(nested["_zip_content"], dict):
                    action["_document_bundle_summary"] = _summarize_document_bundle(nested["_zip_content"])
            return ok
        except Exception:
            return False

    if atype == "open_request_response_zip":
        try:
            if not _open_app_more_actions_menu(page, wait_ms=5_000):
                return False
            if _is_stop_requested(stop_flag):
                return False
            if not _cooperative_wait(page, 800, stop_flag):
                return False
            if not _click_app_more_actions_item(page, "How To", wait_ms=10_000):
                return False
            how_to_modal = frame.locator('div[role="dialog"]')
            how_to_modal.wait_for(state="visible", timeout=10_000)
            if how_to_modal.get_by_role("heading", name="How To").count() > 0:
                how_to_modal.get_by_role("heading", name="How To").first.wait_for(state="visible", timeout=5_000)
            scroll_attempts = 0
            click_here = None
            while click_here is None and scroll_attempts < 5:
                for candidate in [
                    how_to_modal.get_by_role("button", name="Click Here").first,
                    how_to_modal.locator("button:visible").filter(has_text="Click Here").first,
                    frame.locator('div').filter(
                        has_text='Need request/response Logs to contact FedEx?'
                    ).get_by_role('button', name='Click Here').first,
                    frame.get_by_role("button", name="Click Here").first,
                ]:
                    try:
                        if candidate.count() > 0 and candidate.is_visible(timeout=1_000):
                            click_here = candidate
                            break
                    except Exception:
                        continue
                if click_here is not None:
                    break
                scroll_attempts += 1
                try:
                    how_to_modal.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
                except Exception:
                    try:
                        page.mouse.wheel(0, 1200)
                    except Exception:
                        pass
                if not _cooperative_wait(page, 700, stop_flag):
                    return False
            if click_here is None:
                return False
            try:
                click_here.scroll_into_view_if_needed(timeout=5_000)
            except Exception:
                pass
            nested = {"action": "download_zip", "target": "Click Here"}
            with page.expect_download(timeout=30_000) as dl_info:
                click_here.click(timeout=5_000, force=True)
            dl = dl_info.value
            if _is_stop_requested(stop_flag):
                return False
            tmp_dir = tempfile.mkdtemp(prefix="sav_zip_")
            zip_path = os.path.join(tmp_dir, "fedex_download.zip")
            dl.save_as(zip_path)
            if not _cooperative_wait(page, 500, stop_flag):
                return False
            extracted: dict[str, object] = {}
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        ext = name.rsplit(".", 1)[-1].lower()
                        raw = zf.read(name)
                        if ext == "json":
                            raw_text = raw.decode("utf-8", errors="replace")
                            try:
                                extracted[name] = json.loads(raw_text)
                            except Exception:
                                extracted[name] = raw_text
                        else:
                            extracted[name] = raw.decode("utf-8", errors="replace")[:3000]
            except Exception as zip_err:
                extracted["_error"] = str(zip_err)
            finally:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
            nested["_zip_content"] = extracted
            ok = True
            if ok and "_zip_content" in nested:
                action["_zip_content"] = nested["_zip_content"]
            try:
                close_btn = how_to_modal.get_by_role("button", name="Close")
                if close_btn.count() > 0:
                    close_btn.first.click(timeout=3_000)
            except Exception:
                pass
            return ok
        except Exception:
            return False

    if atype == "download_zip":
        # Click `target` to trigger a file download, save the ZIP, unzip it,
        # read all JSON files inside, and store the parsed content in
        # action["_zip_content"] so the agentic loop can pass it to Claude.
        try:
            tmp_dir  = tempfile.mkdtemp(prefix="sav_zip_")
            zip_path = os.path.join(tmp_dir, "fedex_download.zip")

            # Locate the element that triggers the download (iframe-first strategy)
            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_zip: target '%s' not found in page/iframe", target)
                return False

            # Use Playwright's expect_download context to intercept the file
            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            if _is_stop_requested(stop_flag):
                return False
            dl.save_as(zip_path)
            if not _cooperative_wait(page, 500, stop_flag):
                return False

            # Unzip and read all files inside the ZIP
            extracted: dict[str, object] = {}
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        ext = name.rsplit(".", 1)[-1].lower()
                        if ext == "json":
                            raw_text = zf.read(name).decode("utf-8", errors="replace")
                            try:
                                extracted[name] = json.loads(raw_text)
                            except Exception:
                                extracted[name] = raw_text
                        elif ext == "pdf":
                            raw_bytes = zf.read(name)
                            pdf_text = _extract_pdf_text_from_bytes(raw_bytes)
                            pdf_summary = {
                                "type": "pdf",
                                "size_bytes": len(raw_bytes),
                            }
                            if pdf_text:
                                pdf_summary["pdf_text"] = pdf_text[:12000]
                                pdf_summary["pdf_text_preview"] = pdf_text[:4000]
                                pdf_summary.update(_summarize_pdf_text(pdf_text))
                            extracted[name] = pdf_summary
                        elif ext in ("csv", "txt", "xml", "log"):
                            # Text files — read as string so Claude can verify content
                            raw_text = zf.read(name).decode("utf-8", errors="replace")
                            extracted[name] = raw_text[:3000]  # cap at 3000 chars
                        else:
                            # Binary file (PDF, PNG, etc.) — record size only
                            info = zf.getinfo(name)
                            extracted[name] = f"({ext.upper()} binary — {info.file_size:,} bytes)"
            except Exception as zip_err:
                logger.debug("ZIP extraction error: %s", zip_err)
                extracted["_error"] = str(zip_err)

            action["_zip_content"] = extracted
            action["_document_bundle_summary"] = _summarize_document_bundle(extracted)
            logger.info(
                "download_zip: extracted %d file(s) from ZIP — %s",
                len(extracted), list(extracted.keys()),
            )

            # Cleanup temp files
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.debug("download_zip failed: %s", e)
            return False

    if atype == "download_file":
        # Download any file (CSV, Excel, PDF) — read content and inject into context.
        # Use this for: Generate Report (CSV), any non-ZIP direct download.
        try:
            tmp_dir   = tempfile.mkdtemp(prefix="sav_file_")
            tmp_path  = os.path.join(tmp_dir, "fedex_download")

            # Locate the trigger element (iframe-first)
            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_file: target '%s' not found", target)
                return False

            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            if _is_stop_requested(stop_flag):
                return False
            filename = dl.suggested_filename or "download"
            save_path = os.path.join(tmp_dir, filename)
            dl.save_as(save_path)
            if not _cooperative_wait(page, 500, stop_flag):
                return False

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            content: dict = {"filename": filename}

            if ext == "csv":
                # Read CSV as text — inject all rows so Claude can verify column values
                import csv as _csv
                try:
                    raw = Path(save_path).read_text(encoding="utf-8-sig", errors="replace")
                    lines = raw.splitlines()
                    reader = _csv.reader(lines)
                    rows = list(reader)
                    headers = rows[0] if rows else []
                    sample  = rows[1:6]   # first 5 data rows
                    content["headers"]    = headers
                    content["row_count"]  = len(rows) - 1  # exclude header
                    content["sample_rows"] = sample
                    content["raw_preview"] = "\n".join(lines[:20])  # first 20 lines
                    logger.info("download_file: CSV '%s' — %d rows, headers: %s",
                                filename, len(rows) - 1, headers)
                except Exception as csv_err:
                    content["raw_preview"] = Path(save_path).read_text(
                        encoding="utf-8", errors="replace")[:3000]
                    logger.debug("CSV parse error: %s", csv_err)

            elif ext in ("xlsx", "xls"):
                # Excel — record size, try reading with openpyxl if available
                size = os.path.getsize(save_path)
                content["note"] = f"Excel file ({size:,} bytes) — verify by row count or column headers"
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(save_path, read_only=True, data_only=True)
                    ws = wb.active
                    rows = list(ws.iter_rows(values_only=True))
                    content["headers"]    = [str(c) for c in (rows[0] if rows else [])]
                    content["row_count"]  = len(rows) - 1
                    content["sample_rows"] = [[str(c) for c in r] for r in rows[1:6]]
                    wb.close()
                except ImportError:
                    pass  # openpyxl not installed — size note is enough

            elif ext == "pdf":
                size = os.path.getsize(save_path)
                content["note"] = f"PDF file ({size:,} bytes)"
                content["size_bytes"] = size
                try:
                    pdf_text = _extract_pdf_text_from_bytes(Path(save_path).read_bytes())
                    if pdf_text:
                        content["pdf_text"] = pdf_text[:12000]
                        content["pdf_text_preview"] = pdf_text[:4000]
                except Exception as pdf_err:
                    logger.debug("PDF parse error: %s", pdf_err)

            else:
                size = os.path.getsize(save_path)
                raw  = Path(save_path).read_bytes()
                try:
                    content["raw_preview"] = raw.decode("utf-8", errors="replace")[:2000]
                except Exception:
                    content["note"] = f"{ext.upper()} file ({size:,} bytes)"

            action["_file_content"] = content
            logger.info("download_file: downloaded '%s' — %s", filename, list(content.keys()))

            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.debug("download_file failed: %s", e)
            return False

    if not target:
        return False

    if atype == "click":
        for fn in [
            lambda: frame.get_by_role("button",   name=target, exact=False),
            lambda: frame.get_by_role("checkbox", name=target, exact=False),
            lambda: frame.get_by_role("switch",   name=target, exact=False),
            lambda: frame.get_by_role("link",     name=target, exact=False),
            lambda: frame.get_by_role("tab",      name=target, exact=False),
            lambda: frame.get_by_text(target, exact=False),
            lambda: page.get_by_role("button", name=target, exact=False),
            lambda: page.get_by_text(target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.click(timeout=5_000)
                    return _cooperative_wait(page, 400, stop_flag)   # reduced: was 800ms
            except Exception:
                continue
        logger.debug("Click target not found: '%s'", target)
        return False

    if atype == "fill":
        for fn in [
            lambda: frame.get_by_label(target, exact=False),
            lambda: frame.get_by_placeholder(target, exact=False),
            lambda: frame.get_by_role("textbox", name=target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.clear()
                    el.first.fill(value, timeout=5_000)
                    return True
            except Exception:
                continue
        return False

    if atype == "select":
        # Handle dropdown/select elements — tries both native <select> (selectOption)
        # and Polaris/React custom dropdowns (click to open → click option text).
        # target = label or aria-name of the dropdown
        # value  = the option to select (visible text)
        if not value:
            logger.debug("select action requires value — skipping")
            return False

        # Strategy 1: native <select> via label (e.g. weight unit lb/kg, packing method)
        # Matches automation's .selectOption() pattern used in PackagingSettingsPage etc.
        for fn in [
            lambda: frame.get_by_label(target, exact=False),
            lambda: frame.get_by_role("combobox", name=target, exact=False),
            lambda: page.get_by_label(target, exact=False),
            lambda: page.get_by_role("combobox", name=target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    # Try selectOption first (native <select>)
                    try:
                        el.first.select_option(value, timeout=5_000)
                        if not _cooperative_wait(page, 400, stop_flag):
                            return False
                        logger.debug("select: native selectOption('%s') on '%s'", value, target)
                        return True
                    except Exception:
                        pass
                    # Fallback: Polaris custom dropdown — click to open, then click option
                    try:
                        el.first.click(timeout=5_000)
                        if not _cooperative_wait(page, 300, stop_flag):
                            return False
                        for opt_fn in [
                            lambda v=value: frame.get_by_role("option", name=v, exact=False),
                            lambda v=value: frame.get_by_text(v, exact=False),
                            lambda v=value: page.get_by_role("option", name=v, exact=False),
                            lambda v=value: page.get_by_text(v, exact=False),
                        ]:
                            opt = opt_fn()
                            if opt.count() > 0:
                                opt.first.click(timeout=3_000)
                                if not _cooperative_wait(page, 400, stop_flag):
                                    return False
                                logger.debug("select: Polaris click('%s') on '%s'", value, target)
                                return True
                    except Exception:
                        pass
            except Exception:
                continue

        logger.debug("select: could not find dropdown '%s' or option '%s'", target, value)
        return False

    return True


# ── Code RAG ─────────────────────────────────────────────────────────────────

def _extract_ui_elements(code_docs: list) -> list[str]:
    """Extract UI element names from POM code using regex patterns.

    Returns deduplicated list like ["button: 'Generate Label'", "label: 'Dry Ice Weight'"].
    """
    import re

    elements: list[str] = []
    seen: set[str] = set()

    patterns = [
        # getByRole('button', { name: 'Generate Label' }) → button: 'Generate Label'
        (r"getByRole\(['\"](\w+)['\"][\s\S]*?name:\s*['\"]([^'\"]+)['\"]", lambda m: f"{m.group(1)}: '{m.group(2)}'"),
        # getByLabel('Dry Ice Weight') → label: 'Dry Ice Weight'
        (r"getByLabel\(['\"]([^'\"]+)['\"]", lambda m: f"label: '{m.group(1)}'"),
        # getByPlaceholder('Search by order id') → placeholder: 'Search by order id'
        (r"getByPlaceholder\(['\"]([^'\"]+)['\"]", lambda m: f"placeholder: '{m.group(1)}'"),
        # getByText('Generate Label') → text: 'Generate Label'
        (r"getByText\(['\"]([^'\"]+)['\"]", lambda m: f"text: '{m.group(1)}'"),
    ]

    for doc in code_docs:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        for pattern, formatter in patterns:
            try:
                for match in re.finditer(pattern, content):
                    entry = formatter(match)
                    if entry not in seen:
                        seen.add(entry)
                        elements.append(entry)
                        if len(elements) >= 25:
                            return elements
            except Exception:
                continue

    return elements


def _extract_backend_fields(code_docs: list, scenario: str) -> list[str]:
    """Extract backend field names from mongoose schema definitions.

    Returns deduplicated list like ["isDryIceNeeded", "dryIceWeight", "signatureOptionType"].
    """
    import re

    fields: list[str] = []
    seen: set[str] = set()

    # Mongoose schema field pattern: fieldName: { type: ... } or fieldName: String/Number/Boolean
    schema_pattern = re.compile(
        r"\b(\w+):\s*\{?\s*(?:type:\s*)?(?:String|Number|Boolean|Schema\.Types|mongoose\.Schema\.Types)"
    )
    # Also catch plain field assignments: isDryIceNeeded: false, dryIceWeight: 0
    assignment_pattern = re.compile(r"\b(is[A-Z]\w+|[a-z]+(?:[A-Z][a-z]+)+):\s*(?:false|true|0|null|''|\"\"|\[)")

    scenario_lower = scenario.lower()

    for doc in code_docs:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        for pattern in (schema_pattern, assignment_pattern):
            try:
                for match in pattern.finditer(content):
                    field = match.group(1)
                    # Filter: keep camelCase fields, skip generic names and schema keywords
                    _SKIP = {
                        "get", "set", "use", "app", "res", "req", "err",
                        "type", "ref", "default", "required", "unique", "index",
                        "min", "max", "trim", "enum", "validate",
                    }
                    if len(field) < 3 or field in _SKIP:
                        continue
                    if field not in seen:
                        seen.add(field)
                        fields.append(field)
                        if len(fields) >= 15:
                            return fields
            except Exception:
                continue

    return fields


def _extract_api_endpoints(code_docs: list) -> list[str]:
    """Extract API endpoint URLs from frontend axios calls.

    Returns deduplicated list like ["/api/v1/in-app-labels/manual/generate"].
    """
    import re

    endpoints: list[str] = []
    seen: set[str] = set()

    patterns = [
        # axios.post('/api/v1/...', ...)
        re.compile(r"axios\.\w+\(['\"](/api/[^'\"]+)['\"]"),
        # standalone string '/api/v1/...'
        re.compile(r"['\"](/api/v\d[^'\"]+)['\"]"),
    ]

    for doc in code_docs:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        for pattern in patterns:
            try:
                for match in pattern.finditer(content):
                    ep = match.group(1).rstrip("/")
                    if ep not in seen:
                        seen.add(ep)
                        endpoints.append(ep)
                        if len(endpoints) >= 8:
                            return endpoints
            except Exception:
                continue

    return endpoints


def _code_context(scenario: str, card_name: str) -> str:
    """Query automation POM + backend API + QA knowledge for structured context.

    Returns labelled sections:
      - Known UI elements (from POM — exact names for clicks/fills)
      - Verification fields (from backend — field names to check in ZIP JSON)
      - API endpoints to watch (from frontend)
      - Automation workflow (POM code snippet showing step sequence)
      - Domain knowledge (RAG)
    """
    parts: list[str] = []
    query = f"{card_name} {scenario}"

    pom_docs: list = []
    be_docs: list = []
    fe_docs: list = []

    try:
        from rag.code_indexer import search_code

        # Always fetch label generation workflow from automation — it has the exact steps
        label_docs = search_code(
            "generate label More Actions click order Shopify navigate",
            k=5, source_type="automation",
        )

        # Scenario-specific automation code
        scenario_pom_docs = search_code(query, k=5, source_type="automation")

        pom_docs = (label_docs or []) + (scenario_pom_docs or [])

        # Backend models/schema
        be_docs = search_code(query, k=3, source_type="backend") or []

        # Frontend API files
        try:
            fe_docs = search_code(query, k=3, source_type="frontend") or []
        except Exception:
            fe_docs = []

    except Exception as e:
        logger.debug("Code RAG error: %s", e)

    # ── Section 1: UI elements ────────────────────────────────────────────────
    try:
        ui_elements = _extract_ui_elements(pom_docs)
        if ui_elements:
            parts.append(
                "=== KNOWN UI ELEMENTS (from automation POM — use EXACT names for clicks/fills) ===\n"
                + "\n".join(ui_elements)
            )
        elif pom_docs:
            # Fallback: raw POM snippets (existing behaviour)
            snippets = "\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:600]}"
                for d in pom_docs[:5]
            )
            parts.append(f"=== AUTOMATION WORKFLOW (from POM) ===\n{snippets}")
    except Exception as e:
        logger.debug("UI element extraction error: %s", e)
        if pom_docs:
            try:
                snippets = "\n---\n".join(
                    f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:600]}"
                    for d in pom_docs[:5]
                )
                parts.append(f"=== AUTOMATION WORKFLOW (from POM) ===\n{snippets}")
            except Exception:
                pass

    # ── Section 2: Verification fields ───────────────────────────────────────
    try:
        fields = _extract_backend_fields(be_docs, scenario)
        if fields:
            parts.append(
                "=== VERIFICATION FIELDS (from backend — check these exact field names in downloaded ZIP JSON) ===\n"
                + ", ".join(fields)
            )
        elif be_docs:
            snippets = "\n---\n".join(d.page_content[:400] for d in be_docs)
            parts.append(f"=== Backend API ===\n{snippets}")
    except Exception as e:
        logger.debug("Backend field extraction error: %s", e)
        if be_docs:
            try:
                snippets = "\n---\n".join(d.page_content[:400] for d in be_docs)
                parts.append(f"=== Backend API ===\n{snippets}")
            except Exception:
                pass

    # ── Section 3: API endpoints ──────────────────────────────────────────────
    try:
        endpoints = _extract_api_endpoints(fe_docs + be_docs)
        if endpoints:
            parts.append(
                "=== API ENDPOINTS TO WATCH (from frontend — these appear in network calls) ===\n"
                + "\n".join(endpoints)
            )
    except Exception as e:
        logger.debug("API endpoint extraction error: %s", e)

    # ── Section 4: Domain knowledge ───────────────────────────────────────────
    try:
        from rag.vectorstore import search as qs
        docs = qs(query, k=3)
        if docs:
            snippets = "\n---\n".join(d.page_content[:400] for d in docs)
            parts.append(f"=== DOMAIN KNOWLEDGE ===\n{snippets}")
    except Exception as e:
        logger.debug("QA knowledge RAG error: %s", e)

    return "\n\n".join(parts) if parts else "(no code context indexed yet)"


# ── Domain Expert ─────────────────────────────────────────────────────────────

def _ask_domain_expert(scenario: str, card_name: str, claude: "ChatAnthropic") -> str:
    """Ask the domain expert what this scenario should do.

    Queries both the domain RAG (PluginHive docs, FedEx API knowledge) and the
    code RAG (automation POM, backend), then asks Claude to synthesise a concise
    answer covering:
      - Expected UI behaviour
      - API/request fields to watch
      - Specific things that confirm the feature is working

    Returns a plain-text answer (≤200 words) ready to be injected into the plan
    and step prompts.
    """
    query = f"{card_name} {scenario}"
    api_query = f"{scenario} API request field FedEx"
    domain_sections: list[str] = []
    code_parts:      list[str] = []

    # ── Domain RAG — 5 targeted sub-queries, one per source type ─────────────
    # Each sub-query is filtered to a single source_type so Claude receives a
    # clearly labelled section for each knowledge category rather than an
    # anonymous blob where source attribution is impossible.
    _DOMAIN_SOURCES = [
        # (source_type,       query_to_use, label,                                   k)
        ("pluginhive_docs",  query,        "PluginHive Official Documentation",      4),
        ("pluginhive_seeds", query,        "PluginHive FAQ & Guides",                3),
        ("fedex_rest",       api_query,    "FedEx REST API Reference",               4),
        ("wiki",             query,        "Internal Wiki (Product & Engineering)",  5),
        ("pdf",              query,        "Test Cases & Acceptance Criteria",        3),
    ]

    try:
        from rag.vectorstore import search_filtered
        for src_type, q, label, k in _DOMAIN_SOURCES:
            try:
                docs = search_filtered(q, k=k, source_type=src_type)
                if docs:
                    # For wiki docs add the category tag so Claude sees sub-topic
                    def _fmt(d: "Document") -> str:
                        cat = d.metadata.get("category", "")
                        prefix = f"[{cat}] " if cat else ""
                        return f"{prefix}{d.page_content[:450]}"
                    chunks = "\n\n".join(_fmt(d) for d in docs)
                    domain_sections.append(f"[{label}]\n{chunks}")
            except Exception as e:
                logger.debug("Domain RAG sub-query failed (source_type=%s): %s", src_type, e)
    except ImportError as e:
        logger.debug("search_filtered not available — falling back to unfiltered search: %s", e)
        try:
            from rag.vectorstore import search as rag_search
            docs = rag_search(query, k=8)
            if docs:
                domain_sections.append("\n\n".join(
                    f"[{d.metadata.get('source_type','doc')}] {d.page_content[:450]}"
                    for d in docs
                ))
        except Exception as e2:
            logger.debug("Fallback domain RAG also failed: %s", e2)

    # ── Code RAG (automation POM + backend) ───────────────────────────────────
    try:
        from rag.code_indexer import search_code
        auto_docs = search_code(query, k=5, source_type="automation")
        if auto_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:500]}"
                for d in auto_docs
            ))
        be_docs = search_code(query, k=4, source_type="backend")
        if be_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:400]}"
                for d in be_docs
            ))
    except Exception as e:
        logger.debug("Code RAG error in expert: %s", e)

    domain_context = "\n\n---\n\n".join(domain_sections) or "(no domain knowledge indexed)"
    code_context   = "\n\n".join(code_parts)              or "(no code indexed)"

    # Inject hardcoded pre-requirements if available (from automation spec files)
    preconditions = _get_preconditions(scenario)
    preconditions_section = (
        f"KNOWN PRE-REQUIREMENTS (from automation spec files):\n{preconditions}"
        if preconditions else ""
    )

    prompt = _DOMAIN_EXPERT_PROMPT.format(
        scenario=scenario,
        card_name=card_name,
        domain_context=domain_context[:4000],
        code_context=code_context[:3000],
        preconditions_section=preconditions_section,
    )

    try:
        resp = _claude_invoke_with_retry(
            claude,
            [HumanMessage(content=prompt)],
            purpose=f"domain expert: {scenario[:80]}",
        )
        answer = resp.content.strip()
        if isinstance(answer, list):
            answer = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in answer)
        return answer[:1200]   # cap so it doesn't crowd other context
    except Exception as e:
        logger.warning("Domain expert query failed: %s", e)
        return "(domain expert unavailable)"


# ── Claude helpers ────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    """Extract JSON from Claude's response — handles markdown fences, prefix/suffix text."""
    # 1. Try direct parse first
    clean = re.sub(r"```(?:json)?\n?", "", raw.strip()).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except Exception:
        pass

    # 2. Find the first { ... } or [ ... ] block (handles "Here is the JSON: {...}" or "[...]")
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return {}


def _is_retryable_claude_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return False
    text = str(exc).lower()
    retry_markers = (
        "429",
        "too many requests",
        "rate limit",
        "rate_limit",
        "overloaded",
        "temporarily unavailable",
        "readtimeout",
        "connecttimeout",
        "pooltimeout",
    )
    return any(marker in text for marker in retry_markers)


def _claude_invoke_with_retry(
    claude: ChatAnthropic,
    messages: list,
    *,
    purpose: str,
    max_attempts: int = 5,
    base_delay_s: float = 5.0,
    max_delay_s: float = 45.0,
):
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return claude.invoke(messages)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_claude_error(exc):
                raise
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            logger.warning(
                "Claude call retry for %s after attempt %d/%d: %s; sleeping %.1fs",
                purpose,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Claude call failed for {purpose}")


def _extract_scenarios(ac: str, claude: ChatAnthropic) -> list[str]:
    try:
        resp = _claude_invoke_with_retry(
            claude,
            [HumanMessage(content=_EXTRACT_PROMPT.format(ac=ac))],
            purpose="extract scenarios",
        )
        raw  = resp.content.strip()
        data = _parse_json(raw)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning("Scenario extraction failed; using line-based fallback: %s", e)
    # fallback: parse line by line
    return [
        ln.strip("- ").strip()
        for ln in ac.splitlines()
        if ln.strip().startswith(("Given", "When", "Scenario", "Then", "-"))
    ][:12]


def _find_first_key(obj, target_key: str):
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]
        for value in obj.values():
            found = _find_first_key(value, target_key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_key(item, target_key)
            if found is not None:
                return found
    return None


def _verify_soldto_payload_from_scenario(scenario: str, captured_requests: list[dict[str, object]]) -> tuple[str, str] | None:
    if not captured_requests:
        return None
    scenario_lower = (scenario or "").lower()
    if not any(token in scenario_lower for token in ("soldto", "sold to", "billing address")):
        return None

    payload = (captured_requests[-1] or {}).get("payload")
    if not isinstance(payload, dict):
        return None
    sold_to = _find_first_key(payload, "soldTo")
    sold_to_address = sold_to.get("address", {}) if isinstance(sold_to, dict) else {}

    def _extract_expected(field: str) -> str:
        match = re.search(rf"{field}\s*=\s*\"([^\"]+)\"", scenario, re.I)
        return (match.group(1).strip() if match else "")

    expected_city = _extract_expected("city")
    expected_street = _extract_expected("street(?:Lines)?")
    expected_state = _extract_expected("state")
    expected_postal = _extract_expected("postal")

    if any(token in scenario_lower for token in ("completely absent", "omits soldto node", "omit soldto node", "does not call getsoldtodetailsusing")):
        if sold_to is None:
            return "pass", "Captured label request confirms the soldTo node is absent, matching the scenario."
        return "fail", "Captured label request still contains soldTo when the scenario expected it to be absent."

    if any(token in scenario_lower for token in ("city field is absent", "city field is **absent**", "whitespace-only city", "short and whitespace-only")):
        city_value = sold_to_address.get("city") if isinstance(sold_to_address, dict) else None
        if sold_to is None:
            return "fail", "Captured label request omitted soldTo entirely; this scenario expected soldTo to exist without the city field."
        if city_value in (None, ""):
            return "pass", "Captured label request keeps soldTo but omits the invalid city field, matching the scenario."
        return "fail", f"Captured label request still sent city='{city_value}' when the scenario expected the city field to be omitted."

    if any(token in scenario_lower for token in ("complete soldto node", "includes full soldto node", "exactly 3 characters is included", "sent with only valid fields")):
        if sold_to is None or not isinstance(sold_to_address, dict):
            return "fail", "Captured label request did not contain a soldTo node with an address payload."
        checks: list[str] = []
        if expected_city and sold_to_address.get("city") != expected_city:
            checks.append(f"city expected '{expected_city}' got '{sold_to_address.get('city')}'")
        if expected_state and sold_to_address.get("stateOrProvinceCode") != expected_state:
            checks.append(f"state expected '{expected_state}' got '{sold_to_address.get('stateOrProvinceCode')}'")
        if expected_postal and sold_to_address.get("postalCode") != expected_postal:
            checks.append(f"postal expected '{expected_postal}' got '{sold_to_address.get('postalCode')}'")
        if expected_street:
            street_lines = sold_to_address.get("streetLines") or []
            first_line = street_lines[0] if isinstance(street_lines, list) and street_lines else ""
            if first_line != expected_street:
                checks.append(f"street expected '{expected_street}' got '{first_line}'")
        if checks:
            return "fail", "Captured soldTo payload did not match expectations: " + "; ".join(checks)
        return "pass", "Captured soldTo payload matches the expected billing-address fields for this scenario."

    return None


def parse_test_cases(test_cases_markdown: str) -> list[ParsedTestCase]:
    blocks = re.split(r"(?=###\s+TC-\d+)", test_cases_markdown or "")
    parsed: list[ParsedTestCase] = []

    for block in blocks:
        block = block.strip()
        if not block or not re.match(r"###\s+TC-\d+", block):
            continue

        title_match = re.match(r"###\s+(TC-\d+):\s*(.+)", block)
        tc_id = title_match.group(1).strip() if title_match else f"TC-{len(parsed) + 1}"
        title = title_match.group(2).strip() if title_match else "Untitled"
        type_match = re.search(r"\*\*Type:\*\*\s*(Positive|Negative|Edge)", block, re.I)
        priority_match = re.search(r"\*\*Priority:\*\*\s*(High|Medium|Low)", block, re.I)
        preconditions_match = re.search(r"\*\*Preconditions:\*\*\s*(.+)", block, re.I)

        body_lines: list[str] = []
        capture = False
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("**Steps:**"):
                capture = True
                continue
            if capture:
                body_lines.append(line.rstrip())

        parsed.append(ParsedTestCase(
            index=len(parsed) + 1,
            tc_id=tc_id,
            title=title,
            tc_type=(type_match.group(1).title() if type_match else ""),
            priority=(priority_match.group(1).title() if priority_match else "Medium"),
            preconditions=(preconditions_match.group(1).strip() if preconditions_match else ""),
            body="\n".join(body_lines).strip(),
            execution_flow=_infer_test_case_execution_flow(
                "\n".join([
                    title,
                    preconditions_match.group(1).strip() if preconditions_match else "",
                    "\n".join(body_lines).strip(),
                ])
            ),
        ))

    return parsed


def _is_browser_verifiable_test_case(tc: ParsedTestCase) -> bool:
    text = "\n".join([
        tc.title or "",
        tc.preconditions or "",
        tc.body or "",
    ]).lower()

    backend_only_signals = (
        "call `", "call ", "invoke ", "function", "method", "helper",
        "test harness", "mock ", "mocked ", "stub ", "inspect returned object",
        "returned object", "return object", "assert that the returned",
        "assert the returned", "contains a `", "contains a '", "does not contain a `",
        "getsoldtodetailsusing", "fedexrestrequestbuilder", "request builder",
        "unit test", "backend", "object contains", "city key", "null or an empty object",
        "returns `null`", "returns null",
    )
    browser_signals = (
        "logged into the ph fedex app", "logged into the app", "navigate to orders",
        "generate a label", "generate label", "auto-generate", "manual label",
        "view logs", "request/response", "download documents", "print documents",
        "label generates successfully", "order exists", "shopify", "shipping grid",
        "order summary", "more actions", "fedex request", "request payload",
    )

    has_backend_only = _has_any(text, backend_only_signals)
    has_browser_signal = _has_any(text, browser_signals)

    # Explicit code-level/unit-style tests should not be sent to the live browser verifier.
    if has_backend_only and not has_browser_signal:
        return False

    # Default to browser-verifiable unless it strongly looks like a pure unit/backend test.
    return True


def rank_test_cases_for_execution(test_cases_markdown: str) -> list[ParsedTestCase]:
    parsed = parse_test_cases(test_cases_markdown)
    parsed = [tc for tc in parsed if _is_browser_verifiable_test_case(tc)]
    type_rank = {"Positive": 0, "Negative": 1, "Edge": 2}
    return sorted(
        parsed,
        key=lambda tc: (tc.priority_rank, type_rank.get(tc.tc_type, 3), tc.index),
    )


def _has_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _infer_test_case_execution_flow(text: str) -> str:
    s = f" {(text or '').lower()} "

    manual_signals = (
        "view logs", "rate log", "rates log", "request log", "before generate label",
        "before label generation", "before generating", "get shipping rates", "generate packages",
        "side dock", "sidedock", "hold at location", "hal", "signature", "insurance", "cod",
        "duties", "taxes", "packaging", "fedex box", "custom box",
    )
    auto_signals = (
        "auto-generate", "auto generate", "auto label", "auto-label",
        "download request", "download response", "request/response zip",
        "request response zip", "download documents", "print documents",
        "order summary", "label generated", "after label generation", "after generating",
    )

    if _has_any(s, manual_signals):
        return "manual"
    if _has_any(s, auto_signals):
        return "auto"
    return "manual"


def _infer_address_type(scenario: str) -> str:
    s = f" {scenario.lower()} "
    if _has_any(s, ("canada", " canadian ", " ottawa ", " on ", " ca ")):
        return "CA"
    if _has_any(s, (
        "uk", "united kingdom", "britain", "london", "cross-border", "overseas", "international",
        "commercial invoice", " customs ", "ci pdf", " ci ", "packing slip + ci", "invoice document",
    )):
        return "UK"
    return "default"


def _build_prerequisite_plan(scenario: str, execution_flow_override: str = "") -> ScenarioPrerequisitePlan:
    """
    REST-only prerequisite planner.
    Converts a scenario into the concrete setup the verifier should prepare before testing.
    """
    s = f" {scenario.lower()} "
    needs_manual_flow = _has_any(s, (
        "manual label", "generate label", "label generation", "side dock", "sidedock",
        "view logs", "rate log", "request log", "before generate label",
        "hold at location", " hal ", "insurance", "cod ", "cash on delivery",
        "duties", "taxes", "declared value", "one rate", "fedex one rate",
        "packaging", "packing method", "weight based", "box packing", "box based",
        "volumetric", "weight and dimensions unit",
    ))
    wants_auto_flow = _has_any(s, (
        "auto-generate", "auto generate", "auto label", "automatically generate",
        "auto-generated",
    ))
    needs_final_generated_output = _has_any(s, (
        "download documents", "print documents", "print document",
        "request/response zip", "request response zip", "download request", "download response",
        "download label", "label generated", "order summary",
    ))
    label_flow = "manual" if needs_manual_flow else "auto" if wants_auto_flow or needs_final_generated_output else "manual"
    if execution_flow_override in ("manual", "auto"):
        label_flow = execution_flow_override

    if _has_any(s, (
        "250 variants",
        "250+ variants",
        "250 product variants",
        "250+ product variants",
        "more than 250 variants",
        "more than 250 product variants",
        "high variant",
        "variant pagination",
    )):
        return ScenarioPrerequisitePlan(
            category="high_variant_product",
            order_action="create_product_250_variants",
            setup_steps=(
                "Create or reuse a Shopify product with at least 250 variants.",
                "Open Shopify Products and verify variant rendering/pagination on that product.",
            ),
            verification_signals=(
                "Variant count is at least 250.",
                "The product page remains usable while variants are visible.",
            ),
        )

    if _has_any(s, (
        "create new product", "new simple product", "add product to config",
        "existing products to config", "product config", "shopify products",
        "product summary", "product page", "country of origin", "track inventory",
        "sku", "tags", "variant_id", "product_id",
    )) and not _has_any(s, ("checkout", "customer sees rates", "rates at checkout", "storefront", "cart", "bogus payment", "pay now")):
        return ScenarioPrerequisitePlan(
            category="product_admin",
            order_action="none",
            setup_steps=(
                "Open Shopify Products or FedEx App Products depending on whether the scenario edits Shopify catalog data or FedEx product configuration.",
                "Search for the relevant product or start a new product flow.",
                "Verify save/config actions on the product page instead of launching label generation.",
            ),
            verification_signals=(
                "The correct product management surface is open.",
                "Product fields or config entries can be edited and saved.",
                "The expected product/config state is visible after saving.",
            ),
        )

    if _has_any(s, (
        "weight sync", "product weight sync", "stale weight", "shopify weight update",
        "weight mismatch", "weight not updated", "inventoryitem", "inventory item measurement",
    )):
        return ScenarioPrerequisitePlan(
            category="product_admin",
            order_action="none",
            setup_steps=(
                "Open Shopify Products and update or inspect the product/variant weight there first.",
                "Open FedEx App Products or the related product surface and verify the updated weight is reflected.",
                "Use rate or label generation only as downstream confirmation after product sync is visible.",
            ),
            verification_signals=(
                "The Shopify product weight change is visible.",
                "The FedEx app product/rate flow reflects the same updated weight.",
                "Any downstream rate or label behavior uses the synced weight.",
            ),
        )

    if _has_any(s, (
        "packaging", "packing method", "weight based", "box packing", "box based",
        "volumetric", "weight and dimensions unit", "pre-packed",
        "default product dimensions", "additional weight",
        "fedex small box", "fedex medium box", "fedex large box",
        "fedex extra small box", "fedex extra large box",
        "fedex envelope", "fedex pak", "fedex tube",
        "fedex 10kg box", "fedex 25kg box", "fedex standard freight box",
        "your packaging", "custom box", "carrier box", "small box", "medium box", "large box",
    )):
        return ScenarioPrerequisitePlan(
            category="packaging_flow",
            order_action="create_new",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open App Settings and set the required packaging method and units.",
                "Open App Products and set product dimensions/weight on a simple product when needed.",
                "Create a fresh order for that product and launch manual label generation.",
            ),
            verification_signals=(
                "Packaging settings are saved and visible.",
                "Product dimensions/weight are saved when the scenario needs them.",
                "Manual-label logs and documents reflect the expected packaging behavior.",
            ),
        )

    if _has_any(s, ("bulk", "50 orders", "100 orders", "multiple orders", "all orders", "batch label", "bulk print", "bulk packing slip", "auto-generate labels")):
        return ScenarioPrerequisitePlan(
            category="bulk_labels",
            order_action="create_bulk",
            setup_steps=(
                "Create several fresh unfulfilled Shopify orders in the test store.",
                "Verify the bulk action flow from Shopify Orders or the app grid.",
            ),
            verification_signals=(
                "Multiple fresh orders exist and are selectable together.",
                "Bulk label actions affect the expected set of orders.",
            ),
        )

    if _has_any(s, ("checkout", "customer sees rates", "rates at checkout", "storefront", "cart", "duties & taxes at checkout")):
        checkout_setup_steps = [
            "Open the Shopify storefront flow from admin and navigate to the relevant product or cart.",
            "Run the storefront checkout flow with the required destination/address.",
            "Verify the checkout rates and any duties/taxes messaging.",
        ]
        if _has_any(s, ("signature", "dry ice", "dryice", "dry-ice", "alcohol", "battery", "lithium")):
            checkout_setup_steps.insert(
                0,
                "Apply the required product-level FedEx App Products configuration before starting storefront checkout.",
            )
        return ScenarioPrerequisitePlan(
            category="checkout_rates",
            order_action="none",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            setup_steps=tuple(checkout_setup_steps),
            verification_signals=(
                "FedEx rates are visible at checkout.",
                "Checkout messages or amounts match the scenario expectations.",
                "Rates Log or request payload reflects the expected special-service configuration when the scenario requires it.",
            ),
        )

    if _has_any(s, ("purpose of shipment", "shipment purpose", "slgp override", "slgp purpose")):
        return ScenarioPrerequisitePlan(
            category="manual_label_sidedock",
            order_action="create_new",
            product_type="simple",
            address_type="UK",
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open Settings > International Shipping Settings > more settings and note or save the global Purpose Of Shipment value.",
                "Create a fresh international order and open manual label generation from Shopify Orders.",
                "Change Purpose Of Shipment on the SLGP/manual-label surface before generating the label.",
            ),
            verification_signals=(
                "The SLGP/manual-label purpose field accepts the override value.",
                "The live shipment/rate request uses the override instead of the global default.",
                "The downloaded label-request form uses the override instead of the global default.",
                "Commercial-invoice evidence matches the overridden purpose when documents are generated.",
            ),
        )

    if _has_any(s, ("importer of record", "importerofrecord", "ior", "importedofrecord")):
        return ScenarioPrerequisitePlan(
            category="label_generation",
            order_action="create_new",
            product_type="simple",
            address_type="UK",
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open account settings and ensure Importer Of Record is enabled with populated details.",
                "Create a fresh international order and launch manual label generation.",
                "Generate the label and collect request payload plus commercial-invoice evidence.",
            ),
            verification_signals=(
                "The shipment request payload contains importerOfRecord with the correct key spelling.",
                "The commercial invoice or printed documents include the IOR details.",
            ),
        )

    if _has_any(s, ("fedex error code", "generic error", "error code", "label failure", "city.too.short", "streetline1.empty")):
        return ScenarioPrerequisitePlan(
            category="label_generation",
            order_action="create_new",
            product_type="simple",
            address_type="UK" if _has_any(s, ("city.too.short", "streetline1.empty", "soldto", "billing")) else _infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Create or reuse an order/setup that predictably triggers the target FedEx validation failure.",
                "Open manual label generation and run the flow until the failure UI is shown.",
                "Capture the visible FedEx error code/message from the failure panel.",
            ),
            verification_signals=(
                "The label request fails in a controlled way.",
                "The UI shows the actionable FedEx error code/message instead of only a generic fallback.",
            ),
        )

    if _has_any(s, ("dry ice", "dryice", "dry-ice")):
        return ScenarioPrerequisitePlan(
            category="product_special_service",
            order_action="create_new",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open FedEx App Products and enable Dry Ice on an existing simple product.",
                "Create a fresh order that uses a simple product from the store.",
                "Generate a manual label so request JSON can be inspected before final submission.",
            ),
            verification_signals=(
                "Dry ice checkbox and weight are saved on the product.",
                "Rate or shipment request contains DRY_ICE and the expected dryIceWeight.",
                "Generated label/documents reflect the dry ice workflow.",
            ),
        )

    if _has_any(s, ("alcohol", "battery", "lithium", "dangerous goods", "hazmat", "dg ")):
        return ScenarioPrerequisitePlan(
            category="product_special_service",
            order_action="create_new",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open FedEx App Products and enable the required product-level special service on an existing simple product.",
                "Create a fresh order that uses a simple product from the store.",
                "Generate a manual label so request JSON can be inspected before final submission.",
            ),
            verification_signals=(
                "The product setting is saved successfully.",
                "Rate or shipment request contains the expected special-service payload.",
                "Label/documents reflect the configured service when applicable.",
            ),
        )

    signature_option = _infer_signature_option(scenario)
    if "signature" in s and signature_option:
        if _has_any(s, ("manual label", "generate label", "label generation", "side dock", "sidedock")):
            return ScenarioPrerequisitePlan(
                category="manual_label_sidedock",
                order_action="create_new",
                product_type="simple",
                address_type=_infer_address_type(scenario),
                requires_manual_label=True,
                label_flow="manual",
                setup_steps=(
                    "Create a fresh unfulfilled order in the test store.",
                    "Open manual label generation from Shopify Orders.",
                    f"Select the SideDock signature option '{signature_option[1]}' before generating the label.",
                ),
                verification_signals=(
                    "The SideDock signature dropdown accepts the requested value.",
                    "Rate or shipment request reflects the selected signature option.",
                ),
            )
        return ScenarioPrerequisitePlan(
            category="product_special_service",
            order_action="create_new",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Open FedEx App Products and set the required signature option on an existing simple product.",
                "Create a fresh order that uses a simple product from the store.",
                "Generate a manual label so request JSON can be inspected before final submission.",
            ),
            verification_signals=(
                "The product signature setting is saved successfully.",
                "Rate or shipment request contains the expected signature option.",
                "Generated label/documents reflect the configured signature when applicable.",
            ),
        )

    if _has_any(s, ("return label", "generate return", "download document", "print document", "verify label", "view label", "label shows", "cancel label", "after cancellation", "regenerate", "re-generate", "update address", "updated address", "address update", "next/previous order", "order summary nav")):
        return ScenarioPrerequisitePlan(
            category="existing_label_flow",
            order_action="existing_fulfilled",
            requires_existing_label=True,
            setup_steps=(
                "Use an order that already has a generated forward label.",
                "Open the order summary from the app Shipping grid or Shopify Orders.",
                "Perform the requested action on that existing labeled order.",
            ),
            verification_signals=(
                "The order starts in a labeled/fulfilled state.",
                "Order summary actions and documents are available.",
            ),
        )

    if _has_any(s, ("hold at location", " hal ", "insurance", "cod ", "cash on delivery", "duties", "taxes", "declared value", "one rate", "fedex one rate", "signature")):
        return ScenarioPrerequisitePlan(
            category="manual_label_sidedock",
            order_action="create_new",
            product_type="simple",
            address_type=_infer_address_type(scenario),
            requires_manual_label=True,
            label_flow="manual",
            setup_steps=(
                "Create a fresh unfulfilled order in the test store.",
                "Open manual label generation from Shopify Orders.",
                "Configure the required option in the right-side dock before generating the label.",
            ),
            verification_signals=(
                "The side-dock option is selectable and saved into the request flow.",
                "Rate or shipment request reflects the selected option.",
            ),
        )

    if _has_any(s, ("settings", "configuration", "configure", "save setting", "general settings", "additional services", "packages", "rates log", "rate log", "order grid", "orders grid", "filter", "pagination", "sidebar", "navigation", "pickup", "schedule pickup")):
        return ScenarioPrerequisitePlan(
            category="settings_or_grid",
            order_action="none",
            setup_steps=(
                "Navigate directly to the target app page.",
                "Verify the grid, navigation, settings save, or pickup UI without creating new orders unless the scenario explicitly needs them.",
            ),
            verification_signals=(
                "The target UI is reachable and interactive.",
                "Saved values, filters, or navigation state persist as expected.",
            ),
        )

    return ScenarioPrerequisitePlan(
        category="label_generation",
        order_action="create_new",
        product_type="simple",
        address_type=_infer_address_type(scenario),
        requires_manual_label=(label_flow == "manual"),
        label_flow=label_flow,
        setup_steps=(
            "Create a fresh unfulfilled order that matches the scenario.",
            f"Open the {label_flow} label-generation flow from Shopify Orders.",
        ),
        verification_signals=(
            "The required order exists before verification starts.",
            "The label flow reaches the expected final state.",
        ),
    )


def _is_deterministic_category(category: str) -> bool:
    return category in {
        "packaging_flow",
        "product_special_service",
        "manual_label_sidedock",
        "label_generation",
        "settings_or_grid",
        "existing_label_flow",
        "bulk_labels",
        "high_variant_product",
        "product_admin",
        "checkout_rates",
    }


def _heuristic_plan_data(scenario: str, app_url: str, ctx: str = "") -> dict:
    plan = _build_prerequisite_plan(scenario)
    s = scenario.lower()
    nav_clicks: list[str] = []
    app_path = ""
    look_for = list(plan.verification_signals) or ["Expected UI state is visible."]
    api_to_watch: list[str] = []

    if plan.category == "packaging_flow":
        nav_clicks = ["Settings", "AppProducts", "Orders"]
        app_path = "settings"
        api_to_watch = ["/api/", "/labels", "/rates"]
    elif plan.category == "product_special_service":
        nav_clicks = ["AppProducts", "Orders"]
        app_path = "products"
        api_to_watch = ["/api/", "/labels", "/rates"]
    elif plan.category == "manual_label_sidedock":
        nav_clicks = ["Orders"]
        app_path = "orders"
        api_to_watch = ["/api/", "/labels", "/rates"]
    elif plan.category == "label_generation" and plan.label_flow == "auto":
        nav_clicks = ["Orders"]
        app_path = "orders"
        api_to_watch = ["/api/", "/labels", "/documents"]
    elif plan.category == "existing_label_flow":
        nav_clicks = ["Shipping"]
        app_path = "shipping"
        api_to_watch = ["/api/", "/labels", "/documents"]
    elif plan.category == "settings_or_grid":
        if _has_any(s, ("settings", "configuration", "configure", "save setting", "general settings", "additional services", "packages")):
            nav_clicks = ["Settings"]
            app_path = _settings_route_for_scenario(scenario)
        elif _has_any(s, ("pickup", "schedule pickup")):
            nav_clicks = ["PickUp"]
            app_path = "pickup"
        elif _has_any(s, ("rates log", "rate log", "logs")):
            nav_clicks = ["Rates Log"]
            app_path = "rates log"
        else:
            nav_clicks = ["Shipping"]
            app_path = "shipping"
        api_to_watch = ["/api/"]
    elif plan.category == "bulk_labels":
        nav_clicks = ["Orders"]
        app_path = "orders"
        api_to_watch = ["/api/", "/labels"]
    elif plan.category == "high_variant_product":
        nav_clicks = ["ShopifyProducts"]
        app_path = "shopifyproducts"
        api_to_watch = ["/api/"]
    elif plan.category == "product_admin":
        if _has_any(s, ("app product", "fedex product", "product signature", "dry ice", "alcohol", "battery")):
            nav_clicks = ["AppProducts"]
            app_path = "appproducts"
        else:
            nav_clicks = ["ShopifyProducts"]
            app_path = "shopifyproducts"
        api_to_watch = ["/api/", "/products"]
    elif plan.category == "checkout_rates":
        nav_clicks = []
        app_path = ""
        api_to_watch = ["/api/", "/rates", "/checkout"]
    else:
        nav_clicks = ["Orders"]
        app_path = "orders"
        api_to_watch = ["/api/", "/labels", "/rates"]

    if "rates log" in s or "view logs" in s or "request log" in s:
        api_to_watch = ["/api/", "/rates", "/log"]
    if "download document" in s or "print document" in s:
        api_to_watch = ["/api/", "/documents", "/labels"]
    if "pickup" in s:
        api_to_watch = ["/api/", "/pickup"]

    return {
        "app_path": app_path,
        "look_for": look_for[:5],
        "api_to_watch": api_to_watch,
        "nav_clicks": nav_clicks,
        "plan": "Deterministic heuristic flow selected from scenario category.",
        "order_action": plan.order_action,
    }


def _step_budget_for_category(category: str) -> int:
    return {
        "packaging_flow": 18,
        "product_special_service": 18,
        "manual_label_sidedock": 16,
        "label_generation": 16,
        "settings_or_grid": 12,
        "existing_label_flow": 14,
        "bulk_labels": 12,
        "high_variant_product": 12,
        "product_admin": 14,
        "checkout_rates": 18,
    }.get(category, MAX_STEPS)


def _summarise_report(report: VerificationReport) -> None:
    passed = sum(1 for sv in report.scenarios if sv.status == "pass")
    failed = sum(1 for sv in report.scenarios if sv.status in ("fail", "partial"))
    skipped = sum(1 for sv in report.scenarios if sv.status == "skipped")
    qa_needed = sum(1 for sv in report.scenarios if sv.status == "qa_needed")
    parts = [f"{passed} passed"]
    if failed:
        parts.append(f"{failed} failed/partial")
    if qa_needed:
        parts.append(f"{qa_needed} need QA input")
    if skipped:
        parts.append(f"{skipped} skipped")
    report.summary = " · ".join(parts) if parts else "No scenarios executed."


def _close_browser_async(ctx, browser, timeout_s: float = 5.0) -> None:
    """
    Best-effort Playwright teardown that does not block report delivery forever.

    In some runs the Chrome window closes visually, but Playwright teardown can
    still hang for a long time. That left the dashboard stuck in "verifying"
    even though execution had effectively ended. Run teardown on a daemon
    thread, wait briefly, then return control to the caller.
    """
    def _close() -> None:
        try:
            ctx.close()
        except Exception as close_ctx_err:
            logger.debug("SmartVerifier: ctx.close() skipped: %s", close_ctx_err)
        try:
            browser.close()
        except Exception as close_browser_err:
            logger.debug("SmartVerifier: browser.close() skipped: %s", close_browser_err)

    closer = threading.Thread(target=_close, daemon=True)
    closer.start()
    closer.join(timeout=timeout_s)
    if closer.is_alive():
        logger.warning(
            "SmartVerifier: browser teardown still running after %.1fs; returning report anyway",
            timeout_s,
        )


def _validate_order_action(scenario: str, claude_choice: str) -> str:
    """
    Fix 1 — Python safety net: override clearly wrong order_action choices.
    Claude's plan is usually right; this catches obvious mismatches.
    """
    s = scenario.lower()
    plan = _build_prerequisite_plan(scenario)
    planned_action = plan.order_action
    is_storefront_checkout = plan.category == "checkout_rates"

    if planned_action == "none":
        if claude_choice in ("create_new", "create_bulk", "existing_unfulfilled"):
            logger.info(
                "[order_validate] Overriding '%s' → 'none' "
                "(scenario planner says no order setup is required)",
                claude_choice,
            )
            return "none"
    elif planned_action and claude_choice in ("none", "", "existing_unfulfilled") and planned_action != claude_choice:
        logger.info(
            "[order_validate] Overriding '%s' → '%s' "
            "(scenario prerequisite planner selected the stronger setup)",
            claude_choice, planned_action,
        )
        return planned_action

    # These scenarios MUST have a label to cancel/verify — needs existing_fulfilled
    _fulfilled_signals = [
        "cancel label", "cancel the label", "after cancellation", "after label cancel",
        "address update", "update address", "update the address", "update shipping address",
        "updated address", "regenerate",
        "re-generate", "return label", "generate return", "download document",
        "verify label", "print document", "label shows", "label generated",
        "next/previous order", "order summary nav",
    ]
    if any(kw in s for kw in _fulfilled_signals):
        if claude_choice in ("create_new", "existing_unfulfilled", "none"):
            logger.info(
                "[order_validate] Overriding '%s' → 'existing_fulfilled' "
                "(scenario signals a label must exist)", claude_choice
            )
            return "existing_fulfilled"

    # These scenarios create a brand-new label — needs fresh unfulfilled order
    _new_order_signals = [
        "generate label", "create label", "auto-generate label", "manual label",
        "dry ice", "alcohol", "battery", "signature required", "adult signature",
        "hold at location", " hal ", "cod ", "cash on delivery", "insurance",
        "declared value", "one rate", "fedex one rate",
        "domestic label", "international label",
    ]
    if any(kw in s for kw in _new_order_signals):
        if claude_choice == "none" and not is_storefront_checkout:
            logger.info(
                "[order_validate] Overriding 'none' → 'create_new' "
                "(scenario signals label generation)"
            )
            return "create_new"

    # Bulk keywords
    _bulk_signals = ["bulk", "50 orders", "100 orders", "batch label", "select all orders",
                     "auto-generate labels", "bulk print"]
    if any(kw in s for kw in _bulk_signals):
        if claude_choice in ("none", "create_new", "existing_fulfilled"):
            logger.info("[order_validate] Overriding '%s' → 'create_bulk'", claude_choice)
            return "create_bulk"

    return claude_choice


def _setup_order_ctx(order_action: str, scenario: str, base_ctx: str) -> str:
    """
    Fix 2 (reuse) — build the order context prefix for a given order_action.
    Called at start of scenario AND by reset_order mid-run.
    Returns the context string with order strategy prepended.
    """
    from pipeline.order_creator import resolve_order
    plan = _build_prerequisite_plan(scenario)

    preface_lines = [
        f"SCENARIO CATEGORY: {plan.category}",
        "APP MODE: REST only. Do not reason about SOAP or migration branches.",
    ]
    if plan.setup_steps:
        preface_lines.append("PREREQUISITE SETUP:")
        preface_lines.extend(f"- {step}" for step in plan.setup_steps)
    if plan.verification_signals:
        preface_lines.append("TARGET VERIFICATION SIGNALS:")
        preface_lines.extend(f"- {sig}" for sig in plan.verification_signals)
    if plan.requires_manual_label:
        preface_lines.append("FLOW REQUIREMENT: Use MANUAL label generation so the side dock and pre-submit logs are available.")
    elif plan.label_flow == "auto":
        preface_lines.append("FLOW REQUIREMENT: Use AUTO label generation and verify the final generated outputs from Order Summary / downloads.")
    if plan.requires_existing_label:
        preface_lines.append("FLOW REQUIREMENT: Start from an order that already has a generated forward label.")
    if plan.address_type != "default":
        preface_lines.append(f"TEST DESTINATION: Use {plan.address_type} address data for this scenario.")

    preface = "\n".join(preface_lines) + "\n\n"

    if order_action == "create_product_250_variants":
        from pipeline.product_creator import get_or_create_high_variant_product
        product_info = get_or_create_high_variant_product(variant_count=250)
        if product_info:
            return preface + (
                f"HIGH-VARIANT PRODUCT READY: '{product_info['title']}' — "
                f"{product_info['variant_count']} variants (id: {product_info['id']})\n"
                f"Admin URL: {product_info['admin_url']}\n"
                f"Navigate: ShopifyProducts → search '{product_info['title']}' → open → scroll to Variants.\n\n"
                + base_ctx
            )
        return preface + ("PRODUCT NOTE: Could not create 250-variant product via API. "
                "Navigate to ShopifyProducts and verify manually.\n\n" + base_ctx)

    if order_action == "create_bulk":
        orders = resolve_order(scenario, "create_bulk")
        if orders and isinstance(orders, list):
            names = [o["name"] for o in orders]
            return preface + (
                f"BULK ORDERS CREATED: {len(orders)} fresh unfulfilled orders → {names}\n"
                f"Ready in Shopify admin → Orders list (Unfulfilled tab).\n"
                f"Flow: select all → Actions → Auto-Generate Labels\n\n" + base_ctx
            )
        return preface + ("ORDER STRATEGY: Use existing unfulfilled orders in Shopify admin → "
                "Orders → Unfulfilled tab.\n\n" + base_ctx)

    if order_action == "create_new":
        order = resolve_order(scenario, "create_new")
        if order and isinstance(order, dict):
            product_title = ""
            try:
                line_items = order.get("line_items") or []
                if line_items:
                    product_title = (line_items[0].get("title") or "").strip()
            except Exception:
                product_title = ""
            return preface + (
                f"FRESH ORDER CREATED: {order.get('name')} (id: {order.get('id')}) — "
                f"unfulfilled, ready for label generation. "
                f"Expected test data: product_type={plan.product_type}, address_type={plan.address_type}. "
                + (f"ORDER PRODUCT TITLE: {product_title}. " if product_title else "")
                + f"Find it in Shopify admin → Orders → Unfulfilled tab.\n\n"
                + base_ctx
            )
        # Fallback to existing_unfulfilled
        return preface + ("ORDER STRATEGY: Use an existing UNFULFILLED order. "
                "Shopify admin LEFT sidebar → Orders → Unfulfilled tab → first order.\n\n" + base_ctx)

    if order_action == "existing_unfulfilled":
        return preface + ("ORDER STRATEGY: Use an existing UNFULFILLED order. "
                "Shopify admin LEFT sidebar → Orders → Unfulfilled tab → first order in list.\n\n"
                + base_ctx)

    if order_action == "existing_fulfilled":
        return preface + ("ORDER STRATEGY: Use an order that already HAS a label generated. "
                "App sidebar → Shipping → Label Generated tab → click first order row.\n\n"
                + base_ctx)

    # none
    return preface + base_ctx


def _get_preconditions(scenario: str) -> str:
    """
    Returns hardcoded pre-requirements for known scenario types.
    Based on real automation spec files — exact flows, product names, JSON fields, PDF codes.
    Returns empty string for unknown scenarios (RAG + domain expert handle those).
    """
    s = scenario.lower()
    plan = _build_prerequisite_plan(scenario)
    generic = [
        "REST-ONLY TEST MODE: assume the store is already on FedEx REST.",
        f"Scenario category: {plan.category}",
        f"Required order_action: {plan.order_action}",
        f"Preferred product_type: {plan.product_type}",
        f"Preferred address_type: {plan.address_type}",
    ]
    if plan.requires_manual_label:
        generic.append("Use manual label generation when verifying this scenario.")
    elif plan.label_flow == "auto":
        generic.append("Use auto label generation when verifying this scenario and validate the final generated outputs after completion.")
    if plan.requires_existing_label:
        generic.append("Start from an order that already has a generated forward label.")
    if plan.setup_steps:
        generic.append("Setup sequence:")
        generic.extend(f"- {step}" for step in plan.setup_steps)
    if plan.verification_signals:
        generic.append("Verification focus:")
        generic.extend(f"- {step}" for step in plan.verification_signals)
    generic_text = "\n".join(generic)

    if "purpose of shipment" in s or "shipment purpose" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (FDX-115 / SLGP override flow):
            1. nav_clicks: ["Settings"] → open International Shipping Settings → click "more settings" → note current Purpose Of Shipment
            2. order_action: create_new  (fresh INTERNATIONAL Shopify order)
            3. Open manual label generation from Shopify Orders
            4. On the manual-label / side-dock flow, change Purpose Of Shipment to the scenario value before generating
               - Use the SideDock dropdown labeled "Purpose Of Shipment To be used in Commercial Invoice"
               - Do not use the left-nav Rates Log page for this proof
               - After Get shipping rates, use the ⋯ menu in the "Shipping rates from account" card → View Logs
            VERIFY:
            - Live request-side evidence must use the per-order override value rather than the saved global default
            - Downloaded label-request evidence must also use the per-order override value
            - If commercial invoice is available after generation, use it as secondary confirmation""")

    if "importer of record" in s or "importerofrecord" in s or "ior" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (FDX-164 / IOR commercial-invoice flow):
            1. nav_clicks: ["Settings"] → open account details and ensure Importer Of Record is enabled with details
            2. order_action: create_new  (fresh INTERNATIONAL Shopify order)
            3. Use label generation and collect both request payload and CI/document evidence
            VERIFY:
            - Request payload contains importerOfRecord (correct spelling), not importedOfRecord
            - Commercial invoice / printed documents show the IOR details""")

    if "fedex error code" in s or "generic error" in s or "label failure" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (FDX-113 / failure-state verification):
            1. Create or reuse a setup that predictably fails label generation with a FedEx validation error
            2. Run the label flow until the failure UI is rendered
            VERIFY:
            - The UI shows the real FedEx error code/message
            - Do not treat a generic fallback message as PASS""")

    if "weight sync" in s or "product weight sync" in s or "stale weight" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (FDX-175 / product sync verification):
            1. Open Shopify Products and inspect or update the product/variant weight there first
            2. Open FedEx App Products or the relevant product/rate surface
            VERIFY:
            - The app reflects the updated Shopify weight
            - Use downstream rate or label behavior only as secondary confirmation""")

    if "dry ice" in s or "dryice" in s or "dry-ice" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (from automation spec: dryIce.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Dry Ice Needed' → fill Dry Ice Weight = '0.3' (kg) → Save
            3. order_action: create_new  (fresh Shopify order with simple product, US address)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["DRY_ICE"]
                dryIceWeight.value = 0.3,  unit = "KG"
            VERIFY label text (Strategy 5): Print Documents → 'ICE' text on label
            CLEANUP: AppProducts → uncheck 'Is Dry Ice Needed' → Save""")

    if "alcohol" in s:
        recipient = "LICENSEE" if "licensee" in s else "CONSUMER"
        return generic_text + "\n\n" + dedent(f"""\
            PRE-REQUIREMENTS (from automation spec: alcoholRecipient{'Licensee' if recipient=='LICENSEE' else 'Consumer'}.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Alcohol' → set Alcohol Recipient Type = '{recipient}' → Save
            3. order_action: create_new  (fresh Shopify order with simple product, US address)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["ALCOHOL"]
                alcoholDetail.alcoholRecipientType = "{recipient}"
            VERIFY label text (Strategy 5): Print Documents → 'ALCOHOL' text on label
            CLEANUP: AppProducts → uncheck 'Is Alcohol' → Save""")

    if "battery" in s or "lithium" in s:
        if "metal" in s or "packed with" in s:
            material, packing = "LITHIUM_METAL", "PACKED_WITH_EQUIPMENT"
        else:
            material, packing = "LITHIUM_ION", "CONTAINED_IN_EQUIPMENT"
        return generic_text + "\n\n" + dedent(f"""\
            PRE-REQUIREMENTS (from automation spec: battery{material.title().replace('_','')}.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Battery'
               → set Battery Material Type = '{material}'
               → set Battery Packing Type = '{packing}' → Save
            3. order_action: create_new  (fresh Shopify order with simple product)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["BATTERY"]
                batteryDetails[0].materialType = "{material}"
                batteryDetails[0].batteryPackingType = "{packing}"
                batteryDetails[0].regulatorySubType = "IATA_SECTION_II"
            VERIFY label text (Strategy 5): Print Documents → 'ELB' text on label  ← NOTE: 'ELB' not 'BATTERY'
            CLEANUP: AppProducts → uncheck 'Is Battery' → Save""")

    # Signature at PRODUCT level (e.g. "adult signature on product")
    _SIG_MAP = {
        "adult":          ("ADULT",          "Adult Signature Required",   "ASR"),
        "direct":         ("DIRECT",         "Direct Signature Required",  "DSR"),
        "indirect":       ("INDIRECT",       "Indirect Signature Required","ISR"),
        "service default":("SERVICE_DEFAULT","Service Default",            "SS AVXA"),
    }
    if "signature" in s and any(k in s for k in _SIG_MAP):
        for key, (val, label, pdf_code) in _SIG_MAP.items():
            if key in s:
                return generic_text + "\n\n" + dedent(f"""\
                    PRE-REQUIREMENTS (from automation spec: {key.replace(' ','').title()}Signature.spec.ts):
                    1. nav_clicks: ["AppProducts"]
                    2. AppProducts: search 'BLAZER' → set 'FedEx® Delivery Signature Options' = '{label}' (value: {val}) → Save
                    3. order_action: create_new  (fresh Shopify order)
                    VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
                    - Strategy 4: ⋯ → View Logs → JSON must contain:
                        signatureOptionType = "{val}"
                    VERIFY label text (Strategy 5): Print Documents → '{pdf_code}' text on label
                    CLEANUP: AppProducts → search 'BLAZER' → reset Signature to 'As Per The General Settings' → Save""")

    if "hal" in s or "hold at location" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (from automation spec: holdAtLocationLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (no product config — HAL is configured in SideDock)
            2. order_action: create_new  (fresh Shopify order)
            FLOW during Manual Label:
            - SideDock: click 'Hold at Location' → search location → select 'HHRAA' → confirm
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON must contain:
                specialServices: ["HOLD_AT_LOCATION"]
                holdAtLocationDetail.locationId = "HHRAA"
            VERIFY AFTER generating (Strategy 3 via How To ZIP):
            - More Actions → How To → Click Here ZIP → check locationId + locationType match""")

    if "insurance" in s:
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (from automation spec: insuranceLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (no product config — Insurance is in SideDock)
            2. order_action: create_new
            FLOW during Manual Label:
            - SideDock: check 'Add Third Party Insurance'
              → Liability Type: 'New' or 'Used or Reconditioned'
              → Insurance Type: 'Percentage of Product Price' or 'Declared Value of Product'
              → fill percentage or leave as declared value
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON must contain:
                declaredValue.amount = expected computed value""")

    if "signature" in s and _infer_signature_option(scenario) and _has_any(s, ("sidedock", "side dock", "manual label", "generate label", "label generation")):
        return generic_text + "\n\n" + dedent("""\
            PRE-REQUIREMENTS (from automation spec: signatureSettingsLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (signature set in SideDock — NOT product level)
            2. order_action: create_new
            FLOW during Manual Label:
            - SideDock: 'FedEx® Delivery Signature Options' dropdown → select one of:
              ADULT | DIRECT | INDIRECT | NO_SIGNATURE_REQUIRED
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON: signatureOptionType = selected value""")

    return generic_text


def _automation_env_value(name: str) -> str:
    if name in os.environ and os.environ[name].strip():
        return os.environ[name].strip()
    if _ENV_FILE and _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


def _parse_setup_context(ctx: str) -> dict[str, str]:
    info: dict[str, str] = {}
    patterns = {
        "order_name": r"FRESH ORDER CREATED:\s*([#\w-]+)",
        "order_id": r"FRESH ORDER CREATED:.*\(id:\s*([0-9]+)\)",
        "product_title": r"ORDER PRODUCT TITLE:\s*(.+?)\.",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, ctx)
        if match:
            info[key] = match.group(1).strip()
    return info


def _record_setup_step(result: ScenarioResult, action: str, description: str, target: str = "", success: bool = True) -> None:
    result.steps.append(VerificationStep(
        action=action,
        description=description,
        target=target,
        success=success,
    ))


def _append_evidence_note(result: ScenarioResult, note: str) -> None:
    note = (note or "").strip()
    if note and note not in result.evidence_notes:
        result.evidence_notes.append(note)


def _finalize_scenario_evidence(result: ScenarioResult, page, net_seen: list[str]) -> None:
    try:
        result.final_url = page.url or result.final_url
    except Exception:
        pass
    if not result.final_screenshot_b64:
        result.final_screenshot_b64 = _screenshot(page)
    if net_seen:
        result.final_network_calls = list(net_seen[-10:])


def _first_visible(locators: list, wait_ms: int = 10_000):
    for loc in locators:
        try:
            count = loc.count()
            for idx in range(min(count, 8)):
                candidate = loc.nth(idx)
                try:
                    candidate.wait_for(state="visible", timeout=wait_ms)
                    return candidate
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _click_any(locators: list, timeout: int = 5_000, wait_ms: int = 10_000) -> bool:
    el = _first_visible(locators, wait_ms=wait_ms)
    if el is None:
        return False
    try:
        el.click(timeout=timeout)
        return True
    except Exception:
        return False


def _open_shopify_order_more_actions_menu(page, wait_ms: int = 15_000) -> bool:
    opened = _click_any([
        page.get_by_role("button", name="More actions").first,
        page.get_by_role("button", name="More Actions").first,
        page.locator('button[aria-haspopup="menu"]').filter(has_text=re.compile(r"more actions", re.I)).first,
        page.get_by_text("More Actions", exact=False).first,
    ], wait_ms=wait_ms)
    if not opened:
        return False
    page.wait_for_timeout(1200)
    for popover in [
        page.locator('.Polaris-Popover'),
        page.locator('[role="menu"]'),
        page.locator('.Polaris-ActionList'),
    ]:
        try:
            if popover.count() > 0:
                popover.first.wait_for(state="visible", timeout=3_000)
                return True
        except Exception:
            continue
    page.wait_for_timeout(1200)
    return True


def _click_shopify_order_more_actions_item(page, item_name: str, wait_ms: int = 15_000) -> bool:
    return _click_any([
        page.locator('.Polaris-Popover').get_by_role("link", name=item_name, exact=True).first,
        page.locator('.Polaris-Popover').get_by_role("link", name=item_name, exact=False).first,
        page.locator('.Polaris-Popover').get_by_role("menuitem", name=item_name, exact=True).first,
        page.locator('.Polaris-Popover').get_by_role("menuitem", name=item_name, exact=False).first,
        page.locator('.Polaris-ActionList').get_by_text(item_name, exact=True).first,
        page.locator('.Polaris-ActionList').get_by_text(item_name, exact=False).first,
        page.get_by_role("link", name=item_name, exact=True).first,
        page.get_by_role("link", name=item_name, exact=False).first,
        page.get_by_role("menuitem", name=item_name, exact=True).first,
        page.get_by_role("menuitem", name=item_name, exact=False).first,
        page.get_by_text(item_name, exact=True).first,
        page.get_by_text(item_name, exact=False).first,
    ], wait_ms=wait_ms)


def _open_app_more_actions_menu(page, wait_ms: int = 10_000) -> bool:
    frame = _app_frame(page)
    opened = _click_any([
        frame.get_by_role("button", name="More Actions").last,
        frame.get_by_role("button", name="More actions").last,
        page.get_by_role("button", name="More Actions").last,
        frame.get_by_text("More Actions", exact=False).last,
    ], wait_ms=wait_ms)
    if not opened:
        return False
    page.wait_for_timeout(800)
    for popover in [
        frame.locator('.Polaris-Popover'),
        frame.locator('[role="menu"]'),
        frame.locator('.Polaris-ActionList'),
    ]:
        try:
            if popover.count() > 0:
                popover.first.wait_for(state="visible", timeout=3_000)
                return True
        except Exception:
            continue
    return True


def _click_app_more_actions_item(page, item_name: str, wait_ms: int = 10_000) -> bool:
    frame = _app_frame(page)
    return _click_any([
        frame.locator('.Polaris-Popover').get_by_role("menuitem", name=item_name, exact=True).first,
        frame.locator('.Polaris-Popover').get_by_role("menuitem", name=item_name, exact=False).first,
        frame.locator('.Polaris-Popover').get_by_role("button", name=item_name, exact=True).first,
        frame.locator('.Polaris-Popover').get_by_role("button", name=item_name, exact=False).first,
        frame.locator('.Polaris-ActionList').get_by_text(item_name, exact=True).first,
        frame.locator('.Polaris-ActionList').get_by_text(item_name, exact=False).first,
        frame.get_by_role("menuitem", name=item_name, exact=True).first,
        frame.get_by_role("menuitem", name=item_name, exact=False).first,
        frame.get_by_text(item_name, exact=True).first,
        frame.get_by_text(item_name, exact=False).first,
    ], wait_ms=wait_ms)


def _shopify_order_url(order_id: str) -> str:
    store = _automation_env_value("STORE")
    if not store or not order_id:
        return ""
    return f"https://admin.shopify.com/store/{store}/orders/{order_id}"


def _normalize_order_ref(order_ref: str) -> tuple[str, str]:
    raw = (order_ref or "").strip()
    digits = raw.replace("#", "").strip()
    visible = f"#{digits}" if digits else raw
    return digits, visible


def _shopify_store_root_url() -> str:
    store = _automation_env_value("STORE")
    if not store:
        return ""
    return f"https://admin.shopify.com/store/{store}"


def _shopify_storefront_root_url() -> str:
    store = (_automation_env_value("STORE") or "").strip()
    if not store:
        return ""
    return f"https://{store}.myshopify.com"


def _slugify_storefront_handle(text: str) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    return raw.strip("-")


def _unlock_storefront_if_required(page) -> bool:
    try:
        password_input = page.get_by_label("Enter store password")
        if password_input.count() == 0 and "/password" not in (page.url or ""):
            return True
        storefront_password = (_automation_env_value("STOREFRONT_PASSWORD") or "").strip()
        if not storefront_password:
            return False
        password_input.first.wait_for(state="visible", timeout=8_000)
        password_input.first.fill(storefront_password, timeout=5_000)
        enter_button = page.get_by_role("button", name="Enter")
        enter_button.first.click(timeout=5_000)
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
        return True
    except Exception:
        return False


def _wait_for_storefront_ready(page, timeout_ms: int = 25_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            for candidate in [
                page.locator('[data-testid="standalone-add-to-cart"]').first,
                page.get_by_role("button", name=re.compile(r"add to cart", re.I)).first,
                page.get_by_role("button", name=re.compile(r"buy it now", re.I)).first,
                page.locator('button[name="add"]').first,
                page.locator('button.product-form__submit').first,
                page.locator('button.cart__checkout-button').first,
                page.get_by_role("button", name=re.compile(r"check out", re.I)).first,
                page.locator('a[href="/cart"]').first,
                page.locator('input[name="email"]').first,
                page.locator('input[name="firstName"]').first,
                page.locator('input[name="quantity"]').first,
                page.locator('main h1').first,
                page.locator('.price, .price__regular, .product__price').first,
            ]:
                if candidate.count() > 0:
                    candidate.wait_for(state="visible", timeout=1_500)
                    return True
            ready = page.evaluate(
                """
                () => {
                  const visible = (el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                      style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const title = document.querySelector('main h1');
                  const qty = document.querySelector('input[name="quantity"]');
                  const add = [...document.querySelectorAll('button, input[type="submit"]')].find(
                    el => /add to cart/i.test((el.textContent || el.value || '').trim())
                  );
                  return visible(title) || (visible(qty) && visible(add));
                }
                """
            )
            if ready:
                return True
        except Exception:
            pass
        page.wait_for_timeout(750)
    return False


def _storefront_checkout_address(address_type: str) -> dict[str, str]:
    kind = (address_type or "default").upper()
    if kind == "CA":
        return {
            "email": "test.automation@fedexapp.com",
            "first_name": "Test",
            "last_name": "User",
            "address1": "111 Wellington St",
            "city": "Ottawa",
            "country": "Canada",
            "state": "Ontario",
            "zip": "K1A 0A9",
            "phone": "6135550100",
        }
    if kind == "UK":
        return {
            "email": "test.automation@fedexapp.com",
            "first_name": "Test",
            "last_name": "User",
            "address1": "221B Baker Street",
            "city": "London",
            "country": "United Kingdom",
            "state": "",
            "zip": "NW1 6XE",
            "phone": "2075550100",
        }
    return {
        "email": "test.automation@fedexapp.com",
        "first_name": "Test",
        "last_name": "User",
        "address1": "123 Main St",
        "city": "Los Angeles",
        "country": "United States",
        "state": "California",
        "zip": "90001",
        "phone": "3105550100",
    }


def _open_storefront_from_admin(
    page,
    storefront_root: str,
    progress_cb: "Callable[[str], None] | None" = None,
) -> object | None:
    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
    try:
        _emit("Hovering Online Store in Shopify admin and opening the storefront eye icon…")
        online_store_link = page.get_by_role("link", name="Online Store").first
        online_store_link.wait_for(state="visible", timeout=10_000)
        online_store_link.hover(timeout=5_000)
        page.wait_for_timeout(600)
        with page.context.expect_page(timeout=12_000) as new_page_info:
            clicked = page.evaluate(
                """
                () => {
                  const btn = document.querySelector('button[aria-label="View your online store"]');
                  if (!(btn instanceof HTMLElement)) return false;
                  btn.click();
                  return true;
                }
                """
            )
            if not clicked:
                raise RuntimeError("Storefront eye icon button was not found after hovering Online Store.")
        storefront_page = new_page_info.value
        _emit("Storefront tab opened from the Shopify admin eye icon.")
        storefront_page.wait_for_load_state("domcontentloaded", timeout=20_000)
        storefront_page.wait_for_timeout(2000)
        try:
            storefront_page.bring_to_front()
        except Exception:
            pass
        if storefront_root and storefront_root not in (storefront_page.url or ""):
            _emit("Normalizing the storefront tab onto the configured Shopify storefront root.")
            storefront_page.goto(storefront_root, wait_until="domcontentloaded", timeout=20_000)
            storefront_page.wait_for_timeout(1500)
        return storefront_page
    except Exception:
        return None


def _prepare_storefront_checkout(
    page,
    *,
    storefront_root: str,
    product_handle: str,
    address_type: str,
    stop_flag: "Callable[[], bool] | None" = None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> tuple[bool, str]:
    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    def _visible(locator, timeout: int = 10_000) -> bool:
        try:
            if locator.count() == 0:
                return False
            locator.first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def _click(locator, timeout: int = 10_000) -> bool:
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
            locator.first.click(timeout=timeout)
            return True
        except Exception:
            return False

    storefront_page = _open_storefront_from_admin(page, storefront_root, progress_cb=_emit) or page
    setattr(page, "_sav_storefront_page", storefront_page)
    setattr(page, "_sav_active_page", storefront_page)

    product_url = f"{storefront_root.rstrip('/')}/products/{product_handle}"
    _emit(f"Opening storefront product page for handle '{product_handle}'…")
    if not _goto_shopify_url(storefront_page, product_url):
        return False, f"Could not open storefront product page {product_url}."
    _unlock_storefront_if_required(storefront_page)
    if not _wait_for_storefront_ready(storefront_page, timeout_ms=20_000):
        return False, "Storefront product page did not become ready."
    if _is_stop_requested(stop_flag):
        return False, "Stopped before storefront add-to-cart."

    _emit("Opening the storefront product page and adding the product to cart…")
    add_to_cart_candidates = [
        storefront_page.locator('[data-testid="standalone-add-to-cart"]').first,
        storefront_page.get_by_role("button", name=re.compile(r"add to cart", re.I)).first,
        storefront_page.locator('form[action*="/cart/add"] button[type="submit"]').first,
        storefront_page.locator('button[name="add"]').first,
        storefront_page.locator('button.product-form__submit').first,
    ]
    add_to_cart = None
    for candidate in add_to_cart_candidates:
        if _visible(candidate, timeout=6_000):
            add_to_cart = candidate
            break
    if add_to_cart is None:
        return False, "Add to cart button was not visible on the storefront product page."
    try:
        with storefront_page.expect_response(
            lambda res: "/cart/add" in (res.url or ""),
            timeout=10_000,
        ):
            add_to_cart.click(timeout=10_000)
    except Exception:
        try:
            add_to_cart.click(timeout=10_000, force=True)
        except Exception as exc:
            return False, f"Could not click Add to cart on the storefront: {exc}"
    storefront_page.wait_for_timeout(1000)

    if _is_stop_requested(stop_flag):
        return False, "Stopped before opening the storefront cart."
    _emit("Opening the storefront cart and proceeding to checkout…")
    cart_url = f"{storefront_root.rstrip('/')}/cart"
    if not _goto_shopify_url(storefront_page, cart_url):
        return False, f"Could not open storefront cart page {cart_url}."
    _unlock_storefront_if_required(storefront_page)
    if not _wait_for_storefront_ready(storefront_page, timeout_ms=15_000):
        return False, "Storefront cart page did not become ready."

    checkout_button = (
        storefront_page.locator('button.cart__checkout-button').first
        if storefront_page.locator('button.cart__checkout-button').count() > 0
        else storefront_page.get_by_role("button", name=re.compile(r"check out", re.I)).first
    )
    if not _click(checkout_button):
        alt_checkout = storefront_page.locator('input[name="checkout"]').first
        if not _click(alt_checkout):
            return False, "Could not proceed from cart to checkout."
    _emit("Storefront cart opened — proceeding into checkout.")
    storefront_page.wait_for_load_state("domcontentloaded", timeout=20_000)
    storefront_page.wait_for_timeout(3000)
    _unlock_storefront_if_required(storefront_page)

    if _is_stop_requested(stop_flag):
        return False, "Stopped before filling checkout address."
    _emit("Filling the checkout shipping address to trigger FedEx shipping rates…")
    addr = _storefront_checkout_address(address_type)
    try:
        email_input = storefront_page.locator('input[name="email"]').first
        if _visible(email_input, timeout=6_000):
            email_input.fill(addr["email"], timeout=5_000)
        country_select = storefront_page.locator('select[name="countryCode"]').first
        if not _visible(country_select):
            country_select = storefront_page.locator('#country').first
        if _visible(country_select):
            country_select.select_option(label=addr["country"], timeout=5_000)
            storefront_page.wait_for_timeout(1500)
        storefront_page.locator('input[name="firstName"]').first.fill(addr["first_name"], timeout=5_000)
        last_name_input = storefront_page.locator('input[name="lastName"]').first
        last_name_input.fill(addr["last_name"], timeout=5_000)
        address1_input = storefront_page.locator('input[name="address1"]').first
        address1_input.fill(addr["address1"], timeout=5_000)
        storefront_page.wait_for_timeout(600)
        try:
            storefront_page.keyboard.press("Escape")
        except Exception:
            pass
        storefront_page.locator('input[name="city"]').first.fill(addr["city"], timeout=5_000)
        state_select = storefront_page.locator('select[name="zone"]').first
        if state_select.count() == 0:
            state_select = storefront_page.locator('#province').first
        if addr["state"] and _visible(state_select, timeout=4_000):
            state_select.select_option(label=addr["state"], timeout=5_000)
        zip_input = storefront_page.locator('input[name="postalCode"]').first
        if zip_input.count() == 0:
            zip_input = storefront_page.locator('#zip').first
        zip_input.fill(addr["zip"], timeout=5_000)
        try:
            storefront_page.keyboard.press("Tab")
        except Exception:
            pass
        phone_input = storefront_page.locator('input[name="phone"]').first
        if _visible(phone_input, timeout=4_000):
            phone_input.fill(addr["phone"], timeout=5_000)
    except Exception as exc:
        return False, f"Could not fill storefront checkout address: {exc}"

    _emit("Waiting for FedEx shipping options to appear at checkout…")
    shipping_option = storefront_page.locator('input[name="shippingMethods"], input[name=\"checkout[shipping_rate][id]\"]').first
    shipping_not_available = storefront_page.get_by_text("Shipping not available")
    for attempt in range(4):
        if _is_stop_requested(stop_flag):
            return False, "Stopped while waiting for storefront shipping rates."
        if _visible(shipping_option, timeout=10_000):
            _emit("FedEx shipping rates are visible at storefront checkout.")
            return True, "Storefront checkout reached the shipping-method step and FedEx rates became visible."
        try:
            if shipping_not_available.is_visible(timeout=1_000):
                last_name_input = storefront_page.locator('input[name="lastName"]').first
                last_name_input.fill(f"LN-{attempt + 1}", timeout=5_000)
                try:
                    storefront_page.keyboard.press("Enter")
                except Exception:
                    pass
                storefront_page.wait_for_timeout(2000)
        except Exception:
            pass
    return False, "FedEx shipping methods did not appear at storefront checkout after retries."


def _complete_storefront_checkout(
    page,
    *,
    scenario: str,
    stop_flag: "Callable[[], bool] | None" = None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> tuple[bool, str, dict[str, object]]:
    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    def _visible(locator, timeout: int = 8_000) -> bool:
        try:
            if locator.count() == 0:
                return False
            locator.first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def _click(locator, timeout: int = 8_000) -> bool:
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
            locator.first.click(timeout=timeout)
            return True
        except Exception:
            return False

    summary: dict[str, object] = {
        "shipping_selected": False,
        "continued_to_payment": False,
        "payment_submitted": False,
        "order_confirmed": False,
        "confirmation_number": "",
    }
    scenario_lower = (scenario or "").lower()

    if _is_stop_requested(stop_flag):
        return False, "Stopped before selecting a storefront shipping method.", summary

    _emit("Selecting the FedEx shipping method at storefront checkout…")
    shipping_candidates = [
        page.get_by_role("radio", name=re.compile(r"fedex", re.I)),
        page.locator('input[name="shippingMethods"], input[name="checkout[shipping_rate][id]"]'),
    ]
    shipping_selected = False
    for locator in shipping_candidates:
        try:
            if locator.count() == 0:
                continue
            locator.first.wait_for(state="visible", timeout=12_000)
            locator.first.check(timeout=8_000)
            shipping_selected = True
            break
        except Exception:
            continue
    if not shipping_selected:
        return False, "Could not select a storefront FedEx shipping option.", summary
    summary["shipping_selected"] = True

    continue_to_payment = [
        page.get_by_role("button", name=re.compile(r"continue to payment", re.I)),
        page.get_by_role("button", name=re.compile(r"continue to shipping", re.I)),
        page.locator('button[type="submit"]').filter(has_text=re.compile(r"continue|payment|shipping", re.I)),
    ]
    _emit("Continuing the storefront checkout flow after shipping selection…")
    for locator in continue_to_payment:
        if _click(locator):
            summary["continued_to_payment"] = True
            break
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    if _is_stop_requested(stop_flag):
        return False, "Stopped before payment handling at storefront checkout.", summary

    pay_now = page.locator('#checkout-pay-button').first
    card_number_frame = page.frame_locator('iframe[title="Field container for: Card number"]')
    card_number_input = card_number_frame.locator('input[placeholder="Card number"]')
    card_expiry_frame = page.frame_locator('iframe[title="Field container for: Expiration date (MM / YY)"]')
    card_expiry_input = card_expiry_frame.locator('input[placeholder="Expiration date (MM / YY)"]')
    card_cvv_frame = page.frame_locator('iframe[title="Field container for: Security code"]')
    card_cvv_input = card_cvv_frame.locator('input[placeholder="Security code"]')
    card_name_frame = page.frame_locator('iframe[title="Field container for: Name on card"]')
    card_name_input = card_name_frame.locator('input[placeholder="Name on card"]')

    needs_full_checkout = any(token in scenario_lower for token in (
        "place order",
        "payment",
        "bogus",
        "rates log",
        "rate log",
        "request log",
        "special service",
        "adult signature",
        "direct signature",
        "indirect signature",
        "service default",
    ))

    payment_surface_visible = False
    try:
        payment_surface_visible = _visible(pay_now, timeout=10_000) or _visible(card_number_input, timeout=5_000)
    except Exception:
        payment_surface_visible = False

    if needs_full_checkout or payment_surface_visible:
        _emit("Filling the bogus payment method and placing the storefront order…")
        try:
            if _visible(card_number_input, timeout=10_000):
                card_number_input.fill("1", timeout=5_000)
                if _visible(card_expiry_input, timeout=3_000):
                    card_expiry_input.fill("1229", timeout=5_000)
                if _visible(card_cvv_input, timeout=3_000):
                    card_cvv_input.fill("123", timeout=5_000)
                if _visible(card_name_input, timeout=3_000):
                    card_name_input.fill("Test Automation", timeout=5_000)
            if _click(pay_now, timeout=10_000) or _click(page.get_by_role("button", name=re.compile(r"pay now", re.I)), timeout=10_000):
                summary["payment_submitted"] = True
            try:
                page.wait_for_load_state("domcontentloaded", timeout=25_000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
        except Exception as exc:
            return False, f"Storefront payment submission did not complete: {exc}", summary

        confirmation_locators = [
            page.locator('h2.os-header__heading'),
            page.locator('[data-order-confirmation-text]'),
            page.get_by_role("heading", name=re.compile(r"thank you|order confirmed", re.I)),
            page.locator('.os-order-number, [data-checkout-order-name]'),
            page.locator('p').filter(has_text=re.compile(r"confirmation\\s*#", re.I)),
        ]
        confirmed = False
        for locator in confirmation_locators:
            if _visible(locator, timeout=20_000):
                confirmed = True
                break
        if not confirmed and needs_full_checkout:
            return False, "The storefront order confirmation page did not appear after payment.", summary
        summary["order_confirmed"] = confirmed
        if confirmed:
            summary["confirmation_number"] = (
                _text_of(page.locator('p').filter(has_text=re.compile(r"confirmation\\s*#", re.I)).first)
                or _text_of(page.locator('.os-order-number, [data-checkout-order-name]').first)
            )

    note = "Selected a FedEx shipping method at storefront checkout."
    if summary["order_confirmed"]:
        note += " Completed bogus payment and reached the order confirmation page."
    elif summary["payment_submitted"]:
        note += " Submitted payment, but the confirmation page could not be proved yet."
    return True, note, summary


def _capture_rates_log_evidence(
    page,
    *,
    scenario: str,
    app_base: str,
    stop_flag: "Callable[[], bool] | None" = None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> tuple[bool, str, dict[str, object]]:
    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    evidence: dict[str, object] = {
        "reference_id": "",
        "row_button": "",
        "row_index": -1,
        "payload": {},
    }
    if _is_stop_requested(stop_flag):
        return False, "Stopped before opening Rates Log.", evidence

    rates_url = _resolve_nav_url(app_base, "rates log")
    if not rates_url or not _goto_shopify_url(page, rates_url):
        return False, "Could not open the FedEx app Rates Log page.", evidence
    if not _wait_for_rates_log_ready(page, timeout_ms=35_000):
        return False, "Rates Log did not become ready after storefront checkout.", evidence
    _emit("Scanning the latest Rates Log entries and capturing the matching request payload…")
    frame = _app_frame(page)
    try:
        expected_signature = None
        baseline_ref = str(getattr(page, "_sav_rates_log_baseline_ref", "") or "").strip()
        if any(token in scenario.lower() for token in ("adult signature", "direct signature", "indirect signature", "service default")):
            inferred = _infer_signature_option(scenario)
            expected_signature = inferred[0] if inferred else None

        def _open_row_and_capture(row_idx: int) -> tuple[bool, str, dict[str, object]]:
            page.goto(rates_url, wait_until="domcontentloaded", timeout=20_000)
            if not _wait_for_rates_log_ready(page, timeout_ms=20_000):
                return False, "", {}
            local_frame = _app_frame(page)
            rows = local_frame.get_by_role("table").get_by_role("rowgroup").last.get_by_role("row")
            rows.first.wait_for(state="visible", timeout=12_000)
            count = rows.count()
            if row_idx >= count:
                return False, "", {}
            row = rows.nth(row_idx)
            ref_cell = row.get_by_role("cell").nth(2)
            ref_id = (_text_of(ref_cell) or "").strip()
            rate_buttons = [
                ("Normal Rates", row.get_by_role("button", name="Normal Rates")),
                ("Freight Rates", row.get_by_role("button", name="Freight Rates")),
                ("Smartpost Rates", row.get_by_role("button", name="Smartpost Rates")),
                ("Saturday Delivery Rates", row.get_by_role("button", name="Saturday Delivery Rates")),
            ]
            chosen_button = ""
            for label, locator in rate_buttons:
                try:
                    if locator.count() == 0:
                        continue
                    locator.first.wait_for(state="visible", timeout=4_000)
                    locator.first.click(timeout=5_000)
                    chosen_button = label
                    break
                except Exception:
                    continue
            if not chosen_button:
                return False, ref_id, {}

            detail_ready = False
            for locator in [
                local_frame.get_by_role("heading", name=re.compile(r"reference|rates", re.I)),
                local_frame.get_by_role("button", name="View Logs"),
                local_frame.get_by_text("Special Services", exact=False),
            ]:
                try:
                    if locator.count() == 0:
                        continue
                    locator.first.wait_for(state="visible", timeout=8_000)
                    detail_ready = True
                    break
                except Exception:
                    continue
            if not detail_ready:
                return False, ref_id, {}

            if not _do_action(page, {"action": "open_view_logs", "target": "View Logs"}, app_base, stop_flag=stop_flag):
                return False, ref_id, {}
            return True, ref_id, {
                "row_button": chosen_button,
                "payload": _extract_request_log_data(page) or {},
            }

        rows_checked = 0
        best_ref = ""
        best_payload: dict[str, object] = {}
        best_button = ""
        max_rows = 5
        latest_retry_attempts = 3
        latest_retry_wait_ms = 2500

        def _payload_signature(payload: dict[str, object]) -> str:
            try:
                return str((_summarize_verification_payload(payload) or {}).get("signature_option_type") or "")
            except Exception:
                return ""

        # Latest row is the source of truth for storefront checkout.
        # Retry it briefly first so delayed log writes can settle before we fall back to older rows.
        for latest_attempt in range(latest_retry_attempts):
            if _is_stop_requested(stop_flag):
                return False, "Stopped while waiting for the latest Rates Log row.", evidence
            _emit(
                "Checking the latest Rates Log row for the storefront checkout request…"
                if latest_attempt == 0 else
                f"Re-checking the latest Rates Log row (attempt {latest_attempt + 1})…"
            )
            opened, ref_id, captured = _open_row_and_capture(0)
            rows_checked += 1
            if opened:
                payload = captured.get("payload") if isinstance(captured, dict) else {}
                button = captured.get("row_button") if isinstance(captured, dict) else ""
                if isinstance(payload, dict) and payload and not best_payload:
                    best_payload = payload
                    best_ref = ref_id
                    best_button = button
                actual_signature = _payload_signature(payload) if isinstance(payload, dict) else ""
                is_new_latest = bool(ref_id) and ref_id != baseline_ref
                if expected_signature:
                    if actual_signature == expected_signature and (is_new_latest or not baseline_ref):
                        evidence["reference_id"] = ref_id
                        evidence["row_button"] = button
                        evidence["row_index"] = 0
                        evidence["payload"] = payload
                        setattr(page, "_sav_last_rates_log_payload", payload)
                        return True, (
                            f"Captured matching storefront Rates Log evidence from the latest row"
                            f"{' (' + ref_id + ')' if ref_id else ''}."
                        ), evidence
                elif isinstance(payload, dict) and payload and (is_new_latest or not baseline_ref):
                    evidence["reference_id"] = ref_id
                    evidence["row_button"] = button
                    evidence["row_index"] = 0
                    evidence["payload"] = payload
                    setattr(page, "_sav_last_rates_log_payload", payload)
                    return True, (
                        f"Captured storefront Rates Log evidence from the latest row"
                        f"{' (' + ref_id + ')' if ref_id else ''}."
                    ), evidence
            if latest_attempt < latest_retry_attempts - 1:
                page.wait_for_timeout(latest_retry_wait_ms)

        # If the latest row never matched, scan a few older recent rows as a safety net.
        for idx in range(1, max_rows):
            if _is_stop_requested(stop_flag):
                return False, "Stopped while scanning Rates Log rows.", evidence
            _emit(f"Latest row did not match yet — checking recent Rates Log row {idx + 1}…")
            opened, ref_id, captured = _open_row_and_capture(idx)
            rows_checked += 1
            if not opened:
                continue
            payload = captured.get("payload") if isinstance(captured, dict) else {}
            button = captured.get("row_button") if isinstance(captured, dict) else ""
            if baseline_ref and ref_id == baseline_ref:
                continue
            if isinstance(payload, dict) and payload and not best_payload:
                best_payload = payload
                best_ref = ref_id
                best_button = button
            actual_signature = _payload_signature(payload) if isinstance(payload, dict) else ""
            if expected_signature and actual_signature == expected_signature:
                evidence["reference_id"] = ref_id
                evidence["row_button"] = button
                evidence["row_index"] = idx
                evidence["payload"] = payload
                setattr(page, "_sav_last_rates_log_payload", payload)
                return True, (
                    f"Captured matching Rates Log evidence from row {idx + 1}"
                    f"{' (' + ref_id + ')' if ref_id else ''}."
                ), evidence
            if not expected_signature and isinstance(payload, dict) and payload:
                evidence["reference_id"] = ref_id
                evidence["row_button"] = button
                evidence["row_index"] = idx
                evidence["payload"] = payload
                setattr(page, "_sav_last_rates_log_payload", payload)
                return True, (
                    f"Captured Rates Log evidence from row {idx + 1}"
                    f"{' (' + ref_id + ')' if ref_id else ''}."
                ), evidence

        if best_payload:
            evidence["reference_id"] = best_ref
            evidence["row_button"] = best_button
            evidence["row_index"] = 0
            evidence["payload"] = best_payload
            setattr(page, "_sav_last_rates_log_payload", best_payload)
            return True, (
                f"Captured Rates Log evidence after checking {rows_checked} row(s), but none matched the exact scenario signature."
            ), evidence
        return False, "Rates Log opened, but no usable request payload was captured from the latest rows.", evidence
    except Exception as exc:
        return False, f"Rates Log evidence capture failed: {exc}", evidence


def _verify_checkout_rates_from_scenario(
    scenario: str,
    checkout_summary: dict[str, object] | None,
    rates_log_payload: dict[str, object] | None,
) -> tuple[str, str] | None:
    scenario_lower = (scenario or "").lower()
    checkout_summary = checkout_summary or {}
    rates_log_payload = rates_log_payload or {}
    payload_summary = _summarize_verification_payload(rates_log_payload) if rates_log_payload else {}

    if "adult signature" in scenario_lower:
        actual = payload_summary.get("signature_option_type")
        if actual == "ADULT":
            return "pass", "Storefront checkout completed and the Rates Log request payload confirms ADULT signature."
        return "fail", f"Storefront checkout ran, but the Rates Log payload did not confirm ADULT signature (got {actual or 'none'})."
    if "direct signature" in scenario_lower:
        actual = payload_summary.get("signature_option_type")
        if actual == "DIRECT":
            return "pass", "Storefront checkout completed and the Rates Log request payload confirms DIRECT signature."
        return "fail", f"Storefront checkout ran, but the Rates Log payload did not confirm DIRECT signature (got {actual or 'none'})."
    if "indirect signature" in scenario_lower:
        actual = payload_summary.get("signature_option_type")
        if actual == "INDIRECT":
            return "pass", "Storefront checkout completed and the Rates Log request payload confirms INDIRECT signature."
        return "fail", f"Storefront checkout ran, but the Rates Log payload did not confirm INDIRECT signature (got {actual or 'none'})."
    if "service default" in scenario_lower:
        actual = payload_summary.get("signature_option_type")
        if actual == "SERVICE_DEFAULT":
            return "pass", "Storefront checkout completed and the Rates Log request payload confirms SERVICE_DEFAULT signature."
        return "fail", f"Storefront checkout ran, but the Rates Log payload did not confirm SERVICE_DEFAULT signature (got {actual or 'none'})."

    if rates_log_payload:
        return "pass", "Storefront checkout completed and a live Rates Log request payload was captured for verification."
    if checkout_summary.get("shipping_selected"):
        return "pass", "Storefront checkout reached FedEx shipping selection successfully."
    return None


def _bypass_shopify_account_selector(page) -> bool:
    """
    If Shopify shows the account chooser, try to click the current QA account automatically.
    """
    try:
        if "accounts.shopify.com/select" not in (page.url or ""):
            return True
        user_email = _automation_env_value("USER_EMAIL")
        if user_email and _click_any([
            page.get_by_text(user_email, exact=False),
            page.get_by_role("button", name=user_email, exact=False),
        ], timeout=8_000):
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
            return "accounts.shopify.com/select" not in (page.url or "")
        account_links = page.get_by_role("link")
        try:
            count = min(account_links.count(), 5)
        except Exception:
            count = 0
        for idx in range(count):
            try:
                text = account_links.nth(idx).inner_text(timeout=2_000).strip()
                if not text:
                    continue
                low = text.lower()
                if any(skip in low for skip in ("add account", "need help", "terms", "privacy policy")):
                    continue
                account_links.nth(idx).click(timeout=8_000)
                page.wait_for_load_state("domcontentloaded", timeout=20_000)
                return "accounts.shopify.com/select" not in (page.url or "")
            except Exception:
                continue
    except Exception:
        pass
    return False


def _goto_shopify_url(page, url: str) -> bool:
    """
    Navigate to a Shopify admin/app URL and recover once from the account chooser if needed.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)
        if "accounts.shopify.com/select" in (page.url or ""):
            if not _bypass_shopify_account_selector(page):
                return False
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)
        return "accounts.shopify.com/select" not in (page.url or "")
    except Exception:
        return False


def _click_app_menu_route(page, app_base: str, route: str, link_name: str) -> bool:
    try:
        base = _normalize_app_base(app_base).rstrip("/")
        target_url = _resolve_nav_url(app_base, route)
        href_suffix = "/" + route.strip("/")
        candidates = [
            page.locator(f'a[href*="{base}"]').filter(has_text=link_name).first,
            page.locator(f'a[href*="{href_suffix}"]').filter(has_text=link_name).first,
            page.get_by_role("link", name=link_name).first,
        ]
        for candidate in candidates:
            try:
                if candidate.count() == 0:
                    continue
                candidate.wait_for(state="visible", timeout=5_000)
                candidate.click(force=True, timeout=5_000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)
                if target_url and target_url.rstrip("/") in (page.url or ""):
                    return True
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _wait_for_shopify_admin_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            for candidate in [
                page.get_by_role("button", name=re.compile(r"search", re.I)).first,
                page.locator("#search-container").first,
            ]:
                if candidate.count() > 0:
                    candidate.wait_for(state="visible", timeout=2_000)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(750)
    return False


def _search_and_open_shopify_order(page, order_ref: str, max_retries: int = 4) -> bool:
    clean_order_id, visible_order_ref = _normalize_order_ref(order_ref)
    if not clean_order_id:
        return False
    if not _wait_for_shopify_admin_ready(page, timeout_ms=30_000):
        return False
    try:
        search_button = page.get_by_role("button", name=re.compile(r"search", re.I)).first
        search_container = page.locator("#search-container")
        orders_button = search_container.get_by_role("button", name="Orders")
        search_input = page.get_by_role("combobox", name="Search")
        search_results = page.locator("ul#search-results")
        order_link = search_results.locator('a[role="option"][href*="/orders/"]', has_text=visible_order_ref)
        fallback_order_link = search_results.locator('a[role="option"][href*="/orders/"]', has_text=clean_order_id)

        page.wait_for_timeout(3000)
        search_button.click(timeout=5_000)
        orders_button.wait_for(state="visible", timeout=10_000)
        orders_button.click(timeout=5_000)
        search_input.wait_for(state="visible", timeout=10_000)
        search_input.fill(visible_order_ref)

        for attempt in range(max_retries):
            try:
                order_link.first.wait_for(state="visible", timeout=1_500)
                order_link.first.click(timeout=5_000)
                page.wait_for_load_state("domcontentloaded")
                return True
            except Exception:
                try:
                    fallback_order_link.first.wait_for(state="visible", timeout=1_000)
                    fallback_order_link.first.click(timeout=5_000)
                    page.wait_for_load_state("domcontentloaded")
                    return True
                except Exception:
                    pass
                if attempt == max_retries - 1:
                    break
                search_input.fill("")
                page.wait_for_timeout(1000)
                search_input.fill(visible_order_ref)
                page.wait_for_timeout(2000)
        return False
    except Exception:
        return False


def _wait_for_fedex_products_screen(page, timeout_ms: int = 15_000) -> bool:
    """
    Treat the rendered FedEx products UI inside the iframe as the source of truth.
    Outer Shopify URLs can vary; the iframe content is what matters.
    """
    deadline = timeout_ms / 1000
    start = time.time()
    expected_markers = (
        "product name",
        "import",
        "export",
        "simple product",
    )

    while time.time() - start < deadline:
        try:
            for frame in page.frames:
                if frame is page.main_frame:
                    continue
                frame_url = frame.url or ""
                if not frame_url or "pluginhive" not in frame_url:
                    continue
                body = (frame.locator("body").inner_text(timeout=2_000) or "").lower()
                if all(marker in body for marker in expected_markers[:3]) or any(marker in body for marker in expected_markers[3:]):
                    return True
        except Exception:
            pass
        page.wait_for_timeout(750)
    return False


def _goto_fedex_products(page, app_base: str) -> bool:
    """
    Reach the FedEx products management screen robustly.
    Prefer the embedded app route and in-app menu navigation, then use a
    store-level products fallback only as a last resort.
    """
    store = _store_from_app_base(_normalize_app_base(app_base))
    app_products_url = _resolve_nav_url(app_base, "appproducts")
    app_root = _normalize_app_base(app_base)
    if app_products_url and _goto_shopify_url(page, app_products_url):
        page.wait_for_timeout(2500)
        if _wait_for_fedex_products_screen(page):
            return True
    if app_root and _goto_shopify_url(page, app_root):
        if _click_app_menu_route(page, app_base, "products", "Products"):
            page.wait_for_timeout(2000)
            if _wait_for_fedex_products_screen(page):
                return True
    fallback_url = f"https://admin.shopify.com/store/{store}/products" if store else ""
    if fallback_url and _goto_shopify_url(page, fallback_url):
        if _click_app_menu_route(page, app_base, "products", "Products"):
            page.wait_for_timeout(2000)
        else:
            page.wait_for_timeout(2500)
        if _wait_for_fedex_products_screen(page):
            return True
        if app_products_url and _goto_shopify_url(page, app_products_url):
            page.wait_for_timeout(2000)
            if _wait_for_fedex_products_screen(page):
                return True
    return False


def _wait_for_manual_label_ready(page, timeout_ms: int = 30_000) -> bool:
    """
    Use the same readiness idea as the Playwright automation:
    the FedEx manual-label page is ready when the iframe is present,
    loading settles, and Generate Packages becomes visible.
    """
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            try:
                spinner = frame.locator('[class*="spinner"], [class*="loading"], .skeleton-loader').first
                if spinner.count() > 0 and spinner.is_visible():
                    page.wait_for_timeout(750)
                    continue
            except Exception:
                pass
            # dynamic readiness signals from automation repo
            for candidate in [
                frame.get_by_role("button", name="Generate Packages"),
                frame.get_by_role("button", name="Get shipping rates"),
                frame.get_by_role("button", name="Generate Label"),
                frame.locator("h1"),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _complete_manual_label_generation(
    page,
    stop_flag: "Callable[[], bool] | None" = None,
    timeout_ms: int = 60_000,
    progress_cb: "Callable[[str], None] | None" = None,
) -> bool:
    """
    Deterministically complete the common manual label path:
    Generate Packages → Get Shipping Rates / Get Rates → select first visible service → Generate Label.
    """
    if not _wait_for_manual_label_ready(page, timeout_ms=min(timeout_ms, 35_000)):
        return False

    frame = _app_frame(page)
    deadline = time.time() + (timeout_ms / 1000)
    captured_label_requests: list[dict[str, object]] = []

    def _capture_label_request(req) -> None:
        try:
            if (getattr(req, "method", "") or "").upper() != "POST":
                return
            try:
                post_data = req.post_data or ""
            except Exception:
                try:
                    post_data = req.post_data() or ""
                except Exception:
                    post_data = ""
            if "requestedShipment" not in (post_data or ""):
                return
            payload: object = post_data
            try:
                payload = json.loads(post_data)
            except Exception:
                pass
            captured_label_requests.append({
                "url": getattr(req, "url", ""),
                "method": getattr(req, "method", "POST"),
                "payload": payload,
            })
        except Exception:
            return

    while time.time() < deadline:
        if _is_stop_requested(stop_flag):
            return False
        if _wait_for_order_summary_ready(page, timeout_ms=2_000):
            if captured_label_requests:
                setattr(page, "_sav_last_label_requests", captured_label_requests[-3:])
            return True
        try:
            if any(
                locator.count() > 0
                for locator in [
                    frame.locator('input[type="radio"]'),
                    frame.get_by_role("radio"),
                    frame.locator('[role="radio"]'),
                ]
            ):
                if progress_cb:
                    progress_cb("Selecting the first available FedEx service rate…")
                service_picked = _click_any([
                    frame.locator('input[type="radio"]').first,
                    frame.get_by_role("radio").first,
                    frame.locator('[role="radio"]').first,
                    frame.locator('label').filter(has_text="$").first,
                ], wait_ms=1_500)
                if service_picked:
                    if not _cooperative_wait(page, 800, stop_flag):
                        return False
                    continue
        except Exception:
            pass

        try:
            if any(
                locator.count() > 0
                for locator in [
                    frame.get_by_role("button", name="Generate Label"),
                    frame.get_by_text("Generate Label", exact=True),
                ]
            ):
                if progress_cb:
                    progress_cb("Generating the label from the selected FedEx service…")
                if _click_any([
                    frame.get_by_role("button", name="Generate Label"),
                    frame.get_by_text("Generate Label", exact=True),
                ], wait_ms=1_500):
                    try:
                        page.on("request", _capture_label_request)
                    except Exception:
                        pass
                    try:
                        ready = _wait_for_order_summary_ready(page, timeout_ms=25_000)
                    finally:
                        try:
                            page.remove_listener("request", _capture_label_request)
                        except Exception:
                            pass
                    if ready and captured_label_requests:
                        setattr(page, "_sav_last_label_requests", captured_label_requests[-3:])
                    return ready
        except Exception:
            pass

        try:
            if progress_cb:
                progress_cb("Clicking Generate Packages to prepare the shipment package…")
            if _click_any([
                frame.get_by_role("button", name="Generate Packages"),
                frame.get_by_text("Generate Packages", exact=False),
            ], wait_ms=1_500):
                if not _cooperative_wait(page, 1200, stop_flag):
                    return False
                continue
        except Exception:
            pass

        try:
            if progress_cb:
                progress_cb("Fetching FedEx shipping rates for the prepared package…")
            if _click_any([
                frame.get_by_role("button", name="Get Shipping Rates"),
                frame.get_by_role("button", name="Get Rates"),
                frame.get_by_text("Get Shipping Rates", exact=False),
                frame.get_by_text("Get Rates", exact=False),
                frame.get_by_text("Refresh Rates", exact=False),
            ], wait_ms=1_500):
                if not _cooperative_wait(page, 2500, stop_flag):
                    return False
                continue
        except Exception:
            pass

        if not _cooperative_wait(page, 1000, stop_flag):
            return False

    ready = _wait_for_order_summary_ready(page, timeout_ms=5_000)
    if ready and captured_label_requests:
        setattr(page, "_sav_last_label_requests", captured_label_requests[-3:])
    return ready


def _wait_for_shipping_grid_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in [
                frame.get_by_role("button", name="Search and filter results"),
                frame.get_by_role("table"),
                frame.get_by_text("Shipping", exact=True),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_return_label_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in [
                frame.get_by_role("heading", name="Return Label"),
                frame.get_by_text("Return Label", exact=False),
                frame.get_by_role("button", name="Generate Return Label"),
                frame.locator('input[name="[object Object].returnQuantity"]'),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_order_summary_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in [
                frame.get_by_role("button", name="Print Documents"),
                frame.get_by_role("button", name="More Actions"),
                frame.get_by_text("label generated", exact=False),
                frame.get_by_text("Return packages", exact=False),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_auto_label_ready(page, timeout_ms: int = 30_000) -> bool:
    """
    Auto-generate label does not open the manual-label page.
    It should end on Order Summary / generated-label state.
    """
    if _wait_for_order_summary_ready(page, timeout_ms=timeout_ms):
        return True
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            body = (page.locator("body").inner_text(timeout=2_000) or "").lower()
            if "label generated" in body or "print documents" in body:
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_settings_ready(page, scenario: str = "", timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in _settings_targets_for_scenario(frame, scenario):
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _settings_route_for_scenario(scenario: str) -> str:
    s = (scenario or "").lower()
    if _has_any(s, ("documents/label", "documents label", "packing slip template", "use customer selected service", "ship after", "single file", "show customer references")):
        return "settings/label/details"
    if _has_any(s, ("return label settings", "return rates selection strategy", "return packaging type", "return purpose of shipment")):
        return "settings/auto/returnlabel"
    return "settings/0"


def _settings_targets_for_scenario(frame, scenario: str):
    s = (scenario or "").lower()
    targets: list = []

    if _has_any(s, ("account settings", "subscription settings", "add account", "change plan", "account details")):
        targets.extend([
            frame.get_by_role("heading", name="Account Settings"),
            frame.get_by_role("heading", name="Subscription Settings"),
            frame.get_by_role("button", name="Add Account"),
            frame.get_by_role("button", name="Change"),
        ])
    if _has_any(s, ("shop contact", "first name", "last name", "company name", "mid code")):
        targets.extend([
            frame.get_by_role("heading", name="Shop Contact Details"),
            frame.get_by_role("textbox", name="First Name"),
            frame.get_by_role("textbox", name="Company Name"),
        ])
    if _has_any(s, ("documents/label", "documents label", "packing slip template", "use customer selected service", "ship after", "single file", "show customer references", "allow po box", "display company name")):
        targets.extend([
            frame.get_by_role("heading", name="Documents/Label Settings"),
            frame.get_by_role("checkbox", name="Use Customer Selected Service"),
            frame.get_by_role("spinbutton", name="Ship After These(0 to 7) Many Days"),
            frame.get_by_role("checkbox", name="Single File"),
        ])
    if _has_any(s, ("notifications", "smtp", "notify customer on fulfillment", "fedex notifications", "email reply to")):
        targets.extend([
            frame.get_by_role("heading", name="Notifications"),
            frame.get_by_role("checkbox", name="Enable FedEx Notifications"),
            frame.get_by_role("button", name="Test SMTP Credentials"),
        ])
    if _has_any(s, ("international shipping", "etd", "commercial invoice", "purpose of shipment", "terms of sale", "certificate of origin", "pro forma")):
        targets.extend([
            frame.get_by_role("heading", name="International Shipping Settings"),
            frame.get_by_role("checkbox", name=re.compile(r"Electronic Trade Documents", re.I)),
            frame.get_by_role("button", name="more settings"),
            frame.get_by_role("combobox", name=re.compile(r"Purpose Of Shipment", re.I)),
        ])
    if _has_any(s, ("rate settings", "display estimated delivery time", "include duties and taxes", "debug mode", "carrier services", "fallback services")):
        targets.extend([
            frame.get_by_role("heading", name="Rate Settings"),
            frame.get_by_role("checkbox", name="Enable Debug Mode"),
            frame.get_by_role("checkbox", name="Display Estimated Delivery Time for FedEx Services (If Available)"),
            frame.get_by_role("heading", name="Carrier Services"),
        ])
    if _has_any(s, ("print settings", "outbound label", "commercial invoice copies", "return label copies", "bill of lading")):
        targets.extend([
            frame.get_by_role("heading", name="Print Settings"),
            frame.get_by_role("spinbutton", name="Outbound Label"),
            frame.get_by_role("spinbutton", name="Commercial Invoice"),
            frame.get_by_role("spinbutton", name="Return Label"),
        ])
    if _has_any(s, ("return settings", "generate return with forward", "reason for return", "return signature")):
        targets.extend([
            frame.get_by_role("heading", name="Return Settings"),
            frame.get_by_role("checkbox", name="Generate Return With Forward"),
            frame.get_by_role("combobox", name="Reason for Return"),
            frame.get_by_role("combobox", name="Return Signature"),
        ])
    if _has_any(s, ("return label settings", "return rates selection strategy", "return packaging type", "return purpose of shipment")):
        targets.extend([
            frame.get_by_role("heading", name="Return Label Settings"),
            frame.get_by_role("combobox", name="Return Rates Selection Strategy"),
            frame.get_by_role("combobox", name="Return Packaging Type"),
        ])
    if _has_any(s, ("pickup settings", "pickup start time", "company close time", "package pickup location", "drop-off type", "commodity description")):
        targets.extend([
            frame.get_by_role("heading", name="Pickup Settings"),
            frame.get_by_role("combobox", name="PickUp Start Time"),
            frame.get_by_role("combobox", name="Drop-Off Type"),
        ])
    if _has_any(s, ("additional services", "dry ice", "fedex one rate", "duties and taxes in checkout rates")):
        targets.extend([
            frame.get_by_role("heading", name="Additional Services"),
            frame.get_by_role("heading", name="Dry Ice"),
            frame.get_by_role("heading", name="FedEx One Rate®"),
            frame.get_by_text("Include Duties and Taxes in Checkout Rates", exact=False),
            frame.locator('input[name="isDryIceEnabled"]'),
            frame.locator('input[name="dryIceWeight"]'),
            frame.locator('select[name="dryIceWeightUnit"]'),
            frame.locator('input[name="isOneRateEnabled"]'),
            frame.locator('input[name="isDutiesAndTaxesEnabled"]'),
        ])
    if _has_any(s, ("packing", "package", "weight based", "box packing", "volumetric", "additional weight")):
        targets.extend([
            frame.get_by_text("Packing Method", exact=False),
            frame.get_by_text("Weight And Dimensions Unit", exact=False),
            frame.get_by_role("button", name="more settings"),
        ])

    if not targets:
        targets = [
            frame.get_by_role("heading", name="Settings"),
            frame.get_by_role("heading", name="Rate Settings"),
            frame.get_by_role("heading", name="Additional Services"),
            frame.get_by_text("Packing Method", exact=False),
            frame.get_by_role("button", name="Save"),
        ]
    return targets


def _settings_save_targets_for_scenario(frame, scenario: str):
    s = (scenario or "").lower()
    targets: list = []
    if _has_any(s, ("shop contact", "first name", "last name", "company name", "mid code")):
        targets.append(
            frame.get_by_role("heading", name="Shop Contact Details").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("documents/label", "documents label", "packing slip template", "use customer selected service", "ship after", "single file", "show customer references", "allow po box", "display company name")):
        targets.append(
            frame.get_by_role("heading", name="Documents/Label Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("notifications", "smtp", "notify customer on fulfillment", "fedex notifications", "email reply to")):
        targets.append(
            frame.get_by_role("heading", name="Notifications").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("international shipping", "etd", "certificate of origin", "pro forma")):
        targets.append(
            frame.get_by_role("heading", name="International Shipping Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("commercial invoice", "purpose of shipment", "terms of sale")):
        targets.append(frame.get_by_role("button", name="Save").last)
    if _has_any(s, ("rate settings", "display estimated delivery time", "include duties and taxes", "debug mode", "carrier services", "fallback services")):
        targets.append(
            frame.get_by_role("heading", name="Rate Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("print settings", "outbound label", "commercial invoice copies", "return label copies", "bill of lading")):
        targets.append(
            frame.get_by_role("heading", name="Print Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("return settings", "generate return with forward", "reason for return", "return signature")):
        targets.append(
            frame.get_by_role("heading", name="Return Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("return label settings", "return rates selection strategy", "return packaging type", "return purpose of shipment")):
        targets.append(
            frame.get_by_role("heading", name="Return Label Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if _has_any(s, ("pickup settings", "pickup start time", "company close time", "package pickup location", "drop-off type", "commodity description")):
        targets.append(
            frame.get_by_role("heading", name="Pickup Settings").locator('xpath=ancestor::*[3]').get_by_role("button", name="Save")
        )
    if not targets:
        targets.append(frame.get_by_role("button", name="Save"))
    return targets


def _describe_settings_persistence(scenario: str) -> str:
    s = (scenario or "").lower()
    if _has_any(s, ("international shipping", "commercial invoice", "purpose of shipment", "terms of sale", "certificate of origin", "pro forma")):
        return (
            "Treat International Shipping as a section-scoped settings flow: verify the International Shipping heading "
            "and its ETD / Commercial Invoice controls, use the section Save button (or the more-settings Save on the "
            "Commercial Invoice page), then reopen the same route and re-check the saved field values."
        )
    if _has_any(s, ("rate settings", "display estimated delivery time", "include duties and taxes", "debug mode", "carrier services", "fallback services")):
        return (
            "Treat Rate Settings as a section-scoped save flow: verify the target checkbox/combobox plus the Rate Settings "
            "Save button, save there, then reopen Settings and re-check the same rate fields."
        )
    if _has_any(s, ("print settings", "outbound label", "commercial invoice copies", "return label copies", "bill of lading")):
        return (
            "Treat Print Settings as a copy-count persistence flow: verify the exact spinbutton plus the Print Settings "
            "Save button, save there, then reopen Settings and confirm the same count persisted."
        )
    if _has_any(s, ("return settings", "generate return with forward", "reason for return", "return signature")):
        return (
            "Treat Return Settings as a section-scoped save flow: verify the main return toggle/combobox fields with the "
            "Return Settings Save button, save there, then reopen and confirm the same values persisted."
        )
    if _has_any(s, ("return label settings", "return rates selection strategy", "return packaging type", "return purpose of shipment")):
        return (
            "Treat Return Label Settings as its own page-level persistence flow: verify the Return Label Settings heading "
            "and its comboboxes, use that page's Save button, then reopen `settings/auto/returnlabel` and re-check the same fields."
        )
    if _has_any(s, ("documents/label", "documents label", "packing slip template", "use customer selected service", "ship after", "single file", "show customer references")):
        return (
            "Treat Documents/Label Settings as a section-scoped save flow: verify the exact checkbox/spinbutton plus the "
            "Documents/Label Settings Save button, then reopen `settings/label/details` and confirm the saved state persisted."
        )
    if _has_any(s, ("notifications", "smtp", "notify customer on fulfillment", "fedex notifications", "email reply to")):
        return (
            "Treat Notifications as a settings persistence flow: verify the exact notification control plus the Notifications "
            "Save button, save there, then reopen the page and confirm the notification fields stayed changed."
        )
    if _has_any(s, ("shop contact", "first name", "last name", "company name", "mid code")):
        return (
            "Treat Shop Contact Details as a form persistence flow: verify the exact text field plus the section Save button, "
            "save there, then reopen and confirm the saved values are still visible."
        )
    if _has_any(s, ("pickup settings", "pickup start time", "company close time", "package pickup location", "drop-off type", "commodity description")):
        return (
            "Treat Pickup Settings as a section-scoped save flow: verify the exact pickup field plus the Pickup Settings "
            "Save button, save there, then reopen and confirm the same values persisted."
        )
    return "Treat Settings as a section-scoped save flow: change a field, use the nearest section Save button, then reopen and verify persistence."


def _product_admin_targets_for_scenario(page, scenario: str):
    s = (scenario or "").lower()
    frame = _app_frame(page)
    targets: list = []
    if _has_any(s, ("search by product", "product search", "app product", "fedex product", "products config")):
        targets.extend([
            frame.get_by_role("button", name="Search and filter results"),
            frame.get_by_placeholder("Search by Product Name (Esc to cancel)"),
        ])
    if _has_any(s, ("signature", "adult signature", "direct signature", "indirect signature", "service default")):
        targets.extend([
            frame.locator('select[name="signatureOptionType"]'),
            frame.get_by_text("FedEx® Delivery Signature", exact=False),
        ])
    if _has_any(s, ("dry ice", "dryice", "dry-ice")):
        targets.extend([
            frame.get_by_role("checkbox", name="Is Dry Ice Needed"),
            frame.get_by_role("spinbutton", name="Dry Ice Weight(kg)"),
        ])
    if _has_any(s, ("alcohol", "licensee", "consumer")):
        targets.extend([
            frame.get_by_role("checkbox", name="Is Alcohol"),
            frame.get_by_label("Alcohol Recipient Type"),
        ])
    if _has_any(s, ("battery", "lithium")):
        targets.extend([
            frame.get_by_role("checkbox", name="Is Battery"),
            frame.get_by_label("Battery Material Type"),
            frame.get_by_label("Battery Packing Type"),
        ])
    if _has_any(s, ("country of origin", "hs code", "sku", "barcode", "tags", "track inventory", "create product", "shopify products", "variant")):
        targets.extend([
            page.locator('input[name="title"]'),
            page.locator('input[name="price"]'),
            page.get_by_role('checkbox', { name: 'Inventory tracked' }),
            page.get_by_role('button', { name: 'SKU' }),
            page.locator('#ShippingCardWeight'),
            page.locator('input[name="tags"]'),
            page.get_by_role('button', { name: 'Country of origin' }),
            page.locator('input[name="harmonizedSystemCode"]'),
            page.get_by_role("link", name="Add product"),
            page.get_by_role("button", name=re.compile(r"add product|save", re.I)),
        ])
    targets.append(page.get_by_role("button", name="Save"))
    targets.append(frame.get_by_role("button", name="Save"))
    return targets


def _product_admin_persistence_targets(page, scenario: str):
    s = (scenario or "").lower()
    targets: list = []
    if _has_any(s, ("create product", "title", "price", "inventory", "sku", "barcode", "weight", "tags", "country of origin", "hs code", "harmonized")):
        targets.extend([
            page.locator('input[name="title"]'),
            page.locator('input[name="price"]'),
            page.locator('input[name="sku"]'),
            page.locator('#ShippingCardWeight'),
            page.locator('input[name="tags"]'),
            page.locator('select[name="countryCodeOfOrigin"]'),
            page.locator('input[name="harmonizedSystemCode"]'),
            page.get_by_role("button", name="Save"),
        ])
    if _has_any(s, ("app product", "fedex product", "signature", "dry ice", "alcohol", "battery")):
        targets.extend([
            frame.get_by_role("button", name="Save"),
            frame.locator('select[name="signatureOptionType"]'),
            frame.get_by_role("checkbox", name="Is Dry Ice Needed"),
            frame.get_by_role("checkbox", name="Is Alcohol"),
            frame.get_by_role("checkbox", name="Is Battery"),
        ])
    return targets


def _shipping_targets_for_scenario(frame, scenario: str):
    s = (scenario or "").lower()
    targets: list = [
        frame.get_by_role("button", name="Search and filter results"),
        frame.get_by_role("table"),
    ]
    if _has_any(s, ("order grid", "filter", "search by order", "date filter", "clear all", "label generated", "pending")):
        targets.extend([
            frame.get_by_role("textbox", name=re.compile(r"Search by order id", re.I)),
            frame.get_by_role("button", name=re.compile(r"Date", re.I)),
            frame.get_by_role("button", name=re.compile(r"Add filter", re.I)),
            frame.get_by_role("button", name="Clear all"),
            frame.get_by_role("tab", name="All"),
            frame.get_by_role("tab", name="Pending"),
            frame.get_by_role("tab", name="Label Generated"),
        ])
    if _has_any(s, ("next order", "previous order", "order navigation")):
        targets.extend([
            frame.get_by_role("button", name=re.compile(r"Previous", re.I)),
            frame.get_by_role("button", name=re.compile(r"Next", re.I)),
        ])
    return targets


def _open_shipping_search_and_filters(page) -> tuple[bool, str]:
    frame = _app_frame(page)
    try:
        button = frame.get_by_role("button", name="Search and filter results").first
        button.wait_for(state="visible", timeout=10_000)
        button.click(timeout=5_000)
        page.wait_for_timeout(500)
        return True, "Opened Shipping search and filter controls."
    except Exception as exc:
        return False, f"Could not open Shipping search and filter controls: {exc}"


def _apply_order_grid_requirements(page, scenario: str) -> tuple[bool, str]:
    frame = _app_frame(page)
    req = _extract_order_grid_requirements(scenario)
    notes: list[str] = []
    try:
        opened, note = _open_shipping_search_and_filters(page)
        notes.append(note)
        if not opened:
            return False, " | ".join(notes)

        if req.search_order_id:
            search_input = frame.get_by_role("textbox", name=re.compile(r"Search by order id", re.I)).first
            search_input.wait_for(state="visible", timeout=10_000)
            search_input.fill(req.search_order_id, timeout=5_000)
            search_input.press("Enter")
            page.wait_for_timeout(1200)
            notes.append(f"Applied Search by Order ID filter with `{req.search_order_id}`.")

        if req.date_filter:
            date_button = frame.get_by_role("button", name=re.compile(r"Date", re.I)).first
            date_button.wait_for(state="visible", timeout=10_000)
            date_button.click(timeout=5_000)
            date_radio = frame.get_by_role("radio", name=req.date_filter).first
            date_radio.wait_for(state="visible", timeout=10_000)
            date_radio.click(timeout=5_000)
            page.wait_for_timeout(1000)
            notes.append(f"Applied Date filter `{req.date_filter}`.")

        if req.add_filter:
            add_filter_button = frame.get_by_role("button", name=re.compile(r"Add filter", re.I)).first
            add_filter_button.wait_for(state="visible", timeout=10_000)
            add_filter_button.click(timeout=5_000)
            menu_item = frame.get_by_role("menuitem", name=req.add_filter).first
            menu_item.wait_for(state="visible", timeout=10_000)
            menu_item.click(timeout=5_000)
            page.wait_for_timeout(500)
            notes.append(f"Opened Add filter `{req.add_filter}`.")

            if req.add_filter == "Name" and req.add_filter_value:
                name_input = frame.get_by_role("textbox", name="Name").first
                name_input.wait_for(state="visible", timeout=10_000)
                name_input.fill(req.add_filter_value, timeout=5_000)
                name_input.press("Enter")
                page.wait_for_timeout(1000)
                notes.append(f"Applied Name filter `{req.add_filter_value}`.")
            elif req.add_filter == "SKU" and req.add_filter_value:
                sku_input = frame.get_by_role("textbox", name="SKU").first
                sku_input.wait_for(state="visible", timeout=10_000)
                sku_input.fill(req.add_filter_value, timeout=5_000)
                sku_input.press("Enter")
                page.wait_for_timeout(1000)
                notes.append(f"Applied SKU filter `{req.add_filter_value}`.")
            elif req.add_filter == "Status" or req.status_filter:
                status_name = req.status_filter or "Pending"
                status_radio = frame.get_by_role("radio", name=status_name).first
                status_radio.wait_for(state="visible", timeout=10_000)
                status_radio.click(timeout=5_000)
                page.wait_for_timeout(1000)
                notes.append(f"Applied Status filter `{status_name}`.")

        if req.status_tab:
            tab = frame.get_by_role("tab", name=req.status_tab).first
            tab.wait_for(state="visible", timeout=10_000)
            tab.click(timeout=5_000)
            page.wait_for_timeout(1000)
            notes.append(f"Switched to Shipping status tab `{req.status_tab}`.")

        table = frame.get_by_role("table").first
        table.wait_for(state="visible", timeout=10_000)

        if req.status_filter == "Label Generated":
            labelled_rows = frame.locator('tbody tr:visible').filter(has_text='label generated')
            if labelled_rows.count() > 0:
                notes.append("Observed visible `label generated` rows after applying the status filter.")

        if req.clear_all:
            clear_all = frame.get_by_role("button", name="Clear all").first
            if clear_all.count() > 0:
                clear_all.wait_for(state="visible", timeout=10_000)
                clear_all.click(timeout=5_000)
                page.wait_for_timeout(1000)
                table.wait_for(state="visible", timeout=10_000)
                notes.append("Cleared all active Shipping grid filters and confirmed the table remained visible.")

        return True, " | ".join(notes)
    except Exception as exc:
        return False, " | ".join(notes + [f"Order-grid filter flow failed: {exc}"])


def _additional_services_targets_for_scenario(frame, scenario: str):
    s = (scenario or "").lower()
    targets: list = [
        frame.get_by_role("heading", name="Additional Services"),
    ]
    if _has_any(s, ("dry ice", "dryice", "dry-ice")):
        dry_ice_section = frame.get_by_role("heading", name="Dry Ice").locator("..").locator("..").locator("..")
        targets.extend([
            frame.get_by_role("heading", name="Dry Ice"),
            frame.locator('input[name="isDryIceEnabled"]'),
            frame.locator('input[name="dryIceWeight"]'),
            frame.locator('select[name="dryIceWeightUnit"]'),
            dry_ice_section.get_by_role("button", name=re.compile(r"save", re.I)),
            frame.locator('text=Dry Ice settings saved'),
        ])
    if _has_any(s, ("fedex one rate", "one rate")):
        one_rate_section = frame.get_by_role("heading", name="FedEx One Rate®").locator("..").locator("..").locator("..")
        targets.extend([
            frame.get_by_role("heading", name="FedEx One Rate®"),
            frame.locator('input[name="isOneRateEnabled"]'),
            frame.locator('label:has-text("Enable FedEx One Rate®")'),
            one_rate_section.get_by_role("button", name=re.compile(r"save", re.I)),
            frame.get_by_text("Fedex One Rate® updated", exact=False),
        ])
    if _has_any(s, ("duties and taxes", "duties & taxes", "checkout rates")):
        additional_services_section = frame.get_by_role("heading", name="Additional Services").locator("..").locator("..").locator("..")
        targets.extend([
            frame.locator('input[name="isDutiesAndTaxesEnabled"]'),
            frame.locator('label:has-text("Include Duties and Taxes in Checkout Rates")'),
            additional_services_section.get_by_role("button", name=re.compile(r"save", re.I)),
            frame.get_by_role("heading", name="International Shipping Settings"),
            frame.get_by_role("heading", name="Rate Settings"),
        ])
    return targets


def _describe_additional_services_persistence(scenario: str) -> str:
    s = (scenario or "").lower()
    if _has_any(s, ("dry ice", "dryice", "dry-ice")):
        return (
            "Treat Dry Ice as a full persistence flow: toggle `Enable Dry Ice Support`, set `Dry Ice Weight` "
            "and `dryIceWeightUnit`, click the Dry Ice section Save button, then reopen Additional Services and "
            "verify the toggle, weight, and unit persisted."
        )
    if _has_any(s, ("fedex one rate", "one rate")):
        return (
            "Treat FedEx One Rate as a section-scoped save flow: verify packaging prerequisites first, toggle "
            "`Enable FedEx One Rate®`, click the FedEx One Rate section Save button, then reopen Additional "
            "Services and verify the toggle still matches."
        )
    if _has_any(s, ("duties and taxes", "duties & taxes", "checkout rates")):
        return (
            "Treat Duties and Taxes as a settings persistence flow: toggle `Include Duties and Taxes in Checkout Rates`, "
            "save from the Additional Services section, then reopen Settings and verify the toggle state with "
            "International Shipping / Rate Settings still available nearby."
        )
    return "Treat Additional Services as a section-scoped settings save flow with reopen-and-verify persistence."


def _wait_for_packaging_settings_ready(page, timeout_ms: int = 30_000, expanded: bool = False) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            candidates = [
                frame.get_by_label("Packing Method"),
                frame.get_by_label("Weight And Dimensions Unit"),
            ]
            if expanded:
                candidates.extend([
                    frame.get_by_role("button", name="Restore FedEx Boxes"),
                    frame.get_by_role("button", name=re.compile(r"add custom box", re.I)),
                    frame.get_by_role("checkbox", name="Use Volumetric Weight For Package Generation"),
                    frame.locator("tbody tr"),
                ])
            else:
                candidates.append(frame.get_by_role("button", name="more settings"))
            for candidate in candidates:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _open_packaging_more_settings(page) -> tuple[bool, str]:
    frame = _app_frame(page)
    if _wait_for_packaging_settings_ready(page, timeout_ms=5_000, expanded=True):
        return True, "Packaging more settings were already visible."
    try:
        card = frame.locator('.Polaris-FormLayout__Item').filter(has=frame.get_by_label("Packing Method")).first
        try:
            if card.count() > 0:
                card.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        if not _click_any([
            card.get_by_role("button", name="more settings"),
            card.get_by_role("link", name="more settings"),
            card.get_by_text("more settings", exact=False),
            frame.get_by_role("button", name="more settings"),
            frame.get_by_role("link", name="more settings"),
            frame.get_by_text("more settings", exact=False),
        ], wait_ms=10_000):
            return False, "Could not open packaging more settings from the Packing Method section."
        page.wait_for_timeout(1500)
        if not _wait_for_packaging_settings_ready(page, timeout_ms=20_000, expanded=True):
            return False, "Packaging more settings did not become ready after opening them."
        return True, "Opened packaging more settings."
    except Exception as exc:
        return False, f"Opening packaging more settings failed: {exc}"


def _extract_request_log_data(page) -> dict[str, object]:
    frame = _app_frame(page)
    try:
        request_heading = frame.get_by_role("heading", name="Request", exact=True)
        request_heading.wait_for(state="visible", timeout=5_000)
        request_pre = frame.get_by_role("dialog").locator("pre").first
        raw = (request_pre.inner_text(timeout=5_000) or "").strip()
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    except Exception:
        return {}


def _common_request_object(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    request_object = payload.get("requestObject")
    if isinstance(request_object, dict):
        return request_object
    return payload


def _extract_request_verification_fields(payload: dict[str, object]) -> dict[str, object]:
    request_object = _common_request_object(payload)
    requested_shipment = request_object.get("requestedShipment") if isinstance(request_object, dict) else {}
    if not isinstance(requested_shipment, dict):
        requested_shipment = {}
    package_items = requested_shipment.get("requestedPackageLineItems")
    first_package = package_items[0] if isinstance(package_items, list) and package_items else {}
    if not isinstance(first_package, dict):
        first_package = {}
    package_special = first_package.get("packageSpecialServices")
    if not isinstance(package_special, dict):
        package_special = {}
    shipment_special = requested_shipment.get("shipmentSpecialServices")
    if not isinstance(shipment_special, dict):
        shipment_special = {}
    alcohol_detail = shipment_special.get("alcoholDetail")
    if not isinstance(alcohol_detail, dict):
        alcohol_detail = {}
    hold_detail = shipment_special.get("holdAtLocationDetail")
    if not isinstance(hold_detail, dict):
        hold_detail = {}
    dimensions = first_package.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {}
    weight = first_package.get("weight")
    if not isinstance(weight, dict):
        weight = {}
    total_weight = requested_shipment.get("totalWeight")
    if not isinstance(total_weight, dict):
        total_weight = {}
    declared = first_package.get("declaredValue")
    if not isinstance(declared, dict):
        declared = {}
    dry_ice_weight = package_special.get("dryIceWeight")
    if not isinstance(dry_ice_weight, dict):
        dry_ice_weight = {}

    return {
        "shipment_special_services": shipment_special.get("specialServiceTypes") or [],
        "signature_option_type": package_special.get("signatureOptionType"),
        "hold_at_location_id": hold_detail.get("locationId"),
        "hold_at_location_type": hold_detail.get("locationType"),
        "declared_value_amount": declared.get("amount"),
        "dimensions": {
            "length": dimensions.get("length"),
            "width": dimensions.get("width"),
            "height": dimensions.get("height"),
            "units": dimensions.get("units"),
        },
        "package_weight": {
            "value": weight.get("value"),
            "units": weight.get("units"),
        },
        "total_weight": total_weight,
        "dry_ice_weight": {
            "value": dry_ice_weight.get("value"),
            "units": dry_ice_weight.get("units"),
        },
        "alcohol_recipient_type": alcohol_detail.get("alcoholRecipientType"),
    }


def _first_dict_from(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _extract_response_verification_fields(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}

    output = payload.get("output")
    if not isinstance(output, dict):
        output = {}

    transaction_shipments = output.get("transactionShipments")
    first_tx = _first_dict_from(transaction_shipments)

    notifications = payload.get("notifications")
    if not isinstance(notifications, list):
        notifications = []
    errors = payload.get("errors")
    if not isinstance(errors, list):
        errors = []

    piece_responses = first_tx.get("pieceResponses")
    first_piece = _first_dict_from(piece_responses)
    package_documents = first_piece.get("packageDocuments")
    if not isinstance(package_documents, list):
        package_documents = []
    shipment_documents = first_tx.get("shipmentDocuments")
    if not isinstance(shipment_documents, list):
        shipment_documents = []

    document_types = []
    for doc in [*package_documents, *shipment_documents]:
        if not isinstance(doc, dict):
            continue
        doc_type = doc.get("contentType") or doc.get("docType") or doc.get("type")
        if doc_type:
            document_types.append(doc_type)

    notification_codes = []
    notification_messages = []
    for item in notifications:
        if not isinstance(item, dict):
            continue
        if item.get("code"):
            notification_codes.append(item.get("code"))
        if item.get("message"):
            notification_messages.append(item.get("message"))

    error_codes = []
    error_messages = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        if item.get("code"):
            error_codes.append(item.get("code"))
        if item.get("message"):
            error_messages.append(item.get("message"))

    operational_detail = first_tx.get("operationalDetail")
    if not isinstance(operational_detail, dict):
        operational_detail = {}
    service_detail = first_tx.get("serviceDetail")
    if not isinstance(service_detail, dict):
        service_detail = {}

    response_summary = {
        "master_tracking_number": first_tx.get("masterTrackingNumber"),
        "tracking_number": first_piece.get("trackingNumber") or first_tx.get("masterTrackingNumber"),
        "service_type": first_tx.get("serviceType") or service_detail.get("serviceType"),
        "ship_date": first_tx.get("shipDatestamp"),
        "packaging_description": operational_detail.get("packagingDescription"),
        "service_description": operational_detail.get("serviceDescription"),
        "document_types": document_types,
        "package_document_count": len(package_documents),
        "shipment_document_count": len(shipment_documents),
        "has_label_url": any(
            isinstance(doc, dict) and bool(doc.get("url"))
            for doc in package_documents
        ),
        "has_encoded_label": any(
            isinstance(doc, dict) and bool(doc.get("encodedLabel"))
            for doc in package_documents
        ),
        "notification_codes": notification_codes,
        "notification_messages": notification_messages[:5],
        "error_codes": error_codes,
        "error_messages": error_messages[:5],
    }
    return response_summary


def _summarize_verification_payload(payload: dict[str, object]) -> dict[str, object]:
    summary = {}
    summary.update(_extract_request_verification_fields(payload))
    summary.update(_extract_response_verification_fields(payload))
    compact = {}
    for key, value in summary.items():
        if value in (None, "", [], {}):
            continue
        compact[key] = value
    return compact


def _wait_for_pickup_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in [
                frame.get_by_role("heading", name="Pickups"),
                frame.get_by_role("button", name="Request Pick Up"),
                frame.get_by_role("table"),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_rates_log_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator('iframe[name="app-iframe"]').count() == 0:
                page.wait_for_timeout(750)
                continue
            frame = _app_frame(page)
            for candidate in [
                frame.get_by_text("Rates Log", exact=False),
                frame.get_by_role("table"),
                frame.get_by_role("button", name="Search and filter results"),
            ]:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _get_latest_rates_log_reference_id(page, app_base: str) -> str:
    try:
        rates_url = _resolve_nav_url(app_base, "rates log")
        if not rates_url or not _goto_shopify_url(page, rates_url):
            return ""
        if not _wait_for_rates_log_ready(page, timeout_ms=20_000):
            return ""
        frame = _app_frame(page)
        rows = frame.get_by_role("table").get_by_role("rowgroup").last.get_by_role("row")
        rows.first.wait_for(state="visible", timeout=8_000)
        ref_cell = rows.first.get_by_role("cell").nth(2)
        return (_text_of(ref_cell) or "").strip()
    except Exception:
        return ""


def _wait_for_shopify_orders_list_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            for candidate in [
                page.get_by_role("columnheader", name="Selection").locator("label"),
                page.get_by_role("button", name="Search"),
                page.get_by_text("Orders", exact=True),
            ]:
                if candidate.count() > 0:
                    candidate.first.wait_for(state="visible", timeout=2_000)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _wait_for_shopify_products_ready(page, timeout_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            for candidate in [
                page.get_by_role("link", name="Add product"),
                page.get_by_role("button", name="Search and filter products"),
                page.locator('[role="grid"]'),
                page.locator('input[name="title"]'),
            ]:
                if candidate.count() > 0:
                    candidate.first.wait_for(state="visible", timeout=2_000)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def _open_product_in_shopify(page, scenario: str, product_title: str = "") -> tuple[bool, str]:
    s = (scenario or "").lower()
    try:
        if page.locator('input[name="title"]').count() > 0:
            page.locator('input[name="title"]').first.wait_for(state="visible", timeout=5_000)
            return True, "Shopify product detail form was already open."
    except Exception:
        pass

    try:
        if _has_any(s, ("create product", "add product", "new product", "250 variants")):
            add_product = page.get_by_role("link", name="Add product").first
            add_product.wait_for(state="visible", timeout=10_000)
            add_product.click(timeout=5_000)
            title_input = page.locator('input[name="title"]').first
            title_input.wait_for(state="visible", timeout=20_000)
            return True, "Opened Shopify Add product form and verified the main product fields."
    except Exception:
        pass

    normalized = (product_title or "").strip()
    if normalized:
        try:
            search_button = page.get_by_role("button", name="Search and filter products").first
            search_button.wait_for(state="visible", timeout=10_000)
            search_button.click(timeout=5_000)
            search_input = page.get_by_placeholder("Searching all products").first
            search_input.wait_for(state="visible", timeout=10_000)
            search_input.fill("")
            page.wait_for_timeout(400)
            search_input.fill(normalized)
            page.wait_for_timeout(1000)
            product_link = page.get_by_role("link", name=normalized, exact=True).first
            product_link.wait_for(state="visible", timeout=10_000)
            product_link.click(timeout=5_000)
            page.wait_for_timeout(1000)
            title_input = page.locator('input[name="title"]').first
            title_input.wait_for(state="visible", timeout=20_000)
            return True, f"Opened Shopify product details for `{normalized}` and verified the editable product fields."
        except Exception:
            pass

    return False, "Shopify Products opened, but a specific product detail form was not opened automatically."


def _select_all_orders_on_current_shopify_page(page) -> bool:
    try:
        header_checkbox = page.get_by_role("columnheader", name="Selection").locator("label").first
        header_checkbox.wait_for(state="visible", timeout=10_000)
        header_checkbox.click(timeout=5_000)
        bulk_actions_more = page.locator('[class*="StickyBulkActions"]').get_by_role("button", name="Actions").first
        bulk_actions_more.wait_for(state="visible", timeout=10_000)
        return True
    except Exception:
        return False


def _bulk_auto_generate_labels_from_orders_list(page) -> bool:
    try:
        if not _wait_for_shopify_orders_list_ready(page, timeout_ms=35_000):
            return False
        if not _select_all_orders_on_current_shopify_page(page):
            return False
        bulk_actions_more = page.locator('[class*="StickyBulkActions"]').get_by_role("button", name="Actions").first
        bulk_actions_more.wait_for(state="visible", timeout=8_000)
        bulk_actions_more.click(timeout=5_000)
        auto_generate = page.get_by_role("link", name="Auto-Generate Labels").first
        auto_generate.wait_for(state="visible", timeout=8_000)
        auto_generate.click(timeout=5_000)
        page.wait_for_load_state("domcontentloaded")
        return _wait_for_shipping_grid_ready(page, timeout_ms=35_000)
    except Exception:
        return False


def _wait_for_bulk_labels_generated(page, timeout_ms: int = 240_000, reload_interval_ms: int = 30_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    frame = _app_frame(page)
    while time.time() < deadline:
        try:
            if frame.get_by_text(re.compile(r"label generated", re.I)).first.is_visible():
                return True
        except Exception:
            pass
        if time.time() >= deadline:
            break
        page.wait_for_timeout(reload_interval_ms)
        try:
            page.reload(wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        if not _wait_for_shipping_grid_ready(page, timeout_ms=20_000):
            page.wait_for_timeout(2_000)
    return False


def _request_pickup_from_shipping(page, app_base: str, order_id: str) -> bool:
    clean_order_id = (order_id or "").replace("#", "").strip()
    if not clean_order_id:
        return False
    shipping_url = _resolve_nav_url(app_base, "shipping")
    if not shipping_url or not _goto_shopify_url(page, shipping_url):
        return False
    if not _wait_for_shipping_grid_ready(page, timeout_ms=35_000):
        return False

    frame = _app_frame(page)
    try:
        search_button = frame.get_by_role("button", name="Search and filter results")
        search_input = frame.get_by_role("textbox", name=re.compile(r"Search by order id", re.I))
        order_table_rows = frame.locator("tr.Polaris-IndexTable__TableRow")

        search_button.wait_for(state="visible", timeout=10_000)
        search_button.click(timeout=5_000)
        search_input.wait_for(state="visible", timeout=10_000)
        search_input.fill("")
        page.wait_for_timeout(500)
        search_input.fill(clean_order_id)
        search_input.press("Enter")
        page.wait_for_timeout(2000)

        normalized = f"#{clean_order_id}"
        order_link = frame.locator("a.orderId", has_text=normalized).first
        row = order_table_rows.filter(has=order_link).first
        row.wait_for(state="visible", timeout=10_000)

        checkbox = row.locator('input[id^="Select-"][type="checkbox"]').first
        checkbox.wait_for(state="attached", timeout=10_000)
        checkbox_id = checkbox.get_attribute("id") or ""
        if checkbox_id:
            label = row.locator(f'label[for="{checkbox_id}"]').first
            if label.count() > 0:
                label.click(force=True, timeout=5_000)
            else:
                checkbox.dispatch_event("click")
        else:
            checkbox.dispatch_event("click")

        if not _click_any([
            frame.get_by_role("button", name="More actions").first,
            frame.get_by_role("button", name="More Actions").first,
        ], wait_ms=10_000):
            return False
        page.wait_for_timeout(1000)
        if not _click_any([
            frame.get_by_role("menuitem", name="Request Pick Up").first,
            frame.locator(".Polaris-ActionList button").filter(has_text="Request Pick Up").first,
            frame.get_by_role("button", name="Request Pick Up").first,
            frame.locator("button").filter(has_text="Request Pick Up").first,
        ], wait_ms=10_000):
            return False
        page.wait_for_timeout(1000)
        _click_any([
            frame.get_by_role("button", name="Yes").first,
        ], wait_ms=5_000)
        return _wait_for_pickup_ready(page, timeout_ms=35_000)
    except Exception:
        return False


def _verify_pickup_row(page, order_id: str, requested_at: float | None = None) -> tuple[bool, str]:
    clean_order_id = (order_id or "").replace("#", "").strip()
    if not clean_order_id:
        return False, ""
    frame = _app_frame(page)
    normalized = f"#{clean_order_id}"
    try:
        row = frame.locator("tr.Polaris-IndexTable__TableRow").filter(has_text=normalized).first
        row.wait_for(state="visible", timeout=15_000)
        pickup_number = (row.locator("td").nth(1).inner_text(timeout=5_000) or "").strip()
        status = (row.locator("td").nth(2).inner_text(timeout=5_000) or "").strip().lower()
        requested_time = (row.locator("td").nth(3).inner_text(timeout=5_000) or "").strip()
        orders = (row.locator("td").nth(5).inner_text(timeout=5_000) or "").strip()
        ok = "success" in status and clean_order_id in orders
        if ok and requested_at and requested_time:
            try:
                now = time.localtime(requested_at)
                parsed = time.strptime(f"{requested_time} {now.tm_year}", "%b %d, %I:%M %p %Y")
                row_ts = time.mktime(parsed)
                ok = abs(row_ts - requested_at) <= 40
            except Exception:
                pass
        return ok, pickup_number
    except Exception:
        return False, ""


def _open_pickup_details_and_verify(page, order_id: str, pickup_number: str = "") -> bool:
    clean_order_id = (order_id or "").replace("#", "").strip()
    if not clean_order_id:
        return False
    frame = _app_frame(page)
    normalized = f"#{clean_order_id}"
    try:
        row = frame.locator("tr.Polaris-IndexTable__TableRow").filter(has_text=normalized).first
        row.wait_for(state="visible", timeout=15_000)
        details_link = row.locator('[data-primary-link="true"]').first
        details_link.click(timeout=5_000)
        heading = frame.get_by_role("heading", name="Pickup Details")
        heading.wait_for(state="visible", timeout=15_000)

        def _detail_value(label_text: str) -> str:
            label = frame.locator("p.Polaris-Text--semibold").filter(has_text=label_text).first
            label.wait_for(state="visible", timeout=10_000)
            value = label.locator('xpath=ancestor::div[contains(@class,"Polaris-Grid-Cell")]').locator('xpath=following-sibling::div[1]').locator("p, button").first
            value.wait_for(state="visible", timeout=10_000)
            return (value.inner_text(timeout=5_000) or "").strip()

        status = _detail_value("Status")
        orders = _detail_value("Orders")
        if "SUCCESS" not in status.upper() or clean_order_id not in orders:
            return False
        if pickup_number:
            confirmation = _detail_value("Pickup Confirmation Number")
            if confirmation != pickup_number:
                return False
        return True
    except Exception:
        return False


def _prime_settings_surface(page, scenario: str) -> tuple[bool, str]:
    if _has_any((scenario or "").lower(), ("additional services", "dry ice", "fedex one rate", "duties and taxes in checkout rates", "duties & taxes", "checkout rates")):
        ok, note = _prime_additional_services_surface(page, scenario)
        if ok:
            return ok, note
    frame = _app_frame(page)
    save_note = _describe_settings_persistence(scenario)
    save_targets = _settings_save_targets_for_scenario(frame, scenario)
    save_seen = False
    for candidate in save_targets:
        try:
            if candidate.count() > 0:
                save_seen = True
                break
        except Exception:
            continue
    for candidate in _settings_targets_for_scenario(frame, scenario):
        try:
            if candidate.count() > 0:
                candidate.first.scroll_into_view_if_needed(timeout=5_000)
                candidate.first.wait_for(state="visible", timeout=5_000)
                route = _settings_route_for_scenario(scenario)
                note = f"Opened `{route}` and scrolled the relevant settings section into view for verification."
                if save_seen:
                    note = f"{note} {save_note}"
                return True, note
        except Exception:
            continue
    return False, "Settings page loaded, but the most relevant subsection was not found automatically."


def _prime_product_admin_surface(page, scenario: str) -> tuple[bool, str]:
    persistence_seen = False
    for candidate in _product_admin_persistence_targets(page, scenario):
        try:
            if candidate.count() > 0:
                persistence_seen = True
                break
        except Exception:
            continue
    for candidate in _product_admin_targets_for_scenario(page, scenario):
        try:
            if candidate.count() > 0:
                candidate.first.scroll_into_view_if_needed(timeout=5_000)
                candidate.first.wait_for(state="visible", timeout=5_000)
                note = "Scrolled the relevant product-admin field or control into view for verification."
                if persistence_seen:
                    note += " Use the exact field value plus the page Save control as persistence proof after reopen/re-check."
                return True, note
        except Exception:
            continue
    return False, "Product admin page loaded, but the most relevant product field or control was not found automatically."


def _prime_additional_services_surface(page, scenario: str) -> tuple[bool, str]:
    frame = _app_frame(page)
    for candidate in _additional_services_targets_for_scenario(frame, scenario):
        try:
            if candidate.count() > 0:
                candidate.first.scroll_into_view_if_needed(timeout=5_000)
                candidate.first.wait_for(state="visible", timeout=5_000)
                return True, _describe_additional_services_persistence(scenario)
        except Exception:
            continue
    return False, "Additional Services page loaded, but the exact section toggle/save controls were not found automatically."


def _prime_shipping_surface(page, scenario: str) -> tuple[bool, str]:
    frame = _app_frame(page)
    for candidate in _shipping_targets_for_scenario(frame, scenario):
        try:
            if candidate.count() > 0:
                candidate.first.scroll_into_view_if_needed(timeout=5_000)
                candidate.first.wait_for(state="visible", timeout=5_000)
                return True, "Scrolled the relevant shipping-grid section or filter control into view for verification."
        except Exception:
            continue
    return False, "Shipping page loaded, but the most relevant grid or filter control was not found automatically."

def _open_order_and_launch_label_flow(page, order_id: str, manual: bool = True, order_name: str = "") -> bool:
    order_url = _shopify_order_url(order_id)
    store_root = _shopify_store_root_url()
    if not store_root and not order_url:
        return False
    opened = False
    preferred_order_ref = order_name or order_id
    if store_root and _goto_shopify_url(page, store_root):
        opened = _search_and_open_shopify_order(page, preferred_order_ref, max_retries=5)
    if not opened and order_url:
        opened = _goto_shopify_url(page, order_url)
    if not opened:
        return False
    option_name = "Generate Label" if manual else "Auto-Generate Label"
    for _attempt in range(3):
        if not _open_shopify_order_more_actions_menu(page, wait_ms=15_000):
            page.wait_for_timeout(1000)
            continue
        clicked = _click_shopify_order_more_actions_item(page, option_name, wait_ms=15_000)
        ready = (
            _wait_for_manual_label_ready(page, timeout_ms=35_000)
            if manual else
            _wait_for_auto_label_ready(page, timeout_ms=35_000)
        )
        if clicked and ready:
            return True
        page.wait_for_timeout(2000)
    return (
        _wait_for_manual_label_ready(page, timeout_ms=10_000)
        if manual else
        _wait_for_auto_label_ready(page, timeout_ms=10_000)
    )


def _open_existing_order_from_app_shipping(page, app_base: str, order_id: str) -> bool:
    clean_order_id = (order_id or "").replace("#", "").strip()
    if not clean_order_id:
        return False
    shipping_url = _resolve_nav_url(app_base, "shipping")
    if not shipping_url or not _goto_shopify_url(page, shipping_url):
        return False
    if not _wait_for_shipping_grid_ready(page, timeout_ms=35_000):
        return False

    frame = _app_frame(page)
    try:
        search_button = frame.get_by_role("button", name="Search and filter results")
        search_input = frame.get_by_role("textbox", name=re.compile(r"Search by order id", re.I))
        orders_table = frame.get_by_role("table")

        search_button.wait_for(state="visible", timeout=10_000)
        search_button.click(timeout=5_000)
        search_input.wait_for(state="visible", timeout=10_000)

        for _attempt in range(3):
            search_input.fill("")
            page.wait_for_timeout(500)
            search_input.fill(clean_order_id)
            search_input.press("Enter")
            page.wait_for_timeout(2000)
            try:
                orders_table.wait_for(state="visible", timeout=5_000)
            except Exception:
                pass
            order_row = frame.locator("tbody tr:visible").filter(has_text=f"#{clean_order_id}").first
            if order_row.count() > 0:
                try:
                    order_row.wait_for(state="visible", timeout=5_000)
                    break
                except Exception:
                    pass
            page.wait_for_timeout(2000)

        if not _click_any([
            frame.locator("a.orderId", has_text=f"#{clean_order_id}").first,
            frame.get_by_role("link", name=re.compile(rf"#?{re.escape(clean_order_id)}")).first,
            frame.get_by_text(f"#{clean_order_id}", exact=False).first,
        ], wait_ms=10_000):
            return False

        return _wait_for_order_summary_ready(page, timeout_ms=35_000)
    except Exception:
        return False


def _open_return_label_from_app_shipping(page, app_base: str, order_id: str) -> bool:
    clean_order_id = (order_id or "").replace("#", "").strip()
    if not clean_order_id or not _open_existing_order_from_app_shipping(page, app_base, clean_order_id):
        return False
    frame = _app_frame(page)
    try:
        if not _click_any([
            frame.locator('[id="returnpacks"]'),
            frame.get_by_text("Return packages", exact=False),
        ], wait_ms=15_000):
            return False
        page.wait_for_timeout(1000)
        if not _click_any([
            frame.get_by_role("button", name="Return Packages", exact=True),
            frame.get_by_text("Return Packages", exact=True),
        ], wait_ms=15_000):
            return False
        return _wait_for_return_label_ready(page, timeout_ms=35_000)
    except Exception:
        return False


def _generate_return_label(page) -> bool:
    frame = _app_frame(page)
    try:
        quantity = frame.locator('input[name="[object Object].returnQuantity"]').first
        quantity.wait_for(state="visible", timeout=20_000)
        quantity.fill("1", timeout=5_000)
        page.wait_for_timeout(3000)
        refresh = frame.get_by_role("button", name="Refresh Rates")
        if refresh.count() > 0:
            refresh.first.click(timeout=5_000)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                radios = frame.locator('input[type="radio"][name]')
                if radios.count() > 0:
                    radios.first.wait_for(state="visible", timeout=2_000)
                    break
            except Exception:
                pass
            retry = frame.get_by_role("button", name="Retry")
            try:
                if retry.count() > 0 and retry.first.is_visible():
                    retry.first.click(timeout=5_000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
        generate = frame.get_by_role("button", name="Generate Return Label")
        generate.wait_for(state="visible", timeout=40_000)
        generate.click(timeout=5_000)
        return _wait_for_order_summary_ready(page, timeout_ms=35_000) or frame.get_by_text("SUCCESS", exact=False).count() > 0
    except Exception:
        return False


def _cancel_label_from_order_summary(page) -> bool:
    try:
        if not _open_app_more_actions_menu(page, wait_ms=10_000):
            return False
        page.wait_for_timeout(1000)
        if not _click_app_more_actions_item(page, "Cancel Label", wait_ms=10_000):
            return False
        page.wait_for_timeout(1500)
        frame = _app_frame(page)
        _click_any([
            frame.get_by_role("button", name="Yes", exact=True),
            frame.get_by_role("button", name="Confirm", exact=False),
            frame.get_by_role("button", name="Cancel Label", exact=False),
        ], wait_ms=5_000)
        page.wait_for_timeout(4000)
        return True
    except Exception:
        return False


def _open_order_and_launch_return_label(page, order_id: str) -> bool:
    order_url = _shopify_order_url(order_id)
    store_root = _shopify_store_root_url()
    if not store_root and not order_url:
        return False
    opened = False
    if store_root and _goto_shopify_url(page, store_root):
        opened = _search_and_open_shopify_order(page, order_id, max_retries=5)
    if not opened and order_url:
        opened = _goto_shopify_url(page, order_url)
    if not opened:
        return False
    if not _click_any([
        page.get_by_role("button", name="More actions").first,
        page.get_by_role("button", name="More Actions").first,
    ], wait_ms=15_000):
        return False
    page.wait_for_timeout(1500)
    clicked = _click_any([
        page.get_by_role("link", name="Generate Return Label", exact=True),
        page.get_by_role("link", name="Generate Return Label", exact=False),
        page.get_by_role("menuitem", name="Generate Return Label", exact=True),
        page.get_by_text("Generate Return Label", exact=True),
        page.get_by_text("Generate Return Label", exact=False),
    ], wait_ms=15_000)
    if clicked:
        page.wait_for_timeout(3500)
    return clicked


def _open_product_in_app(page, product_title: str = "") -> bool:
    if not _wait_for_fedex_products_screen(page):
        return False
    frame = _app_frame(page)
    normalized = product_title.strip()
    loose = normalized.lower().replace("test ", "").replace("product", "").strip() if normalized else ""
    candidates = [c for c in [
        normalized,
        f"1. {normalized}" if normalized else "",
        f"2. {normalized}" if normalized else "",
        "1. Simple Product",
        "2. Simple Product",
        "1. Variable Product Small",
        "Test Msd",
    ] if c]

    for name in candidates:
        if _click_any([
            frame.get_by_role("button", name=name, exact=True),
            frame.get_by_role("button", name=name, exact=False),
            frame.get_by_text(name, exact=False),
        ], wait_ms=5_000):
            page.wait_for_timeout(1200)
            return True

    if loose:
        try:
            buttons = frame.get_by_role("button")
            count = min(buttons.count(), 30)
            for idx in range(count):
                txt = (buttons.nth(idx).inner_text(timeout=2_000) or "").strip()
                if txt and loose in txt.lower():
                    buttons.nth(idx).click(timeout=5_000)
                    page.wait_for_timeout(1200)
                    return True
        except Exception:
            pass

    return False


def _set_product_special_service(page, scenario: str, product_title: str = "") -> tuple[bool, str]:
    frame = _app_frame(page)
    if not _open_product_in_app(page, product_title):
        return False, "Could not open the FedEx app product detail page."

    s = scenario.lower()
    try:
        signature_option = _infer_signature_option(scenario)
        if "signature" in s and signature_option:
            value, label = signature_option
            dropdown = frame.locator('select[name="signatureOptionType"]').first
            dropdown.wait_for(state="visible", timeout=10_000)
            dropdown.select_option(value, timeout=5_000)
            changed = f"Set FedEx Delivery Signature Options to {label}."
        elif "dry ice" in s or "dryice" in s or "dry-ice" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Dry Ice Needed")
            label = frame.get_by_text("Is Dry Ice Needed")
            if not checkbox.is_checked():
                label.click(timeout=5_000)
            weight = frame.get_by_role("spinbutton", name="Dry Ice Weight(kg)")
            weight.wait_for(state="visible", timeout=5_000)
            weight.fill("0.3")
            changed = "Enabled Dry Ice and set Dry Ice Weight to 0.3 kg."
        elif "alcohol" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Alcohol")
            label = frame.get_by_text("Is Alcohol")
            if not checkbox.is_checked():
                label.click(timeout=5_000)
            recipient = "LICENSEE" if "licensee" in s else "CONSUMER"
            frame.get_by_label("Alcohol Recipient Type").select_option(recipient, timeout=5_000)
            changed = f"Enabled Alcohol and set Alcohol Recipient Type to {recipient}."
        elif "battery" in s or "lithium" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Battery")
            label = frame.get_by_text("Is Battery")
            if not checkbox.is_checked():
                label.click(timeout=5_000)
            material = "LITHIUM_METAL" if ("metal" in s or "packed with" in s) else "LITHIUM_ION"
            packing = "PACKED_WITH_EQUIPMENT" if material == "LITHIUM_METAL" else "CONTAINED_IN_EQUIPMENT"
            frame.get_by_label("Battery Material Type").select_option(material, timeout=5_000)
            frame.get_by_label("Battery Packing Type").select_option(packing, timeout=5_000)
            changed = f"Enabled Battery and set material={material}, packing={packing}."
        else:
            return True, "No deterministic product-level special service setup required."

        if not _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ]):
            return False, "Special-service fields were updated, but the Save button was not found."
        page.wait_for_timeout(1000)
        return True, changed
    except Exception as exc:
        return False, f"Product special-service setup failed: {exc}"


def _set_sidedock_signature(page, scenario: str) -> tuple[bool, str]:
    signature_option = _infer_signature_option(scenario)
    if not signature_option:
        return True, "No deterministic SideDock signature setup required."
    value, label = signature_option
    frame = _app_frame(page)
    candidates = [
        frame.locator('div:has(> .Polaris-Labelled__LabelWrapper:has-text("FedEx® Delivery Signature Options")) select').first,
        frame.locator('select[name="signatureOptionType"]').first,
        frame.get_by_label("FedEx® Delivery Signature Options"),
    ]
    try:
        dropdown = None
        for candidate in candidates:
            try:
                if candidate.count() > 0:
                    candidate.wait_for(state="visible", timeout=5_000)
                    dropdown = candidate
                    break
            except Exception:
                continue
        if dropdown is None:
            return False, "FedEx Delivery Signature Options dropdown was not visible in the SideDock."
        dropdown.select_option(value, timeout=5_000)
        page.wait_for_timeout(1000)
        return True, f"Selected SideDock signature option {label}."
    except Exception as exc:
        return False, f"SideDock signature setup failed: {exc}"


def _extract_purpose_of_shipment_override(scenario: str) -> tuple[str, str] | None:
    s = (scenario or "").lower()
    mapping = [
        ("NOT_SOLD", "Not Sold", ("not sold",)),
        ("PERSONAL_EFFECT", "Personal Effect", ("personal effect", "personal effects")),
        ("REPAIR_AND_RETURN", "Repair And Return", ("repair and return",)),
        ("SAMPLE", "Sample", ("sample",)),
        ("SOLD", "Sold", ("sold",)),
        ("GIFT", "Gift", ("gift",)),
    ]
    for value, label, tokens in mapping:
        if any(token in s for token in tokens):
            return value, label
    return None


def _set_sidedock_purpose_of_shipment(page, scenario: str) -> tuple[bool, str]:
    override = _extract_purpose_of_shipment_override(scenario)
    if not override:
        return True, "No deterministic SideDock Purpose Of Shipment override required."
    value, label = override
    frame = _app_frame(page)
    candidates = [
        # Prefer the exact accessible label from the working automation flow.
        frame.get_by_role("combobox", name="Purpose Of Shipment To be used in Commercial Invoice"),
        frame.get_by_label("Purpose Of Shipment To be used in Commercial Invoice"),
        frame.locator('select[name="purposeOfShipmentForAccount"]').first,
        frame.get_by_role("combobox", name="Purpose Of Shipment"),
        frame.get_by_label("Purpose Of Shipment"),
        # Keep the older broad container match only as a last fallback.
        frame.locator('div').filter(
            has=frame.locator('label', has_text='Purpose Of Shipment')
        ).locator('select').first,
    ]
    try:
        dropdown = None
        for candidate in candidates:
            try:
                if candidate.count() > 0:
                    candidate.wait_for(state="visible", timeout=5_000)
                    dropdown = candidate
                    break
            except Exception:
                continue
        if dropdown is None:
            return False, "Purpose Of Shipment dropdown was not visible in the SideDock."
        dropdown.select_option(value, timeout=5_000)
        page.wait_for_timeout(1000)
        return True, f"Selected SideDock Purpose Of Shipment as {label}."
    except Exception as exc:
        return False, f"SideDock Purpose Of Shipment setup failed: {exc}"


def _set_manual_label_sidedock(page, scenario: str) -> tuple[bool, str]:
    notes: list[str] = []
    purpose_ok, purpose_note = _set_sidedock_purpose_of_shipment(page, scenario)
    notes.append(purpose_note)
    if not purpose_ok:
        return False, " | ".join(notes)

    signature_ok, signature_note = _set_sidedock_signature(page, scenario)
    notes.append(signature_note)
    if not signature_ok:
        return False, " | ".join(notes)

    return True, " | ".join(note for note in notes if note)


def _cleanup_product_special_service(page, app_base: str, scenario: str, product_title: str = "") -> tuple[bool, str]:
    s = (scenario or "").lower()
    try:
        if not _goto_fedex_products(page, app_base):
            return False, "Could not return to the FedEx products screen for cleanup."
        if not _open_product_in_app(page, product_title):
            return False, "Could not reopen the product detail page for cleanup."

        frame = _app_frame(page)
        changed = False
        signature_option = _infer_signature_option(scenario)

        if "signature" in s and signature_option:
            dropdown = frame.locator('select[name="signatureOptionType"]').first
            dropdown.wait_for(state="visible", timeout=10_000)
            dropdown.select_option("AS_PER_THE_GENERAL_SETTINGS", timeout=5_000)
            changed = True

        if "dry ice" in s or "dryice" in s or "dry-ice" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Dry Ice Needed")
            label = frame.get_by_text("Is Dry Ice Needed")
            if checkbox.is_checked():
                label.click(timeout=5_000)
                changed = True

        if "alcohol" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Alcohol")
            label = frame.get_by_text("Is Alcohol")
            if checkbox.is_checked():
                label.click(timeout=5_000)
                changed = True

        if "battery" in s or "lithium" in s:
            checkbox = frame.get_by_role("checkbox", name="Is Battery")
            label = frame.get_by_text("Is Battery")
            if checkbox.is_checked():
                label.click(timeout=5_000)
                changed = True

        if not changed:
            return True, "No product-level cleanup was required."

        if not _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ]):
            return False, "Cleanup changes were applied, but the Save button was not found."
        page.wait_for_timeout(1000)
        return True, "Reset product-level special-service settings to their default state."
    except Exception as exc:
        return False, f"Product cleanup failed: {exc}"


def _cleanup_packaging_setup(page, app_base: str, req: PackagingRequirements) -> tuple[bool, str]:
    try:
        settings_url = _resolve_nav_url(app_base, "settings")
        if not settings_url or not _goto_shopify_url(page, settings_url):
            return False, "Could not reopen App Settings for packaging cleanup."
        if not _wait_for_packaging_settings_ready(page, timeout_ms=35_000):
            return False, "App Settings did not become ready for packaging cleanup."
        expanded_ok, expanded_note = _open_packaging_more_settings(page)
        if not expanded_ok:
            return False, expanded_note

        frame = _app_frame(page)
        changed = False

        if req.method or req.unit_label:
            packing_dropdown = frame.get_by_label("Packing Method")
            unit_dropdown = frame.get_by_label("Weight And Dimensions Unit")
            packing_dropdown.wait_for(state="visible", timeout=10_000)
            unit_dropdown.wait_for(state="visible", timeout=10_000)
            packing_dropdown.select_option(label="Weight Based", timeout=5_000)
            unit_dropdown.select_option(label="Pounds & Inches", timeout=5_000)
            changed = True

        if req.box_name:
            restore = frame.get_by_role("button", name="Restore FedEx Boxes")
            if restore.count() > 0:
                restore.first.click(timeout=5_000)
                page.wait_for_timeout(1500)
                changed = True

        if req.use_volumetric is not None:
            checkbox = frame.get_by_role("checkbox", name="Use Volumetric Weight For Package Generation")
            label = frame.get_by_text("Use Volumetric Weight For Package Generation", exact=False)
            if checkbox.count() > 0 and checkbox.is_checked():
                label.click(timeout=5_000)
                changed = True

        if req.stack_products_in_boxes is not None:
            checkbox = frame.get_by_role("checkbox", name="Do You Stack Products In Boxes?")
            label = frame.get_by_text("Do You Stack Products In Boxes?", exact=False)
            if checkbox.count() > 0 and checkbox.is_checked():
                label.click(timeout=5_000)
                changed = True

        if req.additional_weight_enabled:
            checkbox = frame.get_by_label("Add Additional Weight To All Packages")
            if checkbox.count() > 0 and checkbox.is_checked():
                checkbox.uncheck(force=True, timeout=5_000)
                changed = True

        if req.custom_box_name:
            rows = frame.locator("tbody tr")
            total = rows.count()
            deleted = False
            for i in reversed(range(total)):
                row = rows.nth(i)
                row_name = (row.locator("th").text_content(timeout=2_000) or "").strip()
                if row_name == req.custom_box_name:
                    row.locator("button").last.click(timeout=5_000)
                    page.wait_for_timeout(700)
                    deleted = True
            changed = changed or deleted

        if not changed:
            return True, "No packaging cleanup was required."

        if not _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ]):
            return False, "Packaging cleanup changes were applied, but Save was not found."
        page.wait_for_timeout(1000)
        return True, "Reset packaging settings and packaging-box changes to the default cleanup state."
    except Exception as exc:
        return False, f"Packaging cleanup failed: {exc}"


def _cleanup_additional_services(page, app_base: str, scenario: str) -> tuple[bool, str]:
    s = (scenario or "").lower()
    try:
        settings_url = _resolve_nav_url(app_base, "settings")
        if not settings_url or not _goto_shopify_url(page, settings_url):
            return False, "Could not reopen App Settings for Additional Services cleanup."
        if not _wait_for_settings_ready(page, scenario=scenario, timeout_ms=35_000):
            return False, "App Settings did not become ready for Additional Services cleanup."

        frame = _app_frame(page)
        changed = False
        notes: list[str] = []

        if _has_any(s, ("dry ice", "dryice", "dry-ice")):
            heading = frame.get_by_role("heading", name="Dry Ice").first
            heading.wait_for(state="visible", timeout=10_000)
            heading.scroll_into_view_if_needed(timeout=5_000)
            checkbox = frame.locator('input[name="isDryIceEnabled"]').first
            if checkbox.count() > 0 and checkbox.is_checked():
                label = frame.locator('label:has-text("Enable Dry Ice Support")').first
                label.click(timeout=5_000)
                changed = True
            save_btn = frame.get_by_role("heading", name="Dry Ice").locator("..").locator("..").locator("..").get_by_role("button", name=re.compile(r"save", re.I)).first
            if changed:
                save_btn.click(timeout=5_000)
                page.wait_for_timeout(1000)
            notes.append("Reset Dry Ice settings to disabled.")

        if _has_any(s, ("fedex one rate", "one rate")):
            heading = frame.get_by_role("heading", name="FedEx One Rate®").first
            heading.wait_for(state="visible", timeout=10_000)
            heading.scroll_into_view_if_needed(timeout=5_000)
            checkbox = frame.locator('input[name="isOneRateEnabled"]').first
            local_changed = False
            if checkbox.count() > 0 and checkbox.is_checked():
                label = frame.locator('label:has-text("Enable FedEx One Rate®")').first
                label.click(timeout=5_000)
                changed = True
                local_changed = True
            save_btn = frame.get_by_role("heading", name="FedEx One Rate®").locator("..").locator("..").locator("..").get_by_role("button", name=re.compile(r"save", re.I)).first
            if local_changed:
                save_btn.click(timeout=5_000)
                page.wait_for_timeout(1000)
            notes.append("Reset FedEx One Rate to disabled.")

        if _has_any(s, ("duties and taxes", "duties & taxes", "checkout rates")):
            heading = frame.get_by_role("heading", name="Additional Services").first
            heading.wait_for(state="visible", timeout=10_000)
            heading.scroll_into_view_if_needed(timeout=5_000)
            checkbox = frame.locator('input[name="isDutiesAndTaxesEnabled"]').first
            local_changed = False
            if checkbox.count() > 0 and checkbox.is_checked():
                label = frame.locator('label:has-text("Include Duties and Taxes in Checkout Rates")').first
                label.click(timeout=5_000)
                changed = True
                local_changed = True
            save_btn = frame.get_by_role("heading", name="Additional Services").locator("..").locator("..").locator("..").get_by_role("button", name=re.compile(r"save", re.I)).first
            if local_changed:
                save_btn.click(timeout=5_000)
                page.wait_for_timeout(1000)
            notes.append("Reset Duties and Taxes in checkout rates to disabled.")

        if not notes:
            return True, "No Additional Services cleanup was required."
        if not changed:
            return True, "Additional Services were already in their default cleanup state."
        return True, " ".join(notes)
    except Exception as exc:
        return False, f"Additional Services cleanup failed: {exc}"


def _infer_packaging_method_and_unit(scenario: str) -> tuple[str, str]:
    req = _extract_packaging_requirements(scenario)
    method = req.method or "Weight Based"
    unit = req.unit_label or "Pounds & Inches"
    return method, unit


def _configure_packaging_settings(page, scenario: str, req: PackagingRequirements | None = None) -> tuple[bool, str]:
    frame = _app_frame(page)
    try:
        req = req or _extract_packaging_requirements(scenario)
        method = req.method or "Weight Based"
        unit = req.unit_label or "Pounds & Inches"
        packing_dropdown = frame.get_by_label("Packing Method")
        unit_dropdown = frame.get_by_label("Weight And Dimensions Unit")
        packing_dropdown.wait_for(state="visible", timeout=10_000)
        packing_dropdown.select_option(label=method, timeout=5_000)
        unit_dropdown.wait_for(state="visible", timeout=10_000)
        unit_dropdown.select_option(label=unit, timeout=5_000)
        _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ])
        page.wait_for_timeout(1000)
        note = f"Set packaging method to {method} and units to {unit}."
        if req.box_name:
            note += f" Target carrier box: {req.box_name}."
        return True, note
    except Exception as exc:
        return False, f"Packaging settings setup failed: {exc}"


def _configure_product_dimensions(page, scenario: str, product_title: str = "", req: PackagingRequirements | None = None) -> tuple[bool, str]:
    frame = _app_frame(page)
    try:
        req = req or _extract_packaging_requirements(scenario)
        if not _open_product_in_app(page, product_title):
            return False, "Could not open the product detail page for packaging setup."
        dims = (
            req.length or "10",
            req.width or "10",
            req.height or "10",
            req.weight or "2",
        )
        frame.locator('input[name="length"]').first.fill(dims[0], timeout=5_000)
        frame.locator('input[name="width"]').first.fill(dims[1], timeout=5_000)
        frame.locator('input[name="height"]').first.fill(dims[2], timeout=5_000)
        weight = frame.get_by_label(re.compile(r"weight", re.I)).first
        weight.fill(dims[3], timeout=5_000)
        if not _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ]):
            return False, "Product dimensions were updated, but Save was not found."
        page.wait_for_timeout(1000)
        return True, f"Set product dimensions to {dims[0]}x{dims[1]}x{dims[2]} and weight to {dims[3]}."
    except Exception as exc:
        return False, f"Product dimension setup failed: {exc}"


def _configure_packaging_advanced(page, req: PackagingRequirements) -> tuple[bool, str]:
    frame = _app_frame(page)
    try:
        changed = False
        notes: list[str] = []
        if req.use_volumetric is not None:
            checkbox = frame.get_by_role("checkbox", name="Use Volumetric Weight For Package Generation")
            label = frame.get_by_text("Use Volumetric Weight For Package Generation", exact=False)
            if checkbox.count() > 0:
                is_checked = checkbox.is_checked()
                if is_checked != req.use_volumetric:
                    label.click(timeout=5_000)
                    changed = True
                notes.append(
                    "Enabled volumetric weight for package generation."
                    if req.use_volumetric else
                    "Disabled volumetric weight for package generation."
                )
        if req.stack_products_in_boxes is not None:
            checkbox = frame.get_by_role("checkbox", name="Do You Stack Products In Boxes?")
            label = frame.get_by_text("Do You Stack Products In Boxes?", exact=False)
            if checkbox.count() > 0:
                is_checked = checkbox.is_checked()
                if is_checked != req.stack_products_in_boxes:
                    label.click(timeout=5_000)
                    changed = True
                notes.append(
                    "Enabled stacking products in boxes."
                    if req.stack_products_in_boxes else
                    "Disabled stacking products in boxes."
                )
        if req.max_weight:
            max_weight_input = frame.get_by_label("Max Weight")
            if max_weight_input.count() > 0:
                max_weight_input.first.fill(req.max_weight, timeout=5_000)
                changed = True
                notes.append(f"Set packaging Max Weight to {req.max_weight}.")
        if req.additional_weight_enabled is not None:
            checkbox = frame.get_by_label("Add Additional Weight To All Packages")
            if checkbox.count() > 0:
                is_checked = checkbox.is_checked()
                if is_checked != req.additional_weight_enabled:
                    if req.additional_weight_enabled:
                        checkbox.check(force=True, timeout=5_000)
                    else:
                        checkbox.uncheck(force=True, timeout=5_000)
                    changed = True
                notes.append(
                    "Enabled additional weight for all packages."
                    if req.additional_weight_enabled else
                    "Disabled additional weight for all packages."
                )
        if req.additional_weight_enabled and req.additional_weight_mode:
            mode_dropdown = frame.get_by_label("Additional Weight Options")
            if mode_dropdown.count() > 0:
                try:
                    mode_dropdown.select_option(label=req.additional_weight_mode, timeout=5_000)
                except Exception:
                    mode_dropdown.select_option(req.additional_weight_mode, timeout=5_000)
                changed = True
                notes.append(f"Set Additional Weight Options to {req.additional_weight_mode}.")
        if req.additional_weight_enabled and req.additional_weight_value:
            value_candidates = [
                frame.get_by_label("Constant Weight To Be Added"),
                frame.get_by_label("Percentage Of Package Weight To Be Added"),
            ]
            for candidate in value_candidates:
                try:
                    if candidate.count() > 0:
                        candidate.first.wait_for(state="visible", timeout=2_000)
                        candidate.first.fill(req.additional_weight_value, timeout=5_000)
                        changed = True
                        notes.append(f"Set additional weight value to {req.additional_weight_value}.")
                        break
                except Exception:
                    continue
        if req.box_name:
            restore = frame.get_by_role("button", name="Restore FedEx Boxes")
            if restore.count() > 0:
                restore.first.click(timeout=5_000)
                page.wait_for_timeout(1500)
                changed = True

            rows = frame.locator("tbody tr")
            total = rows.count()
            occurrence_map: dict[str, int] = {}
            rows_to_delete: list[int] = []
            for i in range(total):
                row = rows.nth(i)
                box_name = (row.locator("th").text_content(timeout=2_000) or "").strip()
                occurrence_map[box_name] = occurrence_map.get(box_name, 0) + 1
                current_index = occurrence_map[box_name]
                if box_name != req.box_name or current_index != 1:
                    rows_to_delete.append(i)

            for index in reversed(rows_to_delete):
                row = rows.nth(index)
                initial_count = rows.count()
                row.locator("button").last.click(timeout=5_000)
                page.wait_for_timeout(500)
                if rows.count() >= initial_count:
                    page.wait_for_timeout(1000)
                changed = True
            notes.append(f"Restricted carrier boxes to {req.box_name}.")

        if req.custom_box_name:
            add_custom = frame.get_by_role("button", name=re.compile(r"add custom box", re.I))
            add_custom.first.wait_for(state="visible", timeout=10_000)
            add_custom.first.click(timeout=5_000)
            dialog = frame.get_by_role("dialog", name=re.compile(r"add package", re.I))
            dialog.wait_for(state="visible", timeout=10_000)
            dialog.get_by_label("Name").fill(req.custom_box_name, timeout=5_000)
            inner = (
                req.length or "10",
                req.width or "10",
                req.height or "10",
            )
            outer = (
                str(float(inner[0]) + 2),
                str(float(inner[1]) + 2),
                str(float(inner[2]) + 2),
            )
            dialog.get_by_label("Length").nth(0).fill(inner[0], timeout=5_000)
            dialog.get_by_label("Width").nth(0).fill(inner[1], timeout=5_000)
            dialog.get_by_label("Height").nth(0).fill(inner[2], timeout=5_000)
            dialog.get_by_label("Length").nth(1).fill(outer[0], timeout=5_000)
            dialog.get_by_label("Width").nth(1).fill(outer[1], timeout=5_000)
            dialog.get_by_label("Height").nth(1).fill(outer[2], timeout=5_000)
            dialog.get_by_label("Box Weight When Empty").fill(req.weight or "1", timeout=5_000)
            dialog.get_by_label("Max Weight").fill(req.weight or "20", timeout=5_000)
            dialog.get_by_role("button", name="Add Box").click(timeout=5_000)
            page.wait_for_timeout(1500)
            changed = True
            notes.append(f"Added custom box {req.custom_box_name} for packaging verification.")

        if not changed:
            return True, "No additional packaging configuration was required in more settings."

        _click_any([
            frame.get_by_role("button", name="Save", exact=True),
            frame.get_by_text("Save", exact=True),
        ])
        page.wait_for_timeout(1000)
        return True, " ".join(notes)
    except Exception as exc:
        return False, f"Packaging advanced setup failed: {exc}"


def _run_prerequisite_orchestration(
    page,
    scenario: str,
    plan: ScenarioPrerequisitePlan,
    ctx: str,
    app_base: str,
    result: ScenarioResult,
    stop_flag: "Callable[[], bool] | None" = None,
    progress_cb: "Callable[[int, str], None] | None" = None,
) -> bool:
    """
    Deterministically prepare the scenario before the agentic loop when possible.
    Returns True if the browser was placed at the intended starting point and the generic
    navigation bootstrap should be skipped.
    """
    setup_info = _parse_setup_context(ctx)
    order_id = setup_info.get("order_id", "")
    order_name = setup_info.get("order_name", "")
    product_title = setup_info.get("product_title", "")
    order_ref = order_name or (f"#{order_id}" if order_id else "")
    s = scenario.lower()

    def _emit_setup(desc: str) -> None:
        if progress_cb:
            progress_cb(3, desc)

    if _is_stop_requested(stop_flag):
        return False

    if plan.category == "product_special_service":
        try:
            if not _goto_fedex_products(page, app_base):
                _record_setup_step(result, "setup", "Could not reach the live FedEx products UI.", target="AppProducts", success=False)
                return False
            if _is_stop_requested(stop_flag):
                return False
            ok, note = _set_product_special_service(page, scenario, product_title)
            _record_setup_step(result, "setup", note, target=product_title or "AppProducts", success=ok)
            if not ok or not order_id:
                return False
            if _is_stop_requested(stop_flag):
                return False
            launched = _open_order_and_launch_label_flow(page, order_id, manual=True, order_name=order_name)
            _record_setup_step(
                result,
                "setup",
                "Opened the freshly prepared Shopify order and launched manual label generation."
                if launched else
                "Prepared the product, but could not launch manual label generation automatically.",
                target=setup_info.get("order_name", order_id),
                success=launched,
            )
            return launched
        except Exception as exc:
            _record_setup_step(result, "setup", f"Product special-service orchestration failed: {exc}", success=False)
            return False

    if plan.category == "packaging_flow":
        try:
            packaging_req = _extract_packaging_requirements(f"{scenario}\n\n{ctx}")
            if any([packaging_req.method, packaging_req.unit_label, packaging_req.length, packaging_req.width, packaging_req.height, packaging_req.weight, packaging_req.box_name]):
                _append_evidence_note(
                    result,
                    "packaging_requirements="
                    f"method:{packaging_req.method or '-'}; "
                    f"unit:{packaging_req.unit_label or '-'}; "
                    f"dims:{'x'.join(v for v in [packaging_req.length, packaging_req.width, packaging_req.height] if v) or '-'}; "
                    f"weight:{packaging_req.weight or '-'}; "
                    f"box:{packaging_req.box_name or '-'}",
                )
            settings_url = _resolve_nav_url(app_base, "settings")
            if not settings_url or not _goto_shopify_url(page, settings_url):
                _record_setup_step(result, "setup", "Could not open App Settings for packaging setup.", target="settings", success=False)
                return False
            if _is_stop_requested(stop_flag):
                return False
            if not _wait_for_packaging_settings_ready(page, timeout_ms=35_000):
                _record_setup_step(result, "setup", "App Settings did not become ready for packaging setup.", target="settings", success=False)
                return False
            if _is_stop_requested(stop_flag):
                return False
            ok_settings, note_settings = _configure_packaging_settings(page, scenario, packaging_req)
            _record_setup_step(result, "setup", note_settings, target="settings", success=ok_settings)
            if not ok_settings:
                return False
            if _is_stop_requested(stop_flag):
                return False
            expanded_ok, expanded_note = _open_packaging_more_settings(page)
            _record_setup_step(result, "setup", expanded_note, target="PackagingMoreSettings", success=expanded_ok)
            if not expanded_ok:
                return False
            if _is_stop_requested(stop_flag):
                return False
            ok_advanced, note_advanced = _configure_packaging_advanced(page, packaging_req)
            _record_setup_step(
                result,
                "setup",
                note_advanced,
                target=packaging_req.box_name or packaging_req.custom_box_name or "PackagingAdvanced",
                success=ok_advanced,
            )
            if not ok_advanced:
                return False

            if not _goto_fedex_products(page, app_base):
                _record_setup_step(result, "setup", "Could not reach FedEx Products for packaging product setup.", target="AppProducts", success=False)
                return False
            if _is_stop_requested(stop_flag):
                return False
            ok_product, note_product = _configure_product_dimensions(page, scenario, product_title, packaging_req)
            _record_setup_step(result, "setup", note_product, target=product_title or "AppProducts", success=ok_product)
            if not ok_product or not order_id:
                return False

            if _is_stop_requested(stop_flag):
                return False
            launched = _open_order_and_launch_label_flow(page, order_id, manual=True, order_name=order_name)
            _record_setup_step(
                result,
                "setup",
                "Configured packaging + product dimensions and launched manual label generation."
                if launched else
                "Packaging setup completed, but automatic launch into manual label generation failed.",
                target=setup_info.get("order_name", order_id),
                success=launched,
            )
            return launched
        except Exception as exc:
            _record_setup_step(result, "setup", f"Packaging orchestration failed: {exc}", success=False)
            return False

    if plan.category == "product_admin":
        try:
            if _has_any(s, ("app product", "fedex product", "product signature", "dry ice", "alcohol", "battery")):
                opened = _goto_fedex_products(page, app_base)
                note = "Could not reach FedEx App Products for product-level configuration verification."
                if opened:
                    _, note = _prime_product_admin_surface(page, scenario)
                _record_setup_step(
                    result,
                    "setup",
                    note if opened else note,
                    target="AppProducts",
                    success=opened,
                )
                return opened

            shopify_products_url = _resolve_nav_url(app_base, "shopifyproducts")
            opened = bool(shopify_products_url and _goto_shopify_url(page, shopify_products_url))
            if opened:
                opened = _wait_for_shopify_products_ready(page, timeout_ms=35_000)
            note = "Could not open Shopify Products for product creation/config verification."
            if opened:
                opened_detail, detail_note = _open_product_in_shopify(page, scenario, product_title)
                _, prime_note = _prime_product_admin_surface(page, scenario)
                note = f"{detail_note} {prime_note}".strip()
            _record_setup_step(
                result,
                "setup",
                note,
                target="ShopifyProducts",
                success=opened,
            )
            return opened
        except Exception as exc:
            _record_setup_step(result, "setup", f"Product admin orchestration failed: {exc}", success=False)
            return False

    if plan.category == "checkout_rates":
        try:
            storefront_root = _shopify_storefront_root_url()
            if not storefront_root:
                _record_setup_step(
                    result,
                    "setup",
                    "Could not resolve the Shopify storefront URL from STORE.",
                    target="Storefront",
                    success=False,
                )
                return False

            if _has_any(s, ("signature", "dry ice", "dryice", "dry-ice", "alcohol", "battery", "lithium")):
                product_ready = _goto_fedex_products(page, app_base)
                _record_setup_step(
                    result,
                    "setup",
                    "Opened FedEx App Products to apply the storefront product-level configuration."
                    if product_ready else
                    "Could not reach FedEx App Products before storefront checkout setup.",
                    target="AppProducts",
                    success=product_ready,
                )
                if not product_ready:
                    return False
                configured, config_note = _set_product_special_service(page, scenario, product_title or "Simple packaging product")
                _record_setup_step(
                    result,
                    "setup",
                    config_note,
                    target=product_title or "Simple packaging product",
                    success=configured,
                )
                if not configured:
                    return False

            wants_rates_log = _has_any(s, ("rates log", "rate log", "request log", "special service", "signature"))
            if wants_rates_log:
                baseline_ref = _get_latest_rates_log_reference_id(page, app_base)
                setattr(page, "_sav_rates_log_baseline_ref", baseline_ref)
                _record_setup_step(
                    result,
                    "setup",
                    f"Captured the current latest Rates Log reference before storefront checkout: {baseline_ref or '(none found)'}",
                    target="Rates Log baseline",
                    success=True,
                )

            product_title = setup_info.get("product_title", "") or "Simple packaging product"
            product_handle = _slugify_storefront_handle(product_title) or "simple-packaging-product"
            opened, note = _prepare_storefront_checkout(
                page,
                storefront_root=storefront_root,
                product_handle=product_handle,
                address_type=plan.address_type,
                stop_flag=stop_flag,
                progress_cb=lambda text: _emit_setup(text),
            )
            _record_setup_step(
                result,
                "setup",
                note,
                target=f"{storefront_root}/products/{product_handle}",
                success=opened,
            )
            if not opened:
                return False

            completed, checkout_note, checkout_summary = _complete_storefront_checkout(
                page,
                scenario=scenario,
                stop_flag=stop_flag,
                progress_cb=lambda text: _emit_setup(text),
            )
            setattr(page, "_sav_last_storefront_checkout", checkout_summary)
            _record_setup_step(
                result,
                "setup",
                checkout_note,
                target="Storefront checkout",
                success=completed,
            )
            if not completed:
                return False

            if wants_rates_log:
                captured, rates_note, rates_evidence = _capture_rates_log_evidence(
                    page,
                    scenario=scenario,
                    app_base=app_base,
                    stop_flag=stop_flag,
                    progress_cb=lambda text: _emit_setup(text),
                )
                setattr(page, "_sav_last_storefront_rates_log", rates_evidence)
                _record_setup_step(
                    result,
                    "setup",
                    rates_note,
                    target="Rates Log",
                    success=captured,
                )
                return captured

            return True
        except Exception as exc:
            _record_setup_step(result, "setup", f"Checkout/storefront orchestration failed: {exc}", success=False)
            return False

    if plan.category in ("manual_label_sidedock", "label_generation") and order_id:
        use_manual = plan.label_flow != "auto"
        if _is_stop_requested(stop_flag):
            return False
        _emit_setup(
            f"Searching Shopify order {order_ref or order_id} and opening the {plan.label_flow} label flow…"
        )
        launched = _open_order_and_launch_label_flow(page, order_id, manual=use_manual, order_name=order_name)
        _record_setup_step(
            result,
            "setup",
            f"Opened the fresh Shopify order and launched the {plan.label_flow} label workflow automatically."
            if launched else
            "Fresh order exists, but automatic launch into the label workflow failed.",
            target=order_name or order_id,
            success=launched,
        )
        if launched and use_manual and plan.category == "label_generation":
            if _is_stop_requested(stop_flag):
                return False
            _emit_setup(
                f"Order {order_ref or order_id} opened — completing Generate Packages, rates, and Generate Label…"
            )
            completed = _complete_manual_label_generation(
                page,
                stop_flag=stop_flag,
                progress_cb=lambda text: _emit_progress(4, text),
            )
            _record_setup_step(
                result,
                "setup",
                "Completed Generate Packages → Get Rates → Generate Label and reached Order Summary."
                if completed else
                "Manual label flow opened, but deterministic completion to Order Summary did not finish automatically.",
                target=order_name or order_id,
                success=completed,
            )
            return completed
        if launched and plan.category == "manual_label_sidedock":
            if _is_stop_requested(stop_flag):
                return False
            sidedock_ok, note = _set_manual_label_sidedock(page, scenario)
            _record_setup_step(
                result,
                "setup",
                note,
                target="Manual-label SideDock",
                success=sidedock_ok,
            )
            return sidedock_ok
        return launched

    if plan.category == "bulk_labels":
        try:
            if not _goto_shopify_url(page, _resolve_nav_url(app_base, "orders")):
                raise RuntimeError("Shopify account selection blocked Orders list access")
            if _is_stop_requested(stop_flag):
                return False
            if not _wait_for_shopify_orders_list_ready(page, timeout_ms=35_000):
                raise RuntimeError("Shopify Orders list did not become ready for bulk selection")
            if _is_stop_requested(stop_flag):
                return False
            launched = _bulk_auto_generate_labels_from_orders_list(page)
            if _is_stop_requested(stop_flag):
                return False
            completed = launched and _wait_for_bulk_labels_generated(page)
            _record_setup_step(
                result,
                "setup",
                "Selected visible Shopify orders, triggered Auto-Generate Labels, and observed 'label generated' in the app Shipping grid."
                if completed else
                "Opened Shopify Orders list, but deterministic bulk completion did not fully reach 'label generated'.",
                target="Orders",
                success=completed,
            )
            return completed
        except Exception as exc:
            _record_setup_step(result, "setup", f"Bulk orchestration failed to open Orders list: {exc}", success=False)
            return False

    if plan.category == "settings_or_grid":
        target_path = "shipping"
        if _has_any(s, ("settings", "configuration", "configure", "save setting", "general settings", "additional services", "packages")):
            target_path = _settings_route_for_scenario(scenario)
        elif _has_any(s, ("pickup", "schedule pickup")):
            target_path = "pickup"
        elif _has_any(s, ("rates log", "rate log", "logs")):
            target_path = "rates log"
        try:
            if not _goto_shopify_url(page, _resolve_nav_url(app_base, target_path)):
                raise RuntimeError(f"Shopify account selection blocked {target_path} access")
            if _is_stop_requested(stop_flag):
                return False
            ready = True
            note = f"Opened {target_path} directly for prerequisite-free verification."
            if target_path.startswith("settings"):
                ready = _wait_for_settings_ready(page, scenario=scenario, timeout_ms=35_000)
                if ready:
                    _, note = _prime_settings_surface(page, scenario)
            elif target_path == "pickup":
                if order_id:
                    requested_at = time.time()
                    requested = _request_pickup_from_shipping(page, app_base, order_id)
                    pickup_number = ""
                    row_verified = False
                    details_verified = False
                    if requested:
                        row_verified, pickup_number = _verify_pickup_row(page, order_id, requested_at=requested_at)
                        if row_verified:
                            _record_setup_step(
                                result,
                                "setup",
                                f"Verified pickup row for the order in Pickups with confirmation number {pickup_number or '(not found)'}.",
                                target=setup_info.get("order_name", order_id),
                                success=True,
                            )
                            details_verified = _open_pickup_details_and_verify(page, order_id, pickup_number)
                            _record_setup_step(
                                result,
                                "setup",
                                "Opened Pickup Details and verified confirmation number, status, and order id."
                                if details_verified else
                                "Pickup row was found, but Pickup Details verification did not fully pass.",
                                target=setup_info.get("order_name", order_id),
                                success=details_verified,
                            )
                    ready = requested and row_verified and details_verified
                    note = (
                        "Requested pickup for the labeled order and verified the pickup row plus Pickup Details."
                        if ready else
                        "Could not complete deterministic pickup request and verification flow from the Shipping grid."
                    )
                else:
                    ready = _wait_for_pickup_ready(page, timeout_ms=35_000)
                    if ready:
                        note = "Opened Pickups and waited for the pickup table/details UI to be ready."
            elif target_path == "rates log":
                ready = _wait_for_rates_log_ready(page, timeout_ms=35_000)
                if ready:
                    note = "Opened Rates Log and waited for the grid/search controls to be ready."
            else:
                ready = _wait_for_shipping_grid_ready(page, timeout_ms=35_000)
                if ready and _has_any(s, ("next order", "previous order", "next/previous", "order navigation")) and order_id:
                    opened = _open_existing_order_from_app_shipping(page, app_base, order_id)
                    ready = opened
                    note = (
                        "Opened the requested order directly in Order Summary for next/previous navigation verification."
                        if opened else
                        "Opened Shipping, but could not jump directly into Order Summary for navigation verification."
                    )
                elif ready and _has_any(s, ("order grid", "filter", "search by order", "date filter", "add filter", "clear all", "pending", "label generated", "status filter", "sku filter", "name filter")):
                    ready, note = _apply_order_grid_requirements(page, scenario)
                elif ready:
                    _, note = _prime_shipping_surface(page, scenario)
            _record_setup_step(result, "setup", note, target=target_path, success=ready)
            return ready
        except Exception as exc:
            _record_setup_step(result, "setup", f"Could not open {target_path}: {exc}", target=target_path, success=False)
            return False

    if plan.category == "existing_label_flow":
        if order_id and ("return label" in s or "generate return" in s):
            if _is_stop_requested(stop_flag):
                return False
            launched = _open_return_label_from_app_shipping(page, app_base, order_id)
            if not launched:
                launched = _open_order_and_launch_return_label(page, order_id)
            if _is_stop_requested(stop_flag):
                return False
            generated = launched and _generate_return_label(page)
            _record_setup_step(
                result,
                "setup",
                "Opened the order from the app Shipping grid and generated the return label automatically."
                if generated else
                "Return-label scenario still needs manual completion after opening the return-label flow.",
                target=setup_info.get("order_name", order_id),
                success=generated,
            )
            return generated
        if order_id and _has_any(s, ("cancel label", "cancel the label", "after cancellation", "after label cancel")):
            if _is_stop_requested(stop_flag):
                return False
            opened = _open_existing_order_from_app_shipping(page, app_base, order_id)
            cancelled = opened and _cancel_label_from_order_summary(page)
            _record_setup_step(
                result,
                "setup",
                "Opened the labeled order in app Order Summary and triggered Cancel Label."
                if cancelled else
                "Could not complete deterministic cancel-label setup from Order Summary.",
                target=setup_info.get("order_name", order_id),
                success=cancelled,
            )
            return cancelled
        if order_id and _has_any(s, ("regenerate", "re-generate", "updated address", "address update", "updated address")):
            if _is_stop_requested(stop_flag):
                return False
            opened = _open_existing_order_from_app_shipping(page, app_base, order_id)
            cancelled = opened and _cancel_label_from_order_summary(page)
            if _is_stop_requested(stop_flag):
                return False
            relaunched = cancelled and _open_order_and_launch_label_flow(page, order_id, manual=True)
            _record_setup_step(
                result,
                "setup",
                "Cancelled the existing label and relaunched manual label generation for regeneration verification."
                if relaunched else
                "Could not complete deterministic regenerate-label setup.",
                target=setup_info.get("order_name", order_id),
                success=relaunched,
            )
            return relaunched
        if order_id:
            if _is_stop_requested(stop_flag):
                return False
            opened = _open_existing_order_from_app_shipping(page, app_base, order_id)
            _record_setup_step(
                result,
                "setup",
                "Opened the labeled order directly in the app Order Summary."
                if opened else
                "Could not open the labeled order directly in the app Order Summary.",
                target=setup_info.get("order_name", order_id),
                success=opened,
            )
            return opened
        try:
            if not _goto_shopify_url(page, _resolve_nav_url(app_base, "shipping")):
                raise RuntimeError("Shopify account selection blocked Shipping grid access")
            _record_setup_step(result, "setup", "Opened the app Shipping grid so verification can start from labeled orders.", target="shipping")
            return True
        except Exception as exc:
            _record_setup_step(result, "setup", f"Could not open Shipping grid: {exc}", target="shipping", success=False)
            return False

    if plan.category == "high_variant_product":
        try:
            if not _goto_shopify_url(page, _resolve_nav_url(app_base, "shopifyproducts")):
                raise RuntimeError("Shopify account selection blocked Shopify Products access")
            _record_setup_step(result, "setup", "Opened Shopify Products for high-variant product verification.", target="shopifyproducts")
            return True
        except Exception as exc:
            _record_setup_step(result, "setup", f"Could not open Shopify Products: {exc}", target="shopifyproducts", success=False)
            return False

    return False


def _plan_scenario(
    scenario: str,
    app_url: str,
    ctx: str,
    expert_insight: str,
    claude: ChatAnthropic,
    feedback_context: str = "",
) -> dict:
    preconditions = _get_preconditions(scenario)
    prompt = _PLAN_PROMPT.format(
        scenario=scenario, app_url=app_url,
        app_workflow_guide=_trim_workflow_guide(scenario),
        expert_insight=expert_insight or "(not available)",
        code_context=(f"{feedback_context}\n\n{ctx}" if feedback_context else ctx)[:5000],
    )
    # Inject preconditions right before the JSON output instruction if available
    if preconditions:
        prompt = prompt.replace(
            "Respond ONLY in JSON:",
            f"KNOWN PRE-REQUIREMENTS FOR THIS SCENARIO (from automation spec files):\n{preconditions}\n\n"
            "Respond ONLY in JSON:",
        )
    try:
        resp = _claude_invoke_with_retry(
            claude,
            [HumanMessage(content=prompt)],
            purpose=f"plan scenario: {scenario[:80]}",
        )
        return _parse_json(resp.content) or {}
    except Exception as e:
        logger.warning("Scenario planning failed; using empty plan fallback for '%s': %s", scenario[:80], e)
        return {}


def _decide_next(
    claude: ChatAnthropic,
    scenario: str,
    url: str,
    ax: str,
    net: list[str],
    steps: list[VerificationStep],
    ctx: str,
    step_num: int,
    scr: str = "",
    expert_insight: str = "",
    feedback_context: str = "",
    max_steps: int = MAX_STEPS,
) -> dict:
    steps_text = "\n".join(
        f"  {i+1}. [{s.action}] {s.description} ({'✓' if s.success else '✗'})"
        for i, s in enumerate(steps)
    )
    prompt_text = _STEP_PROMPT.format(
        scenario=scenario,
        expert_insight=expert_insight or "(not available)",
        app_workflow_guide=_trim_workflow_guide(scenario),
        url=url,
        ax_tree=ax[:3000],
        network_calls="\n".join(net[-10:]) if net else "(none)",
        steps_taken=steps_text or "(just starting)",
        code_context=(f"{feedback_context}\n\n{ctx}" if feedback_context else ctx)[:3000],
        step_num=step_num,
        max_steps=max_steps,
    )
    # Pass screenshot so Claude can SEE the page, not just the AX tree
    if scr:
        msg = HumanMessage(content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": scr,
                },
            },
            {"type": "text", "text": prompt_text},
        ])
    else:
        msg = HumanMessage(content=prompt_text)

    try:
        content = _claude_invoke_with_retry(
            claude,
            [msg],
            purpose=f"decide next: {scenario[:80]} step {step_num}",
        ).content
        raw = content if isinstance(content, str) else \
            " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        parsed = _parse_json(raw)
        if parsed:
            logger.debug("[decide] action=%s target=%s", parsed.get("action"), parsed.get("target", ""))
            return parsed
        # Fallback: log what Claude said so user can see it, then observe (don't end the run)
        logger.warning("[decide] Could not parse JSON from Claude response — falling back to observe.\nRaw: %s", raw[:400])
        return {"action": "observe", "description": "JSON parse failed — re-observing page"}
    except Exception as e:
        logger.warning("[decide] Claude unavailable/rate-limited — falling back to observe: %s", e)
        return {"action": "observe", "description": "Claude temporarily unavailable — re-observing page"}


# ── Core: verify one scenario ─────────────────────────────────────────────────

def _verify_scenario(
    page,
    scenario: str,
    card_name: str,
    app_base: str,
    plan_data: dict,
    ctx: str,
    claude: ChatAnthropic,
    progress_cb: Callable | None = None,
    qa_answer: str = "",
    first_scenario: bool = False,
    expert_insight: str = "",
    feedback_context: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
) -> ScenarioResult:
    result       = ScenarioResult(scenario=scenario)
    net_seen: list[str] = []
    api_endpoints = plan_data.get("api_to_watch", [])
    plan = _build_prerequisite_plan(scenario)
    max_steps = _step_budget_for_category(plan.category)
    result.scenario_category = plan.category
    setup_info = _parse_setup_context(ctx)
    product_title = setup_info.get("product_title", "")
    recovery_count = 0
    consecutive_failures = 0
    order_action = ""
    preferred_recovery_path = str(
        plan_data.get("app_path")
        or (plan_data.get("nav_clicks") or [None])[0]
        or ""
    ).strip()

    def _stop_requested() -> bool:
        return _is_stop_requested(stop_flag)

    def _mark_stopped() -> ScenarioResult:
        result.status = "skipped"
        result.verdict = "Verification stopped by user."
        result.steps.append(VerificationStep(
            action="stopped",
            description="Verification stopped by user.",
            success=False,
        ))
        return result

    def _emit_progress(step_num: int, desc: str) -> None:
        if progress_cb:
            progress_cb(step_num, desc)

    def _recover_navigation(reason: str) -> bool:
        nonlocal recovery_count, consecutive_failures, active_page
        if recovery_count >= MAX_RECOVERIES:
            return False

        recovery_target = preferred_recovery_path or "shipping"
        recovery_url = _resolve_nav_url(app_base, recovery_target)
        try:
            active_page.goto(recovery_url, wait_until="domcontentloaded", timeout=30_000)
            if not _cooperative_wait(active_page, 800, stop_flag):
                return False
            recovery_count += 1
            consecutive_failures = 0
            result.steps.append(VerificationStep(
                action="recover",
                description=f"Recovery navigation to '{recovery_target}' because {reason}",
                target=recovery_target,
                success=True,
            ))
            logger.info("[recover] scenario='%s…' → %s (%s)", scenario[:60], recovery_url, reason)
            return True
        except Exception as recovery_err:
            logger.warning("[recover] failed for '%s': %s", recovery_target, recovery_err)
            result.steps.append(VerificationStep(
                action="recover",
                description=f"Recovery navigation failed because {reason}: {recovery_err}",
                target=recovery_target,
                success=False,
            ))
            recovery_count += 1
            return False

    if _stop_requested():
        return _mark_stopped()

    # Inject QA guidance when resuming a stuck scenario
    if qa_answer:
        ctx = f"QA GUIDANCE: {qa_answer}\n\n{ctx}"

    _emit_progress(1, "Planning verification path…")

    # ── Order setup ───────────────────────────────────────────────────────────
    # Fix 1+2: validate Claude's choice then delegate to _setup_order_ctx
    try:
        from pipeline.order_creator import infer_order_decision
        _claude_order = plan_data.get("order_action") or infer_order_decision(scenario)
        order_action  = _validate_order_action(scenario, _claude_order)
        result.order_action = order_action
        _emit_progress(2, f"Preparing order setup ({order_action or 'none'})…")
        logger.info("[order] scenario='%s…' → claude=%s validated=%s",
                    scenario[:60], _claude_order, order_action)
        ctx = _setup_order_ctx(order_action, scenario, ctx)
    except Exception as oe:
        logger.debug("[order] Order setup skipped (non-fatal): %s", oe)
        _emit_progress(2, "Skipping explicit order setup and continuing with live navigation…")

    specialized_ctx = _build_specialized_verification_context(scenario, plan, ctx)
    if specialized_ctx:
        ctx = f"{specialized_ctx}\n\n{ctx}"
        _append_evidence_note(result, "specialized_verification_context=enabled")

    nav_clicks = plan_data.get("nav_clicks", [])
    first_nav_url = ""
    if nav_clicks:
        first_nav_url = _resolve_nav_url(app_base, str(nav_clicks[0]))

    orchestrated = False
    try:
        _emit_progress(3, f"Launching {plan.label_flow} flow prerequisites…")
        orchestrated = _run_prerequisite_orchestration(
            page, scenario, plan, ctx, app_base, result, stop_flag=stop_flag, progress_cb=_emit_progress
        )
        page = getattr(page, "_sav_active_page", page)
        result.orchestrated = orchestrated
        result.setup_succeeded = orchestrated
        result.setup_url = page.url or ""
        result.setup_screenshot_b64 = _screenshot(page)
        _append_evidence_note(
            result,
            f"scenario_category={plan.category}; order_action={result.order_action or '(none)'}; orchestrated={orchestrated}",
        )
        if orchestrated:
            _emit_progress(4, "Prerequisites ready — entering verification flow…")
            nav_clicks = []
            first_nav_url = ""
    except Exception as orch_err:
        logger.debug("[orchestration] setup skipped (non-fatal): %s", orch_err)
        result.setup_url = page.url or ""
        result.setup_screenshot_b64 = _screenshot(page)
        _append_evidence_note(result, f"orchestration_error={orch_err}")
        _emit_progress(3, "Prerequisite orchestration skipped — continuing with direct navigation…")

    if plan.category == "checkout_rates" and not orchestrated:
        setup_failures = [
            step for step in result.steps
            if step.action == "setup" and not step.success
        ]
        if setup_failures:
            failed_step = setup_failures[-1]
            result.status = "fail"
            result.verdict = (
                "Storefront checkout setup did not complete: "
                f"{failed_step.description}"
            )
            _append_evidence_note(result, f"checkout_setup_failure={failed_step.description}")
            _finalize_scenario_evidence(result, page, net_seen)
            return result

    # Only do a full page.goto() for the first scenario to avoid flickering.
    # For subsequent scenarios, click the app's "Shipping" home link in the sidebar
    # to reset to the home page without a full browser reload.
    app_base = _normalize_app_base(app_base)

    if not orchestrated and (first_scenario or not page.url.startswith(app_base.split("/apps/")[0])):
        try:
            _emit_progress(4, "Navigating to the verification surface…")
            page.goto(first_nav_url or app_base, wait_until="domcontentloaded", timeout=30_000)
            if not _cooperative_wait(page, 600, stop_flag):  # iframe React app settle
                return _mark_stopped()
            if first_nav_url:
                nav_clicks = nav_clicks[1:]
        except Exception as e:
            result.status  = "fail"
            result.verdict = f"Could not navigate to app: {e}"
            _finalize_scenario_evidence(result, page, net_seen)
            return result
    elif not orchestrated:
        # Soft reset — navigate back to app home via direct URL (safest — avoids clicking
        # the wrong "Shipping" link in Shopify's own sidebar which goes to Shopify settings)
        try:
            _emit_progress(4, "Resetting app state before verification…")
            page.goto(first_nav_url or app_base, wait_until="domcontentloaded", timeout=20_000)
            if not _cooperative_wait(page, 600, stop_flag):
                return _mark_stopped()
            if first_nav_url:
                nav_clicks = nav_clicks[1:]
        except Exception:
            pass

    # Click through planned nav items to reach the right section.
    #
    # Navigation strategy:
    #  - "Orders" is a Shopify admin left-sidebar link (outside the iframe)
    #  - "Shipping", "Settings", "PickUp", "Products", "FAQ", "Rates Log"
    #    are FedEx app sidebar links (inside the app iframe)
    #
    # For app nav items: search iframe first (avoids clicking Shopify's own
    # "Shipping and delivery" or "Settings" links by mistake).
    # For Shopify nav items: search the full page first.
    #
    # Nav failures are NON-FATAL — if a click fails, we log it and continue
    # to the agentic loop; Claude will see the current page state and decide
    # what to do next (instead of immediately asking QA).
    # ── Direct URL map for every known app page ───────────────────────────────
    # From live app screenshots: all internal pages follow {app_base}/{path} pattern.
    # Using direct goto() is 100% reliable — no link finding, no iframe confusion.
    _APP_URL_MAP = {
        # ── FedEx app pages (rendered inside the app iframe) ──────────────────
        # Verified from live browser URL bar:
        "shipping":    _resolve_nav_url(app_base, "shipping"),       # App's All Orders grid
        "appproducts": _resolve_nav_url(app_base, "appproducts"),    # FedEx app Products — EDIT FedEx settings
                                                    # on existing products (dry ice, alcohol,
                                                    # battery, dimensions, signature, declared value)
                                                    # Clicking a row → {app_base}/products/{id}
        "products":    _resolve_nav_url(app_base, "appproducts"),    # legacy alias → AppProducts
        "settings":    _resolve_nav_url(app_base, "settings"),       # App Settings (General tab)
        "pickup":      _resolve_nav_url(app_base, "pickup"),         # Pickups list
        "faq":         _resolve_nav_url(app_base, "faq"),            # FAQ
        "rates log":   _resolve_nav_url(app_base, "rates log"),      # Rates Log (NO hyphen — rateslog)
        # ── Shopify admin pages (outside iframe) ──────────────────────────────
        "orders":          _resolve_nav_url(app_base, "orders"),
        # ShopifyProducts = Shopify's own product management page.
        # This is the ONLY place to ADD a new product or edit Shopify product fields
        # (title, price, weight, SKU, barcode, HS code, variants).
        # ⚠️ NOT the FedEx app Products page — that is AppProducts above.
        "shopifyproducts": _resolve_nav_url(app_base, "shopifyproducts"),
    }
    nav_failed: list[str] = []

    for nav_label in nav_clicks:
        clicked   = False
        label_low = nav_label.lower().strip()
        nav_url   = _APP_URL_MAP.get(label_low)

        if nav_url:
            # Direct URL navigation — instant, reliable, no link-clicking ambiguity
            try:
                page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)
                if not _cooperative_wait(page, 600, stop_flag):
                    return _mark_stopped()
                clicked = True
                logger.info("Nav [%s] → %s", nav_label, nav_url)
            except Exception as e:
                logger.warning("Direct nav failed for '%s' (%s): %s", nav_label, nav_url, e)

        if not clicked:
            # Unknown nav label — fall back to clicking the link on the full page
            try:
                for fn in [
                    lambda l=nav_label: page.get_by_role("link",   name=l, exact=True),
                    lambda l=nav_label: page.get_by_role("link",   name=l, exact=False),
                    lambda l=nav_label: page.get_by_text(l, exact=False),
                ]:
                    loc = fn()
                    if loc.count() > 0:
                        loc.first.click(timeout=5_000)
                        if not _cooperative_wait(page, 500, stop_flag):
                            return _mark_stopped()
                        clicked = True
                        break
            except Exception:
                pass

        if not clicked:
            nav_failed.append(nav_label)
            logger.warning("Nav '%s' not found — agentic loop will handle navigation", nav_label)
            result.steps.append(VerificationStep(
                action="observe",
                description=f"Nav '{nav_label}' not found — will navigate from current page state",
                success=False,
            ))

    # Detect bot-challenge page
    try:
        body = page.inner_text("body").lower()
        if any(p in body for p in _CHALLENGE_PHRASES):
            result.status  = "skipped"
            result.verdict = "⚠️ Shopify bot-detection challenge. Refresh auth.json and retry."
            _finalize_scenario_evidence(result, page, net_seen)
            return result
    except Exception:
        pass

    # Agentic loop ────────────────────────────────────────────────────────────
    # `active_page` may change when Claude opens/closes a new tab (e.g. PDF viewer)
    active_page = page
    _emit_progress(5, "Running browser actions and collecting evidence…")
    # Accumulated ZIP content from download_zip actions — prepended to ctx so
    # Claude can read the extracted JSON on subsequent steps.
    zip_ctx = ""
    scenario_lower = scenario.lower()
    if any(token in scenario_lower for token in ("soldto", "sold to", "billing address", "request payload", "city.too.short")):
        captured_requests = getattr(page, "_sav_last_label_requests", None)
        if captured_requests:
            try:
                summarized_requests = []
                for item in list(captured_requests)[-3:]:
                    payload = item.get("payload")
                    if isinstance(payload, dict):
                        summarized_requests.append({
                            "url": item.get("url", ""),
                            "payload_summary": _summarize_verification_payload(payload) or payload,
                        })
                    else:
                        summarized_requests.append(item)
                zip_ctx = (
                    "=== CAPTURED LABEL REQUEST PAYLOADS ===\n"
                    f"{json.dumps(summarized_requests, indent=2)[:4000]}\n"
                    "=======================================\n\n"
                )
                _append_evidence_note(result, "captured_label_request_payload=available")
            except Exception:
                pass
            deterministic_payload_verdict = _verify_soldto_payload_from_scenario(scenario, list(captured_requests))
            if deterministic_payload_verdict:
                verdict_status, verdict_text = deterministic_payload_verdict
                result.status = verdict_status
                result.verdict = verdict_text
                result.steps.append(VerificationStep(
                    action="verify",
                    description="Verified the captured label request payload against soldTo expectations.",
                    success=(verdict_status == "pass"),
                ))
                _append_evidence_note(result, "soldto_payload_verification=deterministic")
                _finalize_scenario_evidence(result, active_page, net_seen)
                return result
    if plan.category == "checkout_rates":
        checkout_summary = getattr(page, "_sav_last_storefront_checkout", None)
        storefront_rates_log = getattr(page, "_sav_last_storefront_rates_log", None) or {}
        rates_log_payload = {}
        if isinstance(storefront_rates_log, dict):
            maybe_payload = storefront_rates_log.get("payload")
            if isinstance(maybe_payload, dict):
                rates_log_payload = maybe_payload
        deterministic_checkout_verdict = _verify_checkout_rates_from_scenario(
            scenario,
            checkout_summary if isinstance(checkout_summary, dict) else {},
            rates_log_payload,
        )
        if deterministic_checkout_verdict:
            verdict_status, verdict_text = deterministic_checkout_verdict
            result.status = verdict_status
            result.verdict = verdict_text
            result.steps.append(VerificationStep(
                action="verify",
                description="Verified the storefront checkout flow using captured checkout and Rates Log evidence.",
                success=(verdict_status == "pass"),
            ))
            if rates_log_payload:
                try:
                    zip_ctx = (
                        "=== STOREFRONT RATES LOG PAYLOAD ===\n"
                        f"{json.dumps(_summarize_verification_payload(rates_log_payload) or rates_log_payload, indent=2)[:4000]}\n"
                        "====================================\n\n"
                    )
                except Exception:
                    pass
                _append_evidence_note(result, "storefront_rates_log_payload=available")
            _append_evidence_note(result, "checkout_rates_verification=deterministic")
            _finalize_scenario_evidence(result, active_page, net_seen)
            return result

    for step_num in range(1, max_steps + 1):
        if _stop_requested():
            return _mark_stopped()

        ax  = _ax_tree(active_page)
        scr = _screenshot(active_page)
        net = _network(active_page, api_endpoints)
        net_seen.extend(n for n in net if n not in net_seen)

        if _stop_requested():
            return _mark_stopped()

        # Prepend any previously downloaded ZIP content so Claude can reason about it
        effective_ctx = f"{zip_ctx}{ctx}" if zip_ctx else ctx

        action = _decide_next(claude, scenario, active_page.url, ax, net_seen,
                              result.steps, effective_ctx, step_num, scr=scr,
                              expert_insight=expert_insight,
                              feedback_context=feedback_context,
                              max_steps=max_steps)

        if _stop_requested():
            return _mark_stopped()

        atype = action.get("action", "observe")
        _desc = action.get("description", atype)
        _tgt  = action.get("target", "")

        # Always log what the agent is doing — visible in dashboard logs
        logger.info("[step %d/%d] action=%-12s target=%-30s | %s",
                    step_num, max_steps, atype, _tgt[:30], _desc[:80])
        if progress_cb:
            progress_cb(step_num, f"[{atype}] {_desc[:60]}")

        step  = VerificationStep(
            action=atype,
            description=_desc,
            target=_tgt,
            screenshot_b64=scr,
            network_calls=list(net),
        )
        result.steps.append(step)

        if atype == "verify":
            result.status  = action.get("verdict", "partial")
            result.verdict = action.get("finding", "")
            step.screenshot_b64 = _screenshot(active_page)   # final state screenshot
            _append_evidence_note(result, f"verified_at_step={step_num}")
            break

        if atype == "qa_needed":
            if step_num < MIN_QA_STEP and _recover_navigation("Claude asked for QA too early"):
                step.success = False
                step.description = (
                    "Claude asked for QA early; forcing recovery navigation and continuing verification"
                )
                continue
            result.status      = "partial"
            result.qa_question = action.get("question", "I need more guidance to find this feature.")
            result.verdict = (
                "Could not conclusively verify this scenario after recovery attempts. "
                f"Claude asked: {result.qa_question}"
            )
            _append_evidence_note(result, f"qa_needed_at_step={step_num}")
            break

        # Fix 3 — mid-run recovery: agent discovered wrong test data and requests a reset
        if atype == "reset_order":
            new_order_action = action.get("order_action", "existing_fulfilled")
            logger.info("[reset_order] Agent requested order reset → %s", new_order_action)
            try:
                ctx = _setup_order_ctx(new_order_action, scenario, ctx)
                step.success = True
                step.description = f"Order reset → {new_order_action}: {action.get('description', '')}"
            except Exception as reset_err:
                logger.warning("[reset_order] failed: %s", reset_err)
                step.success = False
            continue

        if _stop_requested():
            return _mark_stopped()

        step.success = _do_action(active_page, action, app_base, stop_flag=stop_flag)
        if _stop_requested():
            return _mark_stopped()
        if step.success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 2:
                _recover_navigation(f"{consecutive_failures} consecutive action failures")

        # If download_zip succeeded, accumulate the extracted JSON as future context
        if "_zip_content" in action:
            zip_data = action["_zip_content"]
            summarized_zip = {}
            if isinstance(zip_data, dict):
                for name, content in zip_data.items():
                    if isinstance(content, dict):
                        summary = _summarize_verification_payload(content)
                        summarized_zip[name] = summary or content
                    else:
                        summarized_zip[name] = content
            else:
                summarized_zip = zip_data
            zip_summary = json.dumps(summarized_zip, indent=2)[:4000]
            zip_ctx = (
                f"=== DOWNLOADED ZIP CONTENTS (from '{action.get('target','?')}') ===\n"
                f"{zip_summary}\n"
                f"========================================\n\n"
            )
        if "_document_bundle_summary" in action:
            bundle_summary = json.dumps(action["_document_bundle_summary"], indent=2)[:3000]
            zip_ctx = (
                "=== DOCUMENT BUNDLE SUMMARY ===\n"
                f"{bundle_summary}\n"
                "===============================\n\n"
            ) + zip_ctx

        if "_log_content" in action:
            log_data = action["_log_content"]
            log_summary = json.dumps(_summarize_verification_payload(log_data) or log_data, indent=2)[:4000]
            zip_ctx = (
                "=== REQUEST LOG CONTENT ===\n"
                f"{log_summary}\n"
                "===========================\n\n"
            )

        # If download_file succeeded, accumulate file content as future context
        if "_file_content" in action:
            file_data = action["_file_content"]
            file_summary = json.dumps(file_data, indent=2)[:4000]
            zip_ctx = (
                f"=== DOWNLOADED FILE CONTENTS ('{file_data.get('filename','?')}') ===\n"
                f"{file_summary}\n"
                f"========================================\n\n"
            )
            logger.info("File content accumulated for next step (%d chars)", len(file_summary))

        # If switch_tab / close_tab opened or closed a tab, follow the new page
        if "_new_page" in action:
            active_page = action["_new_page"]

    else:
        # Max steps exhausted without a verify break — complete as best-effort
        # instead of blocking the release flow on QA input.
        result.status = "partial"
        _last_step_desc = result.steps[-1].description if result.steps else "nothing yet"
        result.verdict = (
            f"Exhausted {max_steps} steps after {recovery_count} recovery attempt(s). "
            f"Last observed state: {_last_step_desc}"
        )

    if plan.category == "product_special_service":
        cleanup_ok, cleanup_note = _cleanup_product_special_service(page, app_base, scenario, product_title)
        _record_setup_step(result, "cleanup", cleanup_note, target=product_title or "AppProducts", success=cleanup_ok)
        _append_evidence_note(result, f"cleanup={'ok' if cleanup_ok else 'failed'}")
    elif plan.category == "checkout_rates" and _has_any(scenario.lower(), ("signature", "dry ice", "dryice", "dry-ice", "alcohol", "battery", "lithium")):
        cleanup_ok, cleanup_note = _cleanup_product_special_service(page, app_base, scenario, product_title or "Simple packaging product")
        _record_setup_step(result, "cleanup", cleanup_note, target=product_title or "Simple packaging product", success=cleanup_ok)
        _append_evidence_note(result, f"cleanup={'ok' if cleanup_ok else 'failed'}")
    elif plan.category == "packaging_flow":
        packaging_req = _extract_packaging_requirements(f"{scenario}\n\n{ctx}")
        cleanup_ok, cleanup_note = _cleanup_packaging_setup(page, app_base, packaging_req)
        _record_setup_step(result, "cleanup", cleanup_note, target="settings", success=cleanup_ok)
        _append_evidence_note(result, f"cleanup={'ok' if cleanup_ok else 'failed'}")
    elif plan.category == "settings_or_grid" and _has_any(scenario.lower(), ("additional services", "dry ice", "fedex one rate", "duties and taxes in checkout rates", "duties & taxes", "checkout rates")):
        cleanup_ok, cleanup_note = _cleanup_additional_services(page, app_base, scenario)
        _record_setup_step(result, "cleanup", cleanup_note, target="settings", success=cleanup_ok)
        _append_evidence_note(result, f"cleanup={'ok' if cleanup_ok else 'failed'}")

    _finalize_scenario_evidence(result, active_page, net_seen)
    return result


def _run_verification_scenarios(
    *,
    app_url: str,
    scenarios: list[str],
    card_name: str,
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
    feedback_query_text: str = "",
    scenario_metadata: "dict[str, dict[str, str]] | None" = None,
) -> VerificationReport:
    def _emit_run_progress(scenario_idx: int, scenario_title: str, step_num: int, step_desc: str) -> None:
        if progress_cb:
            progress_cb(scenario_idx, scenario_title, step_num, step_desc)

    if _CODEBASE is None or _AUTH_JSON is None:
        raise RuntimeError("AUTOMATION_CODEBASE_PATH is not set in .env")
    if not app_url:
        app_url = get_auto_app_url()
    if not app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    app_url = _normalize_app_base(app_url)
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,
    )

    report = VerificationReport(card_name=card_name, app_url=app_url)
    feedback_context = ""
    try:
        from pipeline.qa_feedback import build_feedback_context
        feedback_query = " ".join(filter(None, [card_name, feedback_query_text[:800]]))
        feedback_context = build_feedback_context(feedback_query)
        if feedback_context:
            logger.info("SmartVerifier: injecting %d chars of past QA feedback", len(feedback_context))
    except Exception as feedback_err:
        logger.debug("SmartVerifier: feedback lookup skipped (non-fatal): %s", feedback_err)

    logger.info("SmartVerifier: %d execution item(s) for '%s'", len(scenarios), card_name)
    _boot_label = scenarios[0] if scenarios else card_name
    _emit_run_progress(1, _boot_label, 0, "Loading Playwright runtime…")
    from playwright.sync_api import sync_playwright
    _emit_run_progress(1, _boot_label, 0, "Playwright runtime ready — launching browser…")

    with sync_playwright() as p:
        try:
            _emit_run_progress(1, _boot_label, 0, "Launching visible Google Chrome…")
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=_ANTI_BOT_ARGS,
                timeout=15_000,
            )
            logger.debug("SmartVerifier: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            _emit_run_progress(1, _boot_label, 0, "Chrome launch stalled — falling back to Chromium…")
            try:
                browser = p.chromium.launch(
                    headless=False,
                    args=_ANTI_BOT_ARGS,
                    timeout=15_000,
                )
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                    args=_ANTI_BOT_ARGS,
                    timeout=15_000,
                )

        _emit_run_progress(1, _boot_label, 0, "Creating authenticated browser context…")
        ctx = browser.new_context(**_auth_ctx_kwargs())
        _emit_run_progress(1, _boot_label, 0, "Opening a fresh browser page…")
        page = ctx.new_page()
        try:
            _emit_run_progress(1, _boot_label, 0, "Opening Shopify FedEx app…")
            page.goto(app_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(600)
        except Exception as exc:
            logger.warning("Initial app navigation failed; scenario navigation will retry: %s", exc)

        for idx, scenario in enumerate(scenarios):
            if stop_flag and stop_flag():
                logger.info("SmartVerifier: stopped by user after %d scenarios", idx)
                break

            logger.info("[%d/%d] Verifying: %s", idx + 1, len(scenarios), scenario[:70])
            scenario_meta = (scenario_metadata or {}).get(scenario, {})
            scenario_plan = _build_prerequisite_plan(
                scenario,
                execution_flow_override=scenario_meta.get("execution_flow", ""),
            )
            deterministic = _is_deterministic_category(scenario_plan.category)
            if progress_cb:
                progress_cb(
                    idx + 1,
                    scenario,
                    0,
                    "🧭 Using deterministic flow…" if deterministic else "🧠 Asking domain expert…",
                )
            expert_insight = (
                "Deterministic prerequisite flow selected from scenario category."
                if deterministic else _ask_domain_expert(scenario, card_name, claude)
            )
            logger.debug("Expert insight for '%s': %s", scenario[:50], expert_insight[:120])
            if stop_flag and stop_flag():
                logger.info("SmartVerifier: stopped by user after domain expert step")
                break

            _emit_run_progress(idx + 1, scenario, 0, "Loading code and QA feedback context…")
            scenario_feedback_context = ""
            try:
                from pipeline.qa_feedback import build_scenario_feedback_context
                scenario_feedback_context = build_scenario_feedback_context(card_name, scenario)
            except Exception as feedback_err:
                logger.debug("SmartVerifier: scenario feedback lookup skipped (non-fatal): %s", feedback_err)

            code_ctx = _code_context(scenario, card_name)
            if stop_flag and stop_flag():
                logger.info("SmartVerifier: stopped by user after code context step")
                break

            _emit_run_progress(idx + 1, scenario, 0, "Planning verification steps…")
            combined_feedback_context = "\n\n".join(
                part for part in [feedback_context, scenario_feedback_context] if part
            )
            plan_data = (
                _heuristic_plan_data(scenario, app_url, code_ctx)
                if deterministic else
                _plan_scenario(
                    scenario, app_url, code_ctx, expert_insight, claude,
                    feedback_context=combined_feedback_context,
                )
            )
            if stop_flag and stop_flag():
                logger.info("SmartVerifier: stopped by user after plan step")
                break

            qa_answer = (qa_answers or {}).get(scenario, "")

            result = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=(lambda step_num, step_desc, _idx=idx, _scenario=scenario:
                             progress_cb(_idx + 1, _scenario, step_num, step_desc)) if progress_cb else None,
                qa_answer=qa_answer,
                first_scenario=(idx == 0),
                expert_insight=expert_insight,
                feedback_context=combined_feedback_context,
                stop_flag=stop_flag,
            )
            report.scenarios.append(result)
            if progress_cb:
                _final_state = (result.status or "unknown").upper()
                _final_note = result.verdict or "Scenario completed."
                progress_cb(
                    idx + 1,
                    scenario,
                    MAX_STEPS,
                    f"Finished with {_final_state} — {_final_note[:120]}",
                )

    if progress_cb:
        progress_cb(
            max(len(scenarios), 1),
            scenarios[-1] if scenarios else card_name,
            MAX_STEPS,
            "Summarizing AI QA results and preparing final report…",
        )
    _summarise_report(report)
    if progress_cb:
        progress_cb(
            max(len(scenarios), 1),
            scenarios[-1] if scenarios else card_name,
            MAX_STEPS,
            "Closing browser and publishing the final AI QA report…",
        )
    _close_browser_async(ctx, browser)
    if auto_report_bugs:
        _auto_report_bugs(report, card_id=card_id, card_url=card_url, qa_name=qa_name)
    return report


# ── Public entry point ────────────────────────────────────────────────────────

def verify_ac(
    app_url: str,
    ac_text: str,
    card_name: str,
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
    max_scenarios: int | None = None,
) -> VerificationReport:
    """
    Verify AC scenarios for a card against the live Shopify app.

    Args:
        app_url:           Full FedEx app URL in Shopify admin
        ac_text:           Full AC markdown from the Trello card
        card_name:         Card title
        card_id:           Trello card ID — used to get dev members for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the verification (shown in DM)
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found
        max_scenarios:     Cap number of scenarios tested (None = test all).
                           Simple=3, Medium=4, Complex=5. Takes the first N scenarios.

    Returns:
        VerificationReport with per-scenario results + bug_report on failures
    """
    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,
    )
    scenarios = _extract_scenarios(ac_text, claude)
    total_extracted = len(scenarios)
    if max_scenarios and max_scenarios < len(scenarios):
        scenarios = scenarios[:max_scenarios]
        logger.info("SmartVerifier: capped to %d/%d scenarios for '%s' (max_scenarios=%d)",
                    len(scenarios), total_extracted, card_name, max_scenarios)
    else:
        logger.info("SmartVerifier: %d scenarios for '%s'", len(scenarios), card_name)
    return _run_verification_scenarios(
        app_url=app_url,
        scenarios=scenarios,
        card_name=card_name,
        card_id=card_id,
        card_url=card_url,
        qa_name=qa_name,
        progress_cb=progress_cb,
        qa_answers=qa_answers,
        auto_report_bugs=auto_report_bugs,
        stop_flag=stop_flag,
        feedback_query_text=ac_text,
    )


def verify_test_cases(
    app_url: str,
    test_cases_markdown: str,
    card_name: str,
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
    max_test_cases: int | None = None,
) -> VerificationReport:
    if progress_cb:
        progress_cb(1, card_name, 0, "Parsing reviewed test cases…")
    ranked = rank_test_cases_for_execution(test_cases_markdown)
    total_extracted = len(ranked)
    if max_test_cases and max_test_cases < len(ranked):
        ranked = ranked[:max_test_cases]
        logger.info(
            "SmartVerifier: capped to %d/%d test cases for '%s' (max_test_cases=%d)",
            len(ranked), total_extracted, card_name, max_test_cases,
        )
    else:
        logger.info("SmartVerifier: %d ranked test cases for '%s'", len(ranked), card_name)

    scenarios = [tc.execution_text for tc in ranked]
    if progress_cb:
        progress_cb(1, scenarios[0] if scenarios else card_name, 0, "Preparing browser verification flow…")
    scenario_metadata = {
        tc.execution_text: {
            "execution_flow": tc.execution_flow,
        }
        for tc in ranked
    }
    return _run_verification_scenarios(
        app_url=app_url,
        scenarios=scenarios,
        card_name=card_name,
        card_id=card_id,
        card_url=card_url,
        qa_name=qa_name,
        progress_cb=progress_cb,
        qa_answers=qa_answers,
        auto_report_bugs=auto_report_bugs,
        stop_flag=stop_flag,
        feedback_query_text=test_cases_markdown,
        scenario_metadata=scenario_metadata,
    )


def reverify_failed(
    report: VerificationReport,
    app_url: str = "",
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
) -> VerificationReport:
    """
    Re-run only the failed/partial/qa_needed scenarios from an existing report.

    Args:
        report:            Existing VerificationReport from a previous verify_ac() call
        app_url:           Full FedEx app URL (defaults to report.app_url if blank)
        card_id:           Trello card ID — used for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the re-verification
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found

    Returns:
        Updated VerificationReport — previously-passing scenarios kept as-is,
        re-run results merged in, and summary regenerated.
    """
    from playwright.sync_api import sync_playwright

    # Filter to only failed scenarios
    failed_scenarios = [
        sv for sv in report.scenarios
        if sv.status in ("fail", "partial", "qa_needed")
    ]

    # Nothing to re-verify — return report unchanged
    if not failed_scenarios:
        return report

    # Resolve app URL
    _app_url = (app_url or report.app_url or "").strip()
    if not _app_url:
        _app_url = get_auto_app_url()
    if not _app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    _app_url = _normalize_app_base(_app_url)
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,   # 2048 caused JSON truncation → fake "partial" verdicts
    )

    card_name = report.card_name
    feedback_context = ""
    try:
        from pipeline.qa_feedback import build_feedback_context
        scenario_text = "\n".join(sv.scenario for sv in failed_scenarios[:5])
        feedback_query = " ".join(filter(None, [card_name, scenario_text]))
        feedback_context = build_feedback_context(feedback_query)
        if feedback_context:
            logger.info("reverify_failed: injecting %d chars of past QA feedback", len(feedback_context))
    except Exception as feedback_err:
        logger.debug("reverify_failed: feedback lookup skipped (non-fatal): %s", feedback_err)

    failed_count = len(failed_scenarios)
    logger.info(
        "reverify_failed: re-running %d scenario(s) for '%s'",
        failed_count, card_name,
    )

    # Build a lookup for in-place replacement
    # Maps scenario text → index in report.scenarios
    scenario_index: dict[str, int] = {
        sv.scenario: i for i, sv in enumerate(report.scenarios)
    }

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=_ANTI_BOT_ARGS)
            logger.debug("reverify_failed: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            browser = p.chromium.launch(headless=True, args=_ANTI_BOT_ARGS)

        ctx  = browser.new_context(**_auth_ctx_kwargs())
        page = ctx.new_page()
        try:
            page.goto(_app_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(600)
        except Exception as exc:
            logger.warning("Initial app navigation failed during reverify; scenario navigation will retry: %s", exc)

        for idx, old_sv in enumerate(failed_scenarios):
            # Honour stop button
            if stop_flag and stop_flag():
                logger.info("reverify_failed: stop requested after %d/%d scenarios", idx, failed_count)
                break

            scenario = old_sv.scenario
            logger.info(
                "[%d/%d] Re-verifying: %s", idx + 1, failed_count, scenario[:70]
            )

            if progress_cb:
                progress_cb(
                    idx + 1,
                    scenario,
                    0,
                    "🧭 Using deterministic flow…" if _is_deterministic_category(_build_prerequisite_plan(scenario).category)
                    else "🧠 Asking domain expert…",
                )
            scenario_plan = _build_prerequisite_plan(scenario)
            deterministic = _is_deterministic_category(scenario_plan.category)
            expert_insight = (
                "Deterministic prerequisite flow selected from scenario category."
                if deterministic else _ask_domain_expert(scenario, card_name, claude)
            )
            if stop_flag and stop_flag():
                logger.info("reverify_failed: stopped by user after domain expert step")
                break

            scenario_feedback_context = ""
            try:
                from pipeline.qa_feedback import build_scenario_feedback_context
                scenario_feedback_context = build_scenario_feedback_context(card_name, scenario)
            except Exception as feedback_err:
                logger.debug("reverify_failed: scenario feedback lookup skipped (non-fatal): %s", feedback_err)

            code_ctx  = _code_context(scenario, card_name)
            if stop_flag and stop_flag():
                logger.info("reverify_failed: stopped by user after code context step")
                break
            combined_feedback_context = "\n\n".join(
                part for part in [feedback_context, scenario_feedback_context] if part
            )
            plan_data = (
                _heuristic_plan_data(scenario, _app_url, code_ctx)
                if deterministic else
                _plan_scenario(
                    scenario, _app_url, code_ctx, expert_insight, claude,
                    feedback_context=combined_feedback_context,
                )
            )
            if stop_flag and stop_flag():
                logger.info("reverify_failed: stopped by user after planning step")
                break

            def _cb(step_num: int, desc: str, _i: int = idx, _sc: str = scenario) -> None:
                if progress_cb:
                    progress_cb(_i + 1, _sc, step_num, desc)

            qa_ans = (qa_answers or {}).get(scenario, "")

            new_sv = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=_app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=_cb,
                qa_answer=qa_ans,
                expert_insight=expert_insight,
                feedback_context=combined_feedback_context,
                first_scenario=(idx == 0),
                stop_flag=stop_flag,
            )

            # Auto bug report on fail/partial
            if auto_report_bugs and new_sv.status in ("fail", "partial") and card_id:
                if progress_cb:
                    progress_cb(idx + 1, scenario, MAX_STEPS, "🐛 Bug detected — notifying developer…")
                try:
                    from pipeline.bug_reporter import notify_devs_of_bug
                    steps_taken = [
                        f"{s.action}: {s.description}" for s in new_sv.steps
                        if s.action in ("click", "fill", "navigate", "observe")
                    ]
                    bug_result = notify_devs_of_bug(
                        card_id=card_id,
                        card_name=card_name,
                        card_url=card_url,
                        bug_description=new_sv.verdict,
                        scenario=scenario,
                        qa_name=qa_name,
                        verification_steps=steps_taken,
                    )
                    new_sv.bug_report = bug_result
                    logger.info(
                        "Bug report for '%s': sent=%s failed=%s",
                        scenario[:50], bug_result.get("sent_to"), bug_result.get("failed"),
                    )
                except Exception as e:
                    logger.warning("Bug auto-report failed: %s", e)
                    new_sv.bug_report = {"ok": False, "error": str(e)}

            # Replace the old result in-place
            orig_idx = scenario_index.get(scenario)
            if orig_idx is not None:
                report.scenarios[orig_idx] = new_sv
            else:
                # Scenario not found by exact match (shouldn't happen) — append
                report.scenarios.append(new_sv)

    if stop_flag and stop_flag():
        _close_browser_async(ctx, browser)
        report.summary = "Re-verification stopped by user."
        return report

    # Re-generate summary with Claude
    results_txt = "\n".join(
        f"- [{sv.status.upper()}] {sv.scenario}: {sv.verdict}"
        for sv in report.scenarios
    )
    try:
        resp = _claude_invoke_with_retry(
            claude,
            [HumanMessage(content=_SUMMARY_PROMPT.format(
                card_name=card_name, results=results_txt,
            ))],
            purpose=f"reverify summary: {card_name}",
        )
        report.summary = resp.content.strip()
    except Exception as e:
        logger.warning("Re-verify summary generation failed; using fallback summary: %s", e)
        report.summary = (
            f"Re-verification complete: {sum(1 for sv in report.scenarios if sv.status == 'pass')} passed, "
            f"{sum(1 for sv in report.scenarios if sv.status in ('fail', 'partial'))} failed or partial."
        )

    _close_browser_async(ctx, browser)
    return report
