# CSNexus

A learning platform that helps Filipino candidates prepare for the Civil Service Examination (CSE). The backend is a FastAPI server backed by SQLite, paired with a Progressive Web App shell that supports offline lesson study and progress sync.

## Quickstart

```bash
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

Copy `.env.example` to `.env` and adjust values before running the server.
