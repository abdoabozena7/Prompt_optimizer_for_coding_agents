from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CommitInfo:
    full_hash: str
    short_hash: str
    author: str
    date: str
    subject: str


@dataclass(slots=True)
class RepoContextSnippet:
    path: str
    content: str
    reason: str


@dataclass(slots=True)
class ClarificationQuestion:
    question: str
    options: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisResult:
    agent_intent: str
    user_intent: str
    missing_info: list[str] = field(default_factory=list)
    followup_questions: list[ClarificationQuestion] = field(default_factory=list)
    improved_prompt: str = ""
    raw_response: str = ""
