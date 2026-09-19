"""Explainable signature ranking using only observed features."""
from .features import FeatureSet
from .models import Candidate, Diagnosis


def diagnose(features: FeatureSet) -> Diagnosis:
    """Return heuristic evidence scores, never calibrated probabilities."""
    signals = features.signals
    temp, pressure, flow, current = (signals[n] for n in
                                    ("temperature_c", "pressure_mtorr", "gas_flow_sccm", "pump_current_a"))
    near_temp, near_pressure, near_flow, near_current = (abs(v["z"]) <= 3
                                                        for v in (temp, pressure, flow, current))
    rules = {
        "VACUUM_LEAK": (
            (pressure["z"] > 3, 0.45, "pressure z > 3"),
            (pressure["slope"] > 0.25, 0.35, "pressure slope > 0.25 mTorr/s"),
            (0 < current["slope"] < 0.012, 0.10, "0 < current slope < 0.012 A/s"),
            (near_temp and near_flow, 0.10, "temperature and flow near baseline")),
        "COOLING_FAILURE": (
            (temp["z"] > 3, 0.45, "temperature z > 3"),
            (temp["slope"] > 0.35, 0.35, "temperature slope > 0.35 C/s"),
            (near_pressure, 0.10, "pressure near baseline"),
            (near_flow, 0.10, "flow near baseline")),
        "GAS_FLOW_DRIFT": (
            (flow["z"] < -3, 0.45, "flow z < -3"),
            (flow["slope"] < -0.30, 0.35, "flow slope < -0.30 sccm/s"),
            (near_temp, 0.10, "temperature near baseline"),
            (near_current, 0.10, "pump current near baseline")),
        "PUMP_DEGRADATION": (
            (current["z"] > 3, 0.35, "current z > 3"),
            (current["slope"] > 0.015, 0.35, "current slope > 0.015 A/s"),
            (0.05 <= pressure["slope"] <= 0.20, 0.20, "pressure slope in [0.05, 0.20] mTorr/s"),
            (near_temp and near_flow, 0.10, "temperature and flow near baseline")),
    }
    candidates = tuple(sorted((Candidate(cause, round(sum(weight for met, weight, _ in entries if met), 6),
                                         tuple(text for met, _, text in entries if met))
                               for cause, entries in rules.items()), key=lambda c: (-c.score, c.cause)))
    top = candidates[0]
    ambiguous = top.score >= 0.65 and top.score - candidates[1].score <= 0.10 + 1e-9
    decision = "UNKNOWN" if top.score < 0.65 else ("AMBIGUOUS" if ambiguous else top.cause)
    return Diagnosis(decision, candidates, ambiguous, signals)
