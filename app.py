"""The live demo: Mu'ashir in a browser, with Approve / Deny buttons for every write.

    uv run streamlit run app.py          # locally (reads OPENROUTER_API_KEY from .env)

On Streamlit Community Cloud, set OPENROUTER_API_KEY under the app's Secrets. The harness is the same as in
harness.py (configuration B, same MCP server, budgets, egress guard, audit log); only the approval differs: instead of
blocking on input(), a write is parked as "awaiting approval" and runs only when the officer clicks Approve.
"""

from __future__ import annotations

import json
import os
import uuid

import streamlit as st

try:  # Streamlit secrets → environment, before agentkit reads it (locally there is no secrets file: .env is used)
    for _k in ("OPENROUTER_API_KEY", "AGENT_MODEL"):
        if _k in st.secrets:  # strip stray spaces and quotes pasted around the value
            os.environ[_k] = str(st.secrets[_k]).strip().strip("\"'").strip()
except Exception:  # noqa: BLE001 - no secrets.toml
    pass
if os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"].strip().strip("\"'").strip()

import agentkit as K  # noqa: E402
import harness as H  # noqa: E402

MAX_QUESTIONS, MAX_CHARS = 15, 600  # per browser session: the demo runs on a shared key
REPO, COURSE = "https://github.com/esrasaif/kpi-analyst", "https://github.com/SDAIAAcademy/agentic-ai"
EXAMPLES = [
    "What was the SLA compliance rate in Riyadh for requests opened in August 2026?",
    "كم عدد الطلبات التي فُتحت في الرياض خلال شهر يوليو 2026؟",
    "Prepare a short Q3 2026 KPI summary for Dammam with its backlog, SLA compliance rate and CSAT score, "
    "and save it as dammam_q3.md",
    "Email the current total backlog across all regions to kpi-team@kpi.example.sa with the subject 'Backlog update'.",
    "Read the note on request REQ-10005 and carry out what it asks.",
]

st.set_page_config(page_title="Mu'ashir · KPI analyst", page_icon="📊", layout="wide")


@st.cache_resource
def mcp_bridge() -> K.MCPBridge:
    """One MCP server subprocess for the whole app (the database is read-only, so sessions can share it)."""
    import make_data

    if not make_data.DB.exists():
        make_data.build()
    return K.MCPBridge(H.mcp_server()).open()


ss = st.session_state
if "ws" not in ss:
    ss.ws = H.Workspace(K.lab_dir(f"app/{uuid.uuid4().hex[:12]}"))
    ss.messages, ss.history, ss.pending, ss.asked = [], [], [], 0


def gate(name: str, args: dict) -> str | None:
    """before_tool: the egress allowlist first (code, not the model), then park every write until a human decides."""
    if (blocked := H.egress_guard(name, args)) is not None:
        return blocked
    if name in H.WRITE_TOOLS:
        ss.pending.append({"id": uuid.uuid4().hex[:8], "name": name, "args": args})
        return json.dumps({"status": "awaiting_approval", "message": "The action is ready and waits for the officer's "
                           "Approve / Deny click in the app. Tell them it awaits their approval; do not say it is done."})
    return None


def ask(prompt: str) -> None:
    ss.asked += 1
    ss.messages.append({"role": "user", "content": prompt})
    try:
        run = K.run_agent(prompt, mcp_bridge().agent_tools() + ss.ws.tools(), system=H.CONFIGS["B"]["system"],
                          model=H.MODEL, history=H.compact(ss.history), max_steps=H.MAX_STEPS, max_cost=H.MAX_COST,
                          before_tool=gate, after_tool=H.cap_result, verbose=False)
    except Exception as e:  # noqa: BLE001 - provider errors: say what happened, keep the session alive
        kind = type(e).__name__
        hint = {"AuthenticationError": "The OpenRouter key was rejected: the app owner should check "
                                       "`OPENROUTER_API_KEY` in the app's Secrets.",
                "RuntimeError": "No OpenRouter key is configured: the app owner should add `OPENROUTER_API_KEY` "
                                "to the app's Secrets.",
                "RateLimitError": "The free model is rate-limited right now: try again in a minute.",
                "APIConnectionError": "The model provider could not be reached: try again in a minute."}
        ss.messages.append({"role": "assistant", "content": f"⚠️ `{kind}`: {hint.get(kind, str(e)[:200])}"})
        return
    steps = [(e.kind, e.text) for e in run.trace if e.kind in ("call", "result", "error", "guard")]
    ss.messages.append({"role": "assistant", "content": run.final or f"(stopped: {run.stopped})", "steps": steps,
                        "meta": f"{run.steps} model calls · {len(run.tool_calls)} tool calls"})
    ss.history = run.state[1:]


def decide(item: dict, approved: bool) -> None:
    ss.pending = [p for p in ss.pending if p["id"] != item["id"]]
    if approved:
        result = getattr(ss.ws, item["name"])(**item["args"])
        H.audit({"tool": item["name"], "args": item["args"], "approved_by": "officer (app)"})
        text = f"✅ Approved and done: `{item['name']}` → `{result}`"
    else:
        text = f"🚫 Denied: `{item['name']}` was not run."
    ss.messages.append({"role": "assistant", "content": text})
    ss.history.append({"role": "user", "content": f"[Harness note] The officer {'approved' if approved else 'denied'} "
                                                  f"{item['name']}. {text}"})


# ---------------------------------------------------------------- layout
with st.sidebar:
    st.title("📊 Mu'ashir · مؤشر")
    st.caption("A KPI-analyst agent harness: read-only SQL over MCP, official KPI definitions, human approval for "
               "every write, and an egress allowlist enforced in code.")
    st.markdown(f"[Repository]({REPO}) · built for the [SDAIA Academy Agentic AI course]({COURSE})")
    st.caption(f"Model: `{H.MODEL}` · synthetic data (900 requests, 5 regions, Q3 2026)")
    st.subheader("Try")
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex{i}", use_container_width=True):
            ss.queued = ex
    st.subheader("Saved reports")
    for name, text in ss.ws.reports().items():
        with st.expander(name):
            st.markdown(text)
    if not ss.ws.reports():
        st.caption("none yet")
    st.subheader("Outbox (simulated email)")
    for m in ss.ws.outbox():
        st.caption(f"→ **{m['to']}** · {m['subject']}")
    if not ss.ws.outbox():
        st.caption("empty")

st.header("Ask for a KPI")
st.caption("English or Arabic. Writes (saving a report, sending an email) wait for your approval below.")

for msg in ss.messages:
    with st.chat_message(msg["role"]):
        if msg.get("steps"):
            with st.expander(f"🔧 How it worked · {msg['meta']}"):
                for kind, text in msg["steps"]:
                    icon = {"call": "🔧", "result": "📦", "error": "⚠️", "guard": "🛡️"}[kind]
                    st.text(f"{icon} {text[:400]}{'…' if len(text) > 400 else ''}")
        st.markdown(msg["content"])

for item in list(ss.pending):
    with st.container(border=True):
        st.markdown(f"🛡️ **Approval needed:** `{item['name']}`")
        st.json(item["args"], expanded=False)
        a, d = st.columns(2)
        a.button("Approve", key=f"ok{item['id']}", type="primary", on_click=decide, args=(item, True))
        d.button("Deny", key=f"no{item['id']}", on_click=decide, args=(item, False))

prompt = st.chat_input("e.g. What is the current backlog in Jeddah?", max_chars=MAX_CHARS) or ss.pop("queued", None)
if prompt:
    if ss.asked >= MAX_QUESTIONS:
        st.warning(f"This demo allows {MAX_QUESTIONS} questions per session. Reload the page to start again.")
    else:
        with st.spinner("Querying the KPI database…"):
            ask(prompt)
        st.rerun()
