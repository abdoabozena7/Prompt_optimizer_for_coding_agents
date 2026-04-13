from __future__ import annotations

from prompt_optimizer.models import AnalysisResult, BlindSpot, RetrievalHit


class BlindSpotService:
    def apply_guards(
        self,
        analysis_result: AnalysisResult,
        *,
        current_prompt: str,
        selected_commit_hashes: list[str],
        retrieval_hits: list[RetrievalHit],
        clarification_answers: list[dict[str, str]] | None = None,
    ) -> AnalysisResult:
        blind_spots = list(analysis_result.blind_spots)
        model_detected_keys = {
            (blind_spot.title, blind_spot.reason) for blind_spot in blind_spots
        }

        if not current_prompt.strip():
            blind_spots.append(
                BlindSpot(
                    title="Missing current intent",
                    reason="The current user prompt is empty, so the system cannot anchor the requested outcome.",
                    severity="high",
                )
            )

        if not selected_commit_hashes:
            blind_spots.append(
                BlindSpot(
                    title="No diffs selected",
                    reason="At least one missed or relevant commit must be selected before analysis can proceed.",
                    severity="high",
                )
            )

        if not retrieval_hits:
            blind_spots.append(
                BlindSpot(
                    title="No supporting evidence",
                    reason="The retrieval layer did not find enough relevant diff or code evidence for a reliable prompt.",
                    severity="high",
                )
            )

        analysis_result.blind_spots = self._dedupe(blind_spots)
        if self._answers_cover_clarifications(clarification_answers or []):
            for blind_spot in analysis_result.blind_spots:
                if (
                    blind_spot.severity == "high"
                    and (
                        blind_spot.title,
                        blind_spot.reason,
                    )
                    in model_detected_keys
                ):
                    blind_spot.severity = "medium"
        analysis_result.can_generate_final_prompt = not any(
            blind_spot.severity == "high" for blind_spot in analysis_result.blind_spots
        )

        if not analysis_result.missing_info:
            analysis_result.missing_info = [
                blind_spot.reason for blind_spot in analysis_result.blind_spots
            ][:4]

        return analysis_result

    def require_clear_to_generate(self, analysis_result: AnalysisResult) -> None:
        if analysis_result.can_generate_final_prompt:
            return

        blockers = [
            blind_spot.title
            for blind_spot in analysis_result.blind_spots
            if blind_spot.severity == "high"
        ]
        raise RuntimeError(
            "Final prompt generation is blocked until these blind spots are resolved: "
            + ", ".join(blockers)
        )

    def _dedupe(self, blind_spots: list[BlindSpot]) -> list[BlindSpot]:
        unique: list[BlindSpot] = []
        seen: set[tuple[str, str, str]] = set()
        for blind_spot in blind_spots:
            key = (blind_spot.title, blind_spot.reason, blind_spot.severity)
            if key in seen:
                continue
            seen.add(key)
            unique.append(blind_spot)
        return unique

    def _answers_cover_clarifications(
        self, clarification_answers: list[dict[str, str]]
    ) -> bool:
        if not clarification_answers:
            return False
        return all(
            answer.get("selected_option", "").strip()
            or answer.get("custom_text", "").strip()
            for answer in clarification_answers
        )
