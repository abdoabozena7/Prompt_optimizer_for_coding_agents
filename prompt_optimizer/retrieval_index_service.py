from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from prompt_optimizer.commit_sync_service import CommitSyncService
from prompt_optimizer.context import build_repo_context
from prompt_optimizer.diff_utils import extract_changed_paths
from prompt_optimizer.models import RepoContextSnippet, RetrievalDocument, RetrievalHit
from prompt_optimizer.project_memory import replace_retrieval_documents
from prompt_optimizer.repo_ops import ensure_local_project_path

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
DIFF_CHUNK_LINE_LIMIT = 60


class RetrievalIndexService:
    def __init__(self, commit_sync_service: CommitSyncService | None = None) -> None:
        self._commit_sync_service = commit_sync_service or CommitSyncService()

    def build_index(
        self,
        project,
        commits,
        *,
        selected_commit_hashes: list[str],
    ) -> tuple[list[RetrievalDocument], list[RepoContextSnippet], dict[str, str]]:
        documents: list[RetrievalDocument] = []
        diff_by_commit: dict[str, str] = {}
        commit_lookup = {commit.full_hash: commit for commit in commits}
        commit_ranks = {commit.full_hash: rank for rank, commit in enumerate(commits)}

        for rank, commit in enumerate(commits):
            documents.append(
                RetrievalDocument(
                    id=self._doc_id(project.id, "commit_meta", commit.full_hash, ""),
                    kind="commit_meta",
                    title=commit.subject,
                    content="\n".join(
                        [
                            f"Commit: {commit.subject}",
                            f"Author: {commit.author}",
                            f"Date: {commit.date}",
                            f"Hash: {commit.short_hash}",
                            commit.summary.strip() or "(no summary)",
                        ]
                    ),
                    project_id=project.id,
                    commit_hash=commit.full_hash,
                    summary=commit.summary.strip(),
                    recency_rank=rank,
                )
            )

        for entry in project.prompt_history:
            documents.append(
                RetrievalDocument(
                    id=self._doc_id(project.id, "prompt_history", entry.id, ""),
                    kind="prompt_history",
                    title=f"Prompt history {entry.created_at}",
                    content="\n".join(
                        [
                            entry.prompt_text,
                            f"Clarified intent: {entry.clarified_intent or '(none)'}",
                            f"Inferred user intent: {entry.inferred_user_intent or '(none)'}",
                        ]
                    ),
                    project_id=project.id,
                    summary=entry.clarified_intent or entry.inferred_user_intent,
                )
            )

        combined_diff_parts: list[str] = []
        for commit_hash in selected_commit_hashes:
            diff_text = self._commit_sync_service.load_diff(project, commit_hash)
            diff_by_commit[commit_hash] = diff_text
            combined_diff_parts.append(diff_text)
            commit = commit_lookup.get(commit_hash)
            documents.extend(
                self._chunk_diff_document(
                    project_id=project.id,
                    commit_hash=commit_hash,
                    diff_text=diff_text,
                    title=commit.subject if commit else commit_hash,
                    recency_rank=commit_ranks.get(commit_hash, 0),
                )
            )

        combined_diff = "\n\n".join(
            part for part in combined_diff_parts if part.strip()
        )
        repo_context = self._build_repo_context(project, combined_diff)

        for snippet in repo_context:
            documents.append(
                RetrievalDocument(
                    id=self._doc_id(project.id, "repo_context", "", snippet.path),
                    kind="repo_context",
                    title=snippet.path,
                    content=snippet.content,
                    project_id=project.id,
                    file_path=snippet.path,
                    summary=snippet.reason,
                )
            )

        replace_retrieval_documents(project.id, documents)
        return documents, repo_context, diff_by_commit

    def summarize_commit(self, project, commit_hash: str) -> str:
        diff_text = self._commit_sync_service.load_diff(project, commit_hash)
        documents = self._chunk_diff_document(
            project_id=project.id,
            commit_hash=commit_hash,
            diff_text=diff_text,
            title=commit_hash,
            recency_rank=0,
        )
        files = []
        focuses = []
        for document in documents:
            if document.file_path and document.file_path not in files:
                files.append(document.file_path)
            if document.summary and document.summary not in focuses:
                focuses.append(document.summary)

        file_summary = ", ".join(files[:3]) if files else "No changed files detected"
        if len(files) > 3:
            file_summary += f" (+{len(files) - 3} more)"

        focus_summary = "; ".join(focuses[:2]) if focuses else "No focused diff chunks"
        if len(focuses) > 2:
            focus_summary += f" (+{len(focuses) - 2} more)"

        return f"Files: {file_summary}\nFocus: {focus_summary}"

    def retrieve(
        self,
        documents: list[RetrievalDocument],
        *,
        query_text: str,
        selected_commit_hashes: list[str],
        limit: int = 8,
    ) -> list[RetrievalHit]:
        query_vector = self._vectorize(query_text)
        hits: list[RetrievalHit] = []

        for document in documents:
            score = self._score_document(
                document=document,
                query_vector=query_vector,
                selected_commit_hashes=selected_commit_hashes,
            )
            if score <= 0:
                continue
            hits.append(RetrievalHit(document=document, score=score))

        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]

    def render_evidence(self, hits: list[RetrievalHit]) -> list[str]:
        rendered: list[str] = []
        for hit in hits:
            document = hit.document
            rendered.append(
                "\n".join(
                    [
                        f"Kind: {document.kind}",
                        f"Title: {document.title}",
                        f"Summary: {document.summary or '(none)'}",
                        "Content:",
                        document.content[:1200],
                    ]
                )
            )
        return rendered

    def repo_context_from_hits(
        self, hits: list[RetrievalHit]
    ) -> list[RepoContextSnippet]:
        snippets: list[RepoContextSnippet] = []
        for hit in hits:
            document = hit.document
            if document.kind != "repo_context":
                continue
            snippets.append(
                RepoContextSnippet(
                    path=document.file_path or document.title,
                    content=document.content,
                    reason=document.summary or "retrieved context",
                )
            )
        return snippets[:4]

    def diff_text_from_hits(self, hits: list[RetrievalHit]) -> str:
        chunks = [
            hit.document.content
            for hit in hits
            if hit.document.kind == "diff_chunk" and hit.document.content.strip()
        ]
        return "\n\n".join(chunks[:6])

    def _build_repo_context(
        self, project, combined_diff: str
    ) -> list[RepoContextSnippet]:
        if not combined_diff.strip():
            return []
        repo_path = ensure_local_project_path(project.local_path)
        return build_repo_context(repo_path, extract_changed_paths(combined_diff))

    def _chunk_diff_document(
        self,
        *,
        project_id: str,
        commit_hash: str,
        diff_text: str,
        title: str,
        recency_rank: int,
    ) -> list[RetrievalDocument]:
        documents: list[RetrievalDocument] = []
        current_file = ""
        current_chunk: list[str] = []
        current_hunk = ""
        index = 0

        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                if current_chunk:
                    documents.append(
                        self._build_diff_doc(
                            project_id,
                            commit_hash,
                            current_file,
                            title,
                            current_hunk,
                            current_chunk,
                            index,
                            recency_rank,
                        )
                    )
                    index += 1
                    current_chunk = []
                current_file = line.removeprefix("+++ b/").strip()
                current_hunk = ""
                continue

            if line.startswith("@@"):
                if current_chunk:
                    documents.append(
                        self._build_diff_doc(
                            project_id,
                            commit_hash,
                            current_file,
                            title,
                            current_hunk,
                            current_chunk,
                            index,
                            recency_rank,
                        )
                    )
                    index += 1
                    current_chunk = []
                current_hunk = line.strip()

            current_chunk.append(line)
            if len(current_chunk) >= DIFF_CHUNK_LINE_LIMIT:
                documents.append(
                    self._build_diff_doc(
                        project_id,
                        commit_hash,
                        current_file,
                        title,
                        current_hunk,
                        current_chunk,
                        index,
                        recency_rank,
                    )
                )
                index += 1
                current_chunk = []

        if current_chunk:
            documents.append(
                self._build_diff_doc(
                    project_id,
                    commit_hash,
                    current_file,
                    title,
                    current_hunk,
                    current_chunk,
                    index,
                    recency_rank,
                )
            )

        return documents

    def _build_diff_doc(
        self,
        project_id: str,
        commit_hash: str,
        current_file: str,
        title: str,
        current_hunk: str,
        lines: list[str],
        index: int,
        recency_rank: int,
    ) -> RetrievalDocument:
        summary = " ".join(
            item for item in [current_file, current_hunk] if item
        ).strip()
        content = "\n".join(lines).strip()
        return RetrievalDocument(
            id=self._doc_id(
                project_id, "diff_chunk", commit_hash, f"{current_file}:{index}"
            ),
            kind="diff_chunk",
            title=title,
            content=content,
            project_id=project_id,
            commit_hash=commit_hash,
            file_path=current_file,
            summary=summary or title,
            recency_rank=recency_rank,
        )

    def _score_document(
        self,
        *,
        document: RetrievalDocument,
        query_vector: Counter[str],
        selected_commit_hashes: list[str],
    ) -> float:
        document_vector = self._vectorize(
            "\n".join([document.title, document.summary, document.content])
        )
        lexical_score = self._cosine_similarity(query_vector, document_vector)
        if not lexical_score and document.kind not in {"commit_meta", "diff_chunk"}:
            return 0.0

        kind_weight = {
            "prompt_history": 1.2,
            "diff_chunk": 1.15,
            "repo_context": 1.1,
            "commit_meta": 0.95,
        }.get(document.kind, 1.0)
        selection_boost = 0.8 if document.commit_hash in selected_commit_hashes else 0.0
        recency_boost = max(0.0, 0.25 - (document.recency_rank * 0.02))
        return (lexical_score * kind_weight) + selection_boost + recency_boost

    def _vectorize(self, text: str) -> Counter[str]:
        return Counter(token.lower() for token in TOKEN_PATTERN.findall(text))

    def _cosine_similarity(self, left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0

        intersection = set(left) & set(right)
        dot = sum(left[token] * right[token] for token in intersection)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def _doc_id(self, project_id: str, kind: str, commit_hash: str, suffix: str) -> str:
        raw = "::".join([project_id, kind, commit_hash, suffix])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
