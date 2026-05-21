import json

filepath = "data/seed/questions/verbal-ability/grammar/modifiers/questions.json"

with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)

# Fix question 457 - change question text to be unique
for q in data:
    if q["id"] == 457:
        q["question"] = "Which sentence has a faulty comparison error?"
    elif q["id"] == 468:
        q["question"] = "Identify the sentence with a faulty comparison."

with open(filepath, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Verify no more dupes among new questions
new_qs = [q for q in data if q["id"] >= 421]
questions_text = [q["question"] for q in new_qs]
dupes = [t for t in questions_text if questions_text.count(t) > 1]
if dupes:
    print(f"Still have duplicates: {set(dupes)}")
else:
    print("Fixed! No more duplicate question texts among new questions.")

# Also check against existing questions
all_texts = [q["question"] for q in data]
all_dupes = set(t for t in all_texts if all_texts.count(t) > 1)
if all_dupes:
    print(f"Cross-file duplicates remaining: {all_dupes}")
else:
    print("No duplicates across entire file.")
