"""Offline Streamlit dashboard. Run with: streamlit run app.py."""
from importlib.util import find_spec
from math import floor
import time

import pandas as pd
import streamlit as st

from virtual_equipment.config import project_root
from virtual_equipment.models import FaultType, SIGNALS
from virtual_equipment.monitor import EquipmentMonitor
from virtual_equipment.storage import Storage


def initialize() -> None:
    if "storage" not in st.session_state:
        st.session_state.storage = Storage(project_root() / "data" / "equipment.db")
    if "monitor" in st.session_state and not isinstance(st.session_state.monitor, EquipmentMonitor):
        # File watching may reload model classes while session objects survive.
        # End the old run so mixed class identities cannot disable the controls.
        st.session_state.monitor.finish()
        del st.session_state["monitor"]
    if "monitor" not in st.session_state:
        st.session_state.monitor = EquipmentMonitor(42, st.session_state.storage)
        st.session_state.last_tick_at = time.monotonic()


def sidebar_controls() -> None:
    monitor = st.session_state.monitor
    with st.sidebar:
        st.title("Equipment controls")
        seed = int(st.number_input("Seed for next simulation", min_value=0, max_value=2**31 - 1, value=42))
        selected = st.selectbox("Fault type", [fault.value for fault in FaultType])
        duration = int(st.number_input("Fault duration (seconds)", min_value=1, max_value=300, value=30))
        monitor.interlock.auto_recovery = st.toggle("Auto Recovery", value=True)
        if st.button("Inject Fault", type="primary", width="stretch"):
            try:
                monitor.inject(FaultType(selected), duration)
                st.toast(f"Injected {selected} for {duration} simulated seconds")
            except ValueError as error:
                st.error(str(error))
        left, right = st.columns(2)
        if left.button("ACK", width="stretch"):
            try:
                monitor.acknowledge()
                st.toast("Acknowledged. The interlock latch is unchanged.")
            except ValueError as error:
                st.error(str(error))
        if right.button("Manual Reset", width="stretch"):
            try:
                monitor.manual_reset()
                st.toast("Safe dwell satisfied; recovery started")
            except ValueError as error:
                st.error(str(error))
        st.caption("Injection becomes available after 60 normal samples. Reset Simulation starts a new run using the seed above.")
        if st.button("Complete Run", width="stretch"):
            monitor.finish()
            st.toast("Run completed and saved")
        if st.button("Reset Simulation", width="stretch"):
            monitor.finish()
            st.session_state.monitor = EquipmentMonitor(seed, st.session_state.storage,
                                                         auto_recovery=monitor.interlock.auto_recovery)
            st.session_state.last_tick_at = time.monotonic()
            st.session_state.pop("export_data", None)
            st.rerun()
        if st.button("Export Run CSV", width="stretch"):
            st.session_state.export_data = (monitor.run_id, st.session_state.storage.export_csv(monitor.run_id))
        if "export_data" in st.session_state:
            run_id, data = st.session_state.export_data
            st.download_button("Download run CSV", data, file_name=f"{run_id}.csv", mime="text/csv", width="stretch")
        st.divider()
        st.caption("CPU only · SQLite · 1 Hz · Offline runtime")
        st.caption("Optional ML available (not enabled)" if find_spec("sklearn") else "ML module not installed")


def show_diagnosis(monitor: EquipmentMonitor) -> None:
    st.subheader("Root-cause evidence")
    diagnosis = monitor.last_diagnosis
    if diagnosis is None:
        st.info("No diagnosis yet. RCA runs when eligible telemetry triggers an anomaly alarm.")
        return
    st.caption(f"Latest evaluated sample: {monitor.last_diagnosis_sample}. Scores are heuristic evidence scores, not probabilities.")
    first, second = diagnosis.candidates[:2]
    left, right = st.columns(2)
    left.metric("Top-1 candidate", first.cause.replace("_", " "), f"Evidence score {first.score:.2f}", delta_color="off")
    right.metric("Top-2 candidate", second.cause.replace("_", " "), f"Evidence score {second.score:.2f}", delta_color="off")
    if diagnosis.decision == "UNKNOWN":
        st.warning("UNKNOWN — the top evidence score is below 0.65.")
    elif diagnosis.ambiguous:
        st.warning("AMBIGUOUS — the top two scores differ by 0.10 or less.")
    else:
        st.success(f"Candidate: {diagnosis.decision}")
    if monitor.interlock.latched:
        st.caption("Showing the last diagnosis before safety action. Diagnosis is paused during hold and ramp.")
    st.dataframe(pd.DataFrame([{"Candidate": c.cause, "Score": c.score,
                                "Matched evidence": "; ".join(c.evidence)} for c in diagnosis.candidates]),
                 hide_index=True, width="stretch")
    with st.expander("Observed feature values (10 samples)"):
        st.dataframe(pd.DataFrame(diagnosis.feature_values).T, width="stretch")


def show_trends(monitor: EquipmentMonitor) -> None:
    st.subheader("Sensor trends · last 120 seconds")
    if not monitor.samples:
        return
    frame = pd.DataFrame([sample.to_dict() for sample in monitor.samples]).set_index("sample_idx")
    labels = ("Temperature · °C", "Pressure · mTorr", "Gas flow · sccm", "RF power · W", "Pump current · A")
    tabs = st.tabs(list(labels))
    for name, label, tab in zip(SIGNALS, labels, tabs):
        with tab:
            chart = pd.DataFrame({"Actual": frame[name]})
            if monitor.ready:
                low, high = monitor.spc.limits(name)
                chart["SPC UCL"], chart["SPC LCL"] = high, low
                chart["EWMA"] = pd.Series({tick.sample.sample_idx: tick.ewma.get(name)
                                           for tick in monitor.ticks if tick.monitoring_eligible})
            series = chart.reset_index().melt(id_vars="sample_idx", var_name="Series", value_name="Value")
            st.vega_lite_chart(series, {
                "mark": {"type": "line", "strokeWidth": 2},
                "encoding": {
                    "x": {"field": "sample_idx", "type": "quantitative", "title": "Simulated second",
                          "scale": {"domain": [int(frame.index.min()),
                                               max(int(frame.index.min()) + 1, int(frame.index.max()))],
                                    "nice": False}},
                    "y": {"field": "Value", "type": "quantitative", "title": label,
                          "scale": {"zero": False}},
                    "color": {"field": "Series", "type": "nominal",
                              "scale": {"domain": ["Actual", "EWMA", "SPC UCL", "SPC LCL"],
                                        "range": ["#55d6be", "#ffbc66", "#94a3b8", "#c2cede"]},
                              "legend": {"orient": "bottom"}},
                    "strokeDash": {"field": "Series", "type": "nominal",
                                   "scale": {"domain": ["Actual", "EWMA", "SPC UCL", "SPC LCL"],
                                             "range": [[], [], [5, 4], [5, 4]]}, "legend": None},
                    "tooltip": [{"field": "sample_idx", "type": "quantitative", "title": "Second"},
                                {"field": "Series", "type": "nominal"},
                                {"field": "Value", "type": "quantitative", "format": ".3f"}],
                },
            }, height=280, width="stretch")
    st.caption("SPC bands use the initial 60 normal samples. EWMA is hidden while safety commands inhibit anomaly monitoring.")


@st.fragment(run_every=1.0)
def live_region() -> None:
    monitor = st.session_state.monitor
    now = time.monotonic()
    # Widget/full-script reruns must not add extra simulated seconds.
    if not monitor.finished and now - st.session_state.last_tick_at >= 1.0:
        monitor.step()
        st.session_state.last_tick_at += max(1, floor(now - st.session_state.last_tick_at))
    st.caption(f"RUN {monitor.run_id}")
    header = st.columns(3)
    header[0].metric("Elapsed", f"{monitor.simulator.sample_idx} s")
    header[1].metric("Equipment state", monitor.interlock.state.value)
    header[2].metric("Interlock", "LATCHED" if monitor.interlock.latched else "CLEAR")
    if monitor.finished:
        st.info("Run completed. Export its CSV or reset to start another simulation.")
    elif not monitor.ready:
        st.progress(min(monitor.simulator.sample_idx / 60, 1.0), text="Learning the normal baseline · 60 seconds")
    else:
        st.caption("Monitoring active" if not monitor.interlock.latched else
                   f"Safe samples: {monitor.interlock.safe_count}/10 · RF command {monitor.interlock.commands.rf_power_w:g} W · Gas command {monitor.interlock.commands.gas_flow_sccm:g} sccm")
    if monitor.interlock.latched:
        st.error(f"Latched trip: {monitor.interlock.trip_reason}")
    metrics = st.columns(5)
    if monitor.samples:
        sample = monitor.samples[-1]
        for column, label, value, unit in zip(metrics,
                ("Temperature", "Pressure", "Gas Flow", "RF Power", "Pump Current"),
                (sample.temperature_c, sample.pressure_mtorr, sample.gas_flow_sccm, sample.rf_power_w, sample.pump_current_a),
                ("°C", "mTorr", "sccm", "W", "A")):
            column.metric(f"{label} ({unit})", f"{value:.2f}")
    show_trends(monitor)
    show_diagnosis(monitor)
    st.subheader("Events & alarms")
    events = st.session_state.storage.events(monitor.run_id, 30)
    if events.empty:
        st.caption("No events recorded yet.")
    else:
        st.dataframe(events[["sample_idx", "event_type", "severity", "source", "message"]],
                     hide_index=True, width="stretch")


def history_panel() -> None:
    with st.expander("Persistent run history & export"):
        st.button("Refresh History")
        storage = st.session_state.storage
        runs = storage.runs()
        st.dataframe(runs, hide_index=True, width="stretch")
        if not runs.empty:
            selected = st.selectbox("Saved run", runs.run_id.tolist())
            st.download_button("Download saved run CSV", storage.export_csv(selected),
                               file_name=f"{selected}.csv", mime="text/csv")
            st.dataframe(storage.events(selected), hide_index=True, width="stretch")
            with st.expander("Saved diagnoses"):
                st.dataframe(storage.diagnoses(selected), hide_index=True, width="stretch")
        st.caption("A browser refresh creates a new live run. Earlier history remains in SQLite; interrupted runs may have no end timestamp.")


def main() -> None:
    st.set_page_config(page_title="Virtual Equipment Monitor", page_icon="◈", layout="wide")
    initialize()
    st.title("Virtual Semiconductor Equipment Monitor")
    st.caption("ANOMALY MONITORING & EXPLAINABLE FAULT DIAGNOSIS")
    st.info("Synthetic demonstration only. Values and signatures are not real equipment limits, TSMC recipes, fab specifications, or validated physics.")
    sidebar_controls()
    live_region()
    history_panel()


if __name__ == "__main__":
    main()
