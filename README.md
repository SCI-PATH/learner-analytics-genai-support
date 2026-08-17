# Learner Analytics & GenAI Support Component

Research component for **adaptive Socratic tutoring** and **learner mastery tracking** in Grade 6 Science.  
This module is the **central intelligence hub**: it runs BKT mastery modeling, RAG over the syllabus PDF, Groq-powered Socratic hints, and educator dashboards.

---

## Terminal commands

From repo root (learner-analytics-genai-support/). Run these in **separate terminals** (backend first, then each Streamlit app).

**1. Activate the virtual environment**

.\.venv\Scripts\Activate.ps1
cd FastAPI-Backend
uvicorn main:app --reload --host 127.0.0.1 --port 8003

One liner alternative --- .\.venv\Scripts\Activate.ps1; cd FastAPI-Backend; uvicorn main:app --reload --host 127.0.0.1 --port 8003

**3. Frontends (Streamlit) — use a different port for each app**

# Terminal 1 — tutor
.\.venv\Scripts\Activate.ps1
streamlit run Streamlit-UIs/tutor-chatbot.py --server.port 8501

# Terminal 2 — dashboard
.\.venv\Scripts\Activate.ps1
streamlit run Streamlit-UIs/teacher_dashboard.py --server.port 8502
`

- Tutor UI: http://localhost:8501  
- Dashboard UI: http://localhost:8502  
- API docs: http://127.0.0.1:8000/docs  

---

## What this project does

| Part | Role |
|------|------|
| **FastAPI backend** | REST API — BKT updates, tutor hints, mastery matrix, integration endpoints |
| **BKT engine** | Bayesian Knowledge Tracing — params from Postgres, mastery from live attempts |
| **Knowledge base (RAG)** | ChromaDB + local embeddings over Grade 6 Science syllabus PDF |
| **Socratic tutor** | LLM hints grounded in RAG + current mastery state |
| **Teacher dashboard** | Streamlit heatmap — students × topics mastery |
| **Tutor chatbot** | Streamlit UI to test Socratic tutor API |

**External integrations (implemented in this module):**

- POST /api/v1/assessment-submit — Question Engine sends quiz outcomes
- POST /api/v1/engagement/frustration-cue — Engagement module sends frustration signals

See README- Documentation/INTEGRATIONS.md and README- Documentation/DEMO_FLOW.md for full API and demo details.

---

## Repository structure

`	ext
learner-analytics-genai-support/
├── .env                          # local secrets — NOT committed
├── .gitignore
├── requirements.txt
├── README.md
│
├── Data/                         # static input data (committed)
│   ├── Skill-Heirarchies.xlsx
│   ├── Rubrics/hitl_rubric_template.csv
│   └── Syllabi/
│       ├── science G-6 E (1).pdf
│       └── science G-7 P-I E.pdf
│
├── FastAPI-Backend/              # backend API + core logic
│   ├── main.py                   # FastAPI app entry
│   ├── bkt_engine.py
│   ├── knowledge_base.py
│   └── socratic_tutor.py
│
├── Streamlit-UIs/                # frontends (HTTP only — no backend imports)
│   ├── teacher_dashboard.py
│   └── tutor-chatbot.py
│
├── Scripts/                      # offline utilities
│   ├── generate_data.py
│   └── evaluation.py
│
└── README- Documentation/        # detailed docs (demo flow, BKT, integrations, etc.)
`

**Generated at repo root (gitignored, not committed):**

- .chroma_science_g6/ — RAG vector index
- live_state_events.db — persisted BKT / chat / frustration events
- interaction_logs.json — tutor interaction log
- evaluation_outputs/ — output from Scripts/evaluation.py

Use **one virtual environment at repo root** (.venv/). Do not create a second venv under FastAPI-Backend/.

---

## Setup

From repo root (learner-analytics-genai-support/):

`powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
`

Copy or create `.env` at repo root with at least:

```text
GROQ_API_KEY=your_key_here
DATABASE_URL=postgresql://...   # Neon / Postgres (BKT params + learner analytics tables)
```

Analytics (teacher dashboard, student profile, mastery matrix) use **live_state only** — real attempts from Question Engine, tutor turns, and `bkt_mastery` in Postgres. No synthetic CSV replay at runtime.

---

## Run commands (reference)

All commands below assume the repo-root venv is activated. See **Terminal commands** at the top for the usual backend + UI workflow.

### Build / refresh RAG index (Chroma)

`powershell
cd FastAPI-Backend
python knowledge_base.py
`

Optional rebuild and sample query (still from FastAPI-Backend/):

`powershell
python knowledge_base.py --rebuild --topic G6_S8_ELE_CIRCUITS
`

- PDF source: Data/Syllabi/science G-6 E (1).pdf
- Index output: .chroma_science_g6/ at repo root

### Scripts

From repo root (optional offline research scripts only):

```powershell
# Generate synthetic training CSV for Scripts/evaluation.py (not used by the API)
python Scripts/generate_data.py

# BKT evaluation (in-sample + user holdout) — requires synthetic_logs.csv
python Scripts/evaluation.py
```

Evaluation outputs are written to evaluation_outputs/ at repo root by default.
