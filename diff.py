from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess

import streamlit as st

from prompt_optimizer.analysis import (
    analyze_for_clarification,
    generate_final_prompt,
)
from prompt_optimizer.context import build_repo_context
from prompt_optimizer.diff_utils import (
    combine_diff_sources,
    extract_changed_paths,
    looks_like_binary_diff,
)
from prompt_optimizer.models import AnalysisResult, ClarificationQuestion
from prompt_optimizer.preferences import load_preferences, save_preferences
from prompt_optimizer.repo_ops import (
    ensure_local_project_path,
    get_remote_commit_diff,
    get_remote_last_commits,
    is_valid_repo_url,
    save_diff_to_app_storage,
    safe_filename,
)


st.set_page_config(
    page_title="Diff Intent Analyzer",
    page_icon="🎯",
    layout="wide",
)

DEFAULT_MODEL = "gpt-oss:120b-cloud"

LANGUAGE_OPTIONS = {
    "en": "English",
    "ar": "العربية",
}

TEXT = {
    "en": {
        "title": "Diff Intent Analyzer",
        "subtitle": "Analyze first, answer clarifications second, then generate the final prompt in English.",
        "settings": "Settings",
        "language": "Language",
        "prompt_section": "1. Prompt",
        "prompt_placeholder": "Describe what you asked the coding agent to do.",
        "project_section": "2. Local Project Path",
        "project_help": "Used to read the real project files for context.",
        "project_placeholder": r"D:\projects\my-project",
        "diff_section": "3. Diff",
        "diff_placeholder": "Paste a unified diff here.",
        "upload_label": "Upload diff files",
        "upload_help": "Optional. You can upload up to 10 diff files.",
        "remote_section": "Import from remote commits",
        "remote_placeholder": "https://github.com/owner/repo",
        "remote_help": "Optional. Used only to fetch recent commit diffs.",
        "fetch_commits": "Fetch recent commits",
        "refresh_commits": "Refresh",
        "last_refreshed": "Last refreshed: {time}",
        "ready": "Ready",
        "prompt_ready": "Prompt",
        "project_ready": "Project path",
        "changed_files": "Changed files",
        "missing": "Missing",
        "ready_value": "Ready",
        "run": "Run",
        "analyze": "Analyze first",
        "generate_final": "Generate final English prompt",
        "flow_note": "Flow: analyze -> answer questions -> generate final prompt.",
        "results": "Results",
        "agent_trying": "Agent is trying to...",
        "user_trying": "You are trying to say...",
        "missing_points": "Missing / unclear points",
        "no_missing": "No major missing information detected.",
        "questions_title": "Clarification questions",
        "questions_note": "Answer these first. The final prompt will be generated only after this step.",
        "option_label": "Choose one option",
        "custom_label": "Optional clarification",
        "custom_placeholder": "Add your own note if none of the three choices is exact.",
        "final_prompt_title": "Final prompt (English)",
        "no_output": "No output.",
        "no_questions": "No clarification questions were needed. You can generate the final English prompt now.",
        "remote_status_prefix": "Loaded recent commits from",
        "save_diff": "Save {short_hash}.diff locally",
        "put_in_diff": "Put in diff box",
        "saved_diff": "Saved inside Prompt Optimizer: {path}",
        "open_saved_diff": "Open saved diff",
        "skipped_files": "Skipped binary-looking files: {files}",
        "need_input": "Provide at least a prompt/plan or a diff before running analysis.",
        "need_remote_url": "Enter a remote Git URL first.",
        "invalid_remote_url": "Remote Git URL is not a supported GitHub or GitLab URL.",
        "fetching_commits": "Fetching recent commits...",
        "analyzing": "Analyzing diff and preparing clarification questions...",
        "building_prompt": "Generating the final English prompt...",
        "use_local_note": "The local project path is read-only for code context. Remote Git is optional and only used to import commit diffs.",
        "step_two": "Step 2",
        "step_two_desc": "These clarification cards are animated in and each one gives you 3 choices plus a custom note field.",
        "final_note": "The explanations and questions follow the selected UI language. The final prompt stays in English.",
    },
    "ar": {
        "title": "محلل نية الـ Diff",
        "subtitle": "حلل أولًا، جاوب على الأسئلة التوضيحية ثانيًا، وبعدها فقط يتم توليد الـ prompt النهائي بالإنجليزية.",
        "settings": "الإعدادات",
        "language": "اللغة",
        "prompt_section": "1. البرومبت",
        "prompt_placeholder": "اكتب ماذا طلبت من الـ agent أن ينفذه.",
        "project_section": "2. مسار المشروع المحلي",
        "project_help": "يُستخدم لقراءة ملفات المشروع الحقيقية وبناء السياق.",
        "project_placeholder": r"D:\projects\my-project",
        "diff_section": "3. الـ Diff",
        "diff_placeholder": "الصق الـ unified diff هنا.",
        "upload_label": "ارفع ملفات diff",
        "upload_help": "اختياري. يمكنك رفع حتى 10 ملفات diff.",
        "remote_section": "استيراد من commits الريبو",
        "remote_placeholder": "https://github.com/owner/repo",
        "remote_help": "اختياري. يُستخدم فقط لجلب commit diffs.",
        "fetch_commits": "هات آخر commits",
        "refresh_commits": "تحديث",
        "last_refreshed": "آخر تحديث: {time}",
        "ready": "الجاهزية",
        "prompt_ready": "البرومبت",
        "project_ready": "مسار المشروع",
        "changed_files": "الملفات المتغيرة",
        "missing": "ناقص",
        "ready_value": "جاهز",
        "run": "التنفيذ",
        "analyze": "حلل أولًا",
        "generate_final": "ولّد الـ prompt النهائي بالإنجليزية",
        "flow_note": "الترتيب: تحليل -> إجابة الأسئلة -> توليد الـ prompt النهائي.",
        "results": "النتائج",
        "agent_trying": "الـ Agent يحاول أن...",
        "user_trying": "أنت تحاول أن تقول...",
        "missing_points": "النقاط الناقصة / غير الواضحة",
        "no_missing": "لا توجد فجوات كبيرة واضحة.",
        "questions_title": "أسئلة توضيحية",
        "questions_note": "جاوب على هذه الأسئلة أولًا. لن يتم توليد الـ prompt النهائي إلا بعد هذه المرحلة.",
        "option_label": "اختر إجابة واحدة",
        "custom_label": "توضيح إضافي اختياري",
        "custom_placeholder": "أضف ملاحظتك لو لم يكن أي من الاختيارات الثلاثة مناسبًا تمامًا.",
        "final_prompt_title": "الـ Prompt النهائي (بالإنجليزية)",
        "no_output": "لا يوجد ناتج.",
        "no_questions": "لا توجد أسئلة توضيحية ضرورية. يمكنك الآن توليد الـ prompt النهائي بالإنجليزية.",
        "remote_status_prefix": "تم تحميل آخر commits من",
        "save_diff": "احفظ {short_hash}.diff داخل المشروع",
        "put_in_diff": "حطّه في خانة الـ diff",
        "saved_diff": "تم حفظ الـ diff في: {path}",
        "open_saved_diff": "افتح ملف الـ diff المحفوظ",
        "save_needs_project": "أدخل مسار المشروع المحلي أولًا حتى يتم حفظ الـ diff داخله.",
        "skipped_files": "تم تجاهل الملفات التي تبدو binary: {files}",
        "need_input": "أدخل على الأقل برومبت/بلان أو diff قبل بدء التحليل.",
        "need_remote_url": "أدخل رابط الريبو أولًا.",
        "invalid_remote_url": "رابط الريبو غير مدعوم. استخدم GitHub أو GitLab فقط.",
        "fetching_commits": "جاري جلب آخر commits...",
        "analyzing": "جاري تحليل الـ diff وتحضير الأسئلة التوضيحية...",
        "building_prompt": "جاري توليد الـ prompt النهائي بالإنجليزية...",
        "use_local_note": "المسار المحلي يُستخدم لقراءة الكود. رابط الريبو اختياري ويُستخدم فقط لاستيراد commit diffs.",
        "step_two": "الخطوة الثانية",
        "step_two_desc": "ستظهر كروت الأسئلة بحركة خفيفة، وكل سؤال فيه 3 اختيارات بالإضافة إلى خانة توضيح إضافية.",
        "final_note": "الشرح والأسئلة يتبعان اللغة المختارة، لكن الـ prompt النهائي يظل بالإنجليزية دائمًا.",
    },
}


@st.cache_data(show_spinner=False)
def fetch_remote_commits(remote_url: str):
    return get_remote_last_commits(remote_url, 5)


@st.cache_data(show_spinner=False)
def fetch_remote_diff(remote_url: str, commit_hash: str) -> str:
    return get_remote_commit_diff(remote_url, commit_hash)


def initialize_state() -> None:
    preferences = load_preferences()
    st.session_state.setdefault("manual_diff", "")
    st.session_state.setdefault("pending_diff_append", "")
    st.session_state.setdefault("loaded_remote_git_url", "")
    st.session_state.setdefault("remote_commits", [])
    st.session_state.setdefault("analysis_result", None)
    st.session_state.setdefault("analysis_error", "")
    st.session_state.setdefault("remote_status", "")
    st.session_state.setdefault("remote_refreshed_at", "")
    st.session_state.setdefault("generated_prompt", "")
    st.session_state.setdefault("saved_diff_message", "")
    st.session_state.setdefault("saved_diff_path", "")
    st.session_state.setdefault(
        "project_path_input",
        preferences.get("last_project_path", ""),
    )
    st.session_state.setdefault(
        "remote_git_url_input",
        preferences.get("last_remote_git_url", ""),
    )
    st.session_state.setdefault(
        "ui_language",
        preferences.get("last_ui_language", "en"),
    )


def apply_pending_diff() -> None:
    pending = st.session_state.get("pending_diff_append", "").strip()
    if not pending:
        return

    current = st.session_state.get("manual_diff", "").strip()
    if current:
        st.session_state.manual_diff = f"{current}\n\n{pending}\n"
    else:
        st.session_state.manual_diff = f"{pending}\n"
    st.session_state.pending_diff_append = ""


def clear_analysis_state() -> None:
    st.session_state.analysis_result = None
    st.session_state.analysis_error = ""
    st.session_state.generated_prompt = ""


def t(key: str, language_code: str) -> str:
    return TEXT[language_code][key]


def inject_styles(language_code: str) -> None:
    app_font = "'Cairo', sans-serif" if language_code == "ar" else "inherit"
    css = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');

        :root {
            --panel: rgba(15, 23, 42, 0.82);
            --panel-strong: rgba(15, 23, 42, 0.95);
            --border: rgba(148, 163, 184, 0.16);
            --text: #e5eefb;
            --muted: #94a3b8;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(249, 115, 22, 0.14), transparent 28%),
                radial-gradient(circle at top right, rgba(96, 165, 250, 0.14), transparent 25%),
                linear-gradient(180deg, #07111d 0%, #0b1220 42%, #0d1526 100%);
            color: var(--text);
            font-family: __APP_FONT__;
        }

        .stApp,
        .stApp *:not(code):not(pre):not(kbd):not(samp) {
            font-family: __APP_FONT__ !important;
        }

        header[data-testid="stHeader"] {
            display: none !important;
        }

        div[data-testid="stToolbar"] {
            display: none !important;
        }

        .block-container {
            max-width: 1200px;
            padding-top: 1.1rem;
            padding-bottom: 2.5rem;
        }

        .hero {
            background: linear-gradient(135deg, rgba(249,115,22,0.95), rgba(244,63,94,0.88) 52%, rgba(59,130,246,0.92));
            border-radius: 24px;
            padding: 1.2rem 1.3rem;
            margin-bottom: 1rem;
            box-shadow: 0 22px 46px rgba(2, 6, 23, 0.24);
        }

        .hero h1 {
            margin: 0;
            color: white;
            font-size: 2rem;
            line-height: 1.05;
        }

        .hero p {
            margin: 0.55rem 0 0 0;
            color: rgba(255,255,255,0.93);
            max-width: 780px;
        }

        .question-intro {
            background: rgba(59, 130, 246, 0.10);
            border: 1px solid rgba(96, 165, 250, 0.18);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.9rem;
            animation: fadeSlide 0.45s ease both;
        }

        .question-card {
            background: rgba(15, 23, 42, 0.76);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 18px;
            padding: 0.95rem 1rem 0.4rem 1rem;
            margin-bottom: 0.9rem;
            animation: fadeSlide 0.45s ease both;
        }

        .remote-list {
            display: grid;
            gap: 0.85rem;
            margin-top: 0.75rem;
        }

        .remote-card {
            background: rgba(15, 23, 42, 0.66);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 18px;
            padding: 0.95rem 1rem 1rem 1rem;
        }

        .remote-card-title {
            font-size: 1.04rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 0.35rem;
        }

        .remote-card-meta {
            color: var(--muted);
            font-size: 0.92rem;
            margin-bottom: 0.85rem;
            line-height: 1.5;
        }

        .question-title {
            font-weight: 700;
            color: var(--text);
            margin-bottom: 0.75rem;
        }

        @keyframes fadeSlide {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        div[data-testid="stTextArea"] textarea,
        div[data-testid="stTextInput"] input,
        div[data-testid="stFileUploader"] section,
        div[data-testid="stExpander"] details,
        div[data-testid="stCodeBlock"] pre {
            background: var(--panel) !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
            border-radius: 16px !important;
        }

        div[data-testid="stTextArea"] textarea::placeholder,
        div[data-testid="stTextInput"] input::placeholder {
            color: var(--muted) !important;
        }

        div[data-testid="stButton"] button,
        div[data-testid="stDownloadButton"] button {
            border-radius: 999px !important;
        }

        div[data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(135deg, #f97316, #f43f5e 54%, #3b82f6) !important;
            color: white !important;
            border: none !important;
            font-weight: 700 !important;
        }

        div[data-testid="stButton"] button:not([kind="primary"]),
        div[data-testid="stDownloadButton"] button {
            background: var(--panel-strong) !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
        }

        div[data-testid="stRadio"] label,
        div[data-testid="stMetricLabel"],
        div[data-testid="stMetricValue"],
        .stMarkdown, .stCaption, label, p, h1, h2, h3, h4 {
            color: var(--text) !important;
        }

        div[data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 0.8rem 1rem;
        }

        div[data-testid="stInfo"] {
            background: rgba(37, 99, 235, 0.12);
            border: 1px solid rgba(96, 165, 250, 0.18);
        }

        div[data-testid="stWarning"] {
            background: rgba(217, 119, 6, 0.12);
            border: 1px solid rgba(251, 146, 60, 0.18);
        }

        div[data-testid="stError"] {
            background: rgba(190, 24, 93, 0.14);
            border: 1px solid rgba(244, 114, 182, 0.18);
        }
        </style>
        """
    st.markdown(
        css.replace("__APP_FONT__", app_font),
        unsafe_allow_html=True,
    )


def render_header(language_code: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <h1>{t("title", language_code)}</h1>
            <p>{t("subtitle", language_code)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(t("use_local_note", language_code))
    st.caption(t("final_note", language_code))


def load_uploaded_diff_files(uploaded_files) -> tuple[list[tuple[str, str]], list[str]]:
    diff_payloads: list[tuple[str, str]] = []
    skipped_files: list[str] = []

    for uploaded in uploaded_files[:10]:
        raw = uploaded.getvalue()
        if looks_like_binary_diff(raw, uploaded.name):
            skipped_files.append(uploaded.name)
            continue
        diff_payloads.append((uploaded.name, raw.decode("utf-8", errors="replace")))

    return diff_payloads, skipped_files


def queue_commit_diff(diff_text: str) -> None:
    st.session_state.pending_diff_append = diff_text
    clear_analysis_state()


def save_remote_diff(
    commit_short_hash: str,
    commit_subject: str,
    diff_text: str,
    language_code: str,
) -> None:
    try:
        filename = f"{commit_short_hash}_{safe_filename(commit_subject)}.diff"
        target_path = save_diff_to_app_storage(filename, diff_text)
        st.session_state.saved_diff_message = t("saved_diff", language_code).format(
            path=str(target_path)
        )
        st.session_state.saved_diff_path = str(target_path)
        st.session_state.analysis_error = ""
    except Exception as exc:
        st.session_state.analysis_error = str(exc)


def open_saved_diff_path(path_value: str) -> None:
    target_path = Path(path_value).expanduser().resolve()
    if not target_path.exists():
        raise RuntimeError(f"Saved diff file was not found: {target_path}")

    if os.name == "nt":
        subprocess.run(
            ["explorer", f"/select,{target_path}"],
            check=False,
        )
        return

    try:
        os.startfile(str(target_path))  # type: ignore[attr-defined]
    except AttributeError:
        subprocess.run(["xdg-open", str(target_path.parent)], check=False)


def format_display_datetime(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw

    if parsed.tzinfo is None:
        return parsed.strftime("%b %d, %Y %I:%M %p")
    return parsed.astimezone().strftime("%b %d, %Y %I:%M %p")


def format_current_refresh_time() -> str:
    return datetime.now().astimezone().strftime("%b %d, %Y %I:%M %p")


def load_remote_commits(
    remote_git_url: str,
    language_code: str,
    *,
    force_refresh: bool = False,
) -> None:
    clear_analysis_state()
    st.session_state.saved_diff_message = ""
    st.session_state.saved_diff_path = ""

    if not remote_git_url.strip():
        raise RuntimeError(t("need_remote_url", language_code))
    if not is_valid_repo_url(remote_git_url):
        raise RuntimeError(t("invalid_remote_url", language_code))

    if force_refresh:
        fetch_remote_commits.clear()
        fetch_remote_diff.clear()

    with st.spinner(t("fetching_commits", language_code)):
        st.session_state.remote_commits = fetch_remote_commits(remote_git_url.strip())

    st.session_state.loaded_remote_git_url = remote_git_url.strip()
    st.session_state.remote_status = (
        f"{t('remote_status_prefix', language_code)} {remote_git_url.strip()}"
    )
    st.session_state.remote_refreshed_at = format_current_refresh_time()
    st.session_state.analysis_error = ""
    save_preferences(last_remote_git_url=remote_git_url.strip())


def render_result_card(title: str, body: str) -> None:
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(body or "No output.")


def render_question_block(
    question: ClarificationQuestion,
    index: int,
    language_code: str,
) -> None:
    st.markdown(
        f"""
        <div class="question-card" style="animation-delay: {index * 0.08}s;">
            <div class="question-title">{question.question}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.radio(
        t("option_label", language_code),
        options=question.options,
        index=None,
        key=f"clarification_choice_{index}",
    )
    st.text_area(
        t("custom_label", language_code),
        key=f"clarification_custom_{index}",
        placeholder=t("custom_placeholder", language_code),
        height=85,
    )


def render_analysis_result(result: AnalysisResult, language_code: str) -> None:
    st.markdown(f"## {t('results', language_code)}")
    col1, col2 = st.columns(2, gap="large")
    with col1:
        render_result_card(t("agent_trying", language_code), result.agent_intent)
    with col2:
        render_result_card(t("user_trying", language_code), result.user_intent)

    with st.container(border=True):
        st.markdown(f"#### {t('missing_points', language_code)}")
        if result.missing_info:
            for item in result.missing_info:
                st.markdown(f"- {item}")
        else:
            st.success(t("no_missing", language_code))

    if result.followup_questions:
        st.markdown(
            f"""
            <div class="question-intro">
                <strong>{t("step_two", language_code)}</strong><br>
                {t("questions_note", language_code)}<br>
                {t("step_two_desc", language_code)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(f"### {t('questions_title', language_code)}")
        for index, question in enumerate(result.followup_questions):
            render_question_block(question, index, language_code)
    else:
        st.info(t("no_questions", language_code))


def collect_clarification_answers(questions: list[ClarificationQuestion]) -> list[dict[str, str]]:
    answers: list[dict[str, str]] = []
    for index, question in enumerate(questions):
        answers.append(
            {
                "question": question.question,
                "selected_option": st.session_state.get(
                    f"clarification_choice_{index}",
                    "",
                )
                or "",
                "custom_text": st.session_state.get(
                    f"clarification_custom_{index}",
                    "",
                )
                or "",
            }
        )
    return answers


initialize_state()
apply_pending_diff()

language_code = st.radio(
    "Language",
    options=list(LANGUAGE_OPTIONS.keys()),
    format_func=lambda code: LANGUAGE_OPTIONS[code],
    horizontal=True,
    key="ui_language",
)
save_preferences(last_ui_language=language_code)
inject_styles(language_code)

render_header(language_code)

main_col, side_col = st.columns([1.7, 0.9], gap="large")

uploaded_files = []
with main_col:
    with st.container(border=True):
        st.markdown(f"### {t('prompt_section', language_code)}")
        prompt_text = st.text_area(
            "Prompt or plan",
            label_visibility="collapsed",
            placeholder=t("prompt_placeholder", language_code),
            height=170,
            key="prompt_text",
        )

    with st.container(border=True):
        st.markdown(f"### {t('project_section', language_code)}")
        project_path_input = st.text_input(
            "Project path",
            label_visibility="collapsed",
            placeholder=t("project_placeholder", language_code),
            help=t("project_help", language_code),
            key="project_path_input",
        )

    with st.container(border=True):
        st.markdown(f"### {t('diff_section', language_code)}")
        st.text_area(
            "Diff text",
            label_visibility="collapsed",
            placeholder=t("diff_placeholder", language_code),
            height=300,
            key="manual_diff",
        )

        upload_col, helper_col = st.columns([1.1, 0.9], gap="large")
        with upload_col:
            uploaded_files = st.file_uploader(
                t("upload_label", language_code),
                type=["diff", "patch", "txt"],
                accept_multiple_files=True,
                help=t("upload_help", language_code),
            )
        with helper_col:
            st.caption(t("upload_help", language_code))

        with st.expander(t("remote_section", language_code), expanded=False):
            top_col1, top_col2, top_col3 = st.columns([1.55, 0.6, 0.42], gap="medium")
            with top_col1:
                remote_git_url = st.text_input(
                    "Remote Git URL",
                    label_visibility="collapsed",
                    placeholder=t("remote_placeholder", language_code),
                    help=t("remote_help", language_code),
                    key="remote_git_url_input",
                )
            with top_col2:
                if st.button(t("fetch_commits", language_code), use_container_width=True):
                    try:
                        load_remote_commits(remote_git_url, language_code)
                    except Exception as exc:
                        st.session_state.remote_commits = []
                        st.session_state.loaded_remote_git_url = ""
                        st.session_state.remote_status = ""
                        st.session_state.remote_refreshed_at = ""
                        st.session_state.saved_diff_message = ""
                        st.session_state.saved_diff_path = ""
                        st.session_state.analysis_error = str(exc)
            with top_col3:
                if st.button(
                    t("refresh_commits", language_code),
                    use_container_width=True,
                ):
                    try:
                        load_remote_commits(
                            remote_git_url,
                            language_code,
                            force_refresh=True,
                        )
                    except Exception as exc:
                        st.session_state.remote_commits = []
                        st.session_state.loaded_remote_git_url = ""
                        st.session_state.remote_status = ""
                        st.session_state.remote_refreshed_at = ""
                        st.session_state.saved_diff_message = ""
                        st.session_state.saved_diff_path = ""
                        st.session_state.analysis_error = str(exc)

            if st.session_state.remote_status:
                st.info(st.session_state.remote_status)
            if st.session_state.remote_refreshed_at:
                st.caption(
                    t("last_refreshed", language_code).format(
                        time=st.session_state.remote_refreshed_at
                    )
                )
            if st.session_state.saved_diff_message:
                st.success(st.session_state.saved_diff_message)
            if st.session_state.saved_diff_path:
                if st.button(
                    t("open_saved_diff", language_code),
                    key="open_saved_diff_button",
                    use_container_width=False,
                ):
                    try:
                        open_saved_diff_path(st.session_state.saved_diff_path)
                    except Exception as exc:
                        st.session_state.analysis_error = str(exc)
                        st.rerun()

            for commit in st.session_state.remote_commits:
                diff_text = fetch_remote_diff(
                    st.session_state.loaded_remote_git_url,
                    commit.full_hash,
                )
                st.markdown(
                    f"""
                    <div class="remote-card">
                        <div class="remote-card-title">{commit.subject}</div>
                        <div class="remote-card-meta">{commit.short_hash} | {commit.author} | {format_display_datetime(commit.date)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                button_col1, button_col2 = st.columns([1.2, 1.0], gap="large")
                with button_col1:
                    if st.button(
                        t("save_diff", language_code).format(short_hash=commit.short_hash),
                        key=f"save_{commit.full_hash}",
                        use_container_width=True,
                    ):
                        save_remote_diff(
                            commit_short_hash=commit.short_hash,
                            commit_subject=commit.subject,
                            diff_text=diff_text,
                            language_code=language_code,
                        )
                        st.rerun()
                with button_col2:
                    if st.button(
                        t("put_in_diff", language_code),
                        key=f"insert_{commit.full_hash}",
                        use_container_width=True,
                    ):
                        queue_commit_diff(diff_text)
                        st.rerun()

with side_col:
    uploaded_diffs, skipped_binary_files = load_uploaded_diff_files(uploaded_files or [])
    combined_diff = combine_diff_sources(st.session_state.manual_diff, uploaded_diffs)
    changed_paths = extract_changed_paths(combined_diff)

    st.markdown(f"### {t('settings', language_code)}")
    st.metric(
        t("prompt_ready", language_code),
        t("ready_value", language_code) if prompt_text.strip() else t("missing", language_code),
    )
    st.metric(
        t("project_ready", language_code),
        t("ready_value", language_code) if project_path_input.strip() else t("missing", language_code),
    )
    st.metric(t("changed_files", language_code), str(len(changed_paths)))

    if skipped_binary_files:
        st.warning(
            t("skipped_files", language_code).format(
                files=", ".join(skipped_binary_files)
            )
        )

    st.markdown(f"### {t('run', language_code)}")
    analyze_clicked = st.button(
        t("analyze", language_code),
        type="primary",
        use_container_width=True,
    )

    finalize_clicked = False
    if st.session_state.analysis_result is not None:
        finalize_clicked = st.button(
            t("generate_final", language_code),
            use_container_width=True,
        )

    st.caption(t("flow_note", language_code))

if analyze_clicked or finalize_clicked:
    previous_result = st.session_state.analysis_result
    uploaded_diffs, skipped_binary_files = load_uploaded_diff_files(uploaded_files or [])
    combined_diff = combine_diff_sources(st.session_state.manual_diff, uploaded_diffs)
    changed_paths = extract_changed_paths(combined_diff)

    if not prompt_text.strip() and not combined_diff.strip():
        st.session_state.analysis_error = t("need_input", language_code)
    elif analyze_clicked:
        clear_analysis_state()
        try:
            with st.spinner(t("analyzing", language_code)):
                project_path = None
                if project_path_input.strip():
                    project_path = ensure_local_project_path(project_path_input.strip())
                    save_preferences(last_project_path=project_path_input.strip())
                if st.session_state.get("remote_git_url_input", "").strip():
                    save_preferences(
                        last_remote_git_url=st.session_state.remote_git_url_input.strip()
                    )

                repo_context = build_repo_context(project_path, changed_paths)
                result = analyze_for_clarification(
                    prompt_text=prompt_text,
                    diff_text=combined_diff,
                    repo_context=repo_context,
                    ui_language="Arabic" if language_code == "ar" else "English",
                    model=DEFAULT_MODEL,
                )
            st.session_state.analysis_result = result
            st.session_state.analysis_error = ""
            st.session_state.generated_prompt = ""
        except Exception as exc:
            st.session_state.analysis_error = str(exc)
    elif finalize_clicked and previous_result is not None:
        try:
            with st.spinner(t("building_prompt", language_code)):
                project_path = None
                if project_path_input.strip():
                    project_path = ensure_local_project_path(project_path_input.strip())
                    save_preferences(last_project_path=project_path_input.strip())
                if st.session_state.get("remote_git_url_input", "").strip():
                    save_preferences(
                        last_remote_git_url=st.session_state.remote_git_url_input.strip()
                    )

                repo_context = build_repo_context(project_path, changed_paths)
                clarification_answers = collect_clarification_answers(
                    previous_result.followup_questions
                )
                final_prompt = generate_final_prompt(
                    prompt_text=prompt_text,
                    diff_text=combined_diff,
                    repo_context=repo_context,
                    analysis_result=previous_result,
                    clarification_answers=clarification_answers,
                    model=DEFAULT_MODEL,
                )
            st.session_state.generated_prompt = final_prompt
            st.session_state.analysis_error = ""
        except Exception as exc:
            st.session_state.analysis_error = str(exc)

if st.session_state.analysis_error:
    st.error(st.session_state.analysis_error)

if st.session_state.analysis_result:
    render_analysis_result(st.session_state.analysis_result, language_code)

if st.session_state.generated_prompt:
    with st.container(border=True):
        st.markdown(f"### {t('final_prompt_title', language_code)}")
        st.code(st.session_state.generated_prompt, language="markdown")

st.caption(t("use_local_note", language_code))
