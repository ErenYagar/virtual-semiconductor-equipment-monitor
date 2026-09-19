"""Optional IsolationForest; importing this module never imports sklearn."""
import numpy as np

from .models import DetectionResult, Severity


class MLDetector:
    def __init__(self):
        self.model = None
        self.training_count = 0
        self.feature_count = 0

    def fit(self, windows, labels) -> "MLDetector":
        """Use only explicitly curated NORMAL windows; keep held-out runs separate."""
        try:
            from sklearn.ensemble import IsolationForest
        except ImportError as error:
            raise ImportError("ML requires: pip install -r requirements-optional.txt") from error
        values = np.asarray(windows, dtype=float)
        labels = np.asarray(labels)
        if values.ndim != 2 or labels.ndim != 1 or len(values) != len(labels) or not np.isfinite(values).all():
            raise ValueError("Provide a finite feature matrix and one label per window")
        normal = values[labels == "NORMAL"]
        if len(normal) < 10 or values.shape[1] < 1:
            raise ValueError("At least ten NORMAL feature windows are required")
        self.model = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
        self.model.fit(normal)
        self.training_count, self.feature_count = normal.shape
        return self

    def detect(self, window) -> DetectionResult:
        if self.model is None:
            raise ValueError("Fit on NORMAL feature windows before detection")
        values = np.asarray(window, dtype=float)
        if values.shape != (self.feature_count,) or not np.isfinite(values).all():
            raise ValueError("Expected one finite window matching the fitted feature count")
        score = -float(self.model.decision_function(values.reshape(1, -1))[0])
        alarm = score > 0
        return DetectionResult("IsolationForest", "feature_window", alarm,
                               Severity.WARNING if alarm else Severity.INFO, score,
                               "Uncalibrated anomaly score; positive values are anomalous")
