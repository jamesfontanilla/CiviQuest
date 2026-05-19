"""Business logic for the AI tutor feature.

The tutor is rule-based — no external LLM API calls. It uses the question's
existing metadata (explanation, options, correct_answer) combined with
template-based generation to produce helpful responses.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.features.content.models import Question, Subtopic
from app.features.content.repository import QuestionRepository, SubtopicRepository
from app.features.tutor.algorithms.explanation_engine import (
    explain_answer,
    generate_hint,
    generate_similar_question,
    simplify_concept,
    step_by_step,
)
from app.features.tutor.repository import TutorRepository
from app.features.tutor.schemas import (
    SimilarQuestionResponse,
    StepByStepResponse,
    TutorResponse,
)


class TutorService:
    """Orchestrates tutor interactions."""

    def __init__(
        self,
        *,
        tutor_repo: TutorRepository,
        question_repo: QuestionRepository,
        subtopic_repo: SubtopicRepository,
    ) -> None:
        self._tutor_repo = tutor_repo
        self._question_repo = question_repo
        self._subtopic_repo = subtopic_repo

    def _get_question(self, question_id: int) -> Question:
        """Load a question or raise 404."""
        question = self._question_repo.get(question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found",
            )
        return question

    def explain(
        self, *, user_id: int, question_id: int, selected_answer: str | None = None
    ) -> TutorResponse:
        """Generate an explanation for a question."""
        question = self._get_question(question_id)
        text = explain_answer(question=question, selected_answer=selected_answer)

        interaction = self._tutor_repo.create_interaction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=question.subtopic_id,
            interaction_type="explain_answer",
            request_context={"selected_answer": selected_answer},
            response_text=text,
        )
        return TutorResponse(
            interaction_id=interaction.id,
            response_text=text,
            interaction_type="explain_answer",
        )

    def simplify(self, *, user_id: int, question_id: int) -> TutorResponse:
        """Simplify the explanation for a question."""
        question = self._get_question(question_id)
        subtopic = self._subtopic_repo.get(question.subtopic_id)
        subtopic_title = subtopic.title if subtopic else "this topic"

        text = simplify_concept(question=question, subtopic_title=subtopic_title)

        interaction = self._tutor_repo.create_interaction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=question.subtopic_id,
            interaction_type="simplify",
            request_context=None,
            response_text=text,
        )
        return TutorResponse(
            interaction_id=interaction.id,
            response_text=text,
            interaction_type="simplify",
        )

    def similar_question(
        self, *, user_id: int, question_id: int
    ) -> SimilarQuestionResponse:
        """Generate a similar practice question."""
        question = self._get_question(question_id)
        result = generate_similar_question(
            question=question, difficulty=question.difficulty
        )

        response_text = f"Similar question: {result['stem']}"
        interaction = self._tutor_repo.create_interaction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=question.subtopic_id,
            interaction_type="similar_question",
            request_context=None,
            response_text=response_text,
        )
        return SimilarQuestionResponse(
            interaction_id=interaction.id,
            stem=result["stem"],
            options=result["options"],
            correct_answer=result["correct_answer"],
            explanation=result["explanation"],
        )

    def hint(self, *, user_id: int, question_id: int) -> TutorResponse:
        """Generate a hint for a question."""
        question = self._get_question(question_id)
        text = generate_hint(question=question)

        interaction = self._tutor_repo.create_interaction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=question.subtopic_id,
            interaction_type="hint",
            request_context=None,
            response_text=text,
        )
        return TutorResponse(
            interaction_id=interaction.id,
            response_text=text,
            interaction_type="hint",
        )

    def step_by_step_explain(
        self, *, user_id: int, question_id: int
    ) -> StepByStepResponse:
        """Break the solution into numbered steps."""
        question = self._get_question(question_id)
        steps = step_by_step(question=question)

        response_text = " | ".join(steps)
        interaction = self._tutor_repo.create_interaction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=question.subtopic_id,
            interaction_type="step_by_step",
            request_context=None,
            response_text=response_text,
        )
        return StepByStepResponse(
            interaction_id=interaction.id,
            steps=steps,
        )

    def rate_interaction(self, interaction_id: int, helpful: bool) -> None:
        """Rate a tutor interaction as helpful or not."""
        result = self._tutor_repo.rate_interaction(interaction_id, helpful)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found",
            )
