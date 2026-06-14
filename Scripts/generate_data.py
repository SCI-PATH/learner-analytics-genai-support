import csv
import random
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


# Total rows = DEFAULT_USERS * len(topic_ids) * ATTEMPTS_PER_USER_SKILL (set in main()).
TOTAL_ROWS = 2100
# Number of synthetic students.
DEFAULT_USERS = 25
# Latent-state parameters for BKT-friendly synthetic generation.
LEARN_RATE_RANGE = (0.08, 0.22)
SLIP_RANGE = (0.05, 0.15)
GUESS_RANGE = (0.15, 0.30)
FORGET_RATE = 0.01
# Enforce sufficiently long sequences per (user, skill) for stable BKT fitting.
ATTEMPTS_PER_USER_SKILL = 12


def _normalize_header(value: str) -> str:
    """Normalize header text so we can match columns robustly."""
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def read_topic_ids_from_csv(csv_path: Path) -> list[str]:
    """
    Read topic IDs from the Skill Hierarchies CSV.

    The function tries to detect a header containing both 'topic' and 'id'.
    If such a header is not found, it falls back to the first column.
    """
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"No headers found in {csv_path}")

        normalized = {_normalize_header(name): name for name in reader.fieldnames}
        topic_col = None
        for key, original in normalized.items():
            if "topic" in key and "id" in key:
                topic_col = original
                break
        if topic_col is None:
            topic_col = reader.fieldnames[0]

        topic_ids = []
        for row in reader:
            value = (row.get(topic_col) or "").strip()
            if value:
                topic_ids.append(value)

    # De-duplicate while preserving source order.
    unique_topic_ids = list(dict.fromkeys(topic_ids))
    if not unique_topic_ids:
        raise ValueError(f"No topic IDs found in {csv_path}")
    return unique_topic_ids


def read_topic_ids_from_xlsx(xlsx_path: Path) -> list[str]:
    """
    Read topic IDs directly from XLSX without external dependencies.

    XLSX is a ZIP of XML files. We read:
    - shared string table (`xl/sharedStrings.xml`) for string values
    - first worksheet (`xl/worksheets/sheet1.xml`) for row/cell values
    """
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                parts = si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                shared_strings.append("".join((p.text or "") for p in parts))

        sheet_xml = zf.read("xl/worksheets/sheet1.xml")
        sheet_root = ET.fromstring(sheet_xml)
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in sheet_root.findall(".//s:sheetData/s:row", ns):
            row_values = []
            for cell in row.findall("s:c", ns):
                cell_type = cell.attrib.get("t")
                v = cell.find("s:v", ns)
                if v is None or v.text is None:
                    row_values.append("")
                    continue
                raw = v.text
                if cell_type == "s":
                    row_values.append(shared_strings[int(raw)] if raw.isdigit() else "")
                else:
                    row_values.append(raw)
            rows.append(row_values)

    if not rows:
        raise ValueError(f"No rows found in {xlsx_path}")

    # Identify the topic-id column from the header row.
    headers = rows[0]
    normalized_headers = [_normalize_header(h) for h in headers]
    topic_idx = None
    for idx, h in enumerate(normalized_headers):
        if "topic" in h and "id" in h:
            topic_idx = idx
            break
    if topic_idx is None:
        topic_idx = 0

    topic_ids = []
    for row in rows[1:]:
        if topic_idx < len(row):
            value = str(row[topic_idx]).strip()
            if value:
                topic_ids.append(value)

    # De-duplicate while preserving source order.
    unique_topic_ids = list(dict.fromkeys(topic_ids))
    if not unique_topic_ids:
        raise ValueError(f"No topic IDs found in {xlsx_path}")
    return unique_topic_ids


def load_topic_ids(base_dir: Path) -> list[str]:
    """Load topic IDs from CSV if available, otherwise from XLSX."""
    csv_path = base_dir / "Skill-Heirarchies.csv"
    xlsx_path = base_dir / "Skill-Heirarchies.xlsx"

    if csv_path.exists():
        return read_topic_ids_from_csv(csv_path)
    if xlsx_path.exists():
        return read_topic_ids_from_xlsx(xlsx_path)

    raise FileNotFoundError(
        "Could not find Skill-Heirarchies.csv or Skill-Heirarchies.xlsx in Data/."
    )


def generate_synthetic_logs(topic_ids: list[str], output_path: Path) -> None:
    """
    Generate BKT-friendly logs: each user practices every skill a fixed number of times.

    Latent mastery updates per (user, skill) with learn/guess/slip/forget dynamics so
    sequential models see real learning signal.

    Output columns:
    - user_id, skill_name, correct (0/1), response_time
    """
    # Build rows first, then write once.
    rows: list[list[object]] = []

    # Give each skill its own guess/slip behavior so skills are distinguishable.
    skill_params = {
        skill: {"guess": random.uniform(*GUESS_RANGE), "slip": random.uniform(*SLIP_RANGE)}
        for skill in topic_ids
    }

    users = [f"user_{user_num:03d}" for user_num in range(1, DEFAULT_USERS + 1)]
    user_learn = {u: random.uniform(*LEARN_RATE_RANGE) for u in users}
    user_initial_mastery = {u: random.uniform(0.05, 0.20) for u in users}
    mastery_by_user_skill = {
        u: {skill: user_initial_mastery[u] for skill in topic_ids}
        for u in users
    }

    def simulate_attempt(user_id: str, skill_name: str) -> list[object]:
        mastery = mastery_by_user_skill[user_id][skill_name]
        guess = skill_params[skill_name]["guess"]
        slip = skill_params[skill_name]["slip"]

        # Observation model:
        # P(correct) = P(known)*(1-slip) + P(not-known)*guess
        correct_prob = mastery * (1.0 - slip) + (1.0 - mastery) * guess
        correct = 1 if random.random() < correct_prob else 0

        # Response time improves with mastery but retains noise.
        response_mean = 24.0 - 12.0 * mastery
        response_time = max(2.0, random.gauss(response_mean, 2.4))

        # Transition model:
        # mastery_t+1 = posterior learning step with small forgetting.
        if correct == 1:
            denom = mastery * (1.0 - slip) + (1.0 - mastery) * guess
            posterior = (mastery * (1.0 - slip)) / denom if denom > 0 else mastery
        else:
            denom = mastery * slip + (1.0 - mastery) * (1.0 - guess)
            posterior = (mastery * slip) / denom if denom > 0 else mastery
        next_mastery = posterior + (1.0 - posterior) * user_learn[user_id]
        next_mastery = next_mastery * (1.0 - FORGET_RATE)
        mastery_by_user_skill[user_id][skill_name] = float(min(0.999, max(0.001, next_mastery)))

        return [user_id, skill_name, correct, round(response_time, 2)]

    # Generate balanced, long sequences:
    # every user practices every skill ATTEMPTS_PER_USER_SKILL times.
    for user_id in users:
        for skill_name in topic_ids:
            for _ in range(ATTEMPTS_PER_USER_SKILL):
                rows.append(simulate_attempt(user_id, skill_name))

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "skill_name", "correct", "response_time"])
        writer.writerows(rows)


def main() -> None:
    """Script entrypoint: load skills, generate CSV, print summary."""
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "Data"
    topic_ids = load_topic_ids(data_dir)
    # Keep total rows aligned with users x skills x attempts.
    global TOTAL_ROWS
    TOTAL_ROWS = DEFAULT_USERS * len(topic_ids) * ATTEMPTS_PER_USER_SKILL
    output_path = data_dir / "synthetic_logs.csv"
    generate_synthetic_logs(topic_ids, output_path)
    print(f"Generated {TOTAL_ROWS} rows in {output_path.name} using {len(topic_ids)} topic IDs.")


if __name__ == "__main__":
    # Fixed seed for reproducible synthetic output.
    random.seed(42)
    main()
