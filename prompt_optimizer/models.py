from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CommitInfo:
    full_hash: str
    short_hash: str
    author: str
    date: str
    subject: str
    summary: str = ""


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
class BlindSpot:
    title: str
    reason: str
    severity: str = "medium"


@dataclass(slots=True)
class RetrievalDocument:
    id: str
    kind: str
    title: str
    content: str
    project_id: str
    commit_hash: str = ""
    file_path: str = ""
    summary: str = ""
    recency_rank: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalHit:
    document: RetrievalDocument
    score: float


@dataclass(slots=True)
class AnalysisResult:
    agent_intent: str
    user_intent: str
    missing_info: list[str] = field(default_factory=list)
    blind_spots: list[BlindSpot] = field(default_factory=list)
    followup_questions: list[ClarificationQuestion] = field(default_factory=list)
    can_generate_final_prompt: bool = True
    improved_prompt: str = ""
    raw_response: str = ""
