"""
Pipeline Sign-Off Dashboard  —  Step 8
========================================
Streamlit UI that shows the status of every card through the delivery
pipeline and allows the team to sign off features.

Run:
    streamlit run ui/pipeline_dashboard.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime
import json
import logging
import os
import re
import threading
import time

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
# History persistence  — saved to data/pipeline_history.json
# ---------------------------------------------------------------------------

_HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "pipeline_history.json"


def _load_history() -> dict:
    """Load persisted pipeline run history from disk."""
    try:
        if _HISTORY_FILE.exists():
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_history(runs: dict) -> None:
    """Persist pipeline run history to disk."""
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as _e:
        logger.warning("Could not save history: %s", _e)


# ---------------------------------------------------------------------------

def _init_state():
    if "pipeline_runs" not in st.session_state:
        st.session_state.pipeline_runs = _load_history()   # load from disk on first run
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


@st.cache_data(ttl=60)
def _get_board_lists() -> list[tuple[str, str]]:
    """Shared cached fetch of all Trello board lists — (name, id) pairs."""
    from pipeline.trello_client import TrelloClient
    return [(l.name, l.id) for l in TrelloClient().get_lists()]


def main():
    _init_state()

    import config

    # ── Force-initialize code paths from config on first load of each session
    if "code_paths_initialized" not in st.session_state:
        if config.BACKEND_CODE_PATH:
            st.session_state["be_repo_path"] = config.BACKEND_CODE_PATH
        if config.FRONTEND_CODE_PATH:
            st.session_state["fe_repo_path"] = config.FRONTEND_CODE_PATH
        st.session_state["code_paths_initialized"] = True

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

        # ── Code Knowledge Base ───────────────────────────────────────────
        st.markdown("### 🗂️ Code Knowledge Base")
        st.caption("RAG over source code — TCs + automation scripts use real patterns.")

        from rag.code_indexer import get_index_stats, index_codebase, sync_from_git
        _code_stats  = get_index_stats()
        _auto_cnt    = _code_stats.get("automation", 0)
        _be_cnt      = _code_stats.get("backend", 0)
        _fe_cnt      = _code_stats.get("frontend", 0)
        _auto_sync   = _code_stats.get("automation_sync", {})
        _be_sync     = _code_stats.get("backend_sync", {})
        _fe_sync     = _code_stats.get("frontend_sync", {})

        # Status badges
        def _sync_badge(cnt, sync):
            if cnt == 0:
                return "⬜ Not indexed"
            commit = sync.get("commit", "")
            synced = sync.get("synced_at", "")
            tag = f" · `{commit}`" if commit else ""
            return f"✅ {cnt} chunks{tag} · {synced}"

        st.markdown(
            f"<div style='font-size:0.75rem;line-height:1.6'>"
            f"<b>🧪 Automation:</b> {_sync_badge(_auto_cnt, _auto_sync)}<br>"
            f"<b>🖥️ Backend:</b> {_sync_badge(_be_cnt, _be_sync)}<br>"
            f"<b>🌐 Frontend:</b> {_sync_badge(_fe_cnt, _fe_sync)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Automation Code (highest priority — index this first) ─────────
        with st.expander("🧪 Automation Code", expanded=(_auto_cnt == 0)):
            _auto_default = __import__("config").AUTOMATION_CODEBASE_PATH or ""
            _auto_path = st.text_input(
                "Automation repo path",
                value=st.session_state.get("automation_code_path", _auto_default),
                placeholder="/Users/you/projects/fedex-test-automation",
                key="automation_code_path_input",
            )
            st.caption("Index spec files, POMs, helpers — used when writing new automation scripts.")

            # Show current branch + selector
            if _auto_path.strip():
                from rag.code_indexer import get_repo_info
                _auto_repo = get_repo_info(_auto_path.strip())
                if _auto_repo.get("branches"):
                    _auto_branch = st.selectbox(
                        "Branch to pull",
                        options=_auto_repo["branches"],
                        index=_auto_repo["branches"].index(_auto_repo["current_branch"])
                              if _auto_repo["current_branch"] in _auto_repo["branches"] else 0,
                        key="auto_branch_select",
                    )
                    st.caption(f"Current: `{_auto_repo['current_branch']}` @ `{_auto_repo['commit']}`")
                else:
                    _auto_branch = None

            _ac_col1, _ac_col2 = st.columns(2)
            with _ac_col1:
                if st.button("🔄 Pull & Sync", key="sync_auto_btn",
                             use_container_width=True, type="primary",
                             disabled=not _auto_path.strip()):
                    st.session_state["automation_code_path"] = _auto_path.strip()
                    with st.spinner(f"git pull {_auto_branch or ''} → syncing…"):
                        _auto_sync_res = sync_from_git(
                            _auto_path.strip(),
                            source_type="automation",
                            branch=_auto_branch if _auto_branch != _auto_repo.get("current_branch") else None,
                        )
                    if _auto_sync_res.get("error"):
                        st.error(f"❌ {_auto_sync_res['error']}")
                    elif _auto_sync_res.get("message"):
                        st.info(f"ℹ️ {_auto_sync_res['message']}")
                    else:
                        st.success(
                            f"✅ `{_auto_sync_res['commit_before']}` → `{_auto_sync_res['commit_after']}`  "
                            f"| {_auto_sync_res['files_changed']} changed, "
                            f"{_auto_sync_res['chunks_updated']} chunks updated"
                        )
                        if _auto_sync_res.get("diff_summary"):
                            with st.expander("📄 Changed files", expanded=False):
                                st.code("\n".join(_auto_sync_res["diff_summary"]))
                    st.rerun()
            with _ac_col2:
                if st.button("📥 Full Re-index", key="index_auto_btn",
                             use_container_width=True,
                             disabled=not _auto_path.strip()):
                    st.session_state["automation_code_path"] = _auto_path.strip()
                    with st.spinner("Indexing all automation files…"):
                        _auto_result = index_codebase(
                            _auto_path.strip(),
                            source_type="automation",
                            clear_existing=True,
                            extensions=[".ts", ".tsx", ".js"],
                        )
                    if _auto_result.get("error"):
                        st.error(f"❌ {_auto_result['error']}")
                    else:
                        st.success(
                            f"✅ {_auto_result['files_indexed']} files → "
                            f"{_auto_result['chunks_added']} chunks"
                        )
                    st.rerun()

        # ── Backend ──────────────────────────────────────────────────────
        with st.expander("🖥️ Backend Code", expanded=(_be_cnt == 0)):
            _be_path = st.text_input(
                "Backend repo path",
                value=st.session_state.get("backend_code_path",
                      __import__("config").BACKEND_CODE_PATH or ""),
                placeholder="/Users/you/projects/fedex-backend",
                key="be_repo_path",
            )

            if _be_path.strip():
                from rag.code_indexer import get_repo_info as _gri
                _be_repo = _gri(_be_path.strip())
                if _be_repo.get("branches"):
                    _be_branch = st.selectbox(
                        "Branch to pull",
                        options=_be_repo["branches"],
                        index=_be_repo["branches"].index(_be_repo["current_branch"])
                              if _be_repo["current_branch"] in _be_repo["branches"] else 0,
                        key="be_branch_select",
                    )
                    st.caption(f"Current: `{_be_repo['current_branch']}` @ `{_be_repo['commit']}`")
                else:
                    _be_branch = None

            _be_col1, _be_col2 = st.columns(2)
            with _be_col1:
                if st.button("🔄 Pull & Sync", key="sync_be_btn",
                             use_container_width=True, type="primary",
                             disabled=not _be_path.strip()):
                    st.session_state["backend_code_path"] = _be_path.strip()
                    with st.spinner(f"git pull {_be_branch or ''} → syncing…"):
                        _sync_res = sync_from_git(
                            _be_path.strip(), source_type="backend",
                            branch=_be_branch if _be_branch != _be_repo.get("current_branch") else None,
                        )
                    if _sync_res.get("error"):
                        st.error(f"❌ {_sync_res['error']}")
                    elif _sync_res.get("message"):
                        st.info(f"ℹ️ {_sync_res['message']} (commit `{_sync_res['commit_after']}`)")
                    else:
                        st.success(
                            f"✅ `{_sync_res['commit_before']}` → `{_sync_res['commit_after']}`  "
                            f"| {_sync_res['files_changed']} changed, "
                            f"{_sync_res['files_deleted']} deleted, "
                            f"{_sync_res['chunks_updated']} chunks updated"
                        )
                        if _sync_res.get("diff_summary"):
                            with st.expander("📄 Changed files", expanded=False):
                                st.code("\n".join(_sync_res["diff_summary"]))
                    st.rerun()
            with _be_col2:
                if st.button("📥 Full Re-index", key="index_be_btn",
                             use_container_width=True,
                             disabled=not _be_path.strip()):
                    st.session_state["backend_code_path"] = _be_path.strip()
                    with st.spinner("Indexing all backend source files…"):
                        _be_result = index_codebase(
                            _be_path.strip(), source_type="backend", clear_existing=True,
                        )
                    if _be_result.get("error"):
                        st.error(f"❌ {_be_result['error']}")
                    else:
                        st.success(
                            f"✅ {_be_result['files_indexed']} files → "
                            f"{_be_result['chunks_added']} chunks"
                        )
                    st.rerun()

        # ── Frontend ─────────────────────────────────────────────────────
        with st.expander("🌐 Frontend Code", expanded=False):
            _fe_path = st.text_input(
                "Frontend repo path",
                value=st.session_state.get("frontend_code_path",
                      __import__("config").FRONTEND_CODE_PATH or ""),
                placeholder="/Users/you/projects/fedex-frontend",
                key="fe_repo_path",
            )

            if _fe_path.strip():
                from rag.code_indexer import get_repo_info as _gri2
                _fe_repo = _gri2(_fe_path.strip())
                if _fe_repo.get("branches"):
                    _fe_branch = st.selectbox(
                        "Branch to pull",
                        options=_fe_repo["branches"],
                        index=_fe_repo["branches"].index(_fe_repo["current_branch"])
                              if _fe_repo["current_branch"] in _fe_repo["branches"] else 0,
                        key="fe_branch_select",
                    )
                    st.caption(f"Current: `{_fe_repo['current_branch']}` @ `{_fe_repo['commit']}`")
                else:
                    _fe_branch = None

            _fe_col1, _fe_col2 = st.columns(2)
            with _fe_col1:
                if st.button("🔄 Pull & Sync", key="sync_fe_btn",
                             use_container_width=True, type="primary",
                             disabled=not _fe_path.strip()):
                    st.session_state["frontend_code_path"] = _fe_path.strip()
                    with st.spinner(f"git pull {_fe_branch or ''} → syncing…"):
                        _fe_sync_res = sync_from_git(
                            _fe_path.strip(), source_type="frontend",
                            branch=_fe_branch if _fe_branch != _fe_repo.get("current_branch") else None,
                        )
                    if _fe_sync_res.get("error"):
                        st.error(f"❌ {_fe_sync_res['error']}")
                    elif _fe_sync_res.get("message"):
                        st.info(f"ℹ️ {_fe_sync_res['message']}")
                    else:
                        st.success(
                            f"✅ `{_fe_sync_res['commit_before']}` → `{_fe_sync_res['commit_after']}`  "
                            f"| {_fe_sync_res['files_changed']} changed, "
                            f"{_fe_sync_res['chunks_updated']} chunks updated"
                        )
                        if _fe_sync_res.get("diff_summary"):
                            with st.expander("📄 Changed files", expanded=False):
                                st.code("\n".join(_fe_sync_res["diff_summary"]))
                    st.rerun()
            with _fe_col2:
                if st.button("📥 Full Re-index", key="index_fe_btn",
                             use_container_width=True,
                             disabled=not _fe_path.strip()):
                    st.session_state["frontend_code_path"] = _fe_path.strip()
                    with st.spinner("Indexing all frontend source files…"):
                        _fe_result = index_codebase(
                            _fe_path.strip(), source_type="frontend", clear_existing=True,
                        )
                    if _fe_result.get("error"):
                        st.error(f"❌ {_fe_result['error']}")
                    else:
                        st.success(
                            f"✅ {_fe_result['files_indexed']} files → "
                            f"{_fe_result['chunks_added']} chunks"
                        )
                    st.rerun()

        # ── Wiki Knowledge Base ───────────────────────────────────────────
        st.markdown("### 📖 Wiki Knowledge Base")
        st.caption("Internal fedex-wiki markdown docs — bugs, features, API quirks, support insights.")

        from rag.vectorstore import get_source_count, delete_by_source_type, add_documents as _vs_add
        _wiki_cnt = get_source_count("wiki")

        # Status badge
        if _wiki_cnt > 0:
            st.markdown(
                f'<div class="status-badge status-ok">✅ &nbsp;Wiki — {_wiki_cnt:,} chunks indexed</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="status-badge status-warn">⚠️ &nbsp;Wiki — not indexed yet</div>',
                unsafe_allow_html=True,
            )

        with st.expander("📖 Wiki Docs", expanded=(_wiki_cnt == 0)):
            import subprocess as _sp

            _wiki_path = st.text_input(
                "Wiki folder path",
                value=st.session_state.get("wiki_path",
                      __import__("config").WIKI_PATH or ""),
                placeholder="/Users/you/Documents/fedex-wiki",
                key="wiki_path_input",
            )

            # Show git info if it's a git repo
            _wiki_is_git = False
            _wiki_branch = None
            _wiki_commit = "(unknown)"
            if _wiki_path.strip():
                try:
                    import os as _os
                    _git_env = {
                        **_os.environ,
                        "GIT_TERMINAL_PROMPT": "0",
                        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=no",
                    }
                    _wb = _sp.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=_wiki_path.strip(), capture_output=True, text=True,
                        timeout=5, env=_git_env,
                    )
                    if _wb.returncode == 0:
                        _wiki_is_git = True
                        _wiki_branch = _wb.stdout.strip()
                        _wc = _sp.run(
                            ["git", "log", "-1", "--format=%h %s"],
                            cwd=_wiki_path.strip(), capture_output=True, text=True,
                            timeout=5, env=_git_env,
                        )
                        _wiki_commit = _wc.stdout.strip() if _wc.returncode == 0 else "(unknown)"
                        st.caption(f"Git repo — branch `{_wiki_branch}` @ `{_wiki_commit}`")
                except Exception:
                    pass

            _wk_col1, _wk_col2 = st.columns(2)

            with _wk_col1:
                _pull_label = "🔄 Pull & Re-index" if _wiki_is_git else "🔄 Pull & Re-index"
                if st.button(_pull_label, key="wiki_pull_btn",
                             use_container_width=True, type="primary",
                             disabled=not (_wiki_path.strip() and _wiki_is_git)):
                    st.session_state["wiki_path"] = _wiki_path.strip()
                    with st.spinner("git pull → re-indexing wiki…"):
                        try:
                            # 1. Pull latest
                            _pull = _sp.run(
                                ["git", "pull"],
                                cwd=_wiki_path.strip(), capture_output=True, text=True, timeout=60,
                            )
                            _pull_msg = _pull.stdout.strip() or _pull.stderr.strip()
                            # 2. Delete old wiki chunks
                            _deleted = delete_by_source_type("wiki")
                            # 3. Re-index
                            from ingest.wiki_loader import load_wiki_docs as _lwiki
                            _new_docs = _lwiki()
                            _vs_add(_new_docs)
                            st.success(
                                f"✅ git pull: {_pull_msg[:80]}  \n"
                                f"Removed {_deleted} old chunks → added {len(_new_docs)} new chunks"
                            )
                        except Exception as _we:
                            st.error(f"❌ {_we}")
                    st.rerun()

            with _wk_col2:
                if st.button("📥 Full Re-index", key="wiki_reindex_btn",
                             use_container_width=True,
                             disabled=not _wiki_path.strip()):
                    st.session_state["wiki_path"] = _wiki_path.strip()
                    with st.spinner("Re-indexing all wiki markdown files…"):
                        try:
                            import config as _cfg
                            _cfg.WIKI_PATH = _wiki_path.strip()   # honour path change
                            _deleted = delete_by_source_type("wiki")
                            from ingest.wiki_loader import load_wiki_docs as _lwiki2
                            _new_docs = _lwiki2()
                            _vs_add(_new_docs)
                            st.success(
                                f"✅ Removed {_deleted} old chunks → "
                                f"indexed {len(_new_docs)} chunks from wiki"
                            )
                        except Exception as _we2:
                            st.error(f"❌ {_we2}")
                    st.rerun()

        st.divider()

        dry_run = st.toggle("🧪 Dry Run (no writes)", value=False)
        st.caption("Generates output without writing to Trello, repo, or Sheets.")

    # ── Tab layout ──────────────────────────────────────────────────────────
    tab_us, tab_devdone, tab_release, tab_history, tab_signoff, tab_manual, tab_run = st.tabs([
        "📝 User Story", "🔀 Move Cards", "🚀 Release QA", "📋 History", "✅ Sign Off", "✍️ Write Automation", "▶️ Run Automation"
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
                all_lists = _get_board_lists()

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
            def _extract_release(list_name: str) -> str:
                """Extract release label from list name.
                'Ready for QA FedExapp 2.3.115' → 'FedExapp 2.3.115'
                """
                m = re.search(r'(fedex\w*\s+[\d.]+)', list_name, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
                # fallback: grab any version-like pattern
                m2 = re.search(r'(v?[\d]+\.[\d]+[\d.]*)', list_name)
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

                    # ── Detect if already processed (AC in desc, TCs in comments) ──
                    existing_tc_comment = next(
                        (c for c in (card.comments or []) if "📋 **QA Test Cases" in c),
                        None,
                    )
                    has_existing_ac = bool(card.desc and len(card.desc.strip()) > 30)
                    has_existing_tc = bool(existing_tc_comment)
                    already_done    = has_existing_ac and has_existing_tc

                    # Expander icon shows validation + approval status
                    val_icon  = {"PASS": "🟢", "NEEDS_REVIEW": "🟡", "FAIL": "🔴"}.get(
                        vr.overall_status if vr else "", "⚪"
                    )
                    appr_icon = "✅ " if is_approved else ""
                    done_badge = "⚡ " if already_done and not is_approved else ""
                    with st.expander(f"{appr_icon}{done_badge}{val_icon} {card.name}", expanded=not is_approved):

                        # ── Already processed banner ──────────────────────
                        if already_done and not is_approved:
                            st.info(
                                "⚡ **This card was already processed** — AC is in the description "
                                "and test cases exist in a Trello comment."
                            )
                            col_proc1, col_proc2, col_proc3 = st.columns(3)
                            with col_proc1:
                                if st.button(
                                    "➡️ Proceed to Automation",
                                    key=f"proceed_{card.id}",
                                    use_container_width=True,
                                    type="primary",
                                    help="Skip AC + TC generation — use existing and go straight to writing automation",
                                ):
                                    # Pre-fill TC session state from existing Trello comment
                                    tc_store[card.id] = existing_tc_comment
                                    approved_store[card.id] = True
                                    st.session_state[f"ac_saved_{card.id}"] = True
                                    st.rerun()
                            with col_proc2:
                                if st.button(
                                    "📋 View existing TCs",
                                    key=f"view_tc_{card.id}",
                                    use_container_width=True,
                                ):
                                    st.session_state[f"show_existing_tc_{card.id}"] = True
                            with col_proc3:
                                if st.button(
                                    "🔄 Regenerate",
                                    key=f"banner_regen_{card.id}",
                                    use_container_width=True,
                                    help="Start fresh — will add new rows to Trello + Sheet",
                                ):
                                    st.session_state[f"force_regen_{card.id}"] = True

                            if st.session_state.get(f"show_existing_tc_{card.id}"):
                                with st.expander("📋 Existing test cases (from Trello comment)", expanded=True):
                                    st.markdown(existing_tc_comment)
                                    if st.button("✖ Close", key=f"close_tc_{card.id}"):
                                        del st.session_state[f"show_existing_tc_{card.id}"]
                                        st.rerun()

                        # Skip pipeline steps for already-done cards unless Regenerate chosen
                        if (already_done and not is_approved
                                and not st.session_state.get(f"force_regen_{card.id}", False)):
                            continue

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
                            col_save_ac, col_skip_ac, col_dm_ac, col_ch_ac = st.columns(4)
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
                            with col_dm_ac:
                                if st.button("📨 Send via Slack DM", key=f"open_dm_ac_{card.id}",
                                             use_container_width=True):
                                    st.session_state[f"show_dm_ac_{card.id}"] = True
                                    st.session_state[f"show_ch_ac_{card.id}"] = False
                            with col_ch_ac:
                                if st.button("📢 Send to Channel", key=f"open_ch_ac_{card.id}",
                                             use_container_width=True):
                                    st.session_state[f"show_ch_ac_{card.id}"] = True
                                    st.session_state[f"show_dm_ac_{card.id}"] = False

                            # ── Slack Channel panel (AC) ────────────────────
                            if st.session_state.get(f"show_ch_ac_{card.id}"):
                                from pipeline.slack_client import (
                                    dm_token_configured, list_slack_channels,
                                    post_content_to_slack_channel,
                                )
                                if not dm_token_configured():
                                    st.warning(
                                        "⚠️ SLACK_BOT_TOKEN is not set — channel posting requires a bot token.\n\n"
                                        "Add `SLACK_BOT_TOKEN=xoxb-...` to your `.env` file."
                                    )
                                else:
                                    st.markdown("##### 📢 Post AC to Slack Channel")
                                    _ch_cache_key = "slack_channels_cache"
                                    if _ch_cache_key not in st.session_state:
                                        with st.spinner("Loading channels…"):
                                            _chs, _ch_err, _ch_note = list_slack_channels()
                                        if _ch_err:
                                            st.error(f"❌ {_ch_err}")
                                            _chs = []
                                        st.session_state[_ch_cache_key] = (_chs, _ch_note)
                                    else:
                                        _chs, _ch_note = st.session_state[_ch_cache_key]

                                    if _ch_note:
                                        st.caption(f"ℹ️ {_ch_note}")

                                    if _chs:
                                        _ch_options = {
                                            f"{'🔒' if c['is_private'] else '#'} {c['name']}": c["id"]
                                            for c in _chs
                                        }
                                        _ac_ch_sel_col, _ac_ch_ref_col = st.columns([3, 1])
                                        with _ac_ch_sel_col:
                                            _ac_ch_sel = st.selectbox(
                                                "Select channel",
                                                options=list(_ch_options.keys()),
                                                key=f"ac_ch_select_{card.id}",
                                            )
                                        with _ac_ch_ref_col:
                                            st.markdown("<br>", unsafe_allow_html=True)
                                            if st.button("🔄 Refresh", key=f"ac_ch_refresh_{card.id}",
                                                         use_container_width=True):
                                                del st.session_state[_ch_cache_key]
                                                st.rerun()

                                        _ac_ch_sent_key = f"ac_ch_sent_{card.id}"
                                        if st.session_state.get(_ac_ch_sent_key):
                                            st.success("✅ AC posted to channel!")
                                            if st.button("📢 Post again", key=f"ac_ch_resend_{card.id}"):
                                                st.session_state[_ac_ch_sent_key] = False
                                                st.rerun()
                                        else:
                                            if st.button(
                                                f"📢 Post to {_ac_ch_sel}",
                                                key=f"ac_ch_send_btn_{card.id}",
                                                type="primary",
                                                use_container_width=True,
                                            ):
                                                _sel_ch_id = _ch_options[_ac_ch_sel]
                                                with st.spinner("Posting to channel…"):
                                                    _ch_result = post_content_to_slack_channel(
                                                        channel_id=_sel_ch_id,
                                                        card_name=card.name,
                                                        content_text=ac_suggestion,
                                                        content_label="Acceptance Criteria",
                                                        card_url=getattr(card, "url", ""),
                                                    )
                                                if _ch_result["ok"]:
                                                    st.session_state[_ac_ch_sent_key] = True
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {_ch_result['error']}")

                            # ── Slack DM panel (AC) ─────────────────────────
                            if st.session_state.get(f"show_dm_ac_{card.id}"):
                                from pipeline.slack_client import (
                                    dm_token_configured, search_slack_users, send_ac_dm,
                                )
                                if not dm_token_configured():
                                    st.warning(
                                        "⚠️ SLACK_BOT_TOKEN is not set — DMs require a bot token.\n\n"
                                        "Add `SLACK_BOT_TOKEN=xoxb-...` to your `.env` file."
                                    )
                                else:
                                    st.markdown("##### 📨 Send AC via Slack DM")
                                    # ── Search row ───────────────────────────
                                    _dm_col1, _dm_col2 = st.columns([3, 1])
                                    with _dm_col1:
                                        _dm_query = st.text_input(
                                            "Search member",
                                            placeholder="Search by name — add multiple one by one",
                                            key=f"dm_search_query_{card.id}",
                                        )
                                    with _dm_col2:
                                        st.markdown("<br>", unsafe_allow_html=True)
                                        _do_search = st.button(
                                            "🔍 Search",
                                            key=f"dm_search_btn_{card.id}",
                                            use_container_width=True,
                                        )

                                    # Accumulated user pool (across multiple searches)
                                    _pool_key = f"dm_user_pool_{card.id}"
                                    if _pool_key not in st.session_state:
                                        st.session_state[_pool_key] = {}  # {label: id}

                                    if _do_search and _dm_query.strip():
                                        with st.spinner("Searching…"):
                                            _raw = search_slack_users(_dm_query.strip())
                                        _found, _search_err = (_raw if isinstance(_raw, tuple)
                                                               else (_raw or [], ""))
                                        if _search_err:
                                            st.error(f"❌ {_search_err}")
                                        elif not _found:
                                            st.info("No users found — try a different name.")
                                        else:
                                            # Merge into pool
                                            for u in _found:
                                                _lbl = f"{u['name']} (@{u['display_name']})"
                                                st.session_state[_pool_key][_lbl] = u["id"]
                                            st.success(f"Found {len(_found)} user(s) — select below.")

                                    _pool = st.session_state[_pool_key]
                                    if _pool:
                                        _selected_labels = st.multiselect(
                                            "Select recipients (pick multiple)",
                                            options=list(_pool.keys()),
                                            key=f"dm_user_multi_{card.id}",
                                        )
                                        # Clear pool button
                                        if st.button("✖ Clear search results",
                                                     key=f"dm_clear_{card.id}"):
                                            st.session_state[_pool_key] = {}
                                            st.rerun()

                                        _dm_sent_key = f"ac_dm_sent_{card.id}"
                                        if st.session_state.get(_dm_sent_key):
                                            st.success("✅ AC sent via Slack DM!")
                                            if st.button("📨 Send again",
                                                         key=f"dm_resend_{card.id}"):
                                                st.session_state[_dm_sent_key] = False
                                                st.rerun()
                                        elif _selected_labels:
                                            _selected_uids = [_pool[l] for l in _selected_labels]
                                            _n = len(_selected_uids)
                                            if st.button(
                                                f"📨 Send to {_n} person{'s' if _n > 1 else ''}",
                                                key=f"dm_send_btn_{card.id}",
                                                type="primary",
                                                use_container_width=True,
                                            ):
                                                with st.spinner(f"Sending DM to {_n} recipient(s)…"):
                                                    _dm_result = send_ac_dm(
                                                        user_ids=_selected_uids,
                                                        card_name=card.name,
                                                        ac_text=ac_suggestion,
                                                        content_label="Acceptance Criteria",
                                                    )
                                                if _dm_result["ok"]:
                                                    st.session_state[_dm_sent_key] = True
                                                    st.rerun()
                                                else:
                                                    _s, _f = _dm_result.get("sent",0), _dm_result.get("failed",0)
                                                    if _s:
                                                        st.warning(f"⚠️ Sent to {_s}, failed for {_f}: {_dm_result['error']}")
                                                    else:
                                                        st.error(f"❌ DM failed: {_dm_result['error']}")
                                        else:
                                            st.caption("Select at least one recipient above.")
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

                        # ── STEP 2b: Smart AC Verifier (Agentic) ─────────
                        _step_header("2b", "Smart AC Verifier — Claude walks the live app")
                        st.caption(
                            "Claude opens Chrome, uses automation POM + backend API knowledge "
                            "to navigate to the right page, interacts with the feature, "
                            "watches network calls, and gives a per-scenario verdict. "
                            "If it gets stuck it asks you — you answer, it continues."
                        )

                        _sav_key    = f"sav_report_{card.id}"
                        _sav_qa_key = f"sav_qa_{card.id}"
                        sav_report  = st.session_state.get(_sav_key)
                        sav_qa      = st.session_state.get(_sav_qa_key, {})   # {scenario: answer}

                        # ── URL row ───────────────────────────────────────
                        try:
                            from pipeline.smart_ac_verifier import get_auto_app_url
                            _auto_url = get_auto_app_url()
                        except Exception:
                            _auto_url = ""

                        col_sav1, col_sav2 = st.columns([2, 3])
                        with col_sav2:
                            sav_url = st.text_input(
                                "App URL",
                                value=_auto_url,
                                placeholder="https://admin.shopify.com/store/yourstore/apps/testing-553",
                                key=f"sav_url_{card.id}",
                                label_visibility="collapsed",
                            )
                        with col_sav1:
                            _sav_running_key  = f"sav_running_{card.id}"
                            _sav_stop_key     = f"sav_stop_{card.id}"
                            _sav_result_key   = f"sav_result_{card.id}"
                            _sav_prog_key     = f"sav_prog_{card.id}"
                            _is_running       = st.session_state.get(_sav_running_key, False)
                            if _is_running:
                                # Show Stop button while thread is running — replaces Run button
                                if st.button("⏹ Stop", key=f"stop_sav_{card.id}",
                                             use_container_width=True, type="primary"):
                                    st.session_state[_sav_stop_key] = True
                                run_sav = False
                            else:
                                _run_label = "🔁 Re-verify" if sav_report else "🔍 Run Smart Verification"
                                run_sav = st.button(
                                    _run_label,
                                    key=f"run_sav_{card.id}",
                                    use_container_width=True,
                                    help=(
                                        "Claude opens Chrome, clicks through navigation, "
                                        "interacts with the UI and reports pass/fail"
                                    ),
                                )

                        # ── Live progress while thread is running ──────────
                        if _is_running:
                            _result = st.session_state.get(_sav_result_key, {})
                            if _result.get("done"):
                                # Thread finished — harvest results
                                st.session_state[_sav_running_key] = False
                                if _result.get("error"):
                                    if st.session_state.get(_sav_stop_key):
                                        st.warning("⏹ Verification stopped by user.")
                                    else:
                                        st.error(f"❌ Verification error: {_result['error']}")
                                else:
                                    _new_report = _result["report"]
                                    st.session_state[_sav_key] = _new_report
                                    still_stuck = {s.scenario for s in _new_report.qa_needed}
                                    st.session_state[_sav_qa_key] = {
                                        k: v for k, v in sav_qa.items() if k in still_stuck
                                    }
                                st.session_state.pop(_sav_result_key, None)
                                st.session_state.pop(_sav_prog_key, None)
                                st.rerun()
                            else:
                                # Still running — show live progress, auto-rerun every 2 s
                                _prog = st.session_state.get(_sav_prog_key, {})
                                _pct  = _prog.get("pct", 0.0)
                                _txt  = _prog.get("text", "🌐 Chrome is open — Claude is verifying AC scenarios…")
                                st.progress(_pct)
                                st.info(_txt)
                                time.sleep(2)
                                st.rerun()

                        if run_sav:
                            if not sav_url.strip():
                                st.warning("Enter the app URL or set STORE in the automation repo .env")
                            else:
                                from pipeline.smart_ac_verifier import verify_ac as _verify_ac_fn

                                _ac_text     = card.desc or ""
                                _sc_count    = max(1, sum(
                                    1 for ln in _ac_text.splitlines()
                                    if ln.strip().startswith(("Given","When","Scenario","Then","-"))
                                ))
                                # Snapshot mutable values for the thread closure
                                _sav_url_val  = sav_url.strip()
                                _card_id_val  = card.id
                                _card_name_val = card.name
                                _card_url_val = card.url
                                _sav_qa_copy  = dict(sav_qa) if sav_qa else {}
                                _rk = _sav_result_key
                                _pk = _sav_prog_key
                                _sk = _sav_stop_key

                                def _sav_progress_cb(
                                    sc_idx, sc_title, step_num, step_desc,
                                    _total=_sc_count, _pk2=_pk,
                                ):
                                    pct = min(((sc_idx - 1) + (step_num / 10)) / _total, 0.99)
                                    st.session_state[_pk2] = {
                                        "pct":  pct,
                                        "text": (
                                            f"📋 **Scenario {sc_idx}:** {sc_title[:55]}…  "
                                            f"⚡ Step {step_num} — {step_desc}"
                                        ),
                                    }

                                def _run_sav_thread(
                                    _url=_sav_url_val, _ac=_ac_text, _cname=_card_name_val,
                                    _cid=_card_id_val, _curl=_card_url_val, _qa=_sav_qa_copy,
                                    _rk2=_rk, _sk2=_sk,
                                ):
                                    try:
                                        report = _verify_ac_fn(
                                            app_url=_url,
                                            ac_text=_ac,
                                            card_name=_cname,
                                            card_id=_cid,
                                            card_url=_curl,
                                            qa_name="QA Team",
                                            progress_cb=_sav_progress_cb,
                                            qa_answers=_qa or None,
                                            auto_report_bugs=True,
                                            stop_flag=lambda: st.session_state.get(_sk2, False),
                                        )
                                        st.session_state[_rk2] = {"done": True, "report": report, "error": None}
                                    except Exception as _ex:
                                        st.session_state[_rk2] = {"done": True, "report": None, "error": str(_ex)}

                                # Initialise state BEFORE spawning thread
                                st.session_state[_sav_running_key] = True
                                st.session_state[_sav_stop_key]    = False
                                st.session_state[_sav_result_key]  = {"done": False}
                                st.session_state.pop(_sav_prog_key, None)

                                _sav_thread = threading.Thread(target=_run_sav_thread, daemon=True)
                                _sav_thread.start()
                                # Rerun immediately so the Stop button appears
                                st.rerun()

                        # ── Results ───────────────────────────────────────
                        if sav_report:
                            _s_icons = {
                                "pass": "✅", "fail": "❌", "partial": "⚠️",
                                "skipped": "⏭️", "qa_needed": "🙋", "pending": "⏳",
                            }

                            # Re-verify button — only show when there are failures
                            _failed_count = sav_report.failed + len(sav_report.qa_needed)
                            if _failed_count > 0:
                                _rev_col1, _rev_col2 = st.columns([2, 3])
                                with _rev_col1:
                                    _rev_running_key = f"rev_running_{card.id}"
                                    _rev_result_key  = f"rev_result_{card.id}"
                                    _rev_prog_key    = f"rev_prog_{card.id}"
                                    _rev_is_running  = st.session_state.get(_rev_running_key, False)

                                    if _rev_is_running:
                                        st.button("⏹ Re-verify running…", key=f"rev_busy_{card.id}",
                                                  use_container_width=True, disabled=True)
                                        # Check if thread finished
                                        _rev_res = st.session_state.get(_rev_result_key, {})
                                        if _rev_res.get("done"):
                                            st.session_state[_rev_running_key] = False
                                            if _rev_res.get("error"):
                                                st.error(f"❌ Re-verify error: {_rev_res['error']}")
                                            else:
                                                st.session_state[_sav_key] = _rev_res["report"]
                                            st.session_state.pop(_rev_result_key, None)
                                            st.session_state.pop(_rev_prog_key, None)
                                            st.rerun()
                                        else:
                                            _rev_prog = st.session_state.get(_rev_prog_key, {})
                                            if _rev_prog:
                                                st.progress(_rev_prog.get("pct", 0.0))
                                                st.info(_rev_prog.get("text", "🔁 Re-verifying failed scenarios…"))
                                            time.sleep(2)
                                            st.rerun()
                                    elif st.button(
                                        f"🔁 Re-verify {_failed_count} failed scenario(s)",
                                        key=f"reverify_{card.id}",
                                        help="Re-runs only the failed/partial scenarios — passing ones are kept",
                                    ):
                                        from pipeline.smart_ac_verifier import reverify_failed as _rev_fn
                                        _failed_sc_count = max(1, _failed_count)
                                        _rev_report_snap = sav_report
                                        _rev_url_val     = sav_url.strip() if sav_url else ""
                                        _rev_cid         = card.id
                                        _rev_curl        = card.url
                                        _rrk             = _rev_result_key
                                        _rpk             = _rev_prog_key

                                        def _rev_prog_cb(sc_idx, sc_title, step_num, step_desc,
                                                         _tot=_failed_sc_count, _pk3=_rpk):
                                            pct = min(((sc_idx-1) + (step_num/10)) / _tot, 0.99)
                                            st.session_state[_pk3] = {
                                                "pct":  pct,
                                                "text": f"🔁 **Re-verifying:** {sc_title[:55]}…  ⚡ {step_desc}",
                                            }

                                        def _run_rev_thread(
                                            _rpt=_rev_report_snap, _url=_rev_url_val,
                                            _cid=_rev_cid, _curl=_rev_curl,
                                            _rrk2=_rrk,
                                        ):
                                            try:
                                                updated = _rev_fn(
                                                    report=_rpt,
                                                    app_url=_url,
                                                    card_id=_cid,
                                                    card_url=_curl,
                                                    qa_name="QA Team",
                                                    progress_cb=_rev_prog_cb,
                                                    auto_report_bugs=True,
                                                )
                                                st.session_state[_rrk2] = {"done": True, "report": updated, "error": None}
                                            except Exception as _ex2:
                                                st.session_state[_rrk2] = {"done": True, "report": None, "error": str(_ex2)}

                                        st.session_state[_rev_running_key] = True
                                        st.session_state[_rev_result_key]  = {"done": False}
                                        st.session_state.pop(_rev_prog_key, None)
                                        threading.Thread(target=_run_rev_thread, daemon=True).start()
                                        st.rerun()
                                with _rev_col2:
                                    st.caption("💡 Ask the developer to fix, then click Re-verify — only failed scenarios will re-run")

                            # Summary bar
                            _p, _f, _q = (
                                sav_report.passed,
                                sav_report.failed,
                                len(sav_report.qa_needed),
                            )
                            _bar_icon = "✅" if _f == 0 and _q == 0 else "❌"
                            st.markdown(
                                f"{_bar_icon} **{_p} passed · {_f} failed"
                                + (f" · {_q} need your input" if _q else "") + "**"
                            )
                            if sav_report.summary:
                                st.info(sav_report.summary)

                            # Per-scenario results
                            for sv in sav_report.scenarios:
                                _icon = _s_icons.get(sv.status, "❓")
                                with st.expander(
                                    f"{_icon} {sv.scenario}",
                                    expanded=(sv.status in ("fail", "partial", "qa_needed")),
                                ):
                                    if sv.verdict:
                                        _vc = (
                                            "success" if sv.status == "pass"
                                            else "error" if sv.status == "fail"
                                            else "warning"
                                        )
                                        getattr(st, _vc)(sv.verdict)

                                    # Steps taken
                                    if sv.steps:
                                        st.caption("**Steps Claude took:**")
                                        for step in sv.steps:
                                            _si = {"click":"🖱️","fill":"✍️","navigate":"🌐",
                                                   "observe":"👁️","scroll":"↕️","verify":"🔎",
                                                   "qa_needed":"🙋"}.get(step.action, "→")
                                            _ok = "" if step.success else " ❌"
                                            _tgt = f" → `{step.target}`" if step.target else ""
                                            st.caption(f"  {_si} {step.description}{_tgt}{_ok}")
                                            for nc in step.network_calls[:2]:
                                                _nc_short = nc.split("/api/")[-1] if "/api/" in nc else nc[-60:]
                                                st.caption(f"    📡 /api/{_nc_short}")

                                    # Bug report result
                                    _br = sv.bug_report
                                    if _br:
                                        if _br.get("ok"):
                                            _sent = ", ".join(_br.get("sent_to", []))
                                            st.success(f"🐛 Bug DM sent to developer: **{_sent}**")
                                            _loc = _br.get("location", {})
                                            if _loc.get("file_hint"):
                                                st.caption(f"   📁 Likely in: `{_loc['file_hint']}`")
                                            if _loc.get("technical_explanation"):
                                                st.caption(f"   💡 {_loc['technical_explanation']}")
                                        elif _br.get("devs_found", 0) == 0:
                                            st.warning("🐛 Bug found but no developer assigned to this card in Trello.")
                                        else:
                                            st.warning(f"🐛 Bug found — DM failed: {_br.get('error', '')}")

                            # ── QA interaction panel ──────────────────────
                            if sav_report.qa_needed:
                                st.divider()
                                st.warning(
                                    f"🙋 Claude needs your help with "
                                    f"**{len(sav_report.qa_needed)} scenario(s)**. "
                                    "Answer below and click **Continue**."
                                )
                                for _qi, sv in enumerate(sav_report.qa_needed):
                                    st.markdown(f"**Scenario:** {sv.scenario}")
                                    st.markdown(f"🤖 *Claude says:* {sv.qa_question}")
                                    _ans = st.text_input(
                                        "Your answer",
                                        key=f"sav_qa_input_{card.id}_{_qi}",
                                        placeholder="e.g. It's under Additional Services → Freight tab",
                                    )
                                    if _ans.strip():
                                        sav_qa[sv.scenario] = _ans.strip()

                                if st.button(
                                    "▶ Continue Verification",
                                    key=f"sav_continue_{card.id}",
                                    type="primary",
                                ):
                                    st.session_state[_sav_qa_key] = sav_qa
                                    # Clear report so it re-runs on next rerun
                                    del st.session_state[_sav_key]
                                    st.rerun()

                            # ── Feed into automation writer ───────────────
                            if not sav_report.qa_needed:
                                st.session_state[f"sav_context_{card.id}"] = \
                                    sav_report.to_automation_context()

                        st.divider()

                        # ── Ask Domain Expert ─────────────────────────────
                        _step_header("2c", "Ask Domain Expert")
                        st.caption(
                            "Got a doubt while testing? Ask the Domain Expert — "
                            "it uses FedEx docs + backend + frontend knowledge to answer. "
                            "If it spots a code bug, it DMs the developer directly."
                        )

                        _dex_hist_key = f"dex_history_{card.id}"
                        # Load from disk on first access this session
                        if _dex_hist_key not in st.session_state:
                            from pipeline.dex_history import load_history as _load_dex
                            st.session_state[_dex_hist_key] = _load_dex(card.id)

                        _dex_history = st.session_state[_dex_hist_key]

                        # Show conversation history
                        for _entry in _dex_history:
                            st.markdown(f"**🙋 You:** {_entry['q']}")
                            _ans_type = "error" if _entry.get("bug_possible") else "info"
                            getattr(st, _ans_type)(f"🤖 **Domain Expert:** {_entry['a']}")
                            if _entry.get("web_searched"):
                                st.caption("   🌐 Answer enriched with web research")
                            # Show bug DM result if any
                            _br = _entry.get("bug_report", {})
                            if _br and _br.get("ok"):
                                _sent = ", ".join(_br.get("sent_to", []))
                                st.success(f"🐛 Bug DM sent to: **{_sent}**")
                                _loc = _br.get("location", {})
                                if _loc.get("file_hint"):
                                    st.caption(f"   📁 `{_loc['file_hint']}`")
                            st.markdown("---")

                        # Question input
                        _dex_col1, _dex_col2 = st.columns([5, 1])
                        with _dex_col1:
                            _dex_q = st.text_input(
                                "Your question",
                                placeholder="e.g. Is this FedEx One Rate behavior correct? / Why is the API returning 422?",
                                key=f"dex_q_{card.id}",
                                label_visibility="collapsed",
                            )
                        with _dex_col2:
                            _dex_ask = st.button(
                                "Ask 🤖",
                                key=f"dex_ask_{card.id}",
                                use_container_width=True,
                                type="primary",
                            )

                        if _dex_ask and _dex_q.strip():
                            from pipeline.bug_reporter import ask_domain_expert, notify_devs_of_bug
                            with st.spinner("🤖 Domain Expert is thinking…"):
                                _dex_result = ask_domain_expert(
                                    question=_dex_q.strip(),
                                    card_name=card.name,
                                    card_desc=card.desc or "",
                                    history=_dex_history,
                                )

                            _entry = {
                                "q": _dex_q.strip(),
                                "a": _dex_result["answer"],
                                "bug_possible": _dex_result["bug_possible"],
                                "web_searched": _dex_result["web_searched"],
                                "bug_report": {},
                            }

                            # Auto-notify dev if bug detected
                            if _dex_result["bug_possible"]:
                                with st.spinner("🐛 Bug suspected — analysing code + notifying developer…"):
                                    _bug_res = notify_devs_of_bug(
                                        card_id=card.id,
                                        card_name=card.name,
                                        card_url=card.url,
                                        bug_description=_dex_q.strip() + "\n\n" + _dex_result["answer"],
                                        scenario="Manual QA question",
                                        qa_name="QA Team",
                                    )
                                _entry["bug_report"] = _bug_res

                            _dex_history.append(_entry)
                            st.session_state[_dex_hist_key] = _dex_history
                            from pipeline.dex_history import save_history as _save_dex
                            _save_dex(card.id, _dex_history)
                            st.rerun()

                        # Manual bug report button (QA decides it's a bug)
                        if _dex_history:
                            _last = _dex_history[-1]
                            if not _last.get("bug_report") or not _last["bug_report"].get("ok"):
                                if st.button(
                                    "🐛 This is a Bug — Notify Developer",
                                    key=f"dex_bug_{card.id}",
                                    help="Send a DM to the developer assigned to this card",
                                ):
                                    from pipeline.bug_reporter import notify_devs_of_bug
                                    with st.spinner("Sending bug DM to developer…"):
                                        _bug_res = notify_devs_of_bug(
                                            card_id=card.id,
                                            card_name=card.name,
                                            card_url=card.url,
                                            bug_description=_last["q"] + "\n\n" + _last["a"],
                                            scenario="Manual QA report",
                                            qa_name="QA Team",
                                        )
                                    _dex_history[-1]["bug_report"] = _bug_res
                                    st.session_state[_dex_hist_key] = _dex_history
                                    st.rerun()

                        if _dex_history and st.button("🗑 Clear conversation", key=f"dex_clear_{card.id}"):
                            from pipeline.dex_history import clear_history as _clear_dex
                            _clear_dex(card.id)
                            st.session_state[_dex_hist_key] = []
                            st.rerun()

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

                            # ── Send TC via Slack (DM or Channel) ────────
                            _tc_dm_open_key = f"show_dm_tc_{card.id}"
                            _tc_dm_sent_key = f"tc_dm_sent_{card.id}"
                            _tc_ch_open_key = f"show_ch_tc_{card.id}"
                            _tc_ch_sent_key = f"tc_ch_sent_{card.id}"

                            if st.session_state.get(_tc_dm_sent_key):
                                st.success("✅ Test cases sent via Slack DM!")
                                if st.button("📨 Send again", key=f"tc_dm_resend_{card.id}"):
                                    st.session_state[_tc_dm_sent_key] = False
                                    st.session_state[_tc_dm_open_key] = True
                                    st.rerun()
                            elif st.session_state.get(_tc_ch_sent_key):
                                st.success("✅ Test cases posted to Slack channel!")
                                if st.button("📢 Post again", key=f"tc_ch_resend_{card.id}"):
                                    st.session_state[_tc_ch_sent_key] = False
                                    st.session_state[_tc_ch_open_key] = True
                                    st.rerun()
                            else:
                                _tc_btn_col1, _tc_btn_col2 = st.columns(2)
                                with _tc_btn_col1:
                                    if st.button(
                                        "📨 Send Test Cases via Slack DM",
                                        key=f"open_dm_tc_{card.id}",
                                        use_container_width=True,
                                    ):
                                        st.session_state[_tc_dm_open_key] = True
                                        st.session_state[_tc_ch_open_key] = False
                                with _tc_btn_col2:
                                    if st.button(
                                        "📢 Send to Slack Channel",
                                        key=f"open_ch_tc_{card.id}",
                                        use_container_width=True,
                                    ):
                                        st.session_state[_tc_ch_open_key] = True
                                        st.session_state[_tc_dm_open_key] = False

                            # ── Slack Channel panel (TC) ──────────────────
                            if st.session_state.get(_tc_ch_open_key):
                                from pipeline.slack_client import (
                                    dm_token_configured, list_slack_channels,
                                    post_content_to_slack_channel,
                                )
                                if not dm_token_configured():
                                    st.warning(
                                        "⚠️ SLACK_BOT_TOKEN is not set — channel posting requires a bot token.\n\n"
                                        "Add `SLACK_BOT_TOKEN=xoxb-...` to your `.env` file."
                                    )
                                else:
                                    st.markdown("##### 📢 Post Test Cases to Slack Channel")
                                    _ch_cache_key = "slack_channels_cache"
                                    if _ch_cache_key not in st.session_state:
                                        with st.spinner("Loading channels…"):
                                            _chs, _ch_err, _ch_note = list_slack_channels()
                                        if _ch_err:
                                            st.error(f"❌ {_ch_err}")
                                            _chs = []
                                        st.session_state[_ch_cache_key] = (_chs, _ch_note)
                                    else:
                                        _chs, _ch_note = st.session_state[_ch_cache_key]

                                    if _ch_note:
                                        st.caption(f"ℹ️ {_ch_note}")

                                    if _chs:
                                        _ch_options = {
                                            f"{'🔒' if c['is_private'] else '#'} {c['name']}": c["id"]
                                            for c in _chs
                                        }
                                        _tc_ch_sel_col, _tc_ch_ref_col = st.columns([3, 1])
                                        with _tc_ch_sel_col:
                                            _tc_ch_sel = st.selectbox(
                                                "Select channel",
                                                options=list(_ch_options.keys()),
                                                key=f"tc_ch_select_{card.id}",
                                            )
                                        with _tc_ch_ref_col:
                                            st.markdown("<br>", unsafe_allow_html=True)
                                            if st.button("🔄 Refresh", key=f"tc_ch_refresh_{card.id}",
                                                         use_container_width=True):
                                                del st.session_state[_ch_cache_key]
                                                st.rerun()

                                        if st.button(
                                            f"📢 Post to {_tc_ch_sel}",
                                            key=f"tc_ch_send_btn_{card.id}",
                                            type="primary",
                                            use_container_width=True,
                                        ):
                                            _tc_sel_ch_id = _ch_options[_tc_ch_sel]
                                            with st.spinner("Posting to channel…"):
                                                _tc_ch_result = post_content_to_slack_channel(
                                                    channel_id=_tc_sel_ch_id,
                                                    card_name=card.name,
                                                    content_text=tc,
                                                    content_label="Test Cases",
                                                    card_url=getattr(card, "url", ""),
                                                )
                                            if _tc_ch_result["ok"]:
                                                st.session_state[_tc_ch_sent_key] = True
                                                st.session_state[_tc_ch_open_key] = False
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {_tc_ch_result['error']}")

                            # ── Slack DM panel (TC) ───────────────────────
                            if st.session_state.get(_tc_dm_open_key):
                                from pipeline.slack_client import (
                                    dm_token_configured, search_slack_users, send_ac_dm,
                                )
                                if not dm_token_configured():
                                    st.warning(
                                        "⚠️ SLACK_BOT_TOKEN is not set — DMs require a bot token.\n\n"
                                        "Add `SLACK_BOT_TOKEN=xoxb-...` to your `.env` file."
                                    )
                                else:
                                    st.markdown("##### 📨 Send Test Cases via DM")
                                    _tc_dm_col1, _tc_dm_col2 = st.columns([3, 1])
                                    with _tc_dm_col1:
                                        _tc_dm_query = st.text_input(
                                            "Search member",
                                            placeholder="Search by name — add multiple one by one",
                                            key=f"tc_dm_search_query_{card.id}",
                                        )
                                    with _tc_dm_col2:
                                        st.markdown("<br>", unsafe_allow_html=True)
                                        _tc_do_search = st.button(
                                            "🔍 Search",
                                            key=f"tc_dm_search_btn_{card.id}",
                                            use_container_width=True,
                                        )

                                    _tc_pool_key = f"tc_dm_user_pool_{card.id}"
                                    if _tc_pool_key not in st.session_state:
                                        st.session_state[_tc_pool_key] = {}

                                    if _tc_do_search and _tc_dm_query.strip():
                                        with st.spinner("Searching…"):
                                            _tc_raw = search_slack_users(_tc_dm_query.strip())
                                        _tc_found, _tc_search_err = (
                                            _tc_raw if isinstance(_tc_raw, tuple)
                                            else (_tc_raw or [], "")
                                        )
                                        if _tc_search_err:
                                            st.error(f"❌ {_tc_search_err}")
                                        elif not _tc_found:
                                            st.info("No users found — try a different name.")
                                        else:
                                            for u in _tc_found:
                                                _lbl = f"{u['name']} (@{u['display_name']})"
                                                st.session_state[_tc_pool_key][_lbl] = u["id"]
                                            st.success(f"Found {len(_tc_found)} user(s) — select below.")

                                    _tc_pool = st.session_state[_tc_pool_key]
                                    if _tc_pool:
                                        _tc_selected_labels = st.multiselect(
                                            "Select recipients (pick multiple)",
                                            options=list(_tc_pool.keys()),
                                            key=f"tc_dm_user_multi_{card.id}",
                                        )
                                        if st.button("✖ Clear search results",
                                                     key=f"tc_dm_clear_{card.id}"):
                                            st.session_state[_tc_pool_key] = {}
                                            st.rerun()

                                        if st.session_state.get(_tc_dm_sent_key):
                                            st.success("✅ Test cases sent via Slack DM!")
                                            if st.button("📨 Send again",
                                                         key=f"tc_dm_resend_inner_{card.id}"):
                                                st.session_state[_tc_dm_sent_key] = False
                                                st.rerun()
                                        elif _tc_selected_labels:
                                            _tc_selected_uids = [_tc_pool[l] for l in _tc_selected_labels]
                                            _tc_n = len(_tc_selected_uids)
                                            if st.button(
                                                f"📨 Send to {_tc_n} person{'s' if _tc_n > 1 else ''}",
                                                key=f"tc_dm_send_btn_{card.id}",
                                                type="primary",
                                                use_container_width=True,
                                            ):
                                                with st.spinner(f"Sending DM to {_tc_n} recipient(s)…"):
                                                    _tc_dm_result = send_ac_dm(
                                                        user_ids=_tc_selected_uids,
                                                        card_name=card.name,
                                                        ac_text=tc,
                                                        content_label="Test Cases",
                                                    )
                                                if _tc_dm_result["ok"]:
                                                    st.session_state[_tc_dm_sent_key] = True
                                                    st.session_state[_tc_dm_open_key] = False
                                                    st.rerun()
                                                else:
                                                    _ts, _tf = _tc_dm_result.get("sent", 0), _tc_dm_result.get("failed", 0)
                                                    if _ts:
                                                        st.warning(f"⚠️ Sent to {_ts}, failed for {_tf}: {_tc_dm_result['error']}")
                                                    else:
                                                        st.error(f"❌ DM failed: {_tc_dm_result['error']}")
                                        else:
                                            st.caption("Select at least one recipient above.")

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

                                    # Allow QA to create a new tab if needed
                                    _new_tab_key = f"new_tab_name_{card.id}"
                                    _tab_created_key = f"tab_created_{card.id}"

                                    _tc_col1, _tc_col2 = st.columns([3, 2])
                                    with _tc_col1:
                                        tab_options = list(SHEET_TABS)
                                        # Add any newly created tab to options immediately
                                        _newly_created = st.session_state.get(_tab_created_key, "")
                                        if _newly_created and _newly_created not in tab_options:
                                            tab_options.insert(0, _newly_created)

                                        _default_tab = _newly_created if _newly_created else suggested_tab
                                        tab_idx = tab_options.index(_default_tab) if _default_tab in tab_options else 0
                                        chosen_tab = st.selectbox(
                                            "📊 Add to sheet tab",
                                            tab_options,
                                            index=tab_idx,
                                            key=f"tab_{card.id}",
                                        )
                                    with _tc_col2:
                                        _new_tab_name = st.text_input(
                                            "➕ Or create new tab",
                                            placeholder="New tab name…",
                                            key=_new_tab_key,
                                            label_visibility="collapsed",
                                        )
                                        if st.button("➕ Create Tab", key=f"create_tab_{card.id}",
                                                     use_container_width=True):
                                            if _new_tab_name.strip():
                                                from pipeline.sheets_writer import create_new_tab
                                                with st.spinner(f"Creating tab '{_new_tab_name.strip()}'…"):
                                                    _ct_res = create_new_tab(_new_tab_name.strip())
                                                if _ct_res["ok"]:
                                                    _action = "already exists" if _ct_res.get("existed") else "created"
                                                    st.success(f"✅ Tab '{_ct_res['tab']}' {_action}! [Open]({_ct_res['sheet_url']})")
                                                    st.session_state[_tab_created_key] = _ct_res["tab"]
                                                    # Add to SHEET_TABS in memory so selectbox shows it
                                                    if _ct_res["tab"] not in SHEET_TABS:
                                                        SHEET_TABS.append(_ct_res["tab"])
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ Failed: {_ct_res['error']}")
                                            else:
                                                st.warning("Enter a tab name first")

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
                                        _ac_for_rag = (
                                            st.session_state.get(f"ac_suggestion_{card.id}")
                                            or card.desc or ""
                                        )
                                        rag_result = {"chunks_added": 0, "error": ""}
                                        try:
                                            from pipeline.rag_updater import update_rag_from_card
                                            with st.spinner("📚 Updating knowledge base…"):
                                                rag_result = update_rag_from_card(
                                                    card_id=card.id,
                                                    card_name=card.name,
                                                    description=card.desc or "",
                                                    acceptance_criteria=_ac_for_rag,
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

                                        # 4. Save to History
                                        st.session_state.pipeline_runs[card.id] = {
                                            "card_name":   card.name,
                                            "card_url":    card.url or "",
                                            "release":     current_release,
                                            "test_cases":  tc[:500] + ("…" if len(tc) > 500 else ""),
                                            "rag_chunks":  rag_result.get("chunks_added", 0),
                                            "approved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                        }
                                        _save_history(st.session_state.pipeline_runs)

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
                                                st.error(
                                                    f"❌ Tests still failing after {fix_iters} auto-fix attempt(s) — "
                                                    f"push blocked. Fix locally and push manually."
                                                )
                                            with st.expander("🔍 Auto-fix run history", expanded=not fix_passed):
                                                for run in fix_history:
                                                    icon = "✅" if run["passed"] else "❌"
                                                    st.markdown(f"**{icon} Iteration {run['iteration']}**")
                                                    if run.get("fixed_files"):
                                                        st.caption("Fixed: " + ", ".join(f"`{x}`" for x in run["fixed_files"]))
                                                    with st.expander(f"Output (iter {run['iteration']})", expanded=False):
                                                        st.code(run.get("output", "")[-2000:], language="text")

                                        push_err = auto_result.get("push_error", "")
                                        if pushed:
                                            st.success("✅ Pushed to origin")
                                        elif push_err and "skipped" in push_err.lower():
                                            st.warning(f"⚠️ {push_err}")
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

                                    # ── QA Retrospective ─────────────────────
                                    st.divider()
                                    _retro_feedback_count = 0
                                    try:
                                        from pipeline.qa_feedback import get_feedback_count
                                        _retro_feedback_count = get_feedback_count()
                                    except Exception:
                                        pass
                                    _retro_label = (
                                        f"📝 QA Retrospective  ·  📚 {_retro_feedback_count} learning(s) in knowledge base"
                                        if _retro_feedback_count > 0
                                        else "📝 QA Retrospective  —  Help the AI improve on the next card"
                                    )
                                    with st.expander(_retro_label, expanded=False):
                                        st.caption(
                                            "Tell the AI what it missed or got wrong this card. "
                                            "Your feedback is saved and used automatically on future cards — "
                                            "no retraining needed."
                                        )

                                        # Load any existing saved feedback for this card
                                        _retro_key = f"retro_loaded_{card.id}"
                                        _retro_data_key = f"retro_data_{card.id}"
                                        if _retro_key not in st.session_state:
                                            try:
                                                from pipeline.qa_feedback import load_feedback
                                                _existing_fb = load_feedback(card.id)
                                            except Exception:
                                                _existing_fb = None
                                            st.session_state[_retro_key] = True
                                            st.session_state[_retro_data_key] = _existing_fb

                                        _existing_fb = st.session_state.get(_retro_data_key)

                                        if _existing_fb:
                                            st.success(
                                                f"✅ Feedback already saved for this card "
                                                f"(saved {_existing_fb.date}). "
                                                "Edit below to update."
                                            )

                                        # ── AC Gaps ────────────────────────────
                                        st.markdown("**🔴 AC Gaps** — scenarios the AI missed in Acceptance Criteria")
                                        _ac_default = "\n".join(_existing_fb.ac_misses) if _existing_fb else ""
                                        _ac_input = st.text_area(
                                            "AC gaps",
                                            value=_ac_default,
                                            placeholder=(
                                                "One per line. e.g.:\n"
                                                "Missed the case where product weight > 150 lbs triggers LTL freight\n"
                                                "No scenario for COD payment rejection at checkout"
                                            ),
                                            height=110,
                                            key=f"retro_ac_{card.id}",
                                            label_visibility="collapsed",
                                        )

                                        # ── TC Issues ──────────────────────────
                                        st.markdown("**🟠 TC Issues** — wrong or missing test cases")
                                        _tc_default = "\n".join(_existing_fb.tc_issues) if _existing_fb else ""
                                        _tc_input = st.text_area(
                                            "TC issues",
                                            value=_tc_default,
                                            placeholder=(
                                                "One per line. e.g.:\n"
                                                "TC-3 didn't cover the Saturday Delivery edge case\n"
                                                "Missing negative TC for when FedEx account is suspended"
                                            ),
                                            height=100,
                                            key=f"retro_tc_{card.id}",
                                            label_visibility="collapsed",
                                        )

                                        # ── Automation Issues ───────────────────
                                        st.markdown("**🟡 Automation Issues** — problems in the generated Playwright code")
                                        _auto_default = "\n".join(_existing_fb.automation_issues) if _existing_fb else ""
                                        _auto_input = st.text_area(
                                            "Automation issues",
                                            value=_auto_default,
                                            placeholder=(
                                                "One per line. e.g.:\n"
                                                "Label download step doesn't wait for print dialog to close\n"
                                                "Wrong locator used for the carrier service dropdown\n"
                                                "Missing assertion after rate calculation"
                                            ),
                                            height=100,
                                            key=f"retro_auto_{card.id}",
                                            label_visibility="collapsed",
                                        )

                                        # ── What Went Well ──────────────────────
                                        st.markdown("**🟢 What Went Well** — positive reinforcement")
                                        _well_default = "\n".join(_existing_fb.what_went_well) if _existing_fb else ""
                                        _well_input = st.text_area(
                                            "What went well",
                                            value=_well_default,
                                            placeholder=(
                                                "One per line. e.g.:\n"
                                                "Rate calculation scenarios were spot-on\n"
                                                "Automation selectors were accurate for this feature"
                                            ),
                                            height=80,
                                            key=f"retro_well_{card.id}",
                                            label_visibility="collapsed",
                                        )

                                        # ── Overall Notes ───────────────────────
                                        _notes_default = _existing_fb.overall_notes if _existing_fb else ""
                                        _notes_input = st.text_area(
                                            "💬 Overall notes (optional)",
                                            value=_notes_default,
                                            placeholder="Any general comment about this card's pipeline run…",
                                            height=70,
                                            key=f"retro_notes_{card.id}",
                                        )

                                        # ── Save button ─────────────────────────
                                        _retro_save_col, _retro_info_col = st.columns([1, 2])
                                        with _retro_save_col:
                                            if st.button(
                                                "💾 Save & Learn",
                                                key=f"retro_save_{card.id}",
                                                use_container_width=True,
                                                type="primary",
                                            ):
                                                import datetime as _dt
                                                # Parse multi-line inputs → clean list
                                                def _lines(txt):
                                                    return [l.strip() for l in txt.strip().splitlines() if l.strip()]

                                                _has_content = any([
                                                    _ac_input.strip(),
                                                    _tc_input.strip(),
                                                    _auto_input.strip(),
                                                    _well_input.strip(),
                                                    _notes_input.strip(),
                                                ])
                                                if not _has_content:
                                                    st.warning("Add at least one piece of feedback before saving.")
                                                else:
                                                    from pipeline.qa_feedback import QAFeedback, save_feedback as _save_fb
                                                    _fb = QAFeedback(
                                                        card_id=card.id,
                                                        card_name=card.name,
                                                        date=_dt.date.today().isoformat(),
                                                        ac_misses=_lines(_ac_input),
                                                        tc_issues=_lines(_tc_input),
                                                        automation_issues=_lines(_auto_input),
                                                        what_went_well=_lines(_well_input),
                                                        overall_notes=_notes_input.strip(),
                                                    )
                                                    with st.spinner("Saving feedback & updating knowledge base…"):
                                                        _fb_res = _save_fb(_fb)

                                                    if _fb_res["ok"]:
                                                        st.session_state[_retro_data_key] = _fb
                                                        st.success(
                                                            f"✅ Saved! {_fb_res['chunks_added']} chunk(s) added "
                                                            f"to knowledge base — future cards will learn from this."
                                                        )
                                                    else:
                                                        st.error(f"❌ Save failed: {_fb_res['error']}")

                                        with _retro_info_col:
                                            st.caption(
                                                "📖 This feedback is embedded into the AI's knowledge base. "
                                                "Next time a similar feature comes through, Claude will automatically "
                                                "reference these lessons when writing AC and test cases."
                                            )

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
                                    # Hidden when Smart AC Verifier has already walked the app —
                                    # the verified flows feed directly into the automation writer.
                                    _sav_done = bool(st.session_state.get(f"sav_context_{card.id}"))
                                    if _sav_done:
                                        st.caption(
                                            "✅ Smart AC Verifier already walked the app — "
                                            "verified flows will be used for code generation."
                                        )
                                        use_chrome_agent = False
                                    else:
                                        is_new_feature = det and det.kind == "new"
                                        use_chrome_agent = st.checkbox(
                                            "🌐 Walk app live with Chrome Agent (grounded locators)",
                                            key=f"use_chrome_{card.id}",
                                            value=is_new_feature,
                                            help=(
                                                "Navigates the real app and captures UI elements. "
                                                "Run Smart AC Verifier (Step 2b) first for better results — "
                                                "it walks the app AND verifies each AC scenario."
                                            ),
                                        )

                                    if use_chrome_agent:
                                        # Show Chrome Agent section
                                        trace_key = f"chrome_trace_{card.id}"
                                        trace_result = st.session_state.get(trace_key)

                                        if trace_result:
                                            if trace_result.error:
                                                # Check if it's the Shopify bot-challenge error
                                                if "connection-verification" in trace_result.error or "challenge" in trace_result.error.lower():
                                                    st.error("❌ Chrome Agent: Shopify bot-detection blocked the explorer")
                                                    st.warning(
                                                        "**Fix:** Shopify rejected the automated session.\n\n"
                                                        "1. Open a terminal in the automation repo\n"
                                                        "2. Run: `npx playwright test --project=setup --headed`\n"
                                                        "3. A Chrome window opens — log in manually\n"
                                                        "4. Close the window — auth.json is saved automatically\n"
                                                        "5. Click **Explore App** again"
                                                    )
                                                else:
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
                                    # Priority: Smart AC Verifier context > Chrome Agent trace
                                    _sav_ctx    = st.session_state.get(f"sav_context_{card.id}", "")
                                    trace_for_gen = st.session_state.get(f"chrome_trace_{card.id}") if use_chrome_agent else None
                                    chrome_context = (
                                        _sav_ctx                          # Smart AC verified flows first
                                        or (
                                            trace_for_gen.to_context_string()
                                            if trace_for_gen and not trace_for_gen.error
                                            else ""
                                        )
                                    )
                                    if st.button("⚙️ Write Automation Code", key=f"auto_{card.id}",
                                                 use_container_width=True,
                                                 type="primary"):
                                        from pipeline.automation_writer import write_automation
                                        label = (
                                            "✍️ Generating tests from verified AC flows…"
                                            if _sav_ctx
                                            else "✍️ Generating tests from live app trace…"
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
                                _bulk_ac = (
                                    st.session_state.get(f"ac_suggestion_{card.id}")
                                    or card.desc or ""
                                )
                                try:
                                    from pipeline.rag_updater import update_rag_from_card
                                    rag_r = update_rag_from_card(
                                        card_id=card.id,
                                        card_name=card.name,
                                        description=card.desc or "",
                                        acceptance_criteria=_bulk_ac,
                                        test_cases=tc_store[card.id],
                                        release=current_release,
                                    )
                                    rag_total += rag_r.get("chunks_added", 0)
                                except Exception:
                                    rag_r = {"chunks_added": 0}
                                # Save to History
                                st.session_state.pipeline_runs[card.id] = {
                                    "card_name":   card.name,
                                    "card_url":    card.url or "",
                                    "release":     current_release,
                                    "test_cases":  tc_store[card.id][:500],
                                    "rag_chunks":  rag_r.get("chunks_added", 0),
                                    "approved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                }
                                _save_history(st.session_state.pipeline_runs)
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

                                with st.spinner("Creating card in Trello Backlog…"):
                                    try:
                                        created_card = raise_bug(draft)
                                        st.session_state["bug_raised_card"] = created_card
                                        st.session_state.pop("bug_check_result", None)

                                        # ── Link backlog card back to the release card ──
                                        try:
                                            from pipeline.trello_client import TrelloClient as _TC
                                            _TC().add_comment(
                                                card.id,
                                                f"🐛 Bug raised to Backlog: "
                                                f"[{created_card.name}]({created_card.url})\n"
                                                f"Severity: {draft.severity} · Release: {draft.release}",
                                            )
                                        except Exception:
                                            pass  # comment failure must not block

                                        # ── Store bug per release card for sheet export ──
                                        _bugs_key = f"bugs_for_{card.id}"
                                        _existing = st.session_state.get(_bugs_key, [])
                                        _existing.append({
                                            "name": created_card.name,
                                            "url":  created_card.url or "",
                                            "severity": draft.severity,
                                        })
                                        st.session_state[_bugs_key] = _existing

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

            all_board_lists = _get_board_lists()
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
                    move_target_id = all_list_ids.get(move_target, "")
                    moved = 0
                    for card in dd_cards:
                        if card.id in selected_ids:
                            trello.move_card_to_list(card.id, move_target_id)
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
        st.markdown("## 📋 Pipeline Run History")
        st.caption("Cards approved this session — cleared when the app restarts.")

        runs = st.session_state.pipeline_runs
        if not runs:
            st.info("No cards approved yet this session. Approve a card in 🚀 Release QA to see history here.")
        else:
            st.markdown(f"**{len(runs)} card(s) approved this session**")
            if st.button("🗑️ Clear history", key="clear_history"):
                st.session_state.pipeline_runs = {}
                _save_history({})
                st.rerun()
            st.divider()
            for card_id, run in runs.items():
                label = f"✅ {run.get('card_name', card_id)}  ·  {run.get('release', '')}  ·  {run.get('approved_at', '')}"
                with st.expander(label, expanded=False):
                    col_h1, col_h2, col_h3 = st.columns(3)
                    col_h1.metric("📚 RAG chunks", run.get("rag_chunks", 0))
                    col_h2.markdown(f"**Release**  \n{run.get('release', '—')}")
                    col_h3.markdown(f"**Approved at**  \n{run.get('approved_at', '—')}")
                    if run.get("card_url"):
                        st.markdown(f"🔗 [Open in Trello]({run['card_url']})")
                    tc_preview = run.get("test_cases", "")
                    if tc_preview:
                        with st.expander("📝 Test cases preview", expanded=False):
                            st.markdown(tc_preview)

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

        # Bugs raised this session — collected from per-card bug dicts (rich: name + url + severity)
        # bugs_for_{card.id} = [{"name": str, "url": str, "severity": str}]
        _seen_bug_names: set[str] = set()
        so_bugs_with_urls: list[dict] = []   # rich list used for Slack links
        so_bugs_raised: list[str] = []       # flat name list for text_area prefill

        for card in so_cards:
            for bug in st.session_state.get(f"bugs_for_{card.id}", []):
                bname = bug.get("name", "")
                if bname and bname not in _seen_bug_names:
                    _seen_bug_names.add(bname)
                    so_bugs_with_urls.append(bug)
                    so_bugs_raised.append(bname)

        # Also pick up any legacy bug_raised_* card objects (older flow)
        for key, val in st.session_state.items():
            if key.startswith("bug_raised_") and hasattr(val, "name"):
                if val.name not in _seen_bug_names:
                    _seen_bug_names.add(val.name)
                    so_bugs_raised.append(val.name)
                    so_bugs_with_urls.append({"name": val.name, "url": getattr(val, "url", ""), "severity": ""})

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
            so3.metric("🐛 Bugs to backlog",   len(so_bugs_with_urls))

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
                                    backlog_links=so_bugs_with_urls or None,
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
                    # Collect bugs raised per card this session
                    bugs_by_card = {
                        c.id: st.session_state.get(f"bugs_for_{c.id}", [])
                        for c in so_cards
                    }
                    with st.spinner(f"Creating sheet tab '{rel_name}'…"):
                        try:
                            result = create_release_sheet(
                                release_name=rel_name,
                                cards=so_cards,
                                list_name=st.session_state.get("rqa_list_name", rel_name),
                                bugs_by_card=bugs_by_card,
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
                    value=f"automation/{re.sub(r'[^a-z0-9]+', '-', (ma_feature or 'manual').lower()).strip('-')[:40]}",
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
                            st.error(
                                f"❌ Tests still failing after {fix_iters} auto-fix attempt(s) — "
                                f"push blocked. Fix locally and push manually."
                            )
                        with st.expander("🔍 Auto-fix run history", expanded=not fix_passed):
                            for run in fix_history:
                                icon = "✅" if run["passed"] else "❌"
                                st.markdown(f"**{icon} Iteration {run['iteration']}**")
                                if run.get("fixed_files"):
                                    st.caption("Fixed: " + ", ".join(f"`{x}`" for x in run["fixed_files"]))
                                with st.expander(f"Output (iter {run['iteration']})", expanded=False):
                                    st.code(run.get("output", "")[-2000:], language="text")

                    # Branch
                    ma_push_err = ma_result.get("push_error", "")
                    if branch:
                        col_b, col_push = st.columns([3, 1])
                        with col_b:
                            st.info(f"🌿 Branch: `{branch}`")
                            if ma_push_err and "skipped" in ma_push_err.lower():
                                st.warning(f"⚠️ {ma_push_err}")
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
                                    card_id=f"manual_{re.sub(r'[^a-z0-9]', '', ma_feature.lower())}",
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

    # ── Tab 5: User Story Writer ─────────────────────────────────────────────
    with tab_us:
        st.markdown("### 📝 User Story Writer")
        st.caption("Describe what you need — AI will generate a User Story + Acceptance Criteria using the codebase and domain knowledge.")

        if not api_ok:
            st.error("❌ ANTHROPIC_API_KEY not set — add it to .env")
        else:
            from pipeline.user_story_writer import generate_user_story, refine_user_story
            from pipeline.trello_client import TrelloClient as _TC

            # ── Input ──────────────────────────────────────────────────────
            us_request = st.text_area(
                "What do you want to build?",
                placeholder="e.g. We currently show FedEx rates at checkout. Now we need to allow the merchant to set a markup percentage per service type so they can add a profit margin on top of the FedEx rate.",
                height=130,
                key="us_request_input",
            )

            col_gen, col_reset = st.columns([1, 4])
            with col_gen:
                generate_clicked = st.button("✨ Generate", type="primary", key="us_generate_btn",
                                             disabled=not us_request.strip())
            with col_reset:
                if st.button("🔄 Start Over", key="us_reset_btn"):
                    for k in ["us_result", "us_history"]:
                        st.session_state.pop(k, None)
                    st.rerun()

            if generate_clicked and us_request.strip():
                with st.spinner("Querying knowledge base + generating User Story…"):
                    try:
                        result = generate_user_story(us_request.strip())
                        st.session_state["us_result"] = result
                        st.session_state["us_history"] = [result]
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

            # ── Display result ─────────────────────────────────────────────
            if st.session_state.get("us_result"):
                st.divider()
                st.markdown(st.session_state["us_result"])

                # ── Change request loop ────────────────────────────────────
                st.divider()
                change_req = st.text_area(
                    "Request changes (optional)",
                    placeholder="e.g. Add an AC for when the markup is 0% — rate should show as-is. Also change the role to 'store admin'.",
                    height=90,
                    key="us_change_input",
                )
                if st.button("🔁 Refine", key="us_refine_btn", disabled=not change_req.strip()):
                    with st.spinner("Refining…"):
                        try:
                            refined = refine_user_story(st.session_state["us_result"], change_req.strip())
                            st.session_state["us_result"] = refined
                            st.session_state.setdefault("us_history", []).append(refined)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Refinement failed: {e}")

                # ── Trello push ────────────────────────────────────────────
                st.divider()
                st.markdown("#### Push to Trello")

                if not trello_ok:
                    st.warning("Trello credentials missing — set TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID in .env")
                else:
                    # Card title
                    us_card_title = st.text_input(
                        "Card title",
                        placeholder="e.g. Merchant markup percentage per FedEx service type",
                        key="us_card_title",
                    )

                    # Fetch lists + members once
                    try:
                        _tc = _TC()
                        _existing_lists = _tc.get_lists()
                        _list_names = [l.name for l in _existing_lists]
                        _board_members = _tc.get_board_members()
                    except Exception as e:
                        _existing_lists = []
                        _list_names = []
                        _board_members = []
                        st.warning(f"Could not fetch Trello data: {e}")

                    # List selector
                    list_mode = st.radio(
                        "Add to list",
                        ["Existing list", "Create new list"],
                        horizontal=True,
                        key="us_list_mode",
                    )

                    selected_list_id: str | None = None
                    new_list_name = ""
                    if list_mode == "Existing list":
                        if _list_names:
                            chosen_list_name = st.selectbox("Select list", _list_names, key="us_existing_list")
                            selected_list_id = next(
                                (l.id for l in _existing_lists if l.name == chosen_list_name), None
                            )
                        else:
                            st.info("No lists found on board.")
                    else:
                        new_list_name = st.text_input(
                            "New list name",
                            placeholder="e.g. Sprint 42 — Shipping",
                            key="us_new_list_name",
                        )

                    # Assign to developer
                    selected_member_ids: list[str] = []
                    if _board_members:
                        member_options = {m["fullName"] or m["username"]: m["id"] for m in _board_members}
                        chosen_members = st.multiselect(
                            "Assign to (optional)",
                            options=list(member_options.keys()),
                            key="us_assign_members",
                        )
                        selected_member_ids = [member_options[name] for name in chosen_members]

                    push_ready = (
                        us_card_title.strip()
                        and (
                            (list_mode == "Existing list" and selected_list_id)
                            or (list_mode == "Create new list" and new_list_name.strip())
                        )
                    )

                    if st.button("📌 Create Trello Card", type="primary", key="us_push_btn",
                                 disabled=not push_ready):
                        with st.spinner("Creating Trello card…"):
                            try:
                                _tc = _TC()
                                if list_mode == "Create new list":
                                    new_list = _tc.create_list(new_list_name.strip())
                                    selected_list_id = new_list.id
                                    st.info(f"Created new list: **{new_list_name.strip()}**")

                                card = _tc.create_card_in_list(
                                    list_id=selected_list_id,
                                    name=us_card_title.strip(),
                                    desc=st.session_state["us_result"],
                                    member_ids=selected_member_ids or None,
                                )
                                assigned = ", ".join(chosen_members) if selected_member_ids else "unassigned"
                                st.success(f"✅ Card created: **{card.name}** · Assigned: {assigned}")
                            except Exception as e:
                                st.error(f"Failed to create card: {e}")


    # ── Tab 6: Run Automation ────────────────────────────────────────────────
    with tab_run:
        import subprocess as _sp
        import glob as _glob

        st.markdown("### ▶️ Run Automation")
        st.caption("Select a branch and spec files, then run Playwright tests in headed mode.")

        # ── Automation repo path ───────────────────────────────────────────
        _run_auto_path = st.session_state.get(
            "automation_code_path",
            __import__("config").AUTOMATION_CODEBASE_PATH or "",
        ).strip()

        if not _run_auto_path:
            st.warning("Set the Automation repo path in the **Code Knowledge Base** sidebar section first.")
        else:
            from rag.code_indexer import get_repo_info as _gri_run

            # ── Branch selector ────────────────────────────────────────────
            _run_repo = _gri_run(_run_auto_path)
            _run_branches = _run_repo.get("branches", [])
            _run_current = _run_repo.get("current_branch", "")

            col_br, col_store = st.columns(2)
            with col_br:
                selected_branch = st.selectbox(
                    "Branch",
                    options=_run_branches if _run_branches else [_run_current or "main"],
                    index=(_run_branches.index(_run_current)
                           if _run_current in _run_branches else 0),
                    key="run_branch",
                )
            with col_store:
                _store_default = os.getenv("STORE", "")
                store_val = st.text_input(
                    "STORE (Shopify store slug)",
                    value=_store_default,
                    placeholder="your-store-name",
                    key="run_store",
                )

            # ── Spec file list grouped by folder ───────────────────────────
            st.markdown("#### Select spec files to run")

            _all_specs = sorted(
                _glob.glob(f"{_run_auto_path}/tests/**/*.spec.ts", recursive=True)
            )

            if not _all_specs:
                st.info("No spec files found in the automation repo.")
            else:
                # Group by folder relative to tests/
                from collections import defaultdict as _dd
                _spec_groups: dict = _dd(list)
                for sp in _all_specs:
                    rel = sp.replace(_run_auto_path + "/tests/", "")
                    folder = rel.split("/")[0] if "/" in rel else "root"
                    _spec_groups[folder].append(sp)

                for folder, specs in sorted(_spec_groups.items()):
                    with st.expander(f"📁 {folder} ({len(specs)} specs)", expanded=False):
                        all_key = f"run_all_{folder}"

                        def _make_all_cb(folder_specs, fkey):
                            def _cb():
                                val = st.session_state.get(fkey, False)
                                for s in folder_specs:
                                    st.session_state[f"run_spec_{s}"] = val
                            return _cb

                        st.checkbox("All", key=all_key,
                                    on_change=_make_all_cb(specs, all_key))

                        for sp in specs:
                            st.checkbox(sp.split("/")[-1], key=f"run_spec_{sp}")

                selected_specs = [
                    sp for sp in _all_specs
                    if st.session_state.get(f"run_spec_{sp}", False)
                ]

                st.caption(f"{len(selected_specs)} spec(s) selected")

                # ── Run options ────────────────────────────────────────────
                st.divider()
                run_opt_col1, run_opt_col2 = st.columns(2)
                with run_opt_col1:
                    browser_choice = st.selectbox(
                        "Browser",
                        options=["All", "Google Chrome", "Firefox", "Safari"],
                        index=0,
                        key="run_browser",
                    )
                with run_opt_col2:
                    st.write("")  # spacer

                run_col1, run_col2 = st.columns([1, 4])
                with run_col1:
                    run_clicked = st.button(
                        "▶️ Run",
                        type="primary",
                        key="run_automation_btn",
                        disabled=not (selected_specs and store_val.strip()),
                    )

                if not store_val.strip():
                    st.warning("Enter a STORE value to enable running.")

                if run_clicked and selected_specs and store_val.strip():
                    # Checkout branch first
                    try:
                        _sp.run(
                            ["git", "checkout", selected_branch],
                            cwd=_run_auto_path,
                            capture_output=True,
                            timeout=15,
                        )
                    except Exception:
                        pass

                    # Build playwright command
                    spec_args = [s.replace(_run_auto_path + "/", "") for s in selected_specs]
                    cmd = ["npx", "playwright", "test", "--headed"] + spec_args
                    if browser_choice != "All":
                        cmd += ["--project", browser_choice]

                    st.markdown(f"**Running:** `{' '.join(cmd)}`")
                    st.markdown(f"**Branch:** `{selected_branch}` · **Store:** `{store_val}`")

                    with st.spinner(f"Running {len(selected_specs)} spec(s) in headed mode…"):
                        env = {**os.environ, "STORE": store_val.strip(), "SLACK_SEND_RESULTS": "never"}
                        result = _sp.run(
                            cmd,
                            cwd=_run_auto_path,
                            capture_output=True,
                            text=True,
                            timeout=600,
                            env=env,
                        )

                    # ── Output ─────────────────────────────────────────────
                    st.divider()
                    if result.returncode == 0:
                        st.success("✅ All tests passed")
                    else:
                        st.error(f"❌ Tests finished with exit code {result.returncode}")

                    if result.stdout:
                        with st.expander("📄 Output", expanded=True):
                            st.code(result.stdout, language="bash")
                    if result.stderr:
                        with st.expander("⚠️ Errors / Warnings", expanded=result.returncode != 0):
                            st.code(result.stderr, language="bash")


if __name__ == "__main__":
    main()
