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

import streamlit as st

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FedEx Delivery Pipeline",
    page_icon="🚚",
    layout="wide",
)

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

def main():
    _init_state()

    st.title("🚚 FedEx Delivery Pipeline")
    st.caption("End-to-end automation: Trello card → Acceptance Criteria → Tests → Sign Off")

    # ── Sidebar: credentials check ─────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Config")

        import config
        api_ok = bool(config.ANTHROPIC_API_KEY)
        trello_ok = all([
            os.getenv("TRELLO_API_KEY"),
            os.getenv("TRELLO_TOKEN"),
            os.getenv("TRELLO_BOARD_ID"),
        ])

        st.markdown(f"**Claude API:** {'✅ Connected' if api_ok else '❌ Add ANTHROPIC_API_KEY to .env'}")
        st.markdown(f"**Trello:** {'✅ Connected' if trello_ok else '❌ Add TRELLO_* keys to .env'}")
        st.markdown(f"**Ollama (embeddings):** ✅ nomic-embed-text")
        st.divider()
        dry_run = st.toggle("🧪 Dry Run (no writes)", value=True)
        st.caption("Dry run: shows output without writing to Trello or repo")

    # ── Tab layout ──────────────────────────────────────────────────────────
    tab_release, tab_devdone, tab_run, tab_history, tab_signoff = st.tabs([
        "🚀 Release QA", "🛠️ Dev Done", "▶️ Run Pipeline", "📋 History", "✅ Sign Off"
    ])

    # ── Tab 0: Release QA ───────────────────────────────────────────────────
    with tab_release:
        st.subheader("🚀 Release QA — Test Case Generator")
        st.caption("Pick a release list → Claude generates test cases → review → approve → saved to Trello card")

        if not api_ok:
            st.error("❌ Add ANTHROPIC_API_KEY to .env to use this feature")
        elif not trello_ok:
            st.error("❌ Add TRELLO_* credentials to .env to use this feature")
        else:
            from pipeline.trello_client import TrelloClient
            from pipeline.card_processor import (
                generate_test_cases, regenerate_with_feedback, write_test_cases_to_card
            )
            from pipeline.sheets_writer import append_to_sheet, detect_tab, SHEET_TABS
            from pathlib import Path

            sheets_ready = Path(config.GOOGLE_CREDENTIALS_PATH).exists()
            if not sheets_ready:
                st.warning("⚠️ No credentials.json — test cases won't be added to Google Sheets. "
                           "Add service account key to enable sheet sync.")

            # -- List selector
            col_refresh = st.columns([1])[0]
            with col_refresh:
                if st.button("🔄 Refresh lists from Trello"):
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

            # -- Load cards into session state
            if load_btn:
                trello = TrelloClient()
                cards = trello.get_cards_in_list(selected_list_id)
                st.session_state["rqa_cards"] = cards
                st.session_state["rqa_list_name"] = selected_list_name
                st.session_state["rqa_release"] = release_label
                # Clear previous test cases on new load
                st.session_state["rqa_test_cases"] = {}
                st.session_state["rqa_approved"] = {}
                st.info(f"Loaded {len(cards)} cards from **{selected_list_name}**")

            # -- Show cards + generate test cases
            if "rqa_cards" in st.session_state and st.session_state["rqa_cards"]:
                cards = st.session_state["rqa_cards"]
                tc_store = st.session_state.setdefault("rqa_test_cases", {})
                approved_store = st.session_state.setdefault("rqa_approved", {})
                current_release = st.session_state.get("rqa_release", release_label)

                st.divider()
                approved_count = sum(1 for v in approved_store.values() if v)
                st.markdown(f"**{len(cards)} cards** · {approved_count} approved ✅ · {len(cards) - approved_count} pending")

                for card in cards:
                    is_approved = approved_store.get(card.id, False)
                    status_icon = "✅" if is_approved else "⏳"

                    with st.expander(f"{status_icon} {card.name}", expanded=not is_approved):

                        if card.desc:
                            with st.container():
                                st.caption("📋 Card description")
                                st.markdown(card.desc[:500] + ("..." if len(card.desc) > 500 else ""))

                        # Generate test cases if not yet done
                        if card.id not in tc_store:
                            if st.button(f"🤖 Generate Test Cases", key=f"gen_{card.id}"):
                                with st.spinner("Claude is writing test cases…"):
                                    tc_store[card.id] = generate_test_cases(card)
                                st.rerun()
                        else:
                            # Show generated test cases
                            tc = tc_store[card.id]
                            st.markdown(tc)

                            if not is_approved:
                                st.divider()

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

                                col_approve, col_edit = st.columns([1, 2])

                                with col_approve:
                                    if st.button("✅ Approve & Save", key=f"approve_{card.id}",
                                                 use_container_width=True, type="primary"):
                                        trello = TrelloClient()

                                        # 1. Write to Trello card
                                        with st.spinner("Saving to Trello…"):
                                            write_test_cases_to_card(card.id, tc, trello)

                                        # 2. Write to Google Sheets
                                        if sheets_ready:
                                            with st.spinner(f"Adding to '{chosen_tab}' sheet…"):
                                                try:
                                                    result = append_to_sheet(
                                                        card_name=card.name,
                                                        test_cases_markdown=tc,
                                                        tab_name=chosen_tab,
                                                        release=current_release,
                                                    )
                                                    st.success(
                                                        f"✅ Saved to Trello + "
                                                        f"[{result['rows_added']} rows → '{result['tab']}' sheet]"
                                                        f"({result['sheet_url']})"
                                                    )
                                                except Exception as e:
                                                    st.warning(f"Trello saved ✅ but Sheets failed: {e}")
                                        else:
                                            st.success("✅ Saved to Trello card!")

                                        approved_store[card.id] = True
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

                # Bulk approve all
                st.divider()
                if approved_count < len(cards):
                    if st.button("✅ Approve ALL remaining", type="primary"):
                        trello = TrelloClient()
                        remaining = [c for c in cards if not approved_store.get(c.id)]
                        for card in remaining:
                            if card.id in tc_store:
                                write_test_cases_to_card(card.id, tc_store[card.id], trello)
                                approved_store[card.id] = True
                        st.success(f"✅ All {len(remaining)} cards saved to Trello!")
                        st.rerun()

    # ── Tab 1: Dev Done ─────────────────────────────────────────────────────
    with tab_devdone:
        st.subheader("🛠️ Dev Done")
        st.caption("Cards completed by dev — review and move to Ready for QA")

        if not trello_ok:
            st.error("❌ Add TRELLO_* credentials to .env")
        else:
            from pipeline.trello_client import TrelloClient

            col_dd1, col_dd2, col_dd3 = st.columns([3, 1, 1])
            with col_dd1:
                # Let user pick which "Done" list to view
                @st.cache_data(ttl=60)
                def _get_all_lists():
                    return [(l.name, l.id) for l in TrelloClient().get_lists()]

                all_board_lists = _get_all_lists()
                done_lists = [
                    (name, lid) for name, lid in all_board_lists
                    if any(k in name.lower() for k in ["dev done", "done", "in dev", "handed off"])
                ]
                done_list_names = [name for name, _ in done_lists]
                default_done_idx = next(
                    (i for i, n in enumerate(done_list_names) if n.lower() == "dev done"), 0
                )
                selected_done_list = st.selectbox(
                    "View list", done_list_names, index=default_done_idx, key="dd_list_select"
                )
                selected_done_id = next(lid for name, lid in done_lists if name == selected_done_list)

            with col_dd2:
                st.write("")
                st.write("")
                load_done_btn = st.button("📥 Load", use_container_width=True, key="dd_load")

            with col_dd3:
                st.write("")
                st.write("")
                if st.button("🔄 Refresh", use_container_width=True, key="dd_refresh"):
                    st.cache_data.clear()
                    st.rerun()

            # Target list for "Move to QA"
            qa_lists_names = [
                name for name, _ in all_board_lists
                if "ready for qa" in name.lower()
            ]
            move_target = st.selectbox(
                "Move selected cards to →",
                qa_lists_names,
                key="dd_move_target"
            )

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
                st.markdown(f"**{len(dd_cards)} cards** in `{selected_done_list}`")

                # Select all toggle
                col_selall, col_movebtn = st.columns([2, 1])
                with col_selall:
                    if st.checkbox("Select all", key="dd_select_all"):
                        for c in dd_cards:
                            dd_checked[c.id] = True

                selected_ids = [cid for cid, checked in dd_checked.items() if checked]
                with col_movebtn:
                    move_btn = st.button(
                        f"➡️ Move {len(selected_ids)} to QA",
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

    # ── Tab 2: Run Pipeline ─────────────────────────────────────────────────
    with tab_run:
        st.subheader("Process a Card")
        col1, col2 = st.columns([3, 1])

        with col1:
            card_input = st.text_input(
                "Trello Card ID or URL",
                placeholder="5f3a2b1c… or https://trello.com/c/…",
            )

        with col2:
            run_btn = st.button("🚀 Run", use_container_width=True,
                                disabled=not (card_input and api_ok))

        # Also allow manual AC input for testing without Trello
        with st.expander("🔧 Or test without Trello (manual input)"):
            manual_name = st.text_input("Feature name", placeholder="FedEx Hold at Location")
            manual_ac = st.text_area("Raw feature description / AC", height=150,
                                     placeholder="As a merchant I want to enable Hold at Location…")
            manual_btn = st.button("▶️ Run manual input",
                                   disabled=not (manual_name and manual_ac and api_ok))

        if run_btn and card_input:
            card_id = card_input.split("/c/")[-1].split("/")[0] if "trello.com" in card_input else card_input.strip()
            result = _run_pipeline_for_card(card_id, dry_run)
            st.session_state.pipeline_runs[card_id] = result
            st.json(result, expanded=False)

        if manual_btn and manual_name and manual_ac:
            from pipeline.feature_detector import detect_feature
            from pipeline.card_processor import generate_acceptance_criteria

            with st.spinner("✍️ Generating acceptance criteria…"):
                ac = generate_acceptance_criteria(f"{manual_name}\n\n{manual_ac}")
            st.subheader("📝 Generated Acceptance Criteria")
            st.markdown(ac)

            with st.spinner("🔍 Detecting feature type…"):
                detection = detect_feature(manual_name, ac)
            st.info(
                f"{'🆕 NEW' if detection.kind == 'new' else '♻️ EXISTING'} feature "
                f"({detection.confidence:.0%} confidence)\n\n{detection.reasoning}"
            )
            if detection.related_files:
                st.write("**Related test files:**")
                for f in detection.related_files:
                    st.code(f, language=None)

    # ── Tab 2: History ──────────────────────────────────────────────────────
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
        st.subheader("Feature Sign Off")
        st.caption("Review generated tests and AC before marking a card as done.")

        if not st.session_state.pipeline_runs:
            st.info("Run the pipeline on a card first.")
        else:
            for card_id, run in st.session_state.pipeline_runs.items():
                if run.get("error"):
                    continue
                with st.container(border=True):
                    col_name, col_btn = st.columns([4, 1])
                    with col_name:
                        st.markdown(f"**{run.get('card_name', card_id)}**")
                        steps_done = len(run.get("steps", {}))
                        st.caption(f"{steps_done} pipeline steps completed")

                    with col_btn:
                        signed_off = st.session_state.get(f"signed_{card_id}", False)
                        if signed_off:
                            st.success("Signed off ✅")
                        else:
                            if st.button("✅ Sign Off", key=f"sign_{card_id}"):
                                st.session_state[f"signed_{card_id}"] = True
                                # Move card to Done in Trello
                                if trello_ok and not dry_run:
                                    try:
                                        from pipeline.trello_client import TrelloClient
                                        trello = TrelloClient()
                                        trello.move_card_to_list(card_id, "Done")
                                        trello.add_comment(card_id, "✅ Signed off via Pipeline Dashboard")
                                    except Exception as e:
                                        st.warning(f"Trello update failed: {e}")
                                st.rerun()


if __name__ == "__main__":
    main()
