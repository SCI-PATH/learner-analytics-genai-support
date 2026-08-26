# Full Chapter Skill IDs (G6–G9)

**Canonical team file:** `Data/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`  
**Runtime modules:** `FastAPI-Backend/curriculum_topics.py`, log generator, RAG, dashboard

## Format

```text
G{grade}_C{chapter}_{DOMAIN}_{CONCEPT}

Examples:
  G6_C8_ELE_CONDINS   — Grade 6, Chapter 8, Electricity, Conductors/insulators
  G8_C11_PHO_PROCESS  — Grade 8, Chapter 11, Photosynthesis process
  G9_C14_WAV_REFRACT  — Grade 9, Chapter 14, Refraction of light
```

- **`C{n}`** = textbook **chapter number** (not the old “section” `S` code)
- **DOMAIN** = short domain code (ELE, PHO, MAT, …)
- **CONCEPT** = skill focus within that chapter
- Every chapter has **two** skill/topic IDs (focused learning outcomes)

## Coverage

| Grade | Chapters | Skills | Source PDFs |
|------:|----------|-------:|-------------|
| 6 | 1–11 | 22 | Grade 6 volume |
| 7 | 1–19 | 38 | G7 Part I + Part II |
| 8 | 1–15 | 30 | G8 Part I + Part II |
| 9 | 1–19 | 38 | G9 Part I + Part II |
| **Total** | **64 chapters** | **128 skills** | `Data/Syllabi/Grade */` |

Excel sheets:
1. **Skill Hierarchy** — full list with grade, chapter, **Chapter ID** (`G6_C8`), title, part, topic_id, curriculum reference  
2. **Chapter Coverage** — one row per chapter with **Chapter ID** and linked topic IDs  

**Shareable chapter-key CSV for Question Engine:** `Data/chapter_ids_g6_g9.csv`  
Format: `G{grade}_C{chapter}` (example `G6_C8`). 64 rows, Grades 6–9.  

## Rebuild after ID change

```powershell
.\.venv\Scripts\Activate.ps1
python Scripts/build_full_curriculum.py
python Scripts/generate_data.py
cd FastAPI-Backend
python knowledge_base.py --rebuild
```

Then restart uvicorn / Streamlit. Delete old `live_state_events.db` if it still holds pre-migration `_S_` events.

## Legacy S-IDs

`curriculum_topics.normalize_topic_id()` maps common old `G*_S*_…` IDs to new `G*_C*_…` IDs when possible (best-effort). New integrations should use **only** the Full-Chapters Excel.
