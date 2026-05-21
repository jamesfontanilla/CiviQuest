import json

filepath = "data/seed/questions/verbal-ability/grammar/modifiers/questions.json"

with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Current count: {len(data)}")
print(f"Last ID: {data[-1]['id']}")

# Load new questions
with open("scripts/new_modifiers_201_350.json", "r", encoding="utf-8") as f:
    new_questions = json.load(f)

print(f"New questions count: {len(new_questions)}")

# Merge
data.extend(new_questions)
print(f"Total after merge: {len(data)}")

# Write back
with open(filepath, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("Done!")
