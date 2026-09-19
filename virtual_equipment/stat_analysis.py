"""Optional SciPy diagnostics, with no SciPy import at module load time.

Adjacent samples may be autocorrelated: do not treat them blindly as independent.
P-values support diagnostics, not proof of root cause. Correlation is not causation.
Matched same-seed comparisons establish effects only inside this construction,
not in real semiconductor equipment.
"""
import numpy as np


def _stats():
    try:
        from scipy import stats
    except ImportError as error:
        raise ImportError("Statistical helpers require: pip install -r requirements-optional.txt") from error
    return stats


def _values(values, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) < 2 or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain at least two finite scalar observations")
    return array


def welch_t_test(first, second) -> dict[str, float]:
    """Welch test for independently justified observations (prefer run aggregates)."""
    stats = _stats()
    result = stats.ttest_ind(_values(first, "first"), _values(second, "second"), equal_var=False)
    return {"statistic": float(result.statistic), "p_value": float(result.pvalue)}


def pearson_correlation(first, second) -> dict[str, float]:
    stats = _stats()
    x, y = _values(first, "first"), _values(second, "second")
    if x.shape != y.shape or x.std() == 0 or y.std() == 0:
        raise ValueError("Pearson inputs must have equal lengths and nonzero variance")
    result = stats.pearsonr(x, y)
    return {"correlation": float(result.statistic), "p_value": float(result.pvalue)}


def matched_seed_effect(fault_by_seed: dict[int, float], control_by_seed: dict[int, float]) -> dict[str, float]:
    """Estimate paired effects from one aggregate per independent seed/run."""
    stats = _stats()
    if fault_by_seed.keys() != control_by_seed.keys():
        raise ValueError("Fault and control seed sets must match exactly")
    seeds = sorted(fault_by_seed)
    differences = _values([fault_by_seed[s] - control_by_seed[s] for s in seeds], "paired differences")
    mean = float(differences.mean())
    stderr = float(differences.std(ddof=1) / np.sqrt(len(differences)))
    margin = float(stats.t.ppf(0.975, df=len(differences) - 1)) * stderr
    return {"n_pairs": len(differences), "mean_effect": mean, "standard_error": stderr,
            "ci95_low": mean - margin, "ci95_high": mean + margin}
