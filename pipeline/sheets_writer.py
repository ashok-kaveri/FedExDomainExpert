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
from difflib import SequenceMatcher
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
    release: str = ""         # e.g. "FedExapp 2.3.115"
    tc_type: str = "Positive" # Positive | Negative | Edge


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


def _extract_type(tc_text: str) -> str:
    """Extract TC type: Positive | Negative | Edge. Defaults to Positive."""
    match = re.search(r"\*\*Type:\*\*\s*(Positive|Negative|Edge)", tc_text, re.IGNORECASE)
    return match.group(1).capitalize() if match else "Positive"


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
    positive_only: bool = False,
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

    Args:
        positive_only: If True, only return Positive type TCs (for sheet write).
                       Negative and Edge TCs go to Trello comment only.
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

        # Extract TC type — filter here if positive_only
        tc_type = _extract_type(block)
        if positive_only and tc_type != "Positive":
            continue

        # Given/When/Then → Description column (matches master sheet format)
        description = _extract_given_when_then(block)

        # Fallback: if no GWT found, use a cleaned snippet of the block
        if not description:
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
            tc_type=tc_type,
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
# Duplicate detection
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity ratio between two strings (case-insensitive)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _normalise(text: str) -> str:
    """Strip whitespace, lowercase, remove punctuation for comparison."""
    return re.sub(r"[^a-z0-9 ]", "", text.lower().strip())


@dataclass
class DuplicateMatch:
    sheet_row: int          # 1-based row number in sheet
    sheet_scenario: str     # existing scenario text in sheet
    sheet_tab: str
    new_scenario: str       # the new TC scenario being checked
    score: float            # similarity 0.0–1.0
    is_exact: bool          # True if scenario name matches exactly


def check_duplicates(
    new_rows: list[TestCaseRow],
    tab_name: str,
    similarity_threshold: float = 0.75,
) -> list[DuplicateMatch]:
    """
    Compare new test case rows against existing rows in the target sheet tab.
    Returns a list of DuplicateMatch for any rows that look like duplicates.

    A duplicate is detected when:
      - Scenario name similarity >= similarity_threshold (fuzzy), OR
      - Normalised scenario names are identical (exact)

    Args:
        new_rows:             Parsed TestCaseRow list about to be written
        tab_name:             Target sheet tab to check against
        similarity_threshold: Float 0–1, default 0.75 (75% similar = likely dup)

    Returns:
        List of DuplicateMatch objects (empty = no duplicates found)
    """
    try:
        client = _get_gspread_client()
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet(tab_name)
        existing = worksheet.get_all_values()
    except Exception as e:
        logger.warning("Duplicate check failed (sheet read error): %s", e)
        return []

    if len(existing) <= 1:
        return []   # only header row, nothing to compare

    # Build list of (row_number, scenario_text) from existing sheet data
    # Col C (index 2) = Scenarios
    existing_scenarios: list[tuple[int, str]] = []
    for row_idx, row in enumerate(existing[1:], start=2):  # skip header
        if len(row) > 2 and row[2].strip():
            existing_scenarios.append((row_idx, row[2].strip()))

    duplicates: list[DuplicateMatch] = []
    for new_tc in new_rows:
        new_norm = _normalise(new_tc.scenario)
        for sheet_row, sheet_scenario in existing_scenarios:
            sheet_norm = _normalise(sheet_scenario)

            # Exact match
            if new_norm == sheet_norm:
                duplicates.append(DuplicateMatch(
                    sheet_row=sheet_row,
                    sheet_scenario=sheet_scenario,
                    sheet_tab=tab_name,
                    new_scenario=new_tc.scenario,
                    score=1.0,
                    is_exact=True,
                ))
                break

            # Fuzzy match
            score = _similarity(new_tc.scenario, sheet_scenario)
            if score >= similarity_threshold:
                duplicates.append(DuplicateMatch(
                    sheet_row=sheet_row,
                    sheet_scenario=sheet_scenario,
                    sheet_tab=tab_name,
                    new_scenario=new_tc.scenario,
                    score=round(score, 2),
                    is_exact=False,
                ))
                break

    logger.info(
        "Duplicate check: %d new TCs checked against %d existing → %d potential duplicates",
        len(new_rows), len(existing_scenarios), len(duplicates),
    )
    return duplicates


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


def _ensure_release_header(worksheet, all_values: list[list]) -> int:
    """
    Ensure the 'Release' column header exists in row 1.
    Returns the 1-based column index for Release.
    If the header row already has 'Release', returns its index.
    Otherwise appends it after the last header column.
    """
    if not all_values:
        return 9  # default to col I

    header_row = [h.strip().lower() for h in all_values[0]]

    # Already exists?
    if "release" in header_row:
        return header_row.index("release") + 1  # 1-based

    # Append header to the next empty column after the last filled header
    next_col = len(all_values[0]) + 1
    import gspread.utils as gu
    col_letter = gu.rowcol_to_a1(1, next_col)[:-1]  # strip the row number '1'
    worksheet.update(f"{col_letter}1", [["Release"]])
    logger.info("Added 'Release' header at column %s", col_letter)
    return next_col


def append_to_sheet(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    tab_name: str | None = None,
    release: str = "",
) -> dict:
    """
    Parse test cases and append them to the correct tab in the master sheet.

    Args:
        card_name:            Feature/card name
        test_cases_markdown:  Approved test cases in markdown
        epic:                 Epic name (defaults to card_name)
        tab_name:             Force a specific tab (None = auto-detect)
        release:              Release version string, e.g. "FedExapp 2.3.115"

    Returns:
        {"tab": str, "rows_added": int, "sheet_url": str}
    """
    # Step 1: Detect tab
    target_tab = tab_name or detect_tab(card_name, test_cases_markdown)

    # Step 2: Parse into rows — POSITIVE CASES ONLY for the sheet
    # Negative and Edge cases go to Trello comment only (see card_processor.format_qa_comment)
    rows = parse_test_cases_to_rows(card_name, test_cases_markdown, epic=epic or card_name,
                                    positive_only=True)
    if not rows:
        logger.warning("No positive rows parsed for card: %s", card_name)
        return {"tab": target_tab, "rows_added": 0, "sheet_url": "",
                "duplicates": [], "release": release}

    # Set release on every row
    for r in rows:
        r.release = release

    # Step 2b: Duplicate check (warn but don't block — caller decides)
    duplicates = check_duplicates(rows, target_tab)
    if duplicates:
        logger.warning(
            "%d duplicate(s) detected for card '%s' in tab '%s'",
            len(duplicates), card_name, target_tab,
        )

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

    # Step 4: Get existing data + ensure Release column header exists
    all_values = worksheet.get_all_values()
    _ensure_release_header(worksheet, all_values)

    # Find last SI No in column A
    last_sl = 0
    for row in all_values:
        if row and row[0].strip().isdigit():
            last_sl = int(row[0].strip())

    # Step 5: Append rows
    # Col A–H = existing columns, Col I = Release
    rows_to_append = []
    for i, tc in enumerate(rows):
        tc.sl_no = str(last_sl + i + 1)
        rows_to_append.append([
            tc.sl_no,           # A: SI No
            tc.epic,            # B: Epic
            tc.scenario,        # C: Scenarios
            tc.description,     # D: Description (Given/When/Then)
            tc.comments,        # E: Comments / Preconditions
            tc.priority,        # F: Priority
            tc.transaction_id,  # G: Details/Transaction ID
            tc.pass_fail,       # H: Pass/Fail [Shopify]
            tc.release,         # I: Release
        ])

    worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    sheet_url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/edit#gid={worksheet.id}"
    )
    logger.info("Appended %d rows to tab '%s' (release: %s)", len(rows_to_append), target_tab, release)

    return {
        "tab": target_tab,
        "rows_added": len(rows_to_append),
        "sheet_url": sheet_url,
        "release": release,
        "duplicates": duplicates,   # list[DuplicateMatch] — empty if none found
    }
