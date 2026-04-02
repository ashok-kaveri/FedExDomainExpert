"""
Sheets Writer  —  Pipeline Integration
=======================================
After test cases are approved for a feature, this module appends them
to the correct tab in the FedExApp Master Sheet on Google Sheets.

Sheet structure (matches the master sheet):
  Col A: SI No
  Col B: Epic
  Col C: Scenarios
  Col D: Description (Given/When/Then)
  Col E: Comments
  Col F: Priority
  Col G: Details/Transaction ID
  Col H: Pass/Fail [Shopify]

Tab detection:
  Claude reads the feature name + AC and picks the right sheet tab.

Requires:
  - credentials.json (Google Service Account) with edit access to the sheet
  - OR the sheet shared with the service account email

Setup:
  1. Go to console.cloud.google.com → Service Accounts → create key → download JSON
  2. Save as: FedexDomainExpert/credentials.json
  3. Share the Google Sheet with the service account email (Editor access)
"""
import logging
import re
from dataclasses import dataclass, field
from textwrap import dedent
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SHEET_ID = config.GOOGLE_SHEETS_ID

# ---------------------------------------------------------------------------
# Known sheet tabs (map keyword → exact tab name)
# Update this list if new tabs are added to the master sheet
# ---------------------------------------------------------------------------
SHEET_TABS = [
    "Draft Plan",
    "Defects",
    "Bulk order cases",
    "Return Setting & Return Label",
    "Rate Settings",
    "Pickup Settings",
    "Additional Services",
    "Documents/Labels Settings1",
    "Single Label Generation [manual]",
    "Orders Grid [order's page ]",
    "International Shipping Settings",
    "Settings > account settings ",
    "Settings > Print Settings",
    "Settings > Notifications",
    "Settings>Subscription",
    "Pluginhive app setup",
    "Rate_Domestic_Packaging Type",
    "Label_Domestic_Packaging Type",
    "Translation ",
    "Rate_International_Packaging Type",
    "Label_International_Packaging Type",
    "Printing & Downloading",
    "Locations ON/OFF",
]

TAB_KEYWORDS: dict[str, list[str]] = {
    "Rate Settings":                        ["rate setting", "carrier service", "adjustment", "display name",
                                             "rate domestic", "shipping cost", "checkout rate"],
    "Rate_Domestic_Packaging Type":         ["domestic packaging", "domestic package type", "packaging type domestic"],
    "Rate_International_Packaging Type":    ["international packaging", "international package type", "packaging type international"],
    "Label_Domestic_Packaging Type":        ["label domestic packaging", "label package domestic"],
    "Label_International_Packaging Type":   ["label international packaging", "label package international"],
    "Single Label Generation [manual]":     ["single label", "manual label", "generate label", "label generation"],
    "Return Setting & Return Label":        ["return", "return label", "return setting"],
    "Pickup Settings":                      ["pickup", "pick up", "schedule pickup"],
    "Additional Services":                  ["dry ice", "dangerous goods", "alcohol", "signature", "one rate",
                                             "hold at location", "duties", "tax", "saturday delivery",
                                             "pass signature", "priority signature"],
    "Documents/Labels Settings1":           ["document", "commercial invoice", "customs", "ci ", "etd",
                                             "label size", "label format", "label setting"],
    "Printing & Downloading":               ["print", "download", "printing", "downloading", "bulk print"],
    "Bulk order cases":                     ["bulk", "bulk order", "multiple orders"],
    "Orders Grid [order's page ]":          ["order grid", "orders page", "orders grid", "order list", "fulfillment"],
    "International Shipping Settings":      ["international", "international shipping", "global", "cross-border",
                                             "qatar", "kuwait", "postal code", "country"],
    "Settings > account settings ":         ["account setting", "account setup", "api key", "meter number",
                                             "credentials", "fedex account"],
    "Settings > Print Settings":            ["print setting", "label size", "label format", "thermal",
                                             "print format", "label stock"],
    "Settings > Notifications":             ["notification", "email notification", "tracking email", "notify"],
    "Settings>Subscription":                ["subscription", "plan", "billing", "upgrade"],
    "Pluginhive app setup":                 ["app setup", "installation", "install", "onboard", "setup"],
    "Locations ON/OFF":                     ["location", "warehouse", "origin location", "ship from"],
    "Defects":                              ["defect", "bug", "fix", "issue"],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TestCaseRow:
    sl_no: str
    epic: str
    scenario: str
    description: str          # Given/When/Then
    comments: str = ""
    priority: str = "Medium"
    transaction_id: str = ""
    pass_fail: str = ""


# ---------------------------------------------------------------------------
# Tab detector
# ---------------------------------------------------------------------------

def detect_tab(card_name: str, test_cases_markdown: str) -> str:
    """
    Detect the right sheet tab for a feature using keyword matching first,
    then Claude as fallback.
    """
    combined = f"{card_name} {test_cases_markdown}".lower()

    # Keyword match
    for tab, keywords in TAB_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            logger.info("Tab detected by keywords: '%s' for card: %s", tab, card_name)
            return tab

    # Claude fallback
    if config.ANTHROPIC_API_KEY:
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage

            claude = ChatAnthropic(
                model=config.CLAUDE_HAIKU_MODEL,
                api_key=config.ANTHROPIC_API_KEY,
                temperature=0.0,
                max_tokens=100,
            )
            prompt = dedent(f"""\
                Given this feature: "{card_name}"
                Pick the MOST relevant sheet tab from this list:
                {chr(10).join(f'- {t}' for t in SHEET_TABS)}

                Reply with ONLY the exact tab name, nothing else.
            """)
            resp = claude.invoke([HumanMessage(content=prompt)])
            tab = resp.content.strip().strip('"')
            if tab in SHEET_TABS:
                logger.info("Tab detected by Claude: '%s'", tab)
                return tab
        except Exception as e:
            logger.warning("Claude tab detection failed: %s", e)

    # Default fallback
    logger.warning("Could not detect tab for '%s' — using Draft Plan", card_name)
    return "Draft Plan"


# ---------------------------------------------------------------------------
# Parse test cases markdown → rows
# ---------------------------------------------------------------------------

def _extract_priority(tc_text: str) -> str:
    """Extract priority from a test case block."""
    match = re.search(r"\*\*Priority:\*\*\s*(High|Medium|Low)", tc_text, re.IGNORECASE)
    return match.group(1) if match else "Medium"


def _extract_preconditions(tc_text: str) -> str:
    match = re.search(r"\*\*Preconditions?:\*\*\s*(.+?)(?:\n|$)", tc_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_given_when_then(tc_text: str) -> str:
    """
    Extract the Given/When/And/Then steps from a TC block.
    Matches the FedExApp Master Sheet description column format:
      Given I am logged in to the PH FedEx app
      When I navigate to Settings > ...
      And I click on ...
      Then the ... should be visible
    """
    lines = []
    in_steps = False
    for line in tc_text.split("\n"):
        stripped = line.strip()
        # Start collecting after **Steps:** marker
        if re.match(r"\*\*Steps:\*\*", stripped, re.IGNORECASE):
            in_steps = True
            continue
        # Stop at next bold section header (e.g. **Priority:** already consumed above)
        if in_steps and re.match(r"\*\*.+\*\*", stripped) and not re.match(
            r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE
        ):
            break
        # Collect Given/When/And/Then lines (with or without Steps: marker)
        if re.match(r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE):
            lines.append(stripped)
            in_steps = True  # also collect lines if Steps: header was missing

    return "\n".join(lines) if lines else ""


def parse_test_cases_to_rows(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
) -> list[TestCaseRow]:
    """
    Parse the generated test cases markdown into sheet rows.
    Each ### TC-N block becomes one row matching the master sheet structure:
      Col A: SI No
      Col B: Epic
      Col C: Scenarios (test case title)
      Col D: Description (Given/When/Then steps)
      Col E: Comments (Preconditions)
      Col F: Priority
    """
    if not epic:
        epic = card_name

    rows: list[TestCaseRow] = []
    # Split on TC blocks
    blocks = re.split(r"(?=###\s+TC-\d+)", test_cases_markdown)

    for block in blocks:
        if not block.strip() or not re.match(r"###\s+TC-\d+", block.strip()):
            continue

        # Title line → Scenarios column
        title_match = re.match(r"###\s+TC-\d+:\s*(.+)", block.strip())
        scenario = title_match.group(1).strip() if title_match else card_name

        # Given/When/Then → Description column (matches master sheet format)
        description = _extract_given_when_then(block)

        # Fallback: if no GWT found, use a cleaned snippet of the block
        if not description:
            # Remove markdown headers and bold markers, keep plain text
            clean = re.sub(r"###.*\n", "", block)
            clean = re.sub(r"\*\*.+?\*\*.*\n", "", clean)
            clean = re.sub(r"\|.*\|", "", clean)
            clean = re.sub(r"\n{2,}", "\n", clean).strip()
            description = clean[:800]

        priority = _extract_priority(block)
        comments = _extract_preconditions(block)

        rows.append(TestCaseRow(
            sl_no=str(len(rows) + 1),
            epic=epic,
            scenario=scenario,
            description=description,
            priority=priority,
            comments=comments,
        ))

    # If no TC blocks parsed, make one row with the full markdown
    if not rows:
        rows.append(TestCaseRow(
            sl_no="1",
            epic=epic,
            scenario=card_name,
            description=test_cases_markdown[:1000],
        ))

    return rows


# ---------------------------------------------------------------------------
# Google Sheets writer
# ---------------------------------------------------------------------------

def _get_gspread_client():
    """Return an authenticated gspread client using service account credentials."""
    creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {creds_path}.\n"
            "Download a service account key from Google Cloud Console and save it there.\n"
            "Then share the sheet with the service account email (Editor access)."
        )
    from google.oauth2.service_account import Credentials
    import gspread

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.Client(auth=creds)


def append_to_sheet(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    tab_name: str | None = None,
) -> dict:
    """
    Parse test cases and append them to the correct tab in the master sheet.

    Args:
        card_name:            Feature/card name
        test_cases_markdown:  Approved test cases in markdown
        epic:                 Epic name (defaults to card_name)
        tab_name:             Force a specific tab (None = auto-detect)

    Returns:
        {"tab": str, "rows_added": int, "sheet_url": str}
    """
    # Step 1: Detect tab
    target_tab = tab_name or detect_tab(card_name, test_cases_markdown)

    # Step 2: Parse into rows
    rows = parse_test_cases_to_rows(card_name, test_cases_markdown, epic=epic or card_name)
    if not rows:
        logger.warning("No rows parsed for card: %s", card_name)
        return {"tab": target_tab, "rows_added": 0, "sheet_url": ""}

    # Step 3: Open sheet
    client = _get_gspread_client()
    spreadsheet = client.open_by_key(SHEET_ID)

    # Get or find the target worksheet
    try:
        worksheet = spreadsheet.worksheet(target_tab)
    except Exception:
        # Try partial match
        ws_titles = [ws.title for ws in spreadsheet.worksheets()]
        match = next((t for t in ws_titles if target_tab.lower() in t.lower()), None)
        if match:
            worksheet = spreadsheet.worksheet(match)
            target_tab = match
        else:
            logger.warning("Tab '%s' not found. Available: %s", target_tab, ws_titles)
            raise ValueError(f"Sheet tab '{target_tab}' not found. Available tabs: {ws_titles}")

    # Step 4: Find next SI No (last used row)
    all_values = worksheet.get_all_values()
    # Find last non-empty row in column A (SI No)
    last_sl = 0
    for row in all_values:
        if row and row[0].strip().isdigit():
            last_sl = int(row[0].strip())

    # Step 5: Append rows
    rows_to_append = []
    for i, tc in enumerate(rows):
        tc.sl_no = str(last_sl + i + 1)
        rows_to_append.append([
            tc.sl_no,
            tc.epic,
            tc.scenario,
            tc.description,
            tc.comments,
            tc.priority,
            tc.transaction_id,
            tc.pass_fail,
        ])

    worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    sheet_url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/edit#gid={worksheet.id}"
    )
    logger.info("Appended %d rows to tab '%s'", len(rows_to_append), target_tab)

    return {
        "tab": target_tab,
        "rows_added": len(rows_to_append),
        "sheet_url": sheet_url,
    }
