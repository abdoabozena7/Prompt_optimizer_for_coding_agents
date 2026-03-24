from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

from prompt_optimizer.analysis import analyze_for_clarification, generate_final_prompt
from prompt_optimizer.context import build_repo_context
from prompt_optimizer.diff_utils import (
    combine_diff_sources,
    extract_changed_paths,
    looks_like_binary_diff,
)
from prompt_optimizer.preferences import load_preferences, save_preferences
from prompt_optimizer.providers import (
    DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    select_preferred_model,
)
from prompt_optimizer.repo_ops import (
    ensure_local_project_path,
    get_remote_commit_diff,
    get_remote_last_commits,
    is_valid_repo_url,
    safe_filename,
    save_diff_to_app_storage,
)

st.set_page_config(page_title="Prompt Optimizer", page_icon="🧭", layout="wide")

COPY = {
    "en": {
        "lang": "Language",
        "workspace": "Project Workspace",
        "intake": "Intake",
        "analysis": "Analysis",
        "clarifications": "Clarifications",
        "final": "Final Prompt",
        "intent": "Implementation Intent",
        "intent_note": "Define the architectural scope of your prompt",
        "prompt_ph": "Describe your implementation intent...",
        "diff": "Unified Diff Input",
        "diff_ph": "Paste unified diff content here.",
        "project": "Project Context",
        "project_ph": r"D:\projects\my-project",
        "remote": "Remote Source",
        "remote_ph": "https://github.com/owner/repo",
        "fetch": "Fetch Recent Commits",
        "refresh": "Refresh",
        "activity": "Recent Activity",
        "engine": "Engine Config",
        "analyze": "Analyze",
        "generate": "Generate Final Prompt",
        "restart": "Start New Optimization",
        "results": "Analysis Results",
        "results_note": "Review the parsed intent and clarify what is still ambiguous.",
        "agent": "Agent is trying to...",
        "user": "You are trying to say...",
        "missing": "Unclear Points",
        "clarify": "Clarification Required",
        "custom": "Custom definition (optional)...",
        "final_title": "Final Output",
        "final_note": "Refined, structured, and ready for deployment.",
        "copy_ready": "Ready for copy",
        "export": "Export as .md",
        "summary": "Optimization Summary",
        "ollama_off": "Ollama Unavailable",
        "ollama_body": "The local LLM engine could not be detected. Prompt Optimizer requires a running Ollama instance to analyze and optimize your inputs locally.",
        "reconnect": "Reconnect Instance",
        "open_logs": "Open Logs",
        "step1": "Ensure the Ollama desktop application is active.",
        "step2": "Verify port 11434 is open and not blocked.",
        "need_input": "Provide at least a prompt or a diff before running analysis.",
        "need_remote": "Enter a remote Git URL first.",
        "invalid_remote": "Remote Git URL is not a supported GitHub or GitLab URL.",
        "fetching": "Fetching recent commits...",
        "analyzing": "Analyzing diff and preparing clarifications...",
        "building": "Generating the final English prompt...",
        "save": "Save Locally",
        "insert": "Insert Diff",
        "saved": "Saved inside Prompt Optimizer: {path}",
        "open_saved": "Open saved diff",
        "fallback": "Preferred model '{requested}' is unavailable. Using '{resolved}'.",
        "skipped": "Skipped binary-looking files: {files}",
        "no_questions": "No clarification questions were required. The final prompt was generated automatically.",
        "status_ready": "Ready",
        "status_off": "Disconnected",
        "use_local": "The local project path is read-only for code context. Remote Git is optional and only used to import commit diffs.",
    },
    "ar": {
        "lang": "اللغة",
        "workspace": "مساحة المشروع",
        "intake": "الإدخال",
        "analysis": "التحليل",
        "clarifications": "التوضيحات",
        "final": "البرومبت النهائي",
        "intent": "نية التنفيذ",
        "intent_note": "حدد النطاق المعماري للطلب",
        "prompt_ph": "اكتب intent أو الطلب الأساسي هنا...",
        "diff": "إدخال الـ Diff",
        "diff_ph": "الصق unified diff هنا.",
        "project": "سياق المشروع",
        "project_ph": r"D:\projects\my-project",
        "remote": "المصدر البعيد",
        "remote_ph": "https://github.com/owner/repo",
        "fetch": "هات آخر commits",
        "refresh": "تحديث",
        "activity": "آخر النشاط",
        "engine": "إعدادات المحرك",
        "analyze": "حلل",
        "generate": "ولّد البرومبت النهائي",
        "restart": "ابدأ تحسينًا جديدًا",
        "results": "نتائج التحليل",
        "results_note": "راجع فهم النظام وحدد ما بقي غامضًا.",
        "agent": "الوكيل يحاول أن...",
        "user": "أنت تحاول أن تقول...",
        "missing": "النقاط غير الواضحة",
        "clarify": "توضيحات مطلوبة",
        "custom": "توضيح إضافي اختياري...",
        "final_title": "الناتج النهائي",
        "final_note": "منظم وجاهز للاستخدام.",
        "copy_ready": "جاهز للنسخ",
        "export": "تصدير .md",
        "summary": "ملخص التحسين",
        "ollama_off": "Ollama غير متاح",
        "ollama_body": "تعذر الوصول إلى المحرك المحلي. Prompt Optimizer يحتاج Ollama شغالًا لتحليل المدخلات محليًا.",
        "reconnect": "أعد الاتصال",
        "open_logs": "افتح السجلات",
        "step1": "تأكد أن Ollama شغال على الجهاز.",
        "step2": "تأكد أن المنفذ 11434 مفتوح.",
        "need_input": "أدخل prompt أو diff قبل التحليل.",
        "need_remote": "أدخل رابط الريبو أولًا.",
        "invalid_remote": "رابط الريبو غير مدعوم.",
        "fetching": "جاري جلب آخر commits...",
        "analyzing": "جاري التحليل...",
        "building": "جاري توليد البرومبت النهائي...",
        "save": "احفظ محليًا",
        "insert": "أدرج الـ diff",
        "saved": "تم حفظ الـ diff داخل التطبيق: {path}",
        "open_saved": "افتح diff المحفوظ",
        "fallback": "الموديل المفضل '{requested}' غير متاح. سيتم استخدام '{resolved}'.",
        "skipped": "تم تجاهل ملفات تبدو binary: {files}",
        "no_questions": "لا توجد أسئلة توضيحية. تم توليد البرومبت النهائي تلقائيًا.",
        "status_ready": "جاهز",
        "status_off": "منفصل",
        "use_local": "المسار المحلي للقراءة فقط كسياق للكود. الربط البعيد اختياري.",
    },
}


def tr(key: str) -> str:
    return COPY[st.session_state.ui_language][key]


@st.cache_data(show_spinner=False)
def fetch_remote_commits(url: str):
    return get_remote_last_commits(url, 5)


@st.cache_data(show_spinner=False)
def fetch_remote_diff(url: str, commit_hash: str) -> str:
    return get_remote_commit_diff(url, commit_hash)


@st.cache_data(show_spinner=False, ttl=10)
def fetch_ollama_models() -> list[str]:
    return OllamaProvider().list_models()


def init_state() -> None:
    prefs = load_preferences()
    defaults = {
        "prompt_text": "",
        "manual_diff": "",
        "pending_diff_append": "",
        "loaded_remote_git_url": "",
        "remote_commits": [],
        "analysis_result": None,
        "generated_prompt": "",
        "analysis_error": "",
        "saved_diff_message": "",
        "saved_diff_path": "",
        "analysis_signature": "",
        "project_path_input": prefs.get("last_project_path", ""),
        "remote_git_url_input": prefs.get("last_remote_git_url", ""),
        "ui_language": prefs.get("last_ui_language", "en"),
        "selected_model_input": prefs.get("last_model", DEFAULT_OLLAMA_MODEL),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def persist_prefs() -> None:
    save_preferences(
        last_project_path=st.session_state.project_path_input.strip(),
        last_remote_git_url=st.session_state.remote_git_url_input.strip(),
        last_ui_language=st.session_state.ui_language,
        last_model=st.session_state.selected_model_input,
    )


def clear_outputs() -> None:
    st.session_state.analysis_result = None
    st.session_state.generated_prompt = ""
    st.session_state.analysis_error = ""
    st.session_state.analysis_signature = ""


def apply_pending_diff() -> None:
    pending = st.session_state.pending_diff_append.strip()
    if not pending:
        return
    current = st.session_state.manual_diff.strip()
    st.session_state.manual_diff = (
        f"{current}\n\n{pending}\n" if current else f"{pending}\n"
    )
    st.session_state.pending_diff_append = ""


def load_uploaded(files) -> tuple[list[tuple[str, str]], list[str]]:
    payloads, skipped = [], []
    for uploaded in (files or [])[:10]:
        raw = uploaded.getvalue()
        if looks_like_binary_diff(raw, uploaded.name):
            skipped.append(uploaded.name)
            continue
        payloads.append((uploaded.name, raw.decode("utf-8", errors="replace")))
    return payloads, skipped


def signature(
    prompt_text: str, diff_text: str, project_path: str, remote_url: str, model: str
) -> str:
    blob = "\x1f".join(
        [
            prompt_text.strip(),
            diff_text.strip(),
            project_path.strip(),
            remote_url.strip(),
            model.strip(),
        ]
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def active_stage() -> str:
    if st.session_state.generated_prompt:
        return "final"
    if st.session_state.analysis_result is None:
        return "intake"
    return (
        "clarifications"
        if st.session_state.analysis_result.followup_questions
        else "analysis"
    )


def fmt_dt(value: str) -> str:
    if not value.strip():
        return ""
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%b %d %I:%M %p")
        )
    except ValueError:
        return value


def open_saved(path_value: str) -> None:
    target = Path(path_value).expanduser().resolve()
    if not target.exists():
        raise RuntimeError(f"Saved diff file was not found: {target}")
    if os.name == "nt":
        subprocess.run(["explorer", f"/select,{target}"], check=False)
    else:
        subprocess.run(["xdg-open", str(target.parent)], check=False)


def repo_context(project_path_input: str, changed_paths: list[str]) -> list:
    root = None
    if project_path_input.strip():
        root = ensure_local_project_path(project_path_input.strip())
    return build_repo_context(root, changed_paths)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@400;500;600;700&family=Cairo:wght@400;600;700;800&family=Material+Symbols+Outlined&display=swap');
        :root{--bg:#131314;--low:#1b1b1c;--high:#2a2a2b;--highest:#353436;--code:#0e0e0f;--text:#e5e2e3;--muted:#8d90a2;--blue:#0052ff;--blue-soft:#b7c4ff;--danger:#ffb4ab;}
        .stApp{background:var(--bg);color:var(--text)} .stApp *:not(code):not(pre){font-family:'Inter',sans-serif}
        [data-testid="stHeader"],[data-testid="stToolbar"],#MainMenu,footer{display:none!important}
        .block-container{max-width:100%;padding:0 1rem 4rem}
        .topbar{position:sticky;top:0;z-index:50;height:56px;background:rgba(19,19,20,.98);display:flex;align-items:center;justify-content:space-between;padding:0 1rem;margin:0 -1rem 1rem;border-bottom:1px solid rgba(255,255,255,.05);backdrop-filter:blur(14px)}
        .brand{font-family:'Space Grotesk',sans-serif!important;font-size:1.05rem;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:-.04em}
        .nav{display:flex;gap:1rem;color:#8e918f;font-family:'Space Grotesk',sans-serif!important;font-size:.68rem;text-transform:uppercase;letter-spacing:.05em}
        .shell{display:grid;grid-template-columns:250px minmax(0,1fr);gap:1rem;align-items:start}
        .sidebar{position:sticky;top:72px;height:calc(100vh - 88px);background:var(--low);padding:1rem .75rem;overflow:auto}
        .side-title{padding:0 .75rem;margin-bottom:1rem}.side-title h2{margin:0;color:var(--blue);font:700 .78rem 'Space Grotesk',sans-serif!important;text-transform:uppercase;letter-spacing:.12em}.side-title p{margin:.25rem 0 0;color:#8e918f;font-size:.64rem;text-transform:uppercase;letter-spacing:.1em}
        .stage{display:flex;gap:.65rem;align-items:center;padding:.9rem .8rem;color:#8e918f;margin-bottom:.15rem}.stage.active{background:var(--high);color:#fff;border-left:2px solid var(--blue)}
        .icon{font-family:'Material Symbols Outlined'!important;font-size:1rem}.utility{display:flex;gap:.6rem;align-items:center;padding:.55rem .8rem;color:#8e918f;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em}
        .head{margin-bottom:1.25rem;padding-left:1rem;border-left:3px solid var(--blue)} .head h1{margin:0;font:700 2.5rem 'Space Grotesk',sans-serif!important;color:#fff;letter-spacing:-.04em}.head p{margin:.35rem 0 0;color:#9aa0ab}
        .section{display:flex;justify-content:space-between;align-items:center;padding-left:.85rem;border-left:2px solid var(--blue-soft);margin-bottom:.85rem}.section h3,.section h4{margin:0;font:600 1rem 'Space Grotesk',sans-serif!important;text-transform:uppercase;color:#fff}.kicker{margin:.2rem 0 0;color:var(--muted);font-size:.62rem;text-transform:uppercase;letter-spacing:.12em}.chip{display:inline-block;background:rgba(0,82,255,.08);color:rgba(183,196,255,.8);font:.62rem ui-monospace,monospace;padding:.35rem .5rem;text-transform:uppercase;letter-spacing:.12em}
        .panel{background:var(--low);padding:1.15rem}.panel-high{background:var(--high);padding:1.15rem}.question{background:var(--low);padding:1.25rem;margin-bottom:1rem}.qcode{color:var(--blue-soft);font:.68rem ui-monospace,monospace;margin-bottom:.5rem}.qtitle{color:#fff;font:500 1.02rem 'Space Grotesk',sans-serif!important;line-height:1.45;margin-bottom:.8rem}
        .commit{background:var(--high);padding:.95rem;margin-bottom:.65rem}.commit h5{margin:.3rem 0 .65rem;color:#fff;font-size:.82rem;line-height:1.45}.meta{display:flex;justify-content:space-between;color:var(--muted);font-size:.64rem;text-transform:uppercase;letter-spacing:.08em}
        .status{position:fixed;left:0;right:0;bottom:0;height:2rem;background:rgba(19,19,20,.92);backdrop-filter:blur(12px);display:flex;justify-content:space-between;align-items:center;padding:0 1rem;border-top:1px solid rgba(255,255,255,.04);z-index:45}.status span{color:#8e918f;font:.62rem ui-monospace,monospace;text-transform:uppercase;letter-spacing:.11em}
        .good{color:#5dd39e!important}.bad{color:#e5a29b!important}.blue{color:var(--blue-soft)!important}
        .stTextArea textarea,.stTextInput input,.stSelectbox div[data-baseweb="select"]>div,.stFileUploader section{background:var(--high)!important;border:none!important;color:var(--text)!important;border-radius:0!important;box-shadow:none!important}
        .stTextArea textarea,.stTextInput input{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace!important}
        .stButton button,.stDownloadButton button{width:100%;background:var(--high)!important;color:var(--text)!important;border:1px solid rgba(141,144,162,.2)!important;border-radius:0!important;box-shadow:none!important;text-transform:uppercase!important;letter-spacing:.1em!important;font-size:.7rem!important;font-weight:700!important;min-height:2.8rem!important}
        .stButton button[kind="primary"]{background:var(--blue)!important;border-color:var(--blue)!important;color:#fff!important}
        .stRadio label{background:var(--high);border:1px solid rgba(255,255,255,.08);padding:.8rem .9rem!important;margin:0!important;border-radius:0!important;align-items:flex-start!important}
        .stRadio label:has(input:checked){border-color:var(--blue)!important;background:rgba(0,82,255,.12)!important}.stRadio p{color:var(--text)!important}
        .stCodeBlock pre,.stCode code{background:var(--code)!important;border:none!important;border-radius:0!important}
        @media (max-width:1100px){.shell{grid-template-columns:1fr}.sidebar{position:static;height:auto}.nav{display:none}.status{position:static;height:auto;flex-direction:column;align-items:flex-start;gap:.35rem;padding:.75rem 1rem;margin-top:1rem}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar(stage_name: str, available_models: list[str], model_state: str) -> None:
    names = [
        ("intake", "input"),
        ("analysis", "analytics"),
        ("clarifications", "quiz"),
        ("final", "auto_awesome"),
    ]
    st.markdown('<div class="sidebar">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="side-title"><h2>{tr("workspace")}</h2><p>v1.0.4-stable</p></div>',
        unsafe_allow_html=True,
    )
    for name, icon in names:
        active = stage_name == name or (
            name == "analysis" and stage_name == "clarifications"
        )
        cls = "stage active" if active else "stage"
        st.markdown(
            f'<div class="{cls}"><span class="icon">{icon}</span><span>{tr(name if name != "final" else "final")}</span></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div class="utility"><span class="icon">cloud_download</span>{tr("remote")}</div><div class="utility"><span class="icon">history</span>{tr("activity")}</div><div class="utility"><span class="icon">folder_open</span>{tr("project")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(tr("lang"))
    st.radio(
        tr("lang"),
        list(COPY.keys()),
        format_func=lambda x: {"en": "English", "ar": "العربية"}[x],
        key="ui_language",
        horizontal=True,
        label_visibility="collapsed",
    )
    save_preferences(last_ui_language=st.session_state.ui_language)
    if available_models:
        st.selectbox(
            tr("engine"),
            available_models,
            key="selected_model_input",
            label_visibility="collapsed",
        )
        save_preferences(last_model=st.session_state.selected_model_input)
    else:
        st.text_input(
            tr("engine"),
            value="No models available",
            disabled=True,
            label_visibility="collapsed",
        )
    st.markdown(
        f'<div class="chip" style="margin-top:.4rem;">{model_state}</div></div>',
        unsafe_allow_html=True,
    )


init_state()
apply_pending_diff()
inject_styles()

try:
    models = fetch_ollama_models()
    selection = select_preferred_model(models, st.session_state.selected_model_input)
    resolved_model = selection.resolved_model
    if st.session_state.selected_model_input not in models:
        st.session_state.selected_model_input = resolved_model
    model_error = ""
except Exception as exc:
    models, selection, resolved_model, model_error = [], None, "", str(exc)

uploaded_diffs, skipped = load_uploaded(st.session_state.get("uploaded_diff_files", []))
combined_diff = combine_diff_sources(st.session_state.manual_diff, uploaded_diffs)
changed_paths = extract_changed_paths(combined_diff)
current_sig = signature(
    st.session_state.prompt_text,
    combined_diff,
    st.session_state.project_path_input,
    st.session_state.remote_git_url_input,
    st.session_state.selected_model_input if models else "",
)
if (
    st.session_state.analysis_signature
    and current_sig != st.session_state.analysis_signature
):
    clear_outputs()

stage_name = active_stage()
model_state = tr("status_ready") if models else tr("status_off")

st.markdown(
    '<div class="topbar"><div class="brand">Prompt Optimizer</div><div class="nav"><span>MODELS</span><span>SETTINGS</span></div></div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="shell">', unsafe_allow_html=True)
side_col, main_col = st.columns([1, 4], gap="medium")
with side_col:
    sidebar(stage_name, models, model_state)

with main_col:
    if not models:
        st.markdown(
            f'<div class="head"><h1>{tr("ollama_off")}</h1><p>{tr("ollama_body")}</p></div>',
            unsafe_allow_html=True,
        )
        a, b = st.columns(2, gap="medium")
        with a:
            st.markdown(
                f'<div class="panel"><div class="chip">STEP 01</div><div style="margin-top:.7rem">{tr("step1")}</div></div>',
                unsafe_allow_html=True,
            )
        with b:
            st.markdown(
                f'<div class="panel-high"><div class="chip">STEP 02</div><div style="margin-top:.7rem">{tr("step2")}</div></div>',
                unsafe_allow_html=True,
            )
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            if st.button(tr("reconnect"), type="primary", use_container_width=True):
                fetch_ollama_models.clear()
                st.rerun()
        with c2:
            st.button(tr("open_logs"), use_container_width=True, disabled=True)
        if model_error:
            st.error(model_error)
    elif stage_name == "final":
        result = st.session_state.analysis_result
        st.markdown(
            f'<div class="head"><h1>{tr("final_title")}</h1><p>{tr("final_note")}</p></div>',
            unsafe_allow_html=True,
        )
        m1, m2 = st.columns([2.2, 1], gap="large")
        with m1:
            st.markdown(
                f'<div class="panel"><div class="meta"><span>markdown_prompt_final.md</span><span class="blue">{tr("copy_ready")}</span></div></div>',
                unsafe_allow_html=True,
            )
            st.code(st.session_state.generated_prompt, language="markdown")
            st.download_button(
                tr("export"),
                st.session_state.generated_prompt.encode("utf-8"),
                file_name="prompt-optimizer-final.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with m2:
            st.markdown(
                f'<div class="panel"><div class="qtitle" style="font-size:.95rem">{tr("summary")}</div><div class="kicker">Intent</div><div>{result.user_intent if result else "--"}</div><div class="kicker" style="margin-top:1rem">Length</div><div>{len(st.session_state.generated_prompt.split())} tokens</div></div>',
                unsafe_allow_html=True,
            )
    elif stage_name in {"analysis", "clarifications"}:
        result = st.session_state.analysis_result
        st.markdown(
            f'<div class="head"><h1>{tr("results")}</h1><p>{tr("results_note")}</p></div>',
            unsafe_allow_html=True,
        )
        top1, top2 = st.columns([2.2, 1], gap="large")
        with top1:
            i1, i2 = st.columns(2, gap="small")
            with i1:
                st.markdown(
                    f'<div class="panel"><div class="kicker">System Interpretation</div><div class="qtitle">{tr("agent")}</div><div>{result.agent_intent}</div></div>',
                    unsafe_allow_html=True,
                )
            with i2:
                st.markdown(
                    f'<div class="panel-high"><div class="kicker">User Intent</div><div class="qtitle">{tr("user")}</div><div>{result.user_intent}</div></div>',
                    unsafe_allow_html=True,
                )
        with top2:
            st.markdown(
                f'<div class="panel"><div class="kicker">Ambiguity Report</div><div class="qtitle">{tr("missing")}</div>',
                unsafe_allow_html=True,
            )
            if result.missing_info:
                for item in result.missing_info:
                    st.markdown(f"- {item}")
            else:
                st.caption(tr("no_questions"))
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:1rem;margin:1.6rem 0 1rem"><h2 style="margin:0;font-family:Space Grotesk,sans-serif;color:white;">{tr("clarify")}</h2><div style="flex:1;height:1px;background:rgba(255,255,255,.08)"></div></div>',
            unsafe_allow_html=True,
        )
        if result.followup_questions:
            for idx, question in enumerate(result.followup_questions):
                st.markdown(
                    f'<div class="question"><div class="qcode">{idx + 1:02d} // CLARIFICATION</div><div class="qtitle">{question.question}</div></div>',
                    unsafe_allow_html=True,
                )
                st.radio(
                    f"q_{idx}",
                    question.options,
                    key=f"clarification_choice_{idx}",
                    label_visibility="collapsed",
                )
                st.text_input(
                    tr("custom"),
                    key=f"clarification_custom_{idx}",
                    label_visibility="collapsed",
                    placeholder=tr("custom"),
                )
        else:
            st.info(tr("no_questions"))
    else:
        st.markdown(
            f'<div class="section"><div><h3>{tr("intent")}</h3><div class="kicker">{tr("intent_note")}</div></div><div class="chip">BLOCK_01</div></div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            tr("intent"),
            key="prompt_text",
            placeholder=tr("prompt_ph"),
            height=210,
            label_visibility="collapsed",
        )
        left, right = st.columns([2.2, 1], gap="large")
        with left:
            b1, b2 = st.columns(2, gap="large")
            with b1:
                st.markdown(
                    f'<div class="section"><div><h4>{tr("diff")}</h4></div></div>',
                    unsafe_allow_html=True,
                )
                st.file_uploader(
                    tr("diff"),
                    type=["diff", "patch", "txt"],
                    accept_multiple_files=True,
                    key="uploaded_diff_files",
                    label_visibility="collapsed",
                )
                st.text_area(
                    tr("diff"),
                    key="manual_diff",
                    placeholder=tr("diff_ph"),
                    height=220,
                    label_visibility="collapsed",
                )
            with b2:
                st.markdown(
                    f'<div class="section"><div><h4>{tr("project")}</h4></div></div>',
                    unsafe_allow_html=True,
                )
                st.text_input(
                    tr("project"),
                    key="project_path_input",
                    placeholder=tr("project_ph"),
                    label_visibility="collapsed",
                )
                st.markdown(
                    f'<div class="panel"><div class="kicker">Path</div><div class="chip">{st.session_state.project_path_input or "--"}</div><div class="kicker" style="margin-top:1rem">Diff</div><div class="chip">{len(changed_paths)} files</div></div>',
                    unsafe_allow_html=True,
                )
        with right:
            st.markdown(
                f'<div class="panel"><div class="kicker">{tr("remote")}</div>',
                unsafe_allow_html=True,
            )
            st.text_input(
                tr("remote"),
                key="remote_git_url_input",
                placeholder=tr("remote_ph"),
                label_visibility="collapsed",
            )
            f1, f2 = st.columns(2, gap="small")
            with f1:
                if st.button(tr("fetch"), use_container_width=True):
                    try:
                        if not st.session_state.remote_git_url_input.strip():
                            raise RuntimeError(tr("need_remote"))
                        if not is_valid_repo_url(st.session_state.remote_git_url_input):
                            raise RuntimeError(tr("invalid_remote"))
                        with st.spinner(tr("fetching")):
                            st.session_state.remote_commits = fetch_remote_commits(
                                st.session_state.remote_git_url_input.strip()
                            )
                        st.session_state.loaded_remote_git_url = (
                            st.session_state.remote_git_url_input.strip()
                        )
                        persist_prefs()
                        st.rerun()
                    except Exception as exc:
                        st.session_state.analysis_error = str(exc)
            with f2:
                if st.button(tr("refresh"), use_container_width=True):
                    fetch_remote_commits.clear()
                    fetch_remote_diff.clear()
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="panel" style="margin-top:1rem;"><div class="kicker">{tr("activity")}</div>',
                unsafe_allow_html=True,
            )
            for commit in st.session_state.remote_commits:
                diff_text = fetch_remote_diff(
                    st.session_state.loaded_remote_git_url, commit.full_hash
                )
                st.markdown(
                    f'<div class="commit"><div class="meta"><span>#{commit.short_hash}</span><span>{fmt_dt(commit.date)}</span></div><h5>{commit.subject}</h5></div>',
                    unsafe_allow_html=True,
                )
                x, y = st.columns(2, gap="small")
                with x:
                    if st.button(
                        tr("save"),
                        key=f"save_{commit.full_hash}",
                        use_container_width=True,
                    ):
                        path = save_diff_to_app_storage(
                            f"{commit.short_hash}_{safe_filename(commit.subject)}.diff",
                            diff_text,
                        )
                        st.session_state.saved_diff_message = tr("saved").format(
                            path=str(path)
                        )
                        st.session_state.saved_diff_path = str(path)
                        st.rerun()
                with y:
                    if st.button(
                        tr("insert"),
                        key=f"insert_{commit.full_hash}",
                        use_container_width=True,
                    ):
                        st.session_state.pending_diff_append = diff_text
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        if selection is not None and selection.used_fallback:
            st.warning(
                tr("fallback").format(
                    requested=selection.requested_model,
                    resolved=selection.resolved_model,
                )
            )
        if skipped:
            st.warning(tr("skipped").format(files=", ".join(skipped)))
        if st.session_state.saved_diff_message:
            st.success(st.session_state.saved_diff_message)
        if st.session_state.saved_diff_path and st.button(
            tr("open_saved"), use_container_width=False
        ):
            open_saved(st.session_state.saved_diff_path)
        st.caption(tr("use_local"))

st.markdown("</div>", unsafe_allow_html=True)

if (
    models
    and stage_name == "intake"
    and st.button(tr("analyze"), type="primary", use_container_width=True)
):
    try:
        if not st.session_state.prompt_text.strip() and not combined_diff.strip():
            raise RuntimeError(tr("need_input"))
        persist_prefs()
        with st.spinner(tr("analyzing")):
            context = repo_context(st.session_state.project_path_input, changed_paths)
            result = analyze_for_clarification(
                st.session_state.prompt_text,
                combined_diff,
                context,
                "Arabic" if st.session_state.ui_language == "ar" else "English",
                model=resolved_model,
                provider=OllamaProvider(),
            )
        st.session_state.analysis_result = result
        st.session_state.analysis_signature = current_sig
        st.session_state.analysis_error = ""
        if not result.followup_questions:
            with st.spinner(tr("building")):
                st.session_state.generated_prompt = generate_final_prompt(
                    st.session_state.prompt_text,
                    combined_diff,
                    context,
                    result,
                    [],
                    model=resolved_model,
                    provider=OllamaProvider(),
                )
        st.rerun()
    except Exception as exc:
        st.session_state.analysis_error = str(exc)
        st.rerun()
elif (
    models
    and stage_name == "clarifications"
    and st.button(tr("generate"), type="primary", use_container_width=True)
):
    try:
        answers = []
        for idx, question in enumerate(
            st.session_state.analysis_result.followup_questions
        ):
            answers.append(
                {
                    "question": question.question,
                    "selected_option": st.session_state.get(
                        f"clarification_choice_{idx}", ""
                    ),
                    "custom_text": st.session_state.get(
                        f"clarification_custom_{idx}", ""
                    ),
                }
            )
        with st.spinner(tr("building")):
            context = repo_context(st.session_state.project_path_input, changed_paths)
            st.session_state.generated_prompt = generate_final_prompt(
                st.session_state.prompt_text,
                combined_diff,
                context,
                st.session_state.analysis_result,
                answers,
                model=resolved_model,
                provider=OllamaProvider(),
            )
        st.session_state.analysis_error = ""
        st.session_state.analysis_signature = current_sig
        st.rerun()
    except Exception as exc:
        st.session_state.analysis_error = str(exc)
        st.rerun()
elif stage_name == "final" and st.button(
    tr("restart"), type="primary", use_container_width=True
):
    clear_outputs()
    st.rerun()

if st.session_state.analysis_error and models:
    st.error(st.session_state.analysis_error)

path_label = st.session_state.project_path_input.strip() or "--"
status_class = "good" if models else "bad"
st.markdown(
    f'<div class="status"><div style="display:flex;gap:1rem;flex-wrap:wrap;"><span class="{status_class}">OLLAMA STATUS: {model_state}</span><span class="blue">DIFF: {len(changed_paths)} FILES</span><span>PATH: {path_label}</span></div><div style="display:flex;gap:1rem;"><span>{stage_name.upper()}</span><span class="blue">{tr("status_ready")}</span></div></div>',
    unsafe_allow_html=True,
)
