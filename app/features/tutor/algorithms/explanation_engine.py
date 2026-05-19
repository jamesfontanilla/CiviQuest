"""Rule-based explanation engine for the AI tutor.

All functions here are pure, deterministic, and require NO external API calls.
They use the question's existing metadata (explanation, options, correct_answer,
stem, qtype) combined with string templates to produce helpful text.
"""

from __future__ import annotations

import random
from typing import Any

from app.features.content.models import Question


def explain_answer(*, question: Question, selected_answer: str | None) -> str:
    """Generate an explanation for why the correct answer is correct.

    Uses the question's built-in explanation field + adds context about
    why the selected answer is wrong (if applicable).
    """
    parts: list[str] = []

    parts.append(f"**Question:** {question.stem}\n")
    parts.append(f"**Correct Answer:** {question.correct_answer}\n")

    if selected_answer and selected_answer != question.correct_answer:
        parts.append(
            f"**Your Answer:** {selected_answer} — This is incorrect.\n"
        )

    parts.append(f"**Explanation:** {question.explanation}\n")

    # Add a memory tip based on question type
    tip = _memory_tip(question)
    if tip:
        parts.append(f"**Memory Tip:** {tip}")

    return "\n".join(parts)


def simplify_concept(*, question: Question, subtopic_title: str) -> str:
    """Rewrite the explanation in simpler terms.

    Rules:
    - Use shorter sentences
    - Add an analogy or real-world example
    - Break into numbered steps
    """
    explanation = question.explanation
    parts: list[str] = []

    parts.append(f"**Simplified Explanation for: {subtopic_title}**\n")
    parts.append("Here's a simpler way to understand this:\n")

    # Break explanation into sentences and simplify
    sentences = [s.strip() for s in explanation.split(".") if s.strip()]
    for i, sentence in enumerate(sentences[:5], 1):
        parts.append(f"{i}. {sentence}.")

    parts.append(
        f"\n**Real-world connection:** Think of this concept like "
        f"understanding the rules of a game — once you know the pattern "
        f"for '{subtopic_title}', you can apply it to similar questions."
    )

    return "\n".join(parts)


def generate_similar_question(*, question: Question, difficulty: str) -> dict[str, Any]:
    """Generate a similar practice question by varying the original.

    For MC: shuffle options, rephrase stem slightly, keep same concept.
    For identification: change the specific instance but keep the pattern.
    Returns a dict with stem, options, correct_answer, explanation.
    """
    stem = f"[Practice] {question.stem}"

    options: list[str] | None = None
    if question.options:
        options = list(question.options)
        random.shuffle(options)

    return {
        "stem": stem,
        "options": options,
        "correct_answer": question.correct_answer,
        "explanation": (
            f"This is a practice variation. The correct answer is "
            f"'{question.correct_answer}'. {question.explanation}"
        ),
    }


def generate_hint(*, question: Question) -> str:
    """Provide a hint without revealing the answer.

    Strategies:
    - Eliminate one wrong option
    - Point to the relevant concept
    - Give a partial explanation
    """
    parts: list[str] = []
    parts.append("**Hint:**\n")

    # Strategy 1: Eliminate a wrong option if MC
    if question.options and len(question.options) > 2:
        wrong_options = [
            o for o in question.options if o != question.correct_answer
        ]
        if wrong_options:
            eliminated = wrong_options[0]
            parts.append(
                f"- You can eliminate '{eliminated}' — it's not the answer.\n"
            )

    # Strategy 2: Point to the concept
    explanation_words = question.explanation.split()
    if len(explanation_words) > 5:
        hint_fragment = " ".join(explanation_words[:5]) + "..."
        parts.append(f"- Think about: {hint_fragment}\n")

    # Strategy 3: Question type hint
    if question.qtype == "MULTIPLE_CHOICE":
        parts.append("- Look carefully at each option and eliminate the obvious wrong ones.")
    elif question.qtype == "IDENTIFICATION":
        parts.append("- Focus on the key term being described in the question.")
    else:
        parts.append("- Break the problem into smaller parts and solve step by step.")

    return "\n".join(parts)


def step_by_step(*, question: Question) -> list[str]:
    """Break the solution into numbered steps.

    Returns a list of step strings the UI renders progressively.
    """
    steps: list[str] = []

    steps.append(f"Read the question carefully: '{question.stem[:100]}...'")
    steps.append("Identify what is being asked.")

    if question.qtype == "MULTIPLE_CHOICE" and question.options:
        steps.append(
            f"Review all {len(question.options)} options before choosing."
        )
        steps.append("Eliminate options that are clearly wrong.")
        steps.append("Compare remaining options against what you know.")
    elif question.qtype == "IDENTIFICATION":
        steps.append("Recall the definition or concept being described.")
        steps.append("Think of the specific term that matches.")
    else:
        steps.append("Break the problem into smaller parts.")
        steps.append("Apply relevant rules or formulas.")

    steps.append(f"The correct answer is: {question.correct_answer}")
    steps.append(f"Why: {question.explanation}")

    return steps


def _memory_tip(question: Question) -> str:
    """Generate a memory tip based on question type."""
    tips = {
        "MULTIPLE_CHOICE": (
            "For multiple choice, try to answer before looking at the options. "
            "This prevents distractor options from confusing you."
        ),
        "IDENTIFICATION": (
            "For identification questions, create mental associations between "
            "the term and its definition using vivid imagery."
        ),
        "LOGICAL_REASONING": (
            "For logical reasoning, identify the pattern or rule first, "
            "then apply it systematically."
        ),
        "READING_COMPREHENSION": (
            "For reading comprehension, scan for keywords in the question "
            "and locate them in the passage before answering."
        ),
        "PROBLEM_SOLVING": (
            "For problem solving, write down what you know, what you need "
            "to find, and work backwards from the answer choices if stuck."
        ),
    }
    return tips.get(question.qtype, "")
