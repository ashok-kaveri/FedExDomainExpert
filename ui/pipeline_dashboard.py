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
    tab_run, tab_history, tab_signoff = st.tabs([
        "▶️ Run Pipeline", "📋 History", "✅ Sign Off"
    ])

    # ── Tab 1: Run Pipeline ─────────────────────────────────────────────────
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
