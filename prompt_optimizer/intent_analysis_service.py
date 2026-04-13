from __future__ import annotations

from dataclasses import dataclass

from prompt_optimizer.analysis import generate_final_prompt
from prompt_optimizer.blind_spot_service import BlindSpotService
from prompt_optimizer.models import AnalysisResult, RepoContextSnippet, RetrievalHit
from prompt_optimizer.project_memory import build_prompt_context
from prompt_optimizer.retrieval_index_service import RetrievalIndexService


@dataclass(slots=True)
class CuratedContext:
    prompt_text: str
    diff_text: str
    repo_context: list[RepoContextSnippet]
    retrieved_evidence: list[str]
    retrieval_hits: list[RetrievalHit]


class IntentAnalysisService:
    def __init__(
        self,
        retrieval_index_service: RetrievalIndexService | None = None,
        blind_spot_service: BlindSpotService | None = None,
    ) -> None:
        self._retrieval_index_service = (
            retrieval_index_service or RetrievalIndexService()
        )
        self._blind_spot_service = blind_spot_service or BlindSpotService()

    def build_curated_context(
        self,
        *,
        project,
        commits,
        current_prompt: str,
        missed_prompts: list[str],
        selected_commit_hashes: list[str],
    ) -> CuratedContext:
        prompt_text = build_prompt_context(
            current_prompt=current_prompt,
            missed_prompt_trail=missed_prompts,
            stored_history=project.prompt_history,
        )
        documents, _, _ = self._retrieval_index_service.build_index(
            project,
            commits,
            selected_commit_hashes=selected_commit_hashes,
        )
        retrieval_hits = self._retrieval_index_service.retrieve(
            documents,
            query_text=prompt_text,
            selected_commit_hashes=selected_commit_hashes,
            limit=10,
        )
        return CuratedContext(
            prompt_text=prompt_text,
            diff_text=self._retrieval_index_service.diff_text_from_hits(retrieval_hits),
            repo_context=self._retrieval_index_service.repo_context_from_hits(
                retrieval_hits
            ),
            retrieved_evidence=self._retrieval_index_service.render_evidence(
                retrieval_hits
            ),
            retrieval_hits=retrieval_hits,
        )

    def analyze(
        self,
        *,
        provider,
        model: str,
        project,
        commits,
        current_prompt: str,
        missed_prompts: list[str],
        selected_commit_hashes: list[str],
        ui_language: str,
    ) -> tuple[AnalysisResult, CuratedContext]:
        curated_context = self.build_curated_context(
            project=project,
            commits=commits,
            current_prompt=current_prompt,
            missed_prompts=missed_prompts,
            selected_commit_hashes=selected_commit_hashes,
        )
        analysis_result = provider.analyze_for_clarification(
            prompt_text=curated_context.prompt_text,
            diff_text=curated_context.diff_text,
            repo_context=curated_context.repo_context,
            retrieved_evidence=curated_context.retrieved_evidence,
            ui_language=ui_language,
            model=model,
        )
        return (
            self._blind_spot_service.apply_guards(
                analysis_result,
                current_prompt=current_prompt,
                selected_commit_hashes=selected_commit_hashes,
                retrieval_hits=curated_context.retrieval_hits,
            ),
            curated_context,
        )

    def finalize(
        self,
        *,
        provider,
        model: str,
        project,
        commits,
        current_prompt: str,
        missed_prompts: list[str],
        selected_commit_hashes: list[str],
        analysis_result: AnalysisResult,
        clarification_answers: list[dict[str, str]],
    ) -> tuple[str, CuratedContext]:
        curated_context = self.build_curated_context(
            project=project,
            commits=commits,
            current_prompt=current_prompt,
            missed_prompts=missed_prompts,
            selected_commit_hashes=selected_commit_hashes,
        )
        guarded = self._blind_spot_service.apply_guards(
            analysis_result,
            current_prompt=current_prompt,
            selected_commit_hashes=selected_commit_hashes,
            retrieval_hits=curated_context.retrieval_hits,
            clarification_answers=clarification_answers,
        )
        self._blind_spot_service.require_clear_to_generate(guarded)
        return (
            generate_final_prompt(
                prompt_text=curated_context.prompt_text,
                diff_text=curated_context.diff_text,
                repo_context=curated_context.repo_context,
                retrieved_evidence=curated_context.retrieved_evidence,
                analysis_result=guarded,
                clarification_answers=clarification_answers,
                model=model,
                provider=provider,
            ),
            curated_context,
        )
