from pathlib import Path
import os
import re
import sys
import warnings
from collections import defaultdict
from typing import Any, Optional

import pandas as pd
import numpy as np
import sklearn
from sklearn.metrics import mean_squared_error, roc_auc_score


def _major_minor(version: str) -> tuple[int, int]:
    """Return (major, minor) from a semantic version string."""
    parts = version.split(".")
    return int(parts[0]), int(parts[1])


def _validate_runtime() -> None:
    """
    Guardrail for known pyBKT compatibility boundaries.

    pyBKT currently breaks with some newer runtime/library combinations.
    This check fails early with a clear setup message instead of failing deep
    inside pyBKT during import/training.
    """
    py = (sys.version_info.major, sys.version_info.minor)
    np_v = _major_minor(np.__version__)
    sk_v = _major_minor(sklearn.__version__)

    # pyBKT currently has compatibility issues with very new Python/scikit/numpy stacks.
    if py >= (3, 12) or np_v >= (2, 0) or sk_v >= (1, 6):
        raise RuntimeError(
            "Incompatible environment for pyBKT detected. "
            f"Found Python {py[0]}.{py[1]}, numpy {np.__version__}, sklearn {sklearn.__version__}. "
            "Use Python 3.10 or 3.11 with numpy<2.0 and scikit-learn<1.6."
        )


_validate_runtime()

try:
    from pyBKT.models import Model
except ImportError as exc:
    raise ImportError(
        "pyBKT is required. Install it with: pip install pyBKT"
    ) from exc

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Literature defaults when Postgres has no per-skill row (Corbett & Anderson style).
LITERATURE_BKT_DEFAULTS: dict[str, float] = {
    "prior": 0.25,
    "learn": 0.15,
    "guess": 0.20,
    "slip": 0.10,
    "forget": 0.0,
}


class ScienceBKT:
    def __init__(
        self,
        data_path: str | None = None,
        seed: int = 42,
        num_fits: int = 1,
        params_source: str = "postgres",
        persist_mastery: bool = False,
    ):
        """
        Initialize ScienceBKT with pyBKT model setup.

        **Live mastery:** One latent P(L) per ``(user_id, skill_name)`` in
        ``student_state``. Both the assessment module and the Socratic tutor should
        call ``predict_update`` on this same instance so quiz outcomes and dialogue
        observations extend a **single** trajectory.

        params_source:
            ``postgres`` — read ``learner_analytics.bkt_skill_params`` (production).
            ``csv`` — optional offline path; requires ``data_path`` with training logs.
        persist_mastery:
            When True, each ``predict_update`` upserts ``learner_analytics.bkt_mastery``.
        """
        source = str(params_source or "postgres").strip().lower()
        self.params_source = "postgres" if source == "postgres" else "csv"
        self.persist_mastery = bool(persist_mastery)

        if self.params_source == "csv" or data_path:
            self.data_path = self._resolve_data_path(data_path or "synthetic_logs.csv")
            if not self.data_path.exists():
                raise FileNotFoundError(f"Dataset not found: {self.data_path}")
            self.logs_df = pd.read_csv(self.data_path)
        else:
            self.data_path = None
            self.logs_df = pd.DataFrame(
                columns=["user_id", "skill_name", "correct", "response_time"]
            )

        required_cols = {"user_id", "skill_name", "correct"}
        missing = required_cols - set(self.logs_df.columns)
        if missing and not self.logs_df.empty:
            raise ValueError(f"Missing required columns in dataset: {sorted(missing)}")

        if not self.logs_df.empty:
            self.logs_df = self.logs_df.copy()
            self.logs_df["order_id"] = range(1, len(self.logs_df) + 1)
        else:
            self.logs_df["order_id"] = pd.Series(dtype=int)

        # Column mapping expected by pyBKT for non-standard datasets.
        self.defaults = {
            "user_id": "user_id",
            "skill_name": "skill_name",
            "correct": "correct",
            "order_id": "order_id",
        }

        # Core pyBKT model used repeatedly for per-skill fitting (offline csv mode).
        self.model = Model(seed=seed, num_fits=num_fits)
        # Mapping of Grade 6–9 topic IDs used by this engine.
        self.skill_map = {}
        # Cached per-skill parameters (prior/learn/guess/slip/forget).
        self.skill_params = {}
        # Real-time state keyed by (user_id, skill_name): mastery, attempts, streak.
        self.student_state = {}
        # Learners whose Postgres mastery rows were bulk-loaded (avoids N+1 queries).
        self._db_prefetched_users: set[str] = set()
        # Quick lookup for current risk flag per user+skill.
        self.at_risk_flags = defaultdict(dict)
        self.skipped_skills = {}
        # Conservative live-update controls (env-tunable).
        self.update_damping = self._read_env_float("BKT_UPDATE_DAMPING", 0.60, 0.05, 1.0)
        self.early_mastery_cap = self._read_env_float("BKT_EARLY_MASTERY_CAP", 0.90, 0.50, 0.99)
        self.early_mastery_attempts = int(self._read_env_float("BKT_EARLY_MASTERY_ATTEMPTS", 5, 1, 50))
        self.max_step_up = self._read_env_float("BKT_MAX_STEP_UP", 0.12, 0.02, 0.35)
        self.max_step_down = self._read_env_float("BKT_MAX_STEP_DOWN", 0.12, 0.02, 0.35)

    @staticmethod
    def _resolve_data_path(data_path: str) -> Path:
        """
        Resolve CSV path relative to repo root or Data/.

        Search order:
        1) Provided path as-is (relative to current working directory).
        2) Path relative to repo root.
        3) `Data/<filename>` under repo root.
        """
        raw = Path(data_path)
        if raw.is_file():
            return raw.resolve()
        candidates = (
            PROJECT_ROOT / raw,
            PROJECT_ROOT / "Data" / raw.name,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return (PROJECT_ROOT / "Data" / raw.name).resolve()

    @staticmethod
    def _read_env_float(name: str, default: float, lo: float, hi: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return float(default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return float(default)
        return float(np.clip(val, lo, hi))

    def initialize_skills(self) -> dict[str, str]:
        """
        Build the skill map from Grade 6–9 topic IDs.

        Live (``params_source=postgres``) prefers topic IDs already present in
        ``learner_analytics.bkt_skill_params``. Replay falls back to the CSV.
        """
        if self.params_source == "postgres":
            try:
                from postgres_store import list_bkt_skill_ids

                db_topics = [
                    tid
                    for tid in list_bkt_skill_ids()
                    if re.match(r"^G[6-9][_-]", str(tid))
                ]
            except Exception:
                db_topics = []
            if db_topics:
                self.skill_map = {topic_id: topic_id for topic_id in db_topics}
                return self.skill_map

        if not self.logs_df.empty:
            unique_skills = sorted(self.logs_df["skill_name"].dropna().astype(str).unique())
            curriculum_skills = [s for s in unique_skills if re.match(r"^G[6-9][_-]", s)]
            if curriculum_skills:
                self.skill_map = {topic_id: topic_id for topic_id in curriculum_skills}
                return self.skill_map

        from curriculum_topics import TOPIC_IDS

        curriculum_skills = [s for s in TOPIC_IDS if re.match(r"^G[6-9][_-]", str(s))]
        if not curriculum_skills:
            raise ValueError("No Grade 6–9 topic IDs found in Postgres, CSV, or curriculum catalog.")
        self.skill_map = {topic_id: topic_id for topic_id in curriculum_skills}
        return self.skill_map

    def train_model(self) -> dict[str, dict[str, float]]:
        """
        Train and evaluate a BKT model per skill.

        Returns:
            dict[skill_id] = {"auc": float|nan, "rmse": float|nan}
        """
        if not self.skill_map:
            self.initialize_skills()

        metrics = {}
        for topic_id in self.skill_map:
            skill_df = self.logs_df[self.logs_df["skill_name"] == topic_id].copy()
            if skill_df.empty:
                continue
            # Ensure deterministic sequence ordering within each user for this skill.
            skill_df = skill_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
            skill_df["order_id"] = skill_df.groupby("user_id").cumcount() + 1
            is_ok, reason = self._skill_quality_check(skill_df)
            if not is_ok:
                self.skipped_skills[topic_id] = reason
                print(f"{topic_id} -> skipped ({reason})")
                continue

            # Fit and evaluate each skill independently for pyBKT==1.4.1 compatibility.
            with warnings.catch_warnings():
                # pyBKT emits runtime warnings for unstable EM steps.
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                self.model.fit(data=skill_df, defaults=self.defaults, num_fits=12)
            pred_df = self.model.predict(data=skill_df)

            y_true = pred_df["correct"].to_numpy(dtype=float)
            y_pred = pred_df["correct_predictions"].to_numpy(dtype=float)
            valid = np.isfinite(y_true) & np.isfinite(y_pred)

            py_prior_ok = self._pybkt_prior_is_valid(topic_id)
            pred_degenerate = (
                not np.any(valid)
                or (np.any(valid) and float(np.nanstd(y_pred[valid])) < 1e-8)
            )

            # pyBKT EM often collapses on small/custom datasets (NaN prior, constant preds).
            # Fall back to fast random-search calibration on a standard sequential BKT model.
            if (not py_prior_ok) or pred_degenerate:
                calibrated = self._calibrate_bkt_params(skill_df)
                self.skill_params[topic_id] = calibrated
                y_true, y_pred = self._sequence_predict(skill_df, calibrated)
                valid = np.isfinite(y_true) & np.isfinite(y_pred)
            else:
                self.skill_params[topic_id] = self._extract_skill_params(topic_id, skill_df)

            # pyBKT can emit NaN predictions for some edge cases; skip them safely.
            if not np.any(valid):
                auc = float("nan")
                rmse = float("nan")
            else:
                y_true_valid = y_true[valid]
                y_pred_valid = y_pred[valid]
                rmse = float(np.sqrt(mean_squared_error(y_true_valid, y_pred_valid)))
                # AUC requires both classes in y_true.
                if len(np.unique(y_true_valid)) < 2:
                    auc = float("nan")
                else:
                    auc = float(roc_auc_score(y_true_valid, y_pred_valid))

            metrics[topic_id] = {"auc": auc, "rmse": rmse}
            auc_text = f"{auc:.4f}" if np.isfinite(auc) else "N/A"
            rmse_text = f"{rmse:.4f}" if np.isfinite(rmse) else "N/A"
            mode = "seq-cal" if (not py_prior_ok) or pred_degenerate else "pyBKT"
            print(f"{topic_id} -> AUC: {auc_text}, RMSE: {rmse_text} ({mode})")

        return metrics

    def _sequence_predict(self, skill_df: pd.DataFrame, params: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        """
        Generate one-step-ahead correctness probabilities for each row in sequence.
        Prediction at each step is computed before ingesting the current observation.
        """
        y_true_list: list[float] = []
        y_pred_list: list[float] = []

        for _, user_seq in skill_df.groupby("user_id", sort=False):
            user_seq = user_seq.sort_values("order_id", kind="mergesort")
            mastery = float(params["prior"])
            for _, row in user_seq.iterrows():
                p_correct = mastery * (1.0 - params["slip"]) + (1.0 - mastery) * params["guess"]
                y_pred_list.append(float(np.clip(p_correct, 1e-6, 1 - 1e-6)))
                obs = int(row["correct"])
                y_true_list.append(float(obs))

                # Bayesian update then transition.
                if obs == 1:
                    den = mastery * (1.0 - params["slip"]) + (1.0 - mastery) * params["guess"]
                    post = (mastery * (1.0 - params["slip"])) / den if den > 0 else mastery
                else:
                    den = mastery * params["slip"] + (1.0 - mastery) * (1.0 - params["guess"])
                    post = (mastery * params["slip"]) / den if den > 0 else mastery
                mastery = post + (1.0 - post) * params["learn"]
                mastery = mastery * (1.0 - params["forget"])
                mastery = float(np.clip(mastery, 1e-6, 1 - 1e-6))

        return np.asarray(y_true_list, dtype=float), np.asarray(y_pred_list, dtype=float)

    def _pybkt_prior_is_valid(self, skill_id: str) -> bool:
        try:
            prior = float(self.model.params().loc[(skill_id, "prior", "default"), "value"])
        except Exception:
            return False
        return bool(np.isfinite(prior))

    def _calibrate_bkt_params(self, skill_df: pd.DataFrame, trials: int = 64, seed: int = 42) -> dict[str, float]:
        """
        Fast random search for BKT parameters (sequential one-step-ahead log-loss).
        Used when pyBKT's EM fit collapses (NaN prior / constant predictions).
        """
        rng = np.random.default_rng(seed)
        empirical_prior = float(np.clip(skill_df["correct"].mean(), 0.12, 0.88))
        best = None
        best_loss = float("inf")

        for t in range(trials):
            params = {
                "prior": float(rng.uniform(0.06, 0.42)),
                "learn": float(rng.uniform(0.04, 0.28)),
                "guess": float(rng.uniform(0.12, 0.34)),
                "slip": float(rng.uniform(0.05, 0.24)),
                "forget": float(rng.choice([0.0, 0.005, 0.01, 0.02])),
            }
            y_true, y_pred = self._sequence_predict(skill_df, params)
            loss = -np.mean(y_true * np.log(y_pred) + (1.0 - y_true) * np.log(1.0 - y_pred))
            if loss < best_loss:
                best_loss = float(loss)
                best = params

        if best is None:
            return {
                "prior": empirical_prior,
                "learn": 0.15,
                "guess": 0.22,
                "slip": 0.12,
                "forget": 0.01,
            }

        best["prior"] = float(0.45 * best["prior"] + 0.55 * empirical_prior)
        best["learn"] = float(np.clip(best["learn"], 0.03, 0.35))
        best["guess"] = float(np.clip(best["guess"], 0.08, 0.40))
        best["slip"] = float(np.clip(best["slip"], 0.05, 0.30))
        return best

    def _skill_quality_check(self, skill_df: pd.DataFrame) -> tuple[bool, str]:
        """Basic data sufficiency checks to avoid unstable pyBKT fits."""
        n_rows = len(skill_df)
        n_users = skill_df["user_id"].nunique()
        n_correct = int((skill_df["correct"] == 1).sum())
        n_incorrect = int((skill_df["correct"] == 0).sum())
        attempts_per_user = skill_df.groupby("user_id").size()
        median_attempts = float(attempts_per_user.median()) if not attempts_per_user.empty else 0.0

        if n_rows < 80:
            return False, f"too_few_rows:{n_rows}"
        if n_users < 15:
            return False, f"too_few_users:{n_users}"
        if n_correct < 20 or n_incorrect < 20:
            return False, f"class_imbalance:c={n_correct},i={n_incorrect}"
        if median_attempts < 8:
            return False, f"short_sequences:median={median_attempts:.1f}"
        return True, "ok"

    def _extract_skill_params(self, skill_id: str, skill_df: pd.DataFrame) -> dict[str, float]:
        """
        Extracts (or derives) BKT parameters for a skill from the fitted model.
        Falls back to safe defaults when pyBKT returns NaN for sparse/degenerate data.
        """
        params_df = self.model.params()

        def get_param(name: str, fallback: float) -> float:
            # Read fitted value from pyBKT params table; use fallback if missing/NaN.
            value = fallback
            try:
                value = float(params_df.loc[(skill_id, name, "default"), "value"])
            except Exception:
                value = fallback
            if not np.isfinite(value):
                value = fallback
            return float(np.clip(value, 1e-4, 0.9999))

        empirical_prior = float(skill_df["correct"].mean())
        if not np.isfinite(empirical_prior):
            empirical_prior = 0.25

        learn = float(np.clip(get_param("learns", 0.15), 0.03, 0.35))
        return {
            "prior": get_param("prior", empirical_prior),
            "learn": learn,
            "guess": get_param("guesses", 0.2),
            "slip": get_param("slips", 0.1),
            # Keep small forgetting by default to support time-varying retention.
            "forget": get_param("forgets", 0.01),
        }

    @staticmethod
    def literature_default_params() -> dict[str, float]:
        return dict(LITERATURE_BKT_DEFAULTS)

    def _ensure_skill_params(self, skill_name: str) -> None:
        """Load BKT parameters for one skill (Postgres table or literature defaults)."""
        if skill_name in self.skill_params:
            return
        if self.params_source == "postgres":
            try:
                from postgres_store import fetch_skill_params

                db_params = fetch_skill_params(skill_name)
            except Exception:
                db_params = None
            if db_params:
                self.skill_params[skill_name] = db_params
                return
            self.skill_params[skill_name] = self.literature_default_params()
            return
        skill_df = self.logs_df[self.logs_df["skill_name"] == skill_name].copy()
        if skill_df.empty:
            raise ValueError(f"No training rows found for skill_name: {skill_name}")
        skill_df = skill_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
        skill_df["order_id"] = skill_df.groupby("user_id").cumcount() + 1
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            self.model.fit(data=skill_df, defaults=self.defaults, num_fits=12)
            pred_df = self.model.predict(data=skill_df)
        y_pred = pred_df["correct_predictions"].to_numpy(dtype=float)
        valid = np.isfinite(y_pred)
        if (not self._pybkt_prior_is_valid(skill_name)) or (
            not np.any(valid) or float(np.nanstd(y_pred[valid])) < 1e-8
        ):
            self.skill_params[skill_name] = self._calibrate_bkt_params(skill_df)
        else:
            self.skill_params[skill_name] = self._extract_skill_params(skill_name, skill_df)

    def clear_runtime_state_for_learners(self, user_ids: list[str]) -> int:
        """Drop in-memory mastery so the next update reloads from Postgres (or prior)."""
        ids = {str(uid) for uid in user_ids if str(uid).strip()}
        removed = 0
        for uid in ids:
            self._db_prefetched_users.discard(uid)
            self.at_risk_flags.pop(uid, None)
        for key in [k for k in list(self.student_state.keys()) if str(k[0]) in ids]:
            del self.student_state[key]
            removed += 1
        return removed

    def prefetch_learner_states(self, user_id: str) -> None:
        """Bulk-load persisted mastery for one learner (single Postgres round trip)."""
        uid = str(user_id)
        if uid in self._db_prefetched_users:
            return
        self._db_prefetched_users.add(uid)
        if not (self.persist_mastery or self.params_source == "postgres"):
            return
        try:
            from postgres_store import fetch_mastery_states_for_learner

            rows = fetch_mastery_states_for_learner(uid)
        except Exception:
            return
        for topic_id, db_state in rows.items():
            state_key = (uid, str(topic_id))
            self.student_state[state_key] = {
                "mastery": float(db_state["mastery"]),
                "attempts": int(db_state["attempts"]),
                "consecutive_incorrect": int(db_state["consecutive_incorrect"]),
            }
            self.at_risk_flags[uid][str(topic_id)] = (
                "At-Risk" if db_state.get("at_risk") else "On-Track"
            )

    def _hydrate_student_state(self, user_id: str, skill_name: str, prior: float) -> dict[str, Any]:
        """Load (user, skill) state from Postgres if persisted, else start at prior."""
        state_key = (user_id, skill_name)
        if state_key in self.student_state:
            return self.student_state[state_key]
        uid = str(user_id)
        if uid in self._db_prefetched_users:
            state = {
                "mastery": float(prior),
                "attempts": 0,
                "consecutive_incorrect": 0,
            }
            self.student_state[state_key] = state
            return state
        db_state = None
        if self.persist_mastery or self.params_source == "postgres":
            try:
                from postgres_store import fetch_mastery_state

                db_state = fetch_mastery_state(uid, str(skill_name))
            except Exception:
                db_state = None
        if db_state:
            state = {
                "mastery": float(db_state["mastery"]),
                "attempts": int(db_state["attempts"]),
                "consecutive_incorrect": int(db_state["consecutive_incorrect"]),
            }
        else:
            state = {
                "mastery": float(prior),
                "attempts": 0,
                "consecutive_incorrect": 0,
            }
        self.student_state[state_key] = state
        if db_state:
            self.at_risk_flags[user_id][skill_name] = (
                "At-Risk" if db_state.get("at_risk") else "On-Track"
            )
        return state

    def _persist_student_state(
        self,
        user_id: str,
        skill_name: str,
        *,
        mastery: float,
        attempts: int,
        consecutive_incorrect: int,
        at_risk: bool,
    ) -> dict[str, Any]:
        if not self.persist_mastery:
            return {"ok": False, "skipped": True, "reason": "persist_mastery is disabled"}
        try:
            from postgres_store import upsert_mastery_state

            return upsert_mastery_state(
                learner_id=str(user_id),
                topic_id=str(skill_name),
                p_l=float(mastery),
                attempts=int(attempts),
                consecutive_incorrect=int(consecutive_incorrect),
                at_risk=bool(at_risk),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def preload_calibrated_skill_params(self, *, trials: int = 8) -> int:
        """
        Pre-load per-skill BKT parameters.

        Postgres mode: bulk-read ``bkt_skill_params`` (literature defaults for gaps).
        CSV mode: offline calibration from ``logs_df`` (Scripts/evaluation only).
        """
        if self.params_source == "postgres":
            try:
                from postgres_store import fetch_skill_params
            except Exception:
                fetch_skill_params = None  # type: ignore[assignment,misc]
            loaded = 0
            for skill_name in self.skill_map:
                if skill_name in self.skill_params:
                    continue
                db_params = None
                if fetch_skill_params is not None:
                    try:
                        db_params = fetch_skill_params(skill_name)
                    except Exception:
                        db_params = None
                self.skill_params[skill_name] = db_params or self.literature_default_params()
                loaded += 1
            return loaded

        loaded = 0
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            for skill_name in self.skill_map:
                if skill_name in self.skill_params:
                    continue
                skill_df = self.logs_df[self.logs_df["skill_name"] == skill_name].copy()
                if skill_df.empty:
                    continue
                skill_df = skill_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
                skill_df["order_id"] = skill_df.groupby("user_id").cumcount() + 1
                self.skill_params[skill_name] = self._calibrate_bkt_params(
                    skill_df,
                    trials=max(4, int(trials)),
                )
                loaded += 1
        return loaded

    @staticmethod
    def _apply_bkt_observation(prior_mastery: float, p: dict[str, float], is_correct: int) -> float:
        """One BKT step: Bayes update from observation, then learn/forget transition."""
        if is_correct == 1:
            num = prior_mastery * (1.0 - p["slip"])
            den = num + (1.0 - prior_mastery) * p["guess"]
        else:
            num = prior_mastery * p["slip"]
            den = num + (1.0 - prior_mastery) * (1.0 - p["guess"])
        posterior = num / den if den > 0 else prior_mastery
        next_mastery = posterior + (1.0 - posterior) * p["learn"]
        next_mastery = next_mastery * (1.0 - p["forget"])
        return float(np.clip(next_mastery, 0.0, 1.0))

    def predict_update(
        self,
        user_id: str,
        skill_name: str,
        is_correct: int,
        response_time: Optional[float] = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """
        Story 4: process a single interaction (one row), not a CSV batch.

        Updates latent mastery P(L) using trained BKT parameters, applies risk rules,
        and returns a JSON-serializable dict for FastAPI.

        **Callers:** Prefer ``is_correct`` from a **verified** item response (quiz /
        assessment). The Socratic layer may map an LLM ``interaction_score`` to
        ``0``/``1`` and call this method only when that score is present—same engine,
        same ``student_state`` key.

        Risk (at_risk True if either):
        - Mastery after the attempt is strictly lower than before the attempt.
        - The student has just completed 3 incorrect answers in a row on this skill.
        """
        if not self.skill_map:
            self.initialize_skills()
        if skill_name not in self.skill_map:
            raise ValueError(f"Unknown skill_name: {skill_name}. Run initialize_skills() first.")
        if is_correct not in (0, 1):
            raise ValueError("is_correct must be 0 or 1.")

        self._ensure_skill_params(skill_name)
        p = self.skill_params[skill_name]
        state_key = (user_id, skill_name)
        state = self._hydrate_student_state(user_id, skill_name, float(p["prior"]))

        previous_mastery = float(state["mastery"])
        attempts = int(state["attempts"]) + 1
        prev_streak = int(state.get("consecutive_incorrect", 0))

        raw_mastery = self._apply_bkt_observation(previous_mastery, p, is_correct)
        # Smooth large jumps so consecutive correct answers don't over-shoot too fast.
        new_mastery = previous_mastery + self.update_damping * (raw_mastery - previous_mastery)
        # Hard per-attempt bounds to avoid dramatic one-question jumps.
        step = new_mastery - previous_mastery
        if step > self.max_step_up:
            new_mastery = previous_mastery + self.max_step_up
        elif step < -self.max_step_down:
            new_mastery = previous_mastery - self.max_step_down
        # Optional early-attempt cap to avoid unrealistically high confidence too soon.
        if attempts <= self.early_mastery_attempts:
            new_mastery = min(new_mastery, self.early_mastery_cap)
        new_mastery = float(np.clip(new_mastery, 0.0, 1.0))

        if is_correct == 1:
            consecutive_incorrect = 0
        else:
            consecutive_incorrect = prev_streak + 1

        mastery_dropped = new_mastery < previous_mastery
        three_misses = consecutive_incorrect >= 3
        at_risk = bool(mastery_dropped or three_misses)

        self.student_state[state_key] = {
            "mastery": new_mastery,
            "attempts": attempts,
            "consecutive_incorrect": consecutive_incorrect,
        }
        self.at_risk_flags[user_id][skill_name] = "At-Risk" if at_risk else "On-Track"
        postgres_mastery = (
            self._persist_student_state(
                user_id,
                skill_name,
                mastery=new_mastery,
                attempts=attempts,
                consecutive_incorrect=consecutive_incorrect,
                at_risk=at_risk,
            )
            if persist
            else {"ok": False, "skipped": True, "reason": "persist=False"}
        )

        return {
            "user_id": str(user_id),
            "skill_name": str(skill_name),
            "is_correct": int(is_correct),
            "response_time": None if response_time is None else float(response_time),
            "previous_mastery_probability": round(previous_mastery, 6),
            "raw_mastery_probability": round(raw_mastery, 6),
            "mastery_probability": round(new_mastery, 6),
            "update_damping_factor": round(float(self.update_damping), 4),
            "max_step_up": round(float(self.max_step_up), 4),
            "max_step_down": round(float(self.max_step_down), 4),
            "total_attempts": int(attempts),
            "consecutive_incorrect": int(consecutive_incorrect),
            "mastery_decreased": bool(mastery_dropped),
            "three_consecutive_failures": bool(three_misses),
            "at_risk": bool(at_risk),
            "postgres_mastery": postgres_mastery,
            "params_source": self.params_source,
        }

    def get_mastery_update(self, user_id: str, skill_id: str, is_correct: int) -> dict[str, float | int | str]:
        """
        Real-time BKT update for a single attempt.

        Inputs:
        - user_id: student identifier
        - skill_id: topic/skill identifier
        - is_correct: 1 for correct, 0 for incorrect

        Returns updated mastery score and risk status.
        """
        if skill_id not in self.skill_map:
            raise ValueError(f"Unknown skill_id: {skill_id}. Run initialize_skills() first.")
        if is_correct not in (0, 1):
            raise ValueError("is_correct must be 0 or 1.")

        self._ensure_skill_params(skill_id)

        p = self.skill_params[skill_id]
        state_key = (user_id, skill_id)
        if state_key not in self.student_state:
            # First interaction starts from skill prior.
            self.student_state[state_key] = {
                "mastery": float(p["prior"]),
                "attempts": 0,
                "consecutive_incorrect": 0,
            }

        prior_mastery = float(self.student_state[state_key]["mastery"])
        attempts = int(self.student_state[state_key]["attempts"]) + 1
        prev_streak = int(self.student_state[state_key].get("consecutive_incorrect", 0))

        next_mastery = self._apply_bkt_observation(prior_mastery, p, is_correct)
        consecutive_incorrect = 0 if is_correct == 1 else prev_streak + 1

        # Rule-based risk logic requested:
        # after at least 5 attempts, mastery below 0.5 => At-Risk.
        risk_status = "At-Risk" if attempts >= 5 and next_mastery < 0.5 else "On-Track"
        self.at_risk_flags[user_id][skill_id] = risk_status
        self.student_state[state_key] = {
            "mastery": next_mastery,
            "attempts": attempts,
            "consecutive_incorrect": consecutive_incorrect,
        }

        return {
            "user_id": user_id,
            "skill_id": skill_id,
            "mastery": next_mastery,
            "attempts": attempts,
            "risk_status": risk_status,
        }

    def get_current_mastery_probability(self, user_id: str, skill_name: str) -> float:
        """
        Return the student's current P(L) for this skill without recording a new attempt.

        If the learner has no prior state for (user_id, skill_name), uses the skill prior
        from fitted BKT parameters.
        """
        if not self.skill_map:
            self.initialize_skills()
        if skill_name not in self.skill_map:
            raise ValueError(f"Unknown skill_name: {skill_name}. Run initialize_skills() first.")
        self._ensure_skill_params(skill_name)
        p = self.skill_params[skill_name]
        state = self._hydrate_student_state(user_id, skill_name, float(p["prior"]))
        return float(state["mastery"])

    def get_skill_parameters(self, skill_name: str) -> dict[str, float]:
        """
        Return fitted BKT parameters for a skill.

        Useful for analytics endpoints that need interpretable model diagnostics
        (e.g., high slip flags on a topic).
        """
        if not self.skill_map:
            self.initialize_skills()
        if skill_name not in self.skill_map:
            raise ValueError(f"Unknown skill_name: {skill_name}. Run initialize_skills() first.")
        self._ensure_skill_params(skill_name)
        p = self.skill_params[skill_name]
        return {
            "prior": float(p["prior"]),
            "learn": float(p["learn"]),
            "guess": float(p["guess"]),
            "slip": float(p["slip"]),
            "forget": float(p["forget"]),
        }


if __name__ == "__main__":
    engine = ScienceBKT(data_path="synthetic_logs.csv")
    engine.initialize_skills()
    engine.train_model()

    # Tiny walkthrough demo: simulate a single student's live updates
    # so terminal output is easy to interpret.
    demo_user = "demo_user_001"
    demo_skill = next(iter(engine.skill_map))
    demo_attempts = [0, 0, 1, 0, 1, 1]  # 0=incorrect, 1=correct

    print("\n--- Live Mastery Demo ---")
    print(f"User: {demo_user}")
    print(f"Skill: {demo_skill}")
    print("Attempt format: input -> mastery -> risk_status")

    for idx, ans in enumerate(demo_attempts, start=1):
        result = engine.get_mastery_update(demo_user, demo_skill, ans)
        print(
            f"Attempt {idx}: {ans} -> "
            f"{result['mastery']:.4f} -> {result['risk_status']}"
        )

    print("\n--- predict_update (Story 4 API shape) ---")
    demo_api_user = "demo_api_user"
    for rt, ok in [(14.2, 0), (13.1, 0), (12.0, 0)]:
        out = engine.predict_update(demo_api_user, demo_skill, ok, rt)
        print(out)
