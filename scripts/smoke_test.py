"""Quick smoke test to verify the content serves through the API."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Login as pro learner
login = client.post("/v1/auth/sessions", json={"email": "learner-pro@cse.local", "password": "Learner1Pass!"})
print(f"Login: {login.status_code}")
if login.status_code != 201:
    print(f"  Error: {login.json()}")
    sys.exit(1)

token = login.json().get("access_token", "")
headers = {"Authorization": f"Bearer {token}"}

# Get modules
modules = client.get("/v1/modules", headers=headers)
print(f"GET /v1/modules: {modules.status_code}")
data = modules.json()
print(f"  Total modules: {data.get('total', 0)}")
for m in data.get("items", []):
    print(f"  - {m['title']} ({m['category']})")

# Get topics under first module
if data.get("items"):
    mod_id = data["items"][0]["id"]
    topics = client.get(f"/v1/modules/{mod_id}/topics", headers=headers)
    print(f"\nGET /v1/modules/{mod_id}/topics: {topics.status_code}")
    for t in topics.json():
        print(f"  Topic: {t['title']}")

        # Get subtopics
        subtopics = client.get(f"/v1/topics/{t['id']}/subtopics", headers=headers)
        print(f"  GET /v1/topics/{t['id']}/subtopics: {subtopics.status_code}")
        for s in subtopics.json():
            print(f"    Subtopic: {s['title']}")

            # Get lesson
            lesson = client.get(f"/v1/subtopics/{s['id']}/lesson", headers=headers)
            print(f"    GET /v1/subtopics/{s['id']}/lesson: {lesson.status_code}")
            if lesson.status_code == 200:
                content = lesson.json().get("content_json", {})
                expl_count = len(content.get("explanations", []))
                examples_count = len(content.get("worked_examples", []))
                takeaways_count = len(content.get("key_takeaways", []))
                print(f"      Explanations: {expl_count}, Examples: {examples_count}, Takeaways: {takeaways_count}")
                print(f"      Summary length: {len(content.get('summary', ''))} chars")

    # Try starting a quiz
    if topics.json():
        first_topic = topics.json()[0]
        subtopics_resp = client.get(f"/v1/topics/{first_topic['id']}/subtopics", headers=headers)
        if subtopics_resp.json():
            st_id = subtopics_resp.json()[0]["id"]

            # Mark lesson complete first
            complete = client.post(
                f"/v1/subtopics/{st_id}/lesson:complete",
                headers=headers,
                json={"client_event_id": "smoke-test-001", "completed_at": "2025-05-18T10:00:00Z"},
            )
            print(f"\nPOST lesson:complete: {complete.status_code}")

            # Start quiz
            quiz = client.post(f"/v1/subtopics/{st_id}/quiz-attempts", headers=headers)
            print(f"POST quiz-attempts: {quiz.status_code}")
            if quiz.status_code == 201:
                quiz_data = quiz.json()
                print(f"  Quiz started! {quiz_data.get('total_questions', 0)} questions assembled")
            else:
                print(f"  Response: {quiz.json()}")

print("\n--- Smoke test complete ---")
