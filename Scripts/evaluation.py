from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "FastAPI-Backend"))

from bkt_engine import ScienceBKT


def _safe_auc(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    valid = np.isfinite(y_true) & np.isfinite(y_pred)
    if not np.any(valid):
        return float("nan")
    y_t = y_true[valid]
    y_p = y_pred[valid]
    if len(np.unique(y_t)) < 2:
        return float("nan")
    return float(roc_auc_score(y_t, y_p))


def _safe_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    valid = np.isfinite(y_true) & np.isfinite(y_pred)
    if not np.any(valid):
        return float("nan")
    y_t = y_true[valid]
    y_p = y_pred[valid]
    return float(np.sqrt(mean_squared_error(y_t, y_p)))


def _float_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _fit_params_from_train_split(
    engine: ScienceBKT,
    topic_id: str,
    train_df: pd.DataFrame,
) -> tuple[dict[str, float], str]:
    """
    Fit skill parameters from train split only.
    Returns (params, fitting_mode).
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        engine.model.fit(data=train_df, defaults=engine.defaults, num_fits=12)
    pred_train = engine.model.predict(data=train_df)
    y_pred_train = pred_train["correct_predictions"].to_numpy(dtype=float)
    valid = np.isfinite(y_pred_train)

    py_prior_ok = engine._pybkt_prior_is_valid(topic_id)  # intentional use of internal guard
    pred_degenerate = (not np.any(valid)) or (float(np.nanstd(y_pred_train[valid])) < 1e-8)

    if (not py_prior_ok) or pred_degenerate:
        return engine._calibrate_bkt_params(train_df), "seq-cal"
    return engine._extract_skill_params(topic_id, train_df), "pyBKT"


def run_evaluation(
    data_path: str,
    test_ratio: float,
    seed: int,
    auc_target: float,
    output_dir: str,
) -> dict[str, Any]:
    engine = ScienceBKT(data_path=data_path)
    engine.initialize_skills()

    print("Running in-sample skill evaluation...")
    in_sample_metrics = engine.train_model()
    in_sample_df = (
        pd.DataFrame(
            [
                {"topic_id": topic, "auc": vals.get("auc"), "rmse": vals.get("rmse")}
                for topic, vals in in_sample_metrics.items()
            ]
        )
        .sort_values("topic_id")
        .reset_index(drop=True)
    )

    print("Running user-holdout evaluation...")
    rng = np.random.default_rng(seed)
    holdout_rows: list[dict[str, Any]] = []
    logs_df = engine.logs_df.copy()

    for topic_id in sorted(engine.skill_map.keys()):
        skill_df = logs_df[logs_df["skill_name"].astype(str) == str(topic_id)].copy()
        if skill_df.empty:
            continue
        skill_df = skill_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
        skill_df["order_id"] = skill_df.groupby("user_id").cumcount() + 1

        users = sorted(skill_df["user_id"].astype(str).unique())
        n_users = len(users)
        if n_users < 2:
            holdout_rows.append(
                {
                    "topic_id": topic_id,
                    "n_users_total": n_users,
                    "n_train_rows": int(len(skill_df)),
                    "n_test_rows": 0,
                    "fit_mode": "skipped",
                    "auc_train": np.nan,
                    "rmse_train": np.nan,
                    "auc_test": np.nan,
                    "rmse_test": np.nan,
                    "auc_target_pass": None,
                    "skip_reason": "too_few_users",
                }
            )
            continue

        shuffled = users.copy()
        rng.shuffle(shuffled)
        n_test_users = max(1, int(round(n_users * test_ratio)))
        n_test_users = min(n_test_users, n_users - 1)
        test_users = set(shuffled[:n_test_users])
        train_users = set(shuffled[n_test_users:])

        train_df = skill_df[skill_df["user_id"].astype(str).isin(train_users)].copy()
        test_df = skill_df[skill_df["user_id"].astype(str).isin(test_users)].copy()
        train_df = train_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
        test_df = test_df.sort_values(["user_id", "order_id"]).reset_index(drop=True)
        train_df["order_id"] = train_df.groupby("user_id").cumcount() + 1
        test_df["order_id"] = test_df.groupby("user_id").cumcount() + 1

        if train_df.empty or test_df.empty:
            holdout_rows.append(
                {
                    "topic_id": topic_id,
                    "n_users_total": n_users,
                    "n_train_rows": int(len(train_df)),
                    "n_test_rows": int(len(test_df)),
                    "fit_mode": "skipped",
                    "auc_train": np.nan,
                    "rmse_train": np.nan,
                    "auc_test": np.nan,
                    "rmse_test": np.nan,
                    "auc_target_pass": None,
                    "skip_reason": "empty_split",
                }
            )
            continue

        params, fit_mode = _fit_params_from_train_split(engine, topic_id, train_df)
        y_train_true, y_train_pred = engine._sequence_predict(train_df, params)
        y_test_true, y_test_pred = engine._sequence_predict(test_df, params)

        auc_train = _safe_auc(y_train_true, y_train_pred)
        rmse_train = _safe_rmse(y_train_true, y_train_pred)
        auc_test = _safe_auc(y_test_true, y_test_pred)
        rmse_test = _safe_rmse(y_test_true, y_test_pred)
        auc_pass = bool(np.isfinite(auc_test) and (auc_test >= auc_target))

        holdout_rows.append(
            {
                "topic_id": topic_id,
                "n_users_total": n_users,
                "n_train_rows": int(len(train_df)),
                "n_test_rows": int(len(test_df)),
                "fit_mode": fit_mode,
                "auc_train": auc_train,
                "rmse_train": rmse_train,
                "auc_test": auc_test,
                "rmse_test": rmse_test,
                "auc_target_pass": auc_pass if np.isfinite(auc_test) else None,
                "skip_reason": "",
            }
        )

    holdout_df = pd.DataFrame(holdout_rows).sort_values("topic_id").reset_index(drop=True)

    valid_auc = holdout_df["auc_test"].dropna()
    valid_rmse = holdout_df["rmse_test"].dropna()
    pass_mask = holdout_df["auc_target_pass"] == True
    auc_pass_rate = (float(pass_mask.sum()) / float(len(valid_auc))) if len(valid_auc) else np.nan

    summary = {
        "config": {
            "data_path": str(data_path),
            "test_ratio": float(test_ratio),
            "seed": int(seed),
            "auc_target": float(auc_target),
        },
        "in_sample": {
            "topics_evaluated": int(len(in_sample_df)),
            "auc_macro_avg": _float_or_none(float(in_sample_df["auc"].dropna().mean()))
            if not in_sample_df.empty
            else None,
            "rmse_macro_avg": _float_or_none(float(in_sample_df["rmse"].dropna().mean()))
            if not in_sample_df.empty
            else None,
        },
        "holdout": {
            "topics_evaluated": int(len(holdout_df)),
            "topics_with_valid_auc": int(len(valid_auc)),
            "topics_with_valid_rmse": int(len(valid_rmse)),
            "auc_test_macro_avg": _float_or_none(float(valid_auc.mean())) if len(valid_auc) else None,
            "rmse_test_macro_avg": _float_or_none(float(valid_rmse.mean())) if len(valid_rmse) else None,
            "auc_target_pass_rate": _float_or_none(float(auc_pass_rate)),
            "auc_target_topics_passed": int(pass_mask.sum()),
        },
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    in_sample_path = out_dir / "in_sample_metrics.csv"
    holdout_path = out_dir / "holdout_metrics.csv"
    summary_path = out_dir / "summary.json"
    in_sample_df.to_csv(in_sample_path, index=False)
    holdout_df.to_csv(holdout_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nSaved:")
    print(f"- {in_sample_path}")
    print(f"- {holdout_path}")
    print(f"- {summary_path}")
    print("\nKey results:")
    print(json.dumps(summary["holdout"], indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate BKT predictive accuracy with in-sample and user-holdout metrics."
    )
    parser.add_argument(
        "--data-path",
        default=str(PROJECT_ROOT / "Data" / "synthetic_logs.csv"),
        help="Path to training/eval CSV",
    )
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Fraction of users per topic for holdout test")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for user split")
    parser.add_argument("--auc-target", type=float, default=0.75, help="Proposal target threshold for AUC")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "evaluation_outputs"),
        help="Directory for csv/json outputs",
    )
    args = parser.parse_args()

    if not (0.05 <= args.test_ratio <= 0.8):
        raise ValueError("--test-ratio must be between 0.05 and 0.8")

    run_evaluation(
        data_path=args.data_path,
        test_ratio=args.test_ratio,
        seed=args.seed,
        auc_target=args.auc_target,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
