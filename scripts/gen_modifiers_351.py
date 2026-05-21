"""Generate questions 351-500 for modifiers and append to the JSON file."""
import json

filepath = "data/seed/questions/verbal-ability/grammar/modifiers/questions.json"

new_questions = [
    {
        "id": 351,
        "subtest": "Verbal Ability",
        "module": "Grammar and Correct Usage",
        "subtopic": "Modifiers",
        "difficulty": "Easy",
        "question": "Choose the sentence with correct modifier placement.",
        "choices": [
            "The clerk only filed ten documents yesterday.",
            "The clerk filed only ten documents yesterday.",
            "Only the clerk filed ten documents yesterday.",
            "The clerk filed ten only documents yesterday."
        ],
        "answer": "The clerk filed only ten documents yesterday.",
        "explanation": "'Only' should be placed directly before 'ten documents' because it limits the number of documents filed.",
        "tags": ["limiting modifier", "only", "correct placement"],
        "category": ["Professional", "Sub-Professional"],
        "language": "English"
    },
    {
        "id": 352,
        "subtest": "Verbal Ability",
        "module": "Grammar and Correct Usage",
        "subtopic": "Modifiers",
        "difficulty": "Easy",
        "question": "Which sentence contains a dangling modifier?",
        "choices": [
            "After reviewing the memo, the director signed the approval.",
            "After reviewing the memo, the approval was signed.",
            "The director signed the approval after reviewing the memo.",
            "Having reviewed the memo, the director gave her approval."
        ],
        "answer": "After reviewing the memo, the approval was signed.",
        "explanation": "'The approval' cannot review a memo. The modifier dangles because the doer of the action is missing from the subject position.",
        "tags": ["dangling modifier", "participial phrase", "error identification"],
        "category": ["Professional", "Sub-Professional"],
        "language": "English"
    },
    {
        "id": 353,
        "subtest": "Verbal Ability",
        "module": "Grammar and Correct Usage",
        "subtopic": "Modifiers",
        "difficulty": "Easy",
        "question": "Select the correct comparative form: 'This policy is _____ than the previous one.'",
        "choices": [
            "more stricter",
            "most strict",
            "stricter",
            "more strict than"
        ],
        "answer": "stricter",
        "explanation": "'Strict' is a one-syllable adjective that forms the comparative by adding '-er,' not by using 'more.'",
        "tags": ["comparative", "double comparison error", "fill-in-blank"],
        "category": ["Professional", "Sub-Professional"],
        "language": "English"
    }
]

with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)

data.extend(new_questions)

with open(filepath, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Done. Total questions: {len(data)}")
