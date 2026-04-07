"""
Pipeline Sign-Off Dashboard  —  Step 8
========================================
Streamlit UI that shows the status of every card through the delivery
pipeline and allows the team to sign off features.

Run:
    streamlit run ui/pipeline_dashboard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
import os
import re

import streamlit as st

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FedEx QA Pipeline",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Fonts & base ────────────────────────────────────────────────── */
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* ── App header ──────────────────────────────────────────────────── */
.pipeline-header {
    background: linear-gradient(135deg, #1a1f36 0%, #2d3561 100%);
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.pipeline-header h1 {
    color: #ffffff;
    font-size: 1.6rem;
    font-weight: 700;
    margin: 0;
}
.pipeline-header p {
    color: #a0aec0;
    font-size: 0.85rem;
    margin: 4px 0 0 0;
}

/* ── Connection status badges ────────────────────────────────────── */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 11px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    margin: 3px 0;
    width: 100%;
}
.status-ok   { background: #d4edda; color: #155724; }
.status-warn { background: #fff3cd; color: #856404; }
.status-err  { background: #f8d7da; color: #721c24; }

/* ── Pipeline step chips ─────────────────────────────────────────── */
.step-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #eef2ff;
    color: #3730a3;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-bottom: 8px;
}

/* ── Risk level badges ───────────────────────────────────────────── */
.risk-low    { background:#d1fae5; color:#065f46; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.8rem; }
.risk-medium { background:#fef3c7; color:#92400e; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.8rem; }
.risk-high   { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.8rem; }

/* ── Card step headers ───────────────────────────────────────────── */
.step-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 14px 0 6px 0;
}
.step-num {
    background: #6366f1;
    color: white;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    font-weight: 700;
    flex-shrink: 0;
}
.step-title { font-weight: 600; font-size: 0.95rem; color: #1e293b; }

/* ── Metric cards ────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 16px;
}

/* ── Sidebar enhancements ────────────────────────────────────────── */
section[data-testid="stSidebar"] > div {
    padding-top: 1rem;
}

/* ── Tab styling ─────────────────────────────────────────────────── */
button[data-baseweb="tab"] {
    font-weight: 600;
    font-size: 0.85rem;
}

/* ── Expander polish ─────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden;
}

/* ── Progress pipeline bar ───────────────────────────────────────── */
.pipeline-flow {
    display: flex;
    align-items: center;
    gap: 0;
    margin: 12px 0;
    flex-wrap: wrap;
}
.pf-step {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 0.72rem;
    font-weight: 600;
    color: #475569;
    white-space: nowrap;
}
.pf-step.done { background: #d1fae5; border-color: #6ee7b7; color: #065f46; }
.pf-step.active { background: #e0e7ff; border-color: #a5b4fc; color: #3730a3; }
.pf-arrow { color: #94a3b8; font-size: 0.7rem; padding: 0 4px; }

/* ── Bug severity badges ─────────────────────────────────────────── */
.sev-p1 { background:#fee2e2; color:#991b1b; padding:2px 8px; border-radius:10px; font-weight:700; font-size:0.75rem; }
.sev-p2 { background:#ffedd5; color:#9a3412; padding:2px 8px; border-radius:10px; font-weight:700; font-size:0.75rem; }
.sev-p3 { background:#fef9c3; color:#713f12; padding:2px 8px; border-radius:10px; font-weight:700; font-size:0.75rem; }
.sev-p4 { background:#dcfce7; color:#166534; padding:2px 8px; border-radius:10px; font-weight:700; font-size:0.75rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _init_state():
    if "pipeline_runs" not in st.session_state:
        st.session_state.pipeline_runs = {}   # card_id → run data
    if "trello_connected" not in st.session_state:
        st.session_state.trello_connected = False


# ---------------------------------------------------------------------------
# Pipeline runner (called from the UI)
# ---------------------------------------------------------------------------

def _run_pipeline_for_card(card_id: str, dry_run: bool) -> dict:
    """Run the full pipeline for one card and return status dict."""
    import config
    from pipeline.trello_client import TrelloClient
    from pipeline.card_processor import process_card
    from pipeline.feature_detector import detect_feature

    status = {
        "card_id": card_id,
        "card_name": "",
        "steps": {},
        "error": None,
    }

    try:
        trello = TrelloClient()
        card = trello.get_card(card_id)
        status["card_name"] = card.name

        # Step 2 — Card Processor
        with st.spinner(f"✍️ Writing acceptance criteria for '{card.name}'…"):
            ac = process_card(card, trello, dry_run=dry_run)
        status["steps"]["card_processor"] = {"status": "done", "ac": ac}
        st.success("✅ Acceptance criteria written")

        # Step 5.0 — Feature Detector
        with st.spinner("🔍 Detecting new vs existing feature…"):
            detection = detect_feature(card.name, ac)
        status["steps"]["feature_detector"] = {
            "status": "done",
            "kind": detection.kind,
            "confidence": detection.confidence,
            "reasoning": detection.reasoning,
            "related_files": detection.related_files,
        }
        kind_icon = "🆕" if detection.kind == "new" else "♻️"
        st.info(f"{kind_icon} Feature type: **{detection.kind.upper()}** "
                f"({detection.confidence:.0%} confidence)")

        # Step 5a/b — Test Writer
        if detection.kind == "new":
            from pipeline.test_writer.new_feature import generate_new_feature_tests
            with st.spinner("🤖 Generating new Playwright tests…"):
                test_result = generate_new_feature_tests(
                    card_name=card.name,
                    acceptance_criteria=ac,
                    dry_run=dry_run,
                )
            status["steps"]["test_writer"] = {"status": "done", **test_result}
            st.success(f"✅ Tests generated: {len(test_result['files_written'])} file(s)")
        else:
            from pipeline.test_writer.old_feature import update_existing_tests
            with st.spinner("♻️ Updating existing tests…"):
                test_result = update_existing_tests(
                    card_name=card.name,
                    new_ac=ac,
                    related_files=detection.related_files,
                    dry_run=dry_run,
                )
            status["steps"]["test_writer"] = {"status": "done", **test_result}
            branch = test_result.get("branch", "")
            st.warning(f"⚠️ Existing tests updated — review PR on branch `{branch}`")

    except Exception as e:
        status["error"] = str(e)
        st.error(f"Pipeline error: {e}")
        logger.exception("Pipeline failed for card %s", card_id)

    return status


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _status_badge(label: str, ok: bool, err_hint: str = "") -> str:
    """Render an HTML status badge."""
    if ok:
        return f'<div class="status-badge status-ok">✅ &nbsp;{label}</div>'
    else:
        hint = f" — {err_hint}" if err_hint else ""
        return f'<div class="status-badge status-err">❌ &nbsp;{label}{hint}</div>'


def _get_repo_branches() -> list[str]:
    """Return all branches in the automation repo, local + remote, sorted."""
    import subprocess
    codebase = os.path.join(os.path.dirname(__file__), "..", os.environ.get("AUTOMATION_CODEBASE_PATH", "../fedex-test-automation"))
    try:
        import config as _cfg
        codebase = _cfg.AUTOMATION_CODEBASE_PATH
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            cwd=codebase, capture_output=True, text=True, timeout=10,
        )
        branches = []
        for b in result.stdout.splitlines():
            b = b.strip().removeprefix("origin/")
            if b and b != "HEAD" and b not in branches:
                branches.append(b)
        return sorted(branches)
    except Exception:
        return []


def _step_header(num: str, title: str) -> None:
    """Render a numbered step header inline."""
    st.markdown(
        f'<div class="step-header">'
        f'<div class="step-num">{num}</div>'
        f'<div class="step-title">{title}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def main():
    _init_state()

    import config

    # ── Connection status (computed once, used in sidebar + body) ──────────
    api_ok = bool(config.ANTHROPIC_API_KEY)
    trello_ok = all([
        os.getenv("TRELLO_API_KEY"),
        os.getenv("TRELLO_TOKEN"),
        os.getenv("TRELLO_BOARD_ID"),
    ])
    slack_ok = bool(
        os.getenv("SLACK_WEBHOOK_URL", "").strip()
        or (os.getenv("SLACK_BOT_TOKEN", "").strip() and os.getenv("SLACK_CHANNEL", "").strip())
    )
    sheets_ok = bool(os.path.exists(config.GOOGLE_CREDENTIALS_PATH))

    # ── Page header ────────────────────────────────────────────────────────
    current_release = st.session_state.get("rqa_release", "")
    release_badge = f"&nbsp;·&nbsp;<span style='color:#818cf8;font-size:0.85rem'>{current_release}</span>" if current_release else ""
    st.markdown(
        f"""<div class="pipeline-header">
            <div>
                <h1>🚚 FedEx QA Pipeline{release_badge}</h1>
                <p>Trello card &rarr; AC &rarr; Test Cases &rarr; Automation &rarr; Run &rarr; Sign Off</p>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Sidebar ────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ System Status")
        st.markdown(
            _status_badge("Claude API", api_ok, "Set ANTHROPIC_API_KEY") +
            _status_badge("Trello", trello_ok, "Set TRELLO_* in .env") +
            _status_badge("Slack", slack_ok, "Set SLACK_WEBHOOK_URL") +
            _status_badge("Google Sheets", sheets_ok, "Add credentials.json") +
            _status_badge("Ollama Embeddings", True),
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Pipeline progress summary ──────────────────────────────────────
        cards      = st.session_state.get("rqa_cards", [])
        approved   = st.session_state.get("rqa_approved", {})
        tc_store   = st.session_state.get("rqa_test_cases", {})
        n_cards    = len(cards)
        n_approved = sum(1 for c in cards if approved.get(c.id))
        n_tc       = sum(1 for c in cards if c.id in tc_store)
        n_auto     = sum(1 for c in cards if st.session_state.get(f"automation_{c.id}"))
        last_run   = st.session_state.get("last_run_result")

        if current_release:
            st.markdown(f"**📦 Release:** `{current_release}`")
            st.markdown(
                f"""
                <div style="margin-top:8px">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:4px">
                    <span>📋 Cards</span><strong>{n_cards}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:4px">
                    <span>🤖 Test cases</span><strong>{n_tc}/{n_cards}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:4px">
                    <span>✅ Approved</span><strong>{n_approved}/{n_cards}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:4px">
                    <span>⚙️ Automation</span><strong>{n_auto}/{n_cards}</strong>
                </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Mini progress bar
            if n_cards > 0:
                st.progress(n_approved / n_cards, text=f"{n_approved}/{n_cards} approved")

            if last_run and last_run.release == current_release:
                icon = "✅" if last_run.failed == 0 else "❌"
                st.markdown(
                    f"**{icon} Last run:** {last_run.passed}/{last_run.total} passed"
                    f" · {last_run.duration_secs:.0f}s"
                )
        else:
            st.caption("Load a release in 🚀 Release QA to see progress.")

        st.divider()

        dry_run = st.toggle("🧪 Dry Run (no writes)", value=False)
        st.caption("Generates output without writing to Trello, repo, or Sheets.")

    # ── Tab layout ──────────────────────────────────────────────────────────
    tab_release, tab_devdone, tab_manual, tab_history, tab_signoff = st.tabs([
        "🚀 Release QA", "🔀 Move Cards", "✍️ Write Automation", "📋 History", "✅ Sign Off"
    ])

    # ── Tab 0: Release QA ───────────────────────────────────────────────────
    with tab_release:

        if not api_ok:
            st.error("❌ ANTHROPIC_API_KEY not set — add it to .env to use this feature")
        elif not trello_ok:
            st.error("❌ Trello credentials missing — set TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID in .env")
        else:
            from pipeline.trello_client import TrelloClient
            from pipeline.card_processor import (
                generate_test_cases, regenerate_with_feedback, write_test_cases_to_card
            )
            from pipeline.sheets_writer import (
                append_to_sheet, detect_tab, SHEET_TABS,
                check_duplicates, parse_test_cases_to_rows,
            )
            from pipeline.domain_validator import validate_card, ValidationReport
            from pathlib import Path

            sheets_ready = sheets_ok
            if not sheets_ready:
                st.info("ℹ️ Google Sheets not connected — test cases will save to Trello only. "
                        "Add `credentials.json` to enable sheet sync.")

            # ── List selector ─────────────────────────────────────────────
            st.markdown(
                '<div class="step-chip">① Select Release</div>',
                unsafe_allow_html=True,
            )
            col_refresh = st.columns([1])[0]
            with col_refresh:
                if st.button("🔄 Refresh Trello lists", use_container_width=False):
                    st.cache_data.clear()
                    st.rerun()

            col_list, col_load = st.columns([4, 1])
            with col_list:
                @st.cache_data(ttl=60)
                def _get_lists():
                    return [(l.name, l.id) for l in TrelloClient().get_lists()]

                all_lists = _get_lists()

                # Filter toggle — show only QA lists or all lists
                show_all = st.toggle("Show all lists", value=False)
                if show_all:
                    filtered_lists = all_lists
                else:
                    filtered_lists = [
                        (name, lid) for name, lid in all_lists
                        if "ready for qa" in name.lower() or "qa" in name.lower()
                    ]

                list_names = [name for name, _ in filtered_lists]
                # Default to first "Ready for QA FedEx" list
                default_idx = next(
                    (i for i, n in enumerate(list_names) if "fedex" in n.lower() and "ready for qa" in n.lower()), 0
                )
                selected_list_name = st.selectbox(
                    f"Select release list ({len(list_names)} lists)",
                    list_names,
                    index=default_idx,
                )
                selected_list_id = next(lid for name, lid in filtered_lists if name == selected_list_name)

            with col_load:
                st.write("")
                st.write("")
                load_btn = st.button("📥 Load Cards", use_container_width=True)

            # -- Release version input (editable, auto-filled from list name)
            import re as _re
            def _extract_release(list_name: str) -> str:
                """Extract release label from list name.
                'Ready for QA FedExapp 2.3.115' → 'FedExapp 2.3.115'
                """
                m = _re.search(r'(fedex\w*\s+[\d.]+)', list_name, _re.IGNORECASE)
                if m:
                    return m.group(1).strip()
                # fallback: grab any version-like pattern
                m2 = _re.search(r'(v?[\d]+\.[\d]+[\d.]*)', list_name)
                return m2.group(1) if m2 else list_name

            release_label = st.text_input(
                "🏷️ Release version",
                value=_extract_release(selected_list_name),
                placeholder="e.g. FedExapp 2.3.115",
                help="This will be recorded in the 'Release' column of the master sheet",
            )

            # -- Load cards + auto-validate all
            if load_btn:
                trello = TrelloClient()
                cards = trello.get_cards_in_list(selected_list_id)
                st.session_state["rqa_cards"] = cards
                st.session_state["rqa_list_name"] = selected_list_name
                st.session_state["rqa_release"] = release_label
                st.session_state["rqa_test_cases"] = {}
                st.session_state["rqa_approved"] = {}
                # Clear old validations for fresh load
                for c in cards:
                    st.session_state.pop(f"validation_{c.id}", None)

                # Auto-validate all cards immediately
                st.info(f"Loaded {len(cards)} cards from **{selected_list_name}** — running Domain Expert validation…")
                progress = st.progress(0)
                for idx, c in enumerate(cards):
                    with st.spinner(f"🧠 Validating '{c.name}'…"):
                        st.session_state[f"validation_{c.id}"] = validate_card(
                            card_name=c.name,
                            card_desc=c.desc or "",
                            acceptance_criteria=c.desc or "",
                        )
                    progress.progress((idx + 1) / len(cards))
                progress.empty()

                # Cross-card release analysis (runs after per-card validation)
                from pipeline.release_analyser import analyse_release, CardSummary as RASummary
                ra_cards = [
                    RASummary(card_id=c.id, card_name=c.name, card_desc=c.desc or "")
                    for c in cards
                ]
                with st.spinner("🔬 Running cross-card release analysis…"):
                    st.session_state["release_analysis"] = analyse_release(
                        release_name=release_label,
                        cards=ra_cards,
                    )
                st.rerun()

            # -- Main card view
            if "rqa_cards" in st.session_state and st.session_state["rqa_cards"]:
                cards = st.session_state["rqa_cards"]
                tc_store = st.session_state.setdefault("rqa_test_cases", {})
                approved_store = st.session_state.setdefault("rqa_approved", {})
                current_release = st.session_state.get("rqa_release", release_label)

                # ── Release health summary ────────────────────────────────
                st.divider()
                val_statuses = [
                    st.session_state.get(f"validation_{c.id}")
                    for c in cards
                ]
                n_pass  = sum(1 for v in val_statuses if v and v.overall_status == "PASS")
                n_review= sum(1 for v in val_statuses if v and v.overall_status == "NEEDS_REVIEW")
                n_fail  = sum(1 for v in val_statuses if v and v.overall_status == "FAIL")
                n_val   = sum(1 for v in val_statuses if v)
                approved_count = sum(1 for v in approved_store.values() if v)

                hcols = st.columns(5)
                hcols[0].metric("📦 Total Cards", len(cards))
                hcols[1].metric("🟢 Pass", n_pass)
                hcols[2].metric("🟡 Needs Review", n_review)
                hcols[3].metric("🔴 Fail", n_fail)
                hcols[4].metric("✅ Approved", approved_count)

                # ── Release Intelligence (cross-card RAG pre-screen) ──────────
                from pipeline.release_analyser import ReleaseAnalysis
                ra: ReleaseAnalysis | None = st.session_state.get("release_analysis")
                if ra and not ra.error:
                    risk_colors = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}
                    risk_icon = risk_colors.get(ra.risk_level, "⚪")
                    with st.expander(
                        f"{risk_icon} **Release Intelligence — {ra.risk_level} RISK** · {ra.risk_summary}",
                        expanded=True,
                    ):
                        if ra.kb_context_summary:
                            st.info(f"📚 **KB Context:** {ra.kb_context_summary}")

                        col_left, col_right = st.columns(2)

                        with col_left:
                            if ra.conflicts:
                                st.markdown("##### ⚠️ Cross-Card Conflicts")
                                for conflict in ra.conflicts:
                                    cards_involved = " & ".join(conflict.get("cards", []))
                                    area = conflict.get("area", "")
                                    desc = conflict.get("description", "")
                                    st.warning(f"**{cards_involved}** — *{area}*\n\n{desc}")
                            else:
                                st.success("✅ No cross-card conflicts detected")

                            if ra.coverage_gaps:
                                st.markdown("##### 🕳️ Coverage Gaps")
                                for gap in ra.coverage_gaps:
                                    st.caption(f"• {gap}")

                        with col_right:
                            if ra.ordering:
                                st.markdown("##### 📋 Suggested Test Order")
                                for o in ra.ordering:
                                    pos = o.get("position", "")
                                    cname = o.get("card_name", "")
                                    reason = o.get("reason", "")
                                    st.markdown(f"**{pos}.** {cname}")
                                    st.caption(f"   ↳ {reason}")

                        if ra.sources:
                            st.caption(
                                "KB sources: " + " · ".join(
                                    f"[link]({s})" if s.startswith("http") else s
                                    for s in ra.sources[:4]
                                )
                            )
                elif ra and ra.error:
                    st.warning(f"⚠️ Release analysis incomplete: {ra.error}")

                st.divider()

                for card in cards:
                    is_approved = approved_store.get(card.id, False)
                    vr: ValidationReport | None = st.session_state.get(f"validation_{card.id}")

                    # Expander icon shows validation + approval status
                    val_icon  = {"PASS": "🟢", "NEEDS_REVIEW": "🟡", "FAIL": "🔴"}.get(
                        vr.overall_status if vr else "", "⚪"
                    )
                    appr_icon = "✅ " if is_approved else ""
                    with st.expander(f"{appr_icon}{val_icon} {card.name}", expanded=not is_approved):

                        # ── STEP 1: Card Description ──────────────────────
                        _step_header("1", "Card Requirements")
                        if card.desc:
                            st.markdown(card.desc[:600] + ("…" if len(card.desc) > 600 else ""))
                        else:
                            st.caption("_(No description on this card)_")

                        # ── STEP 1b: AI Suggest User Story + AC ───────────
                        _step_header("1b", "AI Suggested User Story & AC")
                        ac_suggest_key = f"ac_suggestion_{card.id}"
                        ac_saved_key   = f"ac_saved_{card.id}"
                        ac_suggestion  = st.session_state.get(ac_suggest_key)
                        ac_saved       = st.session_state.get(ac_saved_key, False)

                        if ac_saved:
                            st.success("✅ AI-generated AC saved to Trello description")
                        elif ac_suggestion:
                            st.markdown(ac_suggestion)
                            col_save_ac, col_skip_ac = st.columns(2)
                            with col_save_ac:
                                if st.button("✅ Save to Trello Description", key=f"save_ac_{card.id}",
                                             use_container_width=True, type="primary"):
                                    with st.spinner("Updating Trello description…"):
                                        TrelloClient().update_card_description(card.id, ac_suggestion)
                                        card.desc = ac_suggestion
                                    st.session_state[ac_saved_key] = True
                                    st.rerun()
                            with col_skip_ac:
                                if st.button("⏭️ Skip — Keep Existing", key=f"skip_ac_{card.id}",
                                             use_container_width=True):
                                    st.session_state[ac_saved_key] = True  # mark done so it collapses
                                    st.rerun()
                        else:
                            if st.button("🤖 Generate User Story & AC", key=f"gen_ac_{card.id}"):
                                from pipeline.card_processor import generate_acceptance_criteria
                                raw = f"{card.name}\n\n{card.desc or ''}".strip()
                                with st.spinner("Claude is generating User Story & AC…"):
                                    st.session_state[ac_suggest_key] = generate_acceptance_criteria(
                                        raw,
                                        attachments=card.attachments,
                                        checklists=card.checklists,
                                    )
                                st.rerun()

                        # ── STEP 2: Domain Expert Validation ──────────────
                        _step_header("2", "Domain Expert Validation")
                        val_key = f"validation_{card.id}"

                        if vr:
                            status_color = {"PASS": "🟢", "NEEDS_REVIEW": "🟡", "FAIL": "🔴"}.get(
                                vr.overall_status, "⚪"
                            )
                            st.markdown(f"{status_color} **{vr.overall_status}** — {vr.summary}")

                            # KB insights
                            if vr.kb_insights:
                                with st.expander("📚 Knowledge Base context", expanded=False):
                                    st.markdown(vr.kb_insights)
                                    if vr.sources:
                                        st.caption("Sources: " + " · ".join(
                                            f"[link]({s})" if s.startswith("http") else s
                                            for s in vr.sources[:4]
                                        ))

                            # Issues grid
                            has_issues = any([vr.requirement_gaps, vr.ac_gaps,
                                              vr.accuracy_issues, vr.suggestions])
                            if has_issues:
                                c1, c2 = st.columns(2)
                                with c1:
                                    if vr.accuracy_issues:
                                        st.error("**❌ Accuracy Issues**")
                                        for issue in vr.accuracy_issues:
                                            st.markdown(f"- {issue}")
                                    if vr.requirement_gaps:
                                        st.warning("**⚠️ Requirement Gaps**")
                                        for gap in vr.requirement_gaps:
                                            st.markdown(f"- {gap}")
                                with c2:
                                    if vr.ac_gaps:
                                        st.warning("**📋 Missing AC Scenarios**")
                                        for gap in vr.ac_gaps:
                                            st.markdown(f"- {gap}")
                                    if vr.suggestions:
                                        st.info("**💡 Suggestions**")
                                        for s in vr.suggestions:
                                            st.markdown(f"- {s}")

                                # Fix + Re-validate
                                st.caption("👆 Fix the card on Trello, then re-validate below")
                                if st.button("🔄 Re-validate after fix", key=f"reval_{card.id}"):
                                    # Refresh card from Trello + re-run validation
                                    with st.spinner("Fetching updated card from Trello…"):
                                        fresh = TrelloClient().get_card(card.id)
                                    with st.spinner("Re-validating…"):
                                        st.session_state[val_key] = validate_card(
                                            card_name=fresh.name,
                                            card_desc=fresh.desc or "",
                                            acceptance_criteria=fresh.desc or "",
                                        )
                                        # Update stored card desc too
                                        card.desc = fresh.desc
                                    st.rerun()
                            else:
                                st.success("✅ Requirements & AC look complete — ready to generate test cases")
                        else:
                            st.caption("_(Validation not run yet)_")

                        st.divider()

                        # ── STEP 2b: LLM QA Explorer (Step 4b) ───────────
                        _step_header("2b", "QA Explorer — Live App (optional)")
                        st.caption(
                            "Let Claude navigate the live QA app and verify each AC "
                            "scenario with vision analysis. Run this while dev is fixing "
                            "issues — it gives you a visual pass/fail before writing tests."
                        )

                        explore_key = f"explore_report_{card.id}"
                        explore_report = st.session_state.get(explore_key)

                        col_exp1, col_exp2 = st.columns([3, 2])
                        with col_exp2:
                            explore_url = st.text_input(
                                "QA App URL",
                                placeholder="https://yourstore.myshopify.com/admin/apps/fedex-shipping",
                                key=f"explore_url_{card.id}",
                                label_visibility="collapsed",
                            )
                        with col_exp1:
                            if st.button(
                                "🔍 Explore with QA Agent",
                                key=f"qa_explore_{card.id}",
                                help="Claude opens the URL, screenshots each AC scenario, and reports pass/fail",
                            ):
                                if not explore_url.strip():
                                    st.warning("Enter the QA app URL first")
                                else:
                                    from pipeline.qa_explorer import explore_feature
                                    with st.spinner("🔍 QA Agent exploring the app… (takes ~60s)"):
                                        explore_report = explore_feature(
                                            app_url=explore_url.strip(),
                                            acceptance_criteria=card.desc or "",
                                            card_name=card.name,
                                        )
                                    st.session_state[explore_key] = explore_report
                                    st.rerun()

                        if explore_report:
                            pass_icon = "✅" if explore_report.failed == 0 else "❌"
                            with st.expander(
                                f"{pass_icon} QA Explorer — {explore_report.passed} passed · {explore_report.failed} failed",
                                expanded=explore_report.failed > 0,
                            ):
                                if explore_report.summary:
                                    st.info(explore_report.summary)
                                for scenario in explore_report.scenarios:
                                    s_icon = {"pass": "✅", "fail": "❌", "unexpected": "⚠️", "skipped": "⏭️"}.get(
                                        scenario.status, "❓"
                                    )
                                    st.markdown(f"{s_icon} **{scenario.scenario}**")
                                    st.caption(f"   {scenario.finding}")

                        st.divider()

                        # ── STEP 3: Generate Test Cases ───────────────────
                        _step_header("3", "Generate Test Cases")
                        if vr and vr.overall_status == "FAIL":
                            st.warning("⚠️ Accuracy issues found above — consider fixing the card before generating. "
                                       "You can still generate if you want to proceed.")

                        if card.id not in tc_store:
                            if st.button("🤖 Generate Test Cases", key=f"gen_{card.id}",
                                         type="primary" if (not vr or vr.overall_status == "PASS") else "secondary"):
                                with st.spinner("Claude is writing test cases…"):
                                    tc_store[card.id] = generate_test_cases(card)
                                st.rerun()
                        else:
                            # Show generated test cases
                            tc = tc_store[card.id]
                            st.markdown(tc)

                            if not is_approved:
                                st.divider()
                                _step_header("4", "Review & Approve")

                                # TC type breakdown summary
                                if sheets_ready:
                                    _all_rows  = parse_test_cases_to_rows(card.name, tc)
                                    _pos_rows  = [r for r in _all_rows if r.tc_type == "Positive"]
                                    _neg_rows  = [r for r in _all_rows if r.tc_type == "Negative"]
                                    _edge_rows = [r for r in _all_rows if r.tc_type == "Edge"]
                                    st.caption(
                                        f"📊 **{len(_all_rows)} total TCs** · "
                                        f"✅ {len(_pos_rows)} positive → Sheet · "
                                        f"❌ {len(_neg_rows)} negative → Trello comment only · "
                                        f"⚠️ {len(_edge_rows)} edge → Trello comment only"
                                    )

                                # Sheet tab selector
                                if sheets_ready:
                                    suggested_tab = detect_tab(card.name, tc)
                                    tab_options = SHEET_TABS
                                    tab_idx = tab_options.index(suggested_tab) if suggested_tab in tab_options else 0
                                    chosen_tab = st.selectbox(
                                        "📊 Add to sheet tab",
                                        tab_options,
                                        index=tab_idx,
                                        key=f"tab_{card.id}",
                                    )

                                # ── Duplicate check (runs when sheet is ready + tab chosen)
                                if sheets_ready:
                                    dup_key = f"dups_{card.id}_{chosen_tab}"
                                    if dup_key not in st.session_state:
                                        try:
                                            new_rows = parse_test_cases_to_rows(card.name, tc)
                                            st.session_state[dup_key] = check_duplicates(new_rows, chosen_tab)
                                        except Exception:
                                            st.session_state[dup_key] = []

                                    dups = st.session_state.get(dup_key, [])
                                    if dups:
                                        with st.expander(f"⚠️ {len(dups)} possible duplicate(s) found in sheet — click to review", expanded=True):
                                            for d in dups:
                                                badge = "🔴 Exact match" if d.is_exact else f"🟡 {int(d.score * 100)}% similar"
                                                st.markdown(
                                                    f"{badge} · Row {d.sheet_row} in **{d.sheet_tab}**\n\n"
                                                    f"- **Existing:** {d.sheet_scenario}\n"
                                                    f"- **New:** {d.new_scenario}"
                                                )
                                            st.caption("You can still approve — duplicates won't be blocked. "
                                                       "Use 'Skip duplicates' to only write non-duplicate TCs.")
                                        force_write = st.checkbox(
                                            "Skip duplicate TCs (only add new ones)",
                                            key=f"skip_dups_{card.id}",
                                        )
                                    else:
                                        force_write = False
                                        st.caption("✅ No duplicates found in sheet")
                                else:
                                    dups = []
                                    force_write = False

                                col_approve, col_edit = st.columns([1, 2])

                                with col_approve:
                                    if st.button("✅ Approve & Save", key=f"approve_{card.id}",
                                                 use_container_width=True, type="primary"):
                                        trello = TrelloClient()

                                        # 1. Write to Trello card
                                        with st.spinner("Saving to Trello…"):
                                            write_test_cases_to_card(
                                                card.id, tc, trello,
                                                release=current_release,
                                                card_name=card.name,
                                            )

                                        # 2. Write to Google Sheets
                                        if sheets_ready:
                                            with st.spinner(f"Adding to '{chosen_tab}' sheet…"):
                                                try:
                                                    tc_to_write = tc
                                                    skipped = 0
                                                    if force_write and dups:
                                                        dup_scenarios = {d.new_scenario.lower().strip() for d in dups}
                                                        tc_lines = tc.split("\n")
                                                        filtered_blocks = []
                                                        current_block = []
                                                        skip_block = False
                                                        for line in tc_lines:
                                                            if line.strip().startswith("### TC-"):
                                                                if current_block and not skip_block:
                                                                    filtered_blocks.extend(current_block)
                                                                elif skip_block:
                                                                    skipped += 1
                                                                current_block = [line]
                                                                title = line.split(":", 1)[-1].strip().lower()
                                                                skip_block = any(title in s or s in title for s in dup_scenarios)
                                                            else:
                                                                current_block.append(line)
                                                        if current_block and not skip_block:
                                                            filtered_blocks.extend(current_block)
                                                        elif skip_block:
                                                            skipped += 1
                                                        tc_to_write = "\n".join(filtered_blocks)

                                                    result = append_to_sheet(
                                                        card_name=card.name,
                                                        test_cases_markdown=tc_to_write,
                                                        tab_name=chosen_tab,
                                                        release=current_release,
                                                    )
                                                    skip_msg = f" ({skipped} duplicates skipped)" if skipped else ""
                                                    st.success(
                                                        f"✅ Saved to Trello + "
                                                        f"[{result['rows_added']} rows → '{result['tab']}' sheet{skip_msg}]"
                                                        f"  [Open sheet]({result['sheet_url']})"
                                                    )
                                                except Exception as e:
                                                    st.warning(f"Trello saved ✅ but Sheets failed: {e}")
                                        else:
                                            st.success("✅ Saved to Trello card!")

                                        approved_store[card.id] = True

                                        # 3. Update RAG knowledge base
                                        try:
                                            from pipeline.rag_updater import update_rag_from_card
                                            with st.spinner("📚 Updating knowledge base…"):
                                                rag_result = update_rag_from_card(
                                                    card_id=card.id,
                                                    card_name=card.name,
                                                    description=card.desc or "",
                                                    acceptance_criteria=card.desc or "",
                                                    test_cases=tc,
                                                    release=current_release,
                                                )
                                            if rag_result["error"]:
                                                st.warning(f"⚠️ RAG update failed: {rag_result['error']}")
                                            else:
                                                st.caption(
                                                    f"📚 Knowledge base updated "
                                                    f"({rag_result['chunks_added']} chunks added)"
                                                )
                                        except Exception as _rag_exc:
                                            st.warning(f"⚠️ RAG update skipped: {_rag_exc}")

                                        st.rerun()

                                with col_edit:
                                    feedback = st.text_input(
                                        "✏️ Request changes",
                                        placeholder="e.g. Add a test case for Saturday delivery, change TC-2 priority to High",
                                        key=f"feedback_{card.id}",
                                    )
                                    if st.button("🔄 Regenerate", key=f"regen_{card.id}",
                                                 use_container_width=True):
                                        if feedback.strip():
                                            with st.spinner("Claude is updating test cases…"):
                                                tc_store[card.id] = regenerate_with_feedback(
                                                    card, tc, feedback
                                                )
                                            st.rerun()
                                        else:
                                            st.warning("Type your feedback first")
                            else:
                                st.success("✅ Approved and saved to Trello")

                                # ── STEP 5: Write Automation ──────────────
                                _step_header("5", "Write Automation Code")
                                auto_key = f"automation_{card.id}"
                                auto_result = st.session_state.get(auto_key)

                                if auto_result:
                                    # Show result from previous run
                                    kind = auto_result.get("kind", "?")
                                    branch = auto_result.get("branch", "")
                                    files = auto_result.get("files_written", [])
                                    pushed = auto_result.get("pushed", False)
                                    err = auto_result.get("error", "")

                                    if err:
                                        st.error(f"❌ Automation failed: {err}")
                                        if st.button("🔄 Retry", key=f"retry_auto_{card.id}"):
                                            del st.session_state[auto_key]
                                            st.rerun()
                                    else:
                                        kind_badge = "🆕 New feature" if kind == "new" else "✏️ Existing feature"
                                        agent_steps = auto_result.get("chrome_trace_steps", 0)
                                        agent_badge = f" · 🌐 {agent_steps}-step agent trace" if agent_steps else ""
                                        st.success(f"{kind_badge} · {len(files)} file(s) written{agent_badge}")
                                        for f in files:
                                            st.caption(f"  📄 `{f}`")

                                        # ── TC filter summary ───────────────
                                        tc_summary = auto_result.get("tc_filter_summary", {})
                                        if tc_summary:
                                            total = tc_summary.get("total", 0)
                                            kept  = tc_summary.get("kept", 0)
                                            neg   = tc_summary.get("negative", 0)
                                            st.caption(
                                                f"📊 Test cases: {kept}/{total} automated "
                                                f"(✅ {tc_summary.get('positive',0)} positive · "
                                                f"⚡ {tc_summary.get('edge',0)} edge · "
                                                f"🚫 {neg} negative skipped — manual only)"
                                            )
                                        if branch:
                                            st.info(f"📦 Branch: `{branch}`")

                                        # ── Auto-fix results ────────────────
                                        fix_history = auto_result.get("fix_history", [])
                                        if fix_history:
                                            fix_passed = auto_result.get("fix_passed", False)
                                            fix_iters  = auto_result.get("fix_iterations", 0)
                                            if fix_passed:
                                                st.success(f"✅ Tests passing after {fix_iters} run(s)")
                                            else:
                                                st.warning(f"⚠️ Tests still failing after {fix_iters} auto-fix attempt(s)")
                                            with st.expander("🔍 Auto-fix run history", expanded=not fix_passed):
                                                for run in fix_history:
                                                    icon = "✅" if run["passed"] else "❌"
                                                    st.markdown(f"**{icon} Iteration {run['iteration']}**")
                                                    if run.get("fixed_files"):
                                                        st.caption("Fixed: " + ", ".join(f"`{x}`" for x in run["fixed_files"]))
                                                    with st.expander(f"Output (iter {run['iteration']})", expanded=False):
                                                        st.code(run.get("output", "")[-2000:], language="text")

                                        if pushed:
                                            st.success("✅ Pushed to origin")
                                        elif branch and not pushed:
                                            col_push, col_rerun = st.columns(2)
                                            with col_push:
                                                if st.button("🚀 Push to origin", key=f"push_{card.id}", use_container_width=True):
                                                    from pipeline.automation_writer import _push_branch
                                                    ok, out = _push_branch(branch)
                                                    if ok:
                                                        st.success(f"✅ Pushed `{branch}` to origin!")
                                                        auto_result["pushed"] = True
                                                        st.session_state[auto_key] = auto_result
                                                    else:
                                                        st.error(f"Push failed: {out}")
                                            with col_rerun:
                                                if st.button("🔄 Re-run on different branch", key=f"rerun_auto_{card.id}", use_container_width=True):
                                                    del st.session_state[auto_key]
                                                    st.rerun()
                                        else:
                                            if st.button("🔄 Re-run on different branch", key=f"rerun_auto2_{card.id}"):
                                                del st.session_state[auto_key]
                                                st.rerun()
                                else:
                                    # Detection preview
                                    det_key = f"detection_{card.id}"
                                    if det_key not in st.session_state and api_ok:
                                        try:
                                            from pipeline.feature_detector import detect_feature
                                            det = detect_feature(card.name, card.desc or "")
                                            st.session_state[det_key] = det
                                        except Exception:
                                            pass

                                    det = st.session_state.get(det_key)
                                    if det:
                                        kind_icon = "🆕" if det.kind == "new" else "✏️"
                                        st.caption(
                                            f"{kind_icon} **{det.kind.capitalize()} feature** "
                                            f"({det.confidence:.0%} confidence) — {det.reasoning[:120]}"
                                        )
                                        if det.related_files:
                                            st.caption("Related files: " + ", ".join(
                                                f"`{f}`" for f in det.related_files[:3]
                                            ))

                                    col_auto, col_branch = st.columns([3, 2])
                                    with col_branch:
                                        _NEW_BRANCH_OPTION = "➕ New branch…"
                                        existing_branches = _get_repo_branches()
                                        default_slug = f"automation/{re.sub(r'[^a-z0-9]+', '-', card.name.lower()).strip('-')[:30]}"
                                        branch_options = existing_branches + [_NEW_BRANCH_OPTION]
                                        # Pre-select the auto-slug if it already exists, else "New branch"
                                        default_idx = branch_options.index(default_slug) if default_slug in branch_options else len(branch_options) - 1
                                        selected_branch = st.selectbox(
                                            "Branch",
                                            options=branch_options,
                                            index=default_idx,
                                            key=f"branch_select_{card.id}",
                                            label_visibility="collapsed",
                                        )
                                        if selected_branch == _NEW_BRANCH_OPTION:
                                            auto_branch_input = st.text_input(
                                                "New branch name",
                                                value=default_slug,
                                                key=f"branch_input_{card.id}",
                                                label_visibility="collapsed",
                                            )
                                        else:
                                            auto_branch_input = selected_branch
                                    with col_auto:
                                        dry_auto = st.checkbox("Dry run (preview only)", key=f"dry_auto_{card.id}", value=False)
                                        push_auto = st.checkbox("Push to origin after commit", key=f"push_auto_{card.id}")

                                    # ── Step 5a: Chrome Agent option ──────────────────
                                    is_new_feature = det and det.kind == "new"
                                    use_chrome_agent = st.checkbox(
                                        "🌐 Walk app live with Chrome Agent (grounded locators)",
                                        key=f"use_chrome_{card.id}",
                                        value=is_new_feature,
                                        help="Agent navigates the real app, captures UI elements, then generates tests from what it sees.",
                                    )

                                    if use_chrome_agent:
                                        # Show Chrome Agent section
                                        trace_key = f"chrome_trace_{card.id}"
                                        trace_result = st.session_state.get(trace_key)

                                        if trace_result:
                                            if trace_result.error:
                                                st.error(f"❌ Chrome Agent: {trace_result.error}")
                                            else:
                                                with st.expander(
                                                    f"🌐 Agent explored {len(trace_result.steps)} steps — {len(trace_result.final_elements.splitlines())} elements captured",
                                                    expanded=False,
                                                ):
                                                    st.markdown(trace_result.navigation_path)
                                                    unique_els = trace_result.final_elements.splitlines()
                                                    if unique_els:
                                                        st.caption("Elements captured:")
                                                        for el in unique_els[:25]:
                                                            st.caption(f"  • {el}")

                                        # Detect app_path from POM registry for this card
                                        chrome_app_path = ""
                                        try:
                                            from pipeline.automation_writer import find_pom
                                            pom_entry = find_pom(card.name)
                                            if pom_entry:
                                                chrome_app_path = pom_entry.get("app_path", "")
                                        except Exception:
                                            pass

                                        col_explore, col_apppath = st.columns([2, 3])
                                        with col_apppath:
                                            chrome_app_path = st.text_input(
                                                "App path (optional)",
                                                value=chrome_app_path,
                                                placeholder="e.g. settings/additional-services",
                                                key=f"chrome_path_{card.id}",
                                                label_visibility="collapsed",
                                            )
                                        with col_explore:
                                            if st.button(
                                                "🌐 Explore App",
                                                key=f"explore_{card.id}",
                                                use_container_width=True,
                                                help="Opens Chrome, walks through the feature, captures real UI elements",
                                            ):
                                                from pipeline.chrome_agent import explore_with_agent
                                                with st.spinner("🌐 Chrome Agent exploring the app… (takes ~30s)"):
                                                    trace = explore_with_agent(
                                                        card_name=card.name,
                                                        acceptance_criteria=card.desc or "",
                                                        app_path=chrome_app_path,
                                                        max_steps=12,
                                                    )
                                                st.session_state[trace_key] = trace
                                                st.rerun()

                                    # ── QA context for this card ──────────────────────
                                    qa_context_key = f"qa_ctx_{card.id}"
                                    qa_context = st.text_area(
                                        "🧪 QA Test Context (optional)",
                                        key=qa_context_key,
                                        placeholder=(
                                            "Tell the AI specific data to use, e.g.:\n"
                                            "• Use HS code 123456 on product 'Test Shirt'\n"
                                            "• Enable Dry Ice with weight 2.5 kg\n"
                                            "• Use FedEx International Priority service"
                                        ),
                                        height=90,
                                        help="This context is passed to the AI so generated tests use the right product, settings, or values.",
                                    )

                                    # ── Auto-fix toggle ────────────────────────────────
                                    auto_fix_enabled = st.toggle(
                                        "🔄 Auto-run & fix until passing",
                                        key=f"auto_fix_{card.id}",
                                        value=False,
                                        help=(
                                            "After writing code, automatically run the tests. "
                                            "If they fail, Claude reads the errors and fixes the code, "
                                            "then re-runs. Repeats up to 3 times."
                                        ),
                                    )

                                    # ── Generate code button ───────────────────────────
                                    trace_for_gen = st.session_state.get(f"chrome_trace_{card.id}") if use_chrome_agent else None
                                    chrome_context = (
                                        trace_for_gen.to_context_string()
                                        if trace_for_gen and not trace_for_gen.error
                                        else ""
                                    )
                                    if st.button("⚙️ Write Automation Code", key=f"auto_{card.id}",
                                                 use_container_width=True,
                                                 type="primary"):
                                        from pipeline.automation_writer import write_automation
                                        label = (
                                            "✍️ Generating tests from live app trace…"
                                            if chrome_context
                                            else "✍️ Claude is writing Playwright tests…"
                                        )
                                        fix_status_placeholder = st.empty()
                                        def _on_fix_progress(iteration, status, output, _ph=fix_status_placeholder):
                                            _ph.info(f"🔄 **Auto-fix iteration {iteration}/3** — {status}")
                                        with st.spinner(label):
                                            result = write_automation(
                                                card_name=card.name,
                                                test_cases_markdown=tc_store.get(card.id, ""),
                                                acceptance_criteria=card.desc or "",
                                                branch_name=auto_branch_input,
                                                dry_run=dry_auto,
                                                push=push_auto,
                                                chrome_trace_context=chrome_context,
                                                qa_context=qa_context.strip(),
                                                auto_fix=auto_fix_enabled and not dry_auto,
                                                fix_iterations=3,
                                                on_fix_progress=_on_fix_progress,
                                            )
                                            # Record how many agent steps contributed
                                            if chrome_context and trace_for_gen:
                                                result["chrome_trace_steps"] = len(trace_for_gen.steps)
                                        st.session_state[auto_key] = result
                                        st.rerun()

                # Bulk approve all
                st.divider()
                if approved_count < len(cards):
                    if st.button("✅ Approve ALL remaining", type="primary"):
                        trello = TrelloClient()
                        remaining = [c for c in cards if not approved_store.get(c.id)]
                        rag_total = 0
                        for card in remaining:
                            if card.id in tc_store:
                                write_test_cases_to_card(card.id, tc_store[card.id], trello)
                                approved_store[card.id] = True
                                # Update RAG for each approved card
                                try:
                                    from pipeline.rag_updater import update_rag_from_card
                                    rag_r = update_rag_from_card(
                                        card_id=card.id,
                                        card_name=card.name,
                                        description=card.desc or "",
                                        acceptance_criteria=card.desc or "",
                                        test_cases=tc_store[card.id],
                                        release=current_release,
                                    )
                                    rag_total += rag_r.get("chunks_added", 0)
                                except Exception:
                                    pass
                        st.success(
                            f"✅ All {len(remaining)} cards saved to Trello! "
                            f"📚 {rag_total} RAG chunks updated."
                        )
                        st.rerun()

                # ── STAGE 6: Run Tests + Post to Slack ───────────────────
                st.divider()
                st.markdown(
                    '<div class="step-chip">⑥ Run Automation &amp; Post to Slack</div>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Run Playwright tests scoped to this release's generated spec files, "
                    "then post results to Slack."
                )

                from pipeline.slack_client import slack_configured, post_results
                from pipeline.test_runner import run_release_tests

                # Collect all spec files written for this release
                all_specs: list[str] = []
                card_spec_map: dict[str, str] = {}
                for card in cards:
                    auto_res = st.session_state.get(f"automation_{card.id}", {})
                    files = auto_res.get("files_written", [])
                    spec = next((f for f in files if f.endswith(".spec.ts")), "")
                    if spec:
                        all_specs.append(spec)
                        card_spec_map[card.name] = spec

                n_approved  = sum(1 for c in cards if approved_store.get(c.id))
                n_with_spec = len(all_specs)

                col_r1, col_r2, col_r3 = st.columns(3)
                col_r1.metric("✅ Cards approved", f"{n_approved}/{len(cards)}")
                col_r2.metric("📄 Spec files ready", n_with_spec)
                col_r3.metric("📣 Slack", "Configured ✅" if slack_configured() else "Not set ❌")

                if not slack_configured():
                    st.warning(
                        "⚠️ Slack not configured — add `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` to `.env` "
                        "to enable result posting. Tests can still be run without Slack."
                    )

                run_scope = st.radio(
                    "Test scope",
                    ["This release only (generated specs)", "Full test suite"],
                    index=0,
                    horizontal=True,
                    key="run_scope",
                )

                col_run, col_slack_only = st.columns([2, 1])
                with col_run:
                    run_disabled = n_approved == 0
                    if st.button(
                        "▶️ Run Tests" + (f" ({n_with_spec} specs)" if run_scope.startswith("This") and n_with_spec else ""),
                        type="primary",
                        use_container_width=True,
                        disabled=run_disabled,
                        key="run_tests_btn",
                    ):
                        specs_to_run = all_specs if run_scope.startswith("This") else []
                        with st.spinner(f"Running Playwright tests… ({len(specs_to_run) or 'full suite'})"):
                            run_result = run_release_tests(
                                release=current_release,
                                spec_files=specs_to_run,
                                card_results_map=card_spec_map if specs_to_run else None,
                            )
                        st.session_state["last_run_result"] = run_result
                        st.rerun()

                # Show last run result
                run_result = st.session_state.get("last_run_result")
                if run_result and run_result.release == current_release:
                    st.divider()
                    res_icon = "✅" if run_result.failed == 0 else "❌"
                    st.markdown(f"#### {res_icon} Test Run — {run_result.release}")

                    rc1, rc2, rc3, rc4 = st.columns(4)
                    rc1.metric("Total",   run_result.total)
                    rc2.metric("✅ Passed", run_result.passed)
                    rc3.metric("❌ Failed", run_result.failed)
                    rc4.metric("Duration", f"{run_result.duration_secs:.0f}s")

                    if run_result.card_results:
                        st.markdown("**Per-card breakdown:**")
                        for cr in run_result.card_results:
                            icon = "✅" if cr.get("failed", 0) == 0 else "❌"
                            st.caption(
                                f"{icon} **{cr['card_name']}** — `{cr.get('spec', '')}` "
                                f"· {cr.get('passed', 0)} passed · {cr.get('failed', 0)} failed"
                            )

                    if run_result.failed_tests:
                        with st.expander(f"❌ {len(run_result.failed_tests)} failed test(s)", expanded=True):
                            for t in run_result.failed_tests:
                                st.code(t, language=None)

                    # Slack post
                    st.divider()
                    slack_key = f"slack_posted_{current_release}"
                    already_posted = st.session_state.get(slack_key, False)

                    if already_posted:
                        st.success("📣 Results already posted to Slack")
                        if st.button("📣 Post again to Slack", key="repost_slack"):
                            st.session_state.pop(slack_key, None)
                            st.rerun()
                    else:
                        if slack_configured():
                            if st.button("📣 Post Results to Slack", type="primary",
                                         use_container_width=True, key="post_slack"):
                                with st.spinner("Posting to Slack…"):
                                    slack_res = post_results(run_result)
                                if slack_res["ok"]:
                                    st.success(f"✅ Posted to Slack! (ts={slack_res['ts']})")
                                    st.session_state[slack_key] = True
                                else:
                                    st.error(f"❌ Slack post failed: {slack_res['error']}")
                        else:
                            st.info(
                                "Configure Slack to enable posting. "
                                "You can copy the summary above manually."
                            )
                            # Show copyable summary
                            summary = (
                                f"*FedEx Automation — {run_result.release}*\n"
                                f"{run_result.status} · "
                                f"{run_result.passed}/{run_result.total} passed "
                                f"({run_result.pass_rate}) · {run_result.duration_secs:.0f}s\n"
                            )
                            if run_result.failed_tests:
                                summary += "\n*Failed:*\n" + "\n".join(f"• {t}" for t in run_result.failed_tests[:5])
                            st.code(summary, language=None)

                # ── STAGE 7: Generate Documentation ──────────────────────────
                st.divider()
                st.markdown(
                    '<div class="step-chip">⑦ Generate Documentation</div>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Generate a feature doc (docs/features/*.md) and CHANGELOG entry "
                    "for each card in this release."
                )

                from pipeline.doc_generator import generate_feature_doc

                # Collect cards with automation results for doc generation
                cards_for_docs = []
                for card in cards:
                    auto_res = st.session_state.get(f"automation_{card.id}", {})
                    files    = auto_res.get("files_written", [])
                    spec     = next((f for f in files if f.endswith(".spec.ts")), "")
                    pom      = next((f for f in files if f.endswith(".ts") and "pages" in f), "")
                    cards_for_docs.append({
                        "card": card,
                        "spec_file": spec,
                        "pom_file": pom,
                        "has_spec": bool(spec),
                    })

                n_with_docs_spec = sum(1 for c in cards_for_docs if c["has_spec"])
                st.caption(
                    f"{n_with_docs_spec}/{len(cards)} cards have spec files ready · "
                    f"Docs will be saved to `docs/features/` in the automation repo"
                )

                # Bulk generate all
                if st.button(
                    "📄 Generate Docs for All Cards",
                    type="primary",
                    key="gen_all_docs",
                    disabled=n_approved == 0,
                ):
                    doc_errors = []
                    for item in cards_for_docs:
                        card = item["card"]
                        doc_key = f"doc_result_{card.id}"
                        if doc_key not in st.session_state:
                            with st.spinner(f"📄 Writing docs for '{card.name}'…"):
                                doc_res = generate_feature_doc(
                                    card_name=card.name,
                                    acceptance_criteria=card.desc or "",
                                    test_cases=tc_store.get(card.id, ""),
                                    spec_file=item["spec_file"],
                                    pom_file=item["pom_file"],
                                    release=current_release,
                                )
                            st.session_state[doc_key] = doc_res
                            if doc_res["error"]:
                                doc_errors.append(f"{card.name}: {doc_res['error']}")
                    if doc_errors:
                        st.warning("Some docs failed:\n" + "\n".join(doc_errors))
                    else:
                        st.success(f"✅ Docs generated for {len(cards_for_docs)} cards")
                    st.rerun()

                # Per-card doc results
                for item in cards_for_docs:
                    card    = item["card"]
                    doc_key = f"doc_result_{card.id}"
                    doc_res = st.session_state.get(doc_key)

                    col_dcard, col_dgen = st.columns([4, 1])
                    with col_dcard:
                        if doc_res:
                            if doc_res.get("error"):
                                st.caption(f"❌ **{card.name}** — {doc_res['error']}")
                            else:
                                st.caption(f"✅ **{card.name}** → `{doc_res.get('doc_path', '')}`")
                        else:
                            spec_label = f"`{item['spec_file']}`" if item["spec_file"] else "_(no spec yet)_"
                            st.caption(f"⚪ **{card.name}** — {spec_label}")

                    with col_dgen:
                        if not doc_res:
                            if st.button("📄", key=f"gen_doc_{card.id}",
                                         help="Generate doc for this card"):
                                with st.spinner(f"Writing doc for '{card.name}'…"):
                                    doc_res = generate_feature_doc(
                                        card_name=card.name,
                                        acceptance_criteria=card.desc or "",
                                        test_cases=tc_store.get(card.id, ""),
                                        spec_file=item["spec_file"],
                                        pom_file=item["pom_file"],
                                        release=current_release,
                                    )
                                st.session_state[doc_key] = doc_res
                                st.rerun()

                    # Show generated doc preview
                    if doc_res and not doc_res.get("error") and doc_res.get("doc_content"):
                        with st.expander(f"📄 Preview: {card.name}", expanded=False):
                            st.markdown(doc_res["doc_content"])
                            if doc_res.get("changelog_entry"):
                                st.caption("**CHANGELOG entry added:**")
                                st.code(doc_res["changelog_entry"], language="markdown")

                # ── 🐛 Bug Reporter — found during manual QA ─────────────────
                st.divider()
                st.markdown(
                    '<div class="step-chip">🐛 Bug Reporter</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("#### Report a Bug Found During QA")
                st.caption(
                    "Describe the issue in plain English → Agent formats it in Jira style → "
                    "checks Trello backlog for duplicates → you approve → it's raised in Trello."
                )

                from pipeline.bug_tracker import check_and_draft_bug, raise_bug

                bug_desc = st.text_area(
                    "Describe the bug",
                    placeholder=(
                        "e.g. FedEx One Rate toggle saves correctly but checkout still shows "
                        "standard Ground rates. Happens when the store has dimensional weight "
                        "rules enabled."
                    ),
                    height=120,
                    key="bug_description",
                )
                col_bug1, col_bug2 = st.columns([3, 2])
                with col_bug1:
                    bug_feature = st.text_input(
                        "Feature / page context",
                        placeholder="e.g. Settings → Additional Services → FedEx One Rate",
                        key="bug_feature_context",
                    )
                with col_bug2:
                    bug_release = st.text_input(
                        "Release",
                        value=st.session_state.get("rqa_release", ""),
                        key="bug_release_input",
                    )

                if st.button("🔍 Check Backlog & Draft Bug", key="check_bug_btn",
                             type="primary", disabled=not bug_desc.strip()):
                    with st.spinner("Formatting bug + checking Trello backlog for duplicates…"):
                        bug_result = check_and_draft_bug(
                            issue_description=bug_desc.strip(),
                            feature_context=bug_feature.strip(),
                            release=bug_release.strip(),
                        )
                    st.session_state["bug_check_result"] = bug_result
                    st.rerun()

                bug_result = st.session_state.get("bug_check_result")
                if bug_result:
                    if bug_result.error:
                        st.error(f"❌ {bug_result.error}")

                    elif bug_result.is_duplicate:
                        # ── Duplicate found ──────────────────────────────
                        dup = bug_result.duplicate_card
                        st.warning(
                            f"⚠️ This issue may already exist in the backlog.\n\n"
                            f"**{bug_result.duplicate_reason}**"
                        )
                        st.markdown(f"**Existing card:** [{dup.name}]({dup.url})")
                        if dup.desc:
                            with st.expander("📋 View existing card description", expanded=False):
                                st.markdown(dup.desc[:800])

                        st.caption(
                            "If this is a different issue, edit your description to be more "
                            "specific and check again."
                        )
                        # Still allow raising as new if QA disagrees
                        if st.button("➕ Raise Anyway (different issue)", key="raise_anyway_btn"):
                            # Override is_duplicate so draft section renders below
                            bug_result.is_duplicate = False
                            st.session_state["bug_check_result"] = bug_result
                            st.rerun()

                    if not bug_result.is_duplicate:
                        # ── New bug — show draft for approval ─────────────
                        draft = bug_result.draft
                        if draft:
                            sev_colors = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🟢"}
                            sev_icon = sev_colors.get(draft.severity, "⚪")

                            st.success("✅ No duplicate found — new bug ready for review")
                            st.markdown("#### Bug Draft — Review before raising")
                            st.markdown(draft.to_display_markdown())

                            st.divider()
                            st.caption(
                                "Review the draft above. You can edit the title or severity "
                                "before raising it in Trello."
                            )

                            col_title, col_sev = st.columns([4, 1])
                            with col_title:
                                edited_title = st.text_input(
                                    "Bug title (editable)",
                                    value=draft.title,
                                    key="bug_edit_title",
                                )
                            with col_sev:
                                edited_sev = st.selectbox(
                                    "Severity",
                                    ["P1", "P2", "P3", "P4"],
                                    index=["P1", "P2", "P3", "P4"].index(draft.severity),
                                    key="bug_edit_sev",
                                )

                            if st.button(
                                "✅ Approve & Raise in Trello → Backlog",
                                type="primary",
                                key="raise_bug_btn",
                                use_container_width=True,
                            ):
                                # Apply edits
                                draft.title    = edited_title.strip() or draft.title
                                draft.severity = edited_sev
                                # Update labels to match edited severity
                                draft.labels = [
                                    lb for lb in draft.labels
                                    if lb not in ["P1", "P2", "P3", "P4"]
                                ] + [edited_sev]

                                with st.spinner("Creating card in Trello Iteration Backlog…"):
                                    try:
                                        created_card = raise_bug(draft)
                                        st.session_state["bug_raised_card"] = created_card
                                        st.session_state.pop("bug_check_result", None)
                                    except Exception as exc:
                                        st.error(f"❌ Failed to create card: {exc}")
                                st.rerun()

                raised_card = st.session_state.get("bug_raised_card")
                if raised_card:
                    st.success(
                        f"🐛 Bug raised in Trello! "
                        f"[{raised_card.name}]({raised_card.url})"
                    )
                    if st.button("🆕 Report another bug", key="clear_bug_btn"):
                        st.session_state.pop("bug_raised_card", None)
                        st.session_state.pop("bug_check_result", None)
                        st.rerun()

    # ── Tab 1: Move Cards ───────────────────────────────────────────────────
    with tab_devdone:
        st.markdown("## 🔀 Move Cards")
        st.caption("Pick any board list, load its cards, select them, and move to any other list — just like Trello.")

        if not trello_ok:
            st.error("❌ Add TRELLO_* credentials to .env")
        else:
            from pipeline.trello_client import TrelloClient

            @st.cache_data(ttl=60)
            def _get_all_lists():
                return [(l.name, l.id) for l in TrelloClient().get_lists()]

            all_board_lists = _get_all_lists()
            all_list_names  = [name for name, _ in all_board_lists]
            all_list_ids    = {name: lid for name, lid in all_board_lists}

            # ── Source & target selectors side by side ───────────────────────
            col_src, col_arrow, col_tgt, col_load, col_refresh = st.columns([3, 0.4, 3, 1, 1])

            with col_src:
                # Default to "Dev Done" if present, otherwise first list
                default_src_idx = next(
                    (i for i, n in enumerate(all_list_names) if n.lower() == "dev done"), 0
                )
                selected_src_list = st.selectbox(
                    "📂 Source list", all_list_names, index=default_src_idx, key="dd_list_select"
                )

            with col_arrow:
                st.write("")
                st.write("")
                st.write("")
                st.markdown("**→**")

            with col_tgt:
                # Exclude source list from target options
                tgt_names = [n for n in all_list_names if n != selected_src_list]
                # Default to "Ready for QA" if present, otherwise first available
                default_tgt_idx = next(
                    (i for i, n in enumerate(tgt_names) if "ready for qa" in n.lower()), 0
                )
                selected_tgt_list = st.selectbox(
                    "📁 Target list", tgt_names, index=default_tgt_idx, key="dd_move_target"
                )

            with col_load:
                st.write("")
                st.write("")
                load_done_btn = st.button("📥 Load", use_container_width=True, key="dd_load")

            with col_refresh:
                st.write("")
                st.write("")
                if st.button("🔄", use_container_width=True, key="dd_refresh", help="Clear cache and refresh lists"):
                    st.cache_data.clear()
                    st.rerun()

            selected_done_id = all_list_ids.get(selected_src_list, "")
            move_target      = selected_tgt_list

            if load_done_btn:
                trello = TrelloClient()
                done_cards = trello.get_cards_in_list(selected_done_id)
                st.session_state["dd_cards"] = done_cards
                st.session_state["dd_checked"] = {c.id: False for c in done_cards}

            # Show cards
            if "dd_cards" in st.session_state and st.session_state["dd_cards"]:
                dd_cards = st.session_state["dd_cards"]
                dd_checked = st.session_state.setdefault("dd_checked", {})

                st.divider()
                st.markdown(f"**{len(dd_cards)} cards** in `{selected_src_list}`")

                # Select all toggle
                col_selall, col_movebtn = st.columns([2, 1])
                with col_selall:
                    if st.checkbox("Select all", key="dd_select_all"):
                        for c in dd_cards:
                            dd_checked[c.id] = True

                # Read checkbox state directly from session_state (always current)
                selected_ids = [
                    card.id for card in dd_cards
                    if st.session_state.get(f"dd_chk_{card.id}", dd_checked.get(card.id, False))
                ]
                with col_movebtn:
                    move_btn = st.button(
                        f"➡️ Move {len(selected_ids)} cards",
                        disabled=len(selected_ids) == 0,
                        use_container_width=True,
                        type="primary",
                        key="dd_move_btn"
                    )

                if move_btn and selected_ids:
                    trello = TrelloClient()
                    moved = 0
                    for card in dd_cards:
                        if card.id in selected_ids:
                            trello.move_card_to_list(card.id, move_target)
                            trello.add_comment(card.id, f"➡️ Moved to **{move_target}** via FedEx Pipeline Dashboard.")
                            moved += 1
                    st.success(f"✅ Moved {moved} cards to **{move_target}**")
                    # Reload cards
                    st.session_state["dd_cards"] = trello.get_cards_in_list(selected_done_id)
                    st.session_state["dd_checked"] = {c.id: False for c in st.session_state["dd_cards"]}
                    st.rerun()

                st.divider()

                # Card list with checkboxes
                for card in dd_cards:
                    col_chk, col_info = st.columns([1, 8])
                    with col_chk:
                        checked = st.checkbox("", key=f"dd_chk_{card.id}",
                                              value=dd_checked.get(card.id, False))
                        dd_checked[card.id] = checked

                    with col_info:
                        with st.expander(f"{'🔲' if not checked else '☑️'} {card.name}"):
                            if card.labels:
                                st.caption("🏷️ " + " · ".join(card.labels))
                            if card.desc:
                                st.markdown(card.desc[:600] + ("…" if len(card.desc) > 600 else ""))
                            else:
                                st.caption("_No description_")
                            st.caption(f"🔗 [Open in Trello]({card.url})")
            elif "dd_cards" in st.session_state:
                st.info("No cards in this list.")

    # ── Tab: History ────────────────────────────────────────────────────────
    with tab_history:
        st.subheader("Pipeline Run History")
        if not st.session_state.pipeline_runs:
            st.info("No runs yet this session.")
        else:
            for card_id, run in st.session_state.pipeline_runs.items():
                with st.expander(f"{'❌' if run.get('error') else '✅'} {run.get('card_name', card_id)}"):
                    st.json(run)

    # ── Tab 3: Sign Off ─────────────────────────────────────────────────────
    with tab_signoff:
        st.markdown(
            '<div class="step-chip">⑧ QA Sign Off</div>',
            unsafe_allow_html=True,
        )
        st.markdown("## ✅ QA Sign Off")
        st.caption(
            "Compose and send the team sign-off message to Slack — "
            "exactly like the format used by your QA team."
        )

        from pipeline.slack_client import post_signoff, slack_configured

        # Pull cards from the active release session
        so_cards     = st.session_state.get("rqa_cards", [])
        so_release   = st.session_state.get("rqa_release", "")
        so_approved  = st.session_state.get("rqa_approved", {})
        so_tc_store  = st.session_state.get("rqa_test_cases", {})

        # Bugs raised this session (from bug_tracker flow)
        so_bugs_raised = []
        raised_card = st.session_state.get("bug_raised_card")
        if raised_card:
            so_bugs_raised.append(raised_card.name)
        # Also check if there are previous raises stored
        for key, val in st.session_state.items():
            if key.startswith("bug_raised_") and hasattr(val, "name"):
                if val.name not in so_bugs_raised:
                    so_bugs_raised.append(val.name)

        if not so_cards:
            st.info("Load a release from the 🚀 Release QA tab first.")
        else:
            # ── Release summary ───────────────────────────────────────────
            approved_cards = [c for c in so_cards if so_approved.get(c.id)]
            n_approved = len(approved_cards)
            n_total    = len(so_cards)

            so1, so2, so3 = st.columns(3)
            so1.metric("📦 Cards in release",  n_total)
            so2.metric("✅ Cards approved",    n_approved)
            so3.metric("🐛 Bugs to backlog",   len(so_bugs_raised))

            if n_approved == 0:
                st.warning("⚠️ No cards approved yet — approve cards in the Release QA tab first.")

            st.divider()

            # ── Cards Verified list (checkboxes — QA picks which passed) ─
            st.markdown("#### Cards Verified")
            st.caption("Select which cards passed QA testing:")

            verified_cards: list[dict] = []
            for card in so_cards:
                is_approved = so_approved.get(card.id, False)
                checked = st.checkbox(
                    f"{card.name}",
                    value=is_approved,
                    key=f"signoff_check_{card.id}",
                )
                if checked:
                    verified_cards.append({"name": card.name, "url": card.url or ""})

            st.divider()

            # ── Bugs added to backlog ─────────────────────────────────────
            st.markdown("#### Cards added to Backlog")
            st.caption("Bugs found during this QA cycle (auto-filled from Bug Tracker):")

            # Allow adding extra bug names manually
            extra_bugs_raw = st.text_area(
                "Bug titles (one per line)",
                value="\n".join(so_bugs_raised),
                height=100,
                key="signoff_bugs_text",
                placeholder="customsClearanceDetail is passing in Domestic Shipment Request-FedEx REST\nHazmat Label Generation Fails...",
            )
            backlog_cards = [b.strip() for b in extra_bugs_raw.splitlines() if b.strip()]

            st.divider()

            # ── Mentions ──────────────────────────────────────────────────
            st.markdown("#### Slack Mentions")

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                mentions_raw = st.text_input(
                    "Tag team members (space-separated Slack IDs or names)",
                    value="here",
                    placeholder="here U0123456 ajeeshpu Deepak Sanoop",
                    key="signoff_mentions",
                    help="Use 'here' for @here, Slack user IDs (U...) for @mentions, or plain names",
                )
            with col_m2:
                cc_raw = st.text_input(
                    "CC (manager / lead)",
                    placeholder="Ashok Kumar N or U0123456",
                    key="signoff_cc",
                )

            qa_lead_name = st.text_input(
                "Your name (QA lead signing off)",
                placeholder="e.g. Madan",
                key="signoff_qa_lead",
            )

            # ── Release name override ─────────────────────────────────────
            so_release_input = st.text_input(
                "Release name",
                value=so_release,
                placeholder="e.g. MCSL 1.0.375p_1",
                key="signoff_release",
            )

            st.divider()

            # ── Live preview ──────────────────────────────────────────────
            st.markdown("#### Message Preview")

            mentions_list = [m.strip() for m in mentions_raw.split() if m.strip()]

            # Build preview text (same logic as slack_client)
            preview_mentions = []
            for m in mentions_list:
                if m in ("here", "channel"):
                    preview_mentions.append(f"@{m}")
                else:
                    preview_mentions.append(f"@{m}")
            preview_mention_line = "  ".join(preview_mentions)

            preview_cards_block = "\n".join(
                f"{c['name']}\n{c['url']}" if c.get("url") else c["name"]
                for c in verified_cards
            ) or "(no cards selected)"

            preview_lines = [
                preview_mention_line,
                "",
                f"We've completed testing  *{so_release_input}*  and it's good for the release ✅",
                "",
                "*Cards Verified:*",
                "",
                preview_cards_block,
                "",
            ]
            if backlog_cards:
                preview_lines += [
                    "*Cards added to backlog :*",
                    "",
                    "\n".join(backlog_cards),
                    "",
                ]
            preview_lines.append("*QA Signed off* 🎉")
            if cc_raw.strip():
                preview_lines += ["", f"CC: @{cc_raw.strip()}"]
            if qa_lead_name.strip():
                preview_lines += [f"Signed by: {qa_lead_name.strip()}"]

            preview_text = "\n".join(preview_lines)
            st.code(preview_text, language=None)

            st.divider()

            # ── Send button ───────────────────────────────────────────────
            signoff_sent = st.session_state.get("signoff_sent", False)

            if signoff_sent:
                st.success("🎉 Sign-off message sent to Slack!")
                if st.button("📤 Send again", key="signoff_resend"):
                    st.session_state["signoff_sent"] = False
                    st.rerun()
            else:
                send_disabled = len(verified_cards) == 0
                if send_disabled:
                    st.caption("⚠️ Select at least one verified card to enable sending.")

                col_send, col_trello = st.columns(2)

                with col_send:
                    if slack_configured():
                        if st.button(
                            "📣 Send Sign-Off to Slack",
                            type="primary",
                            use_container_width=True,
                            disabled=send_disabled,
                            key="signoff_send_btn",
                        ):
                            with st.spinner("Posting sign-off to Slack…"):
                                result = post_signoff(
                                    release=so_release_input,
                                    verified_cards=verified_cards,
                                    backlog_cards=backlog_cards,
                                    mentions=mentions_list,
                                    cc=cc_raw.strip(),
                                    qa_lead=qa_lead_name.strip(),
                                )
                            if result["ok"]:
                                st.session_state["signoff_sent"] = True
                                st.rerun()
                            else:
                                st.error(f"❌ Slack error: {result['error']}")
                    else:
                        st.warning("Slack not configured — set SLACK_WEBHOOK_URL in .env")

                with col_trello:
                    if st.button(
                        "✅ Mark Cards Done in Trello",
                        use_container_width=True,
                        disabled=len(verified_cards) == 0,
                        key="signoff_trello_btn",
                    ):
                        if trello_ok:
                            from pipeline.trello_client import TrelloClient
                            trello_cl = TrelloClient()
                            moved = 0
                            for card in so_cards:
                                if so_approved.get(card.id) and any(
                                    v["name"] == card.name for v in verified_cards
                                ):
                                    try:
                                        trello_cl.add_comment(
                                            card.id,
                                            f"✅ QA Signed off — {so_release_input} · "
                                            f"Signed by: {qa_lead_name or 'QA Team'}",
                                        )
                                        moved += 1
                                    except Exception as exc:
                                        st.warning(f"Trello comment failed for {card.name}: {exc}")
                            st.success(f"✅ Sign-off comment added to {moved} Trello card(s)")

            # ── Export release cards to Google Sheet ─────────────────────────
            st.divider()
            st.markdown("#### 📊 Export Release to Google Sheet")
            st.caption(
                "Creates a new sheet tab named after the release in the FedEx Release doc — "
                "one row per card with URL, description, ticket, toggle info and API type."
            )

            col_sheet, col_sheet_info = st.columns([1, 2])
            with col_sheet:
                export_disabled = len(so_cards) == 0
                if st.button(
                    "📊 Export to Sheet",
                    use_container_width=True,
                    disabled=export_disabled,
                    key="signoff_sheet_btn",
                    type="primary",
                ):
                    from pipeline.sheets_writer import create_release_sheet
                    rel_name = so_release_input or so_release or "Release"
                    with st.spinner(f"Creating sheet tab '{rel_name}'…"):
                        try:
                            result = create_release_sheet(
                                release_name=rel_name,
                                cards=so_cards,
                                list_name=st.session_state.get("rqa_list_name", rel_name),
                            )
                            st.session_state["signoff_sheet_result"] = result
                        except Exception as exc:
                            st.session_state["signoff_sheet_result"] = {"error": str(exc)}
                    st.rerun()

            with col_sheet_info:
                sheet_res = st.session_state.get("signoff_sheet_result")
                if sheet_res:
                    if "error" in sheet_res:
                        st.error(f"❌ Sheet export failed: {sheet_res['error']}")
                    else:
                        action = "Created" if sheet_res.get("created") else "Updated"
                        st.success(
                            f"✅ {action} tab **{sheet_res['tab']}** — "
                            f"{sheet_res['rows_added']} cards written"
                        )
                        st.markdown(f"[🔗 Open Sheet]({sheet_res['sheet_url']})")


    # ── Tab: Manual Automation ──────────────────────────────────────────────
    with tab_manual:
        st.markdown(
            '<div class="step-chip">✍️ Write Automation</div>',
            unsafe_allow_html=True,
        )
        st.markdown("## ✍️ Write Automation")
        st.caption(
            "Write test cases manually → Chrome Agent walks the live app → "
            "generates POM + spec — no Trello card needed."
        )

        if not api_ok:
            st.error("❌ ANTHROPIC_API_KEY not set — add it to .env to use this feature")
        else:
            import re as _re

            # ── Step 1: Feature Info ──────────────────────────────────────
            _step_header("1", "Feature Details")

            col_name, col_path = st.columns(2)
            with col_name:
                ma_feature = st.text_input(
                    "Feature name",
                    placeholder="e.g. FedEx Hold at Location",
                    key="ma_feature_name",
                    help="Used as the card name for POM matching and code generation",
                )
            with col_path:
                ma_app_path = st.text_input(
                    "App path (optional)",
                    placeholder="e.g. settings/additional-services",
                    key="ma_app_path",
                    help="Sub-path in the FedEx app. Leave blank to start from the app root.",
                )

            col_branch, col_dryrun = st.columns([3, 1])
            with col_branch:
                ma_branch = st.text_input(
                    "Branch name",
                    value=f"automation/{_re.sub(r'[^a-z0-9]+', '-', (ma_feature or 'manual').lower()).strip('-')[:40]}",
                    key="ma_branch",
                )
            with col_dryrun:
                st.write("")
                ma_dry = st.checkbox("Dry run", value=True, key="ma_dry",
                                     help="Preview generated code without writing to disk")
                ma_push = st.checkbox("Push branch", value=False, key="ma_push")

            st.divider()

            # ── Step 2: Feature detection preview ────────────────────────
            _step_header("2", "Feature Type Detection")

            det_key = "ma_detection"
            ma_det = st.session_state.get(det_key)

            if ma_feature:
                if st.button("🔍 Detect New or Existing", key="ma_detect_btn"):
                    from pipeline.feature_detector import detect_feature
                    with st.spinner("Checking codebase for existing POM…"):
                        ma_det = detect_feature(ma_feature, "")
                    st.session_state[det_key] = ma_det
                    st.rerun()

                if ma_det:
                    kind_icon  = "🆕" if ma_det.kind == "new" else "✏️"
                    kind_color = "#d1fae5" if ma_det.kind == "new" else "#e0e7ff"
                    kind_text  = "#065f46" if ma_det.kind == "new" else "#3730a3"
                    st.markdown(
                        f'<div style="background:{kind_color};color:{kind_text};'
                        f'border-radius:8px;padding:10px 16px;margin:8px 0;font-weight:600">'
                        f'{kind_icon} {ma_det.kind.upper()} FEATURE — '
                        f'{ma_det.confidence:.0%} confidence<br>'
                        f'<span style="font-weight:400;font-size:0.85rem">{ma_det.reasoning[:200]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if ma_det.related_files:
                        st.caption("Related files: " + " · ".join(
                            f"`{f}`" for f in ma_det.related_files[:4]
                        ))
            else:
                st.caption("Enter a feature name above to detect new vs existing.")

            st.divider()

            # ── Step 3: Write Test Cases ──────────────────────────────────
            _step_header("3", "Write Test Cases")
            st.caption(
                "Type your manual test cases below — positive scenarios, "
                "edge cases, anything you want automated."
            )

            ma_tc = st.text_area(
                "Test cases",
                height=280,
                key="ma_test_cases",
                placeholder=(
                    "### TC-1: Enable Hold at Location\n"
                    "**Steps:**\n"
                    "1. Go to Settings → Additional Services\n"
                    "2. Enable 'Hold at Location' toggle\n"
                    "3. Click Save\n"
                    "**Expected:** Toast shows 'Updated'\n\n"
                    "### TC-2: Verify toggle persists after reload\n"
                    "**Steps:**\n"
                    "1. Reload the page\n"
                    "2. Check 'Hold at Location' toggle state\n"
                    "**Expected:** Toggle remains enabled"
                ),
            )

            st.divider()

            # ── Step 4: Chrome Agent ──────────────────────────────────────
            _step_header("4", "Explore App with Chrome Agent (recommended)")
            st.caption(
                "Agent navigates the live app, captures real UI elements at each step. "
                "Gives Claude grounded locators instead of guessed ones."
            )

            trace_key = "ma_chrome_trace"
            ma_trace  = st.session_state.get(trace_key)

            if ma_trace:
                if ma_trace.error:
                    st.error(f"❌ Agent error: {ma_trace.error}")
                else:
                    st.markdown(
                        f'<div style="background:#d1fae5;color:#065f46;border-radius:8px;'
                        f'padding:10px 16px;margin:8px 0;font-weight:600">'
                        f'✅ Agent explored {len(ma_trace.steps)} steps · '
                        f'{len(ma_trace.final_elements.splitlines())} UI elements captured'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    with st.expander("🌐 View agent navigation path", expanded=False):
                        st.markdown(ma_trace.navigation_path or "(no steps)")
                        elements = ma_trace.final_elements.splitlines()
                        if elements:
                            st.caption("Elements captured:")
                            for el in elements[:30]:
                                st.caption(f"  • {el}")
                            if len(elements) > 30:
                                st.caption(f"  …and {len(elements)-30} more")

            col_exp, col_maxsteps = st.columns([2, 1])
            with col_maxsteps:
                ma_max_steps = st.slider("Max steps", 4, 20, 12, key="ma_max_steps")
            with col_exp:
                explore_disabled = not ma_feature.strip()
                if st.button(
                    "🌐 Explore App Now",
                    key="ma_explore_btn",
                    use_container_width=True,
                    disabled=explore_disabled,
                    help="Opens Chrome, navigates the app, captures UI elements",
                ):
                    from pipeline.chrome_agent import explore_with_agent
                    with st.spinner(f"🌐 Chrome Agent exploring '{ma_feature}'… (up to {ma_max_steps} steps)"):
                        ma_trace = explore_with_agent(
                            card_name=ma_feature,
                            acceptance_criteria=ma_tc or f"Explore the {ma_feature} feature",
                            app_path=ma_app_path.strip(),
                            max_steps=ma_max_steps,
                        )
                    st.session_state[trace_key] = ma_trace
                    st.rerun()

            st.divider()

            # ── Step 5: Generate Automation ───────────────────────────────
            _step_header("5", "Generate Playwright Automation")

            chrome_ctx = (
                ma_trace.to_context_string()
                if ma_trace and not ma_trace.error
                else ""
            )

            if chrome_ctx:
                st.success(
                    f"✅ Will use Chrome Agent trace "
                    f"({len(ma_trace.steps)} steps) for grounded locator generation."
                )
            else:
                st.info(
                    "ℹ️ No agent trace — code will be generated from test cases + "
                    "RAG knowledge base. Run Step 4 for grounded locators."
                )

            ma_qa_context = st.text_area(
                "🧪 QA Test Context (optional)",
                key="ma_qa_context",
                placeholder=(
                    "Tell the AI specific data to use, e.g.:\n"
                    "• Use HS code 123456 on product 'Test Shirt'\n"
                    "• Enable Dry Ice with weight 2.5 kg\n"
                    "• Use FedEx International Priority service"
                ),
                height=90,
                help="Specific product names, HS codes, settings values or any test data the AI should use in the generated tests.",
            )

            gen_disabled = not ma_feature.strip() or not ma_tc.strip()
            if gen_disabled:
                st.caption("⚠️ Enter feature name and test cases above to enable generation.")

            ma_auto_fix = st.toggle(
                "🔄 Auto-run & fix until passing",
                key="ma_auto_fix",
                value=False,
                help=(
                    "After writing code, automatically run the tests. "
                    "If they fail, Claude reads the errors and fixes the code, "
                    "then re-runs. Repeats up to 3 times."
                ),
            )

            if st.button(
                "⚙️ Generate Automation Code",
                key="ma_generate_btn",
                type="primary",
                use_container_width=True,
                disabled=gen_disabled,
            ):
                from pipeline.automation_writer import write_automation
                label = (
                    "✍️ Generating from live app trace…"
                    if chrome_ctx else
                    "✍️ Claude is writing Playwright tests…"
                )
                ma_fix_ph = st.empty()
                def _ma_on_fix(iteration, status, output, _ph=ma_fix_ph):
                    _ph.info(f"🔄 **Auto-fix iteration {iteration}/3** — {status}")
                with st.spinner(label):
                    ma_result = write_automation(
                        card_name=ma_feature,
                        test_cases_markdown=ma_tc,
                        acceptance_criteria=ma_tc,
                        branch_name=ma_branch,
                        dry_run=ma_dry,
                        push=ma_push,
                        chrome_trace_context=chrome_ctx,
                        qa_context=ma_qa_context.strip(),
                        auto_fix=ma_auto_fix and not ma_dry,
                        fix_iterations=3,
                        on_fix_progress=_ma_on_fix,
                    )
                st.session_state["ma_result"] = ma_result
                st.rerun()

            # ── Step 6: Results ───────────────────────────────────────────
            ma_result = st.session_state.get("ma_result")
            if ma_result:
                st.divider()
                _step_header("6", "Results")

                err = ma_result.get("error", "")
                if err:
                    st.error(f"❌ Generation failed: {err}")
                else:
                    kind       = ma_result.get("kind", "")
                    files      = ma_result.get("files_written", [])
                    branch     = ma_result.get("branch", "")
                    pushed     = ma_result.get("pushed", False)
                    agent_steps = ma_result.get("chrome_trace_steps", 0)

                    kind_badge  = "🆕 New POM created" if kind == "new_pom" else "✏️ Existing POM updated"
                    agent_badge = f" · 🌐 {agent_steps}-step agent trace" if agent_steps else ""

                    st.markdown(
                        f'<div style="background:#d1fae5;color:#065f46;border-radius:10px;'
                        f'padding:14px 18px;margin:8px 0">'
                        f'<div style="font-weight:700;font-size:1rem">'
                        f'✅ {kind_badge}{agent_badge}</div>'
                        f'<div style="margin-top:6px;font-size:0.85rem">'
                        f'{len(files)} file(s) written</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Files written
                    if files:
                        st.markdown("**Files:**")
                        for f in files:
                            icon = "📋" if f.endswith(".spec.ts") else "📄"
                            st.code(f"{icon}  {f}", language=None)

                    # Auto-fix results
                    fix_history = ma_result.get("fix_history", [])
                    if fix_history:
                        fix_passed = ma_result.get("fix_passed", False)
                        fix_iters  = ma_result.get("fix_iterations", 0)
                        if fix_passed:
                            st.success(f"✅ Tests passing after {fix_iters} run(s)")
                        else:
                            st.warning(f"⚠️ Tests still failing after {fix_iters} auto-fix attempt(s)")
                        with st.expander("🔍 Auto-fix run history", expanded=not fix_passed):
                            for run in fix_history:
                                icon = "✅" if run["passed"] else "❌"
                                st.markdown(f"**{icon} Iteration {run['iteration']}**")
                                if run.get("fixed_files"):
                                    st.caption("Fixed: " + ", ".join(f"`{x}`" for x in run["fixed_files"]))
                                with st.expander(f"Output (iter {run['iteration']})", expanded=False):
                                    st.code(run.get("output", "")[-2000:], language="text")

                    # Branch
                    if branch:
                        col_b, col_push = st.columns([3, 1])
                        with col_b:
                            st.info(f"🌿 Branch: `{branch}`")
                        with col_push:
                            if not pushed:
                                if st.button("🚀 Push to origin", key="ma_push_btn"):
                                    from pipeline.automation_writer import _push_branch
                                    ok, out = _push_branch(branch)
                                    if ok:
                                        st.success(f"✅ Pushed `{branch}`!")
                                        ma_result["pushed"] = True
                                        st.session_state["ma_result"] = ma_result
                                    else:
                                        st.error(f"Push failed: {out}")
                            else:
                                st.success("✅ Pushed")

                    # Preview generated files
                    spec_file = ma_result.get("spec_file", "")
                    pom_file  = ma_result.get("pom_file", "")
                    if spec_file or pom_file:
                        from pathlib import Path as _Path
                        import config as _cfg
                        codebase = _Path(_cfg.AUTOMATION_CODEBASE_PATH)
                        for fpath, label in [(spec_file, "Spec"), (pom_file, "POM")]:
                            if fpath:
                                full = codebase / fpath
                                if full.exists():
                                    with st.expander(f"👁 Preview {label}: `{fpath}`", expanded=False):
                                        st.code(full.read_text(encoding="utf-8"), language="typescript")

                    # Update RAG
                    rag_key = "ma_rag_done"
                    if not st.session_state.get(rag_key):
                        try:
                            from pipeline.rag_updater import update_rag_from_card
                            with st.spinner("📚 Updating knowledge base…"):
                                rag_res = update_rag_from_card(
                                    card_id=f"manual_{_re.sub(r'[^a-z0-9]', '', ma_feature.lower())}",
                                    card_name=ma_feature,
                                    description=ma_tc,
                                    acceptance_criteria=ma_tc,
                                    test_cases=ma_tc,
                                    release="manual",
                                )
                            st.session_state[rag_key] = True
                            st.caption(f"📚 Knowledge base updated ({rag_res.get('chunks_added', 0)} chunks)")
                        except Exception as rag_exc:
                            st.caption(f"⚠️ RAG update skipped: {rag_exc}")

                    # Reset button
                    st.divider()
                    if st.button("🔄 Start New", key="ma_reset_btn"):
                        for k in ["ma_result", "ma_chrome_trace", "ma_detection", "ma_rag_done"]:
                            st.session_state.pop(k, None)
                        st.rerun()


if __name__ == "__main__":
    main()
