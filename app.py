"""Interfaz PREDWEEM Digital Twin — Bordenave."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from predweem_twin.assimilation import assimilate_observations
from predweem_twin.core import ModelParameters, PracticalANNModel, run_predweem
from predweem_twin.observations import prepare_observations, read_observation_file
from predweem_twin.scenarios import apply_scenario
from predweem_twin.state import build_twin_snapshot, milestone_dates
from predweem_twin.storage import TwinStore
from predweem_twin.weather import fetch_open_meteo, read_weather_file, weather_source_label


BASE = Path(__file__).parent
st.set_page_config(page_title="PREDWEEM Digital Twin", page_icon="🌱", layout="wide")

st.markdown(
    """
    <style>
      .stApp {background: linear-gradient(180deg,#f5f8f3 0%,#eef3ed 100%);}
      [data-testid="stSidebar"] {background:#11291f;}
      [data-testid="stSidebar"] * {color:#f5faf7;}
      div[data-testid="stMetric"] {background:white;border:1px solid #dfe8e1;
        border-radius:16px;padding:18px;box-shadow:0 8px 22px rgba(20,50,35,.06)}
      .hero {padding:22px 26px;border-radius:20px;color:white;margin-bottom:18px;
        background:linear-gradient(120deg,#173f2e,#287653 68%,#74a45b);}
      .eyebrow {letter-spacing:.14em;text-transform:uppercase;font-size:.76rem;opacity:.82}
      .hero h1 {margin:.15rem 0 .25rem;font-size:2.15rem}
      .hero p {margin:0;max-width:900px;opacity:.9}
      .status-pill {display:inline-block;padding:5px 11px;border-radius:999px;
        background:#d9f1dd;color:#174a2d;font-weight:700;font-size:.8rem}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def load_model():
    return PracticalANNModel.from_directory(BASE / "models")


def load_store():
    """Crea el acceso SQLite con el esquema vigente.

    No se almacena en cache_resource: durante una actualización en caliente,
    Streamlit podría conservar una instancia creada con una versión anterior
    de TwinStore y ocultar métodos o migraciones recién incorporados.
    """
    return TwinStore(BASE / "data" / "twin_state.db")


@st.cache_data(ttl=3600, show_spinner=False)
def load_open_meteo(latitude, longitude, start_date):
    return fetch_open_meteo(latitude, longitude, start_date)


def trajectory_chart(df, observations, as_of):
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Bar(
            x=df["Fecha"],
            y=df["EMERREL_TWIN"] * 100,
            name="Flujo diario Twin",
            marker_color="#8ebf69",
            opacity=0.55,
        ),
        secondary_y=True,
    )
    figure.add_trace(
        go.Scatter(
            x=df["Fecha"],
            y=df["EMERAC_NORMALIZADA"] * 100,
            name="PREDWEEM base",
            line=dict(color="#83938b", width=2, dash="dot"),
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=df["Fecha"],
            y=df["EMERAC_TWIN"] * 100,
            name="Estado actualizado",
            line=dict(color="#155d3e", width=4),
            fill="tozeroy",
            fillcolor="rgba(66,137,87,.10)",
        ),
        secondary_y=False,
    )
    if observations is not None and not observations.empty:
        figure.add_trace(
            go.Scatter(
                x=observations["Fecha"],
                y=observations["Observado"] * 100,
                name="Conteo de campo",
                mode="markers",
                marker=dict(color="#df5b3f", size=11, line=dict(color="white", width=2)),
            ),
            secondary_y=False,
        )
    figure.add_vline(x=pd.Timestamp(as_of).timestamp() * 1000, line_color="#162f25", line_dash="dash")
    figure.update_yaxes(title_text="Emergencia acumulada (%)", range=[0, 105], secondary_y=False)
    figure.update_yaxes(title_text="Flujo diario (%)", rangemode="tozero", secondary_y=True)
    figure.update_layout(
        height=470,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.12),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.15,
    )
    return figure


st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">PREDWEEM by Guillermo R. Chantre</div>
      <h1>Gemelo Digital · Lolium Bordenave</h1>
      <p>Estado vivo del lote, actualizado con meteorología y observaciones de campo,
      con proyección a 7 días y simulación de escenarios.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Configuración del gemelo")
    site_id = st.text_input("Identificador del lote", "Bordenave-01")
    latitude = st.number_input("Latitud", value=-37.761671, format="%.6f")
    longitude = st.number_input("Longitud", value=-63.083717, format="%.6f")
    source_option = st.radio(
        "Meteorología",
        ["INTA + ECMWF operativa", "Open-Meteo", "Cargar archivo"],
    )
    uploaded_weather = None
    if source_option == "Cargar archivo":
        uploaded_weather = st.file_uploader("CSV o Excel", type=["csv", "xlsx", "xls"])
    coverage = st.slider("Cobertura de rastrojo (%)", 0, 100, 50, 5)
    w_max = st.slider("Agua superficial Wmax (mm)", 10.0, 36.0, 18.8, 0.5)
    model_uncertainty = st.slider("Incertidumbre del modelo", 0.03, 0.30, 0.12, 0.01)
    st.caption("La asimilación modifica el estado estimado, no recalibra la ANN.")

try:
    if source_option == "Open-Meteo":
        weather = load_open_meteo(latitude, longitude, f"{date.today().year}-01-01")
    elif source_option == "Cargar archivo" and uploaded_weather is not None:
        weather = read_weather_file(uploaded_weather)
    else:
        weather = read_weather_file(BASE / "data" / "meteo_daily.csv")
except Exception as error:
    st.error(f"No fue posible cargar la meteorología: {error}")
    st.stop()

weather_dates = pd.to_datetime(weather["Fecha"] if "Fecha" in weather else weather["FECHA"], errors="coerce")
min_date = weather_dates.min().date()
max_date = weather_dates.max().date()
default_date = min(max(date.today(), min_date), max_date)
as_of = st.sidebar.date_input("Fecha del estado", value=default_date, min_value=min_date, max_value=max_date)

parameters = ModelParameters(
    cobertura_pct=float(coverage),
    w_max=float(w_max),
    latitud=float(latitude),
    longitud=float(longitude),
)
model = load_model()
store = load_store()
base_trajectory = run_predweem(weather, model, parameters)
observations = store.observations(site_id)
twin_trajectory, assimilation_audit = assimilate_observations(
    base_trajectory,
    observations,
    model_uncertainty=model_uncertainty,
)
source_label = weather_source_label(weather)
snapshot = build_twin_snapshot(
    twin_trajectory,
    site_id,
    as_of,
    source_label,
    len(assimilation_audit),
)
milestones = milestone_dates(twin_trajectory)

st.markdown(
    f'<span class="status-pill">● ACTUALIZADO AL {pd.Timestamp(snapshot["as_of"]).strftime("%d/%m/%Y")}</span>',
    unsafe_allow_html=True,
)

metric_columns = st.columns(5)
metric_columns[0].metric("Emergencia estimada", f'{snapshot["emergence"]:.0%}')
metric_columns[1].metric("Emergencia remanente", f'{snapshot["remaining"]:.0%}')
metric_columns[2].metric("Riesgo próximos 7 días", snapshot["risk_7d"], f'+{snapshot["increment_7d"]:.1%}')
metric_columns[3].metric("Agua superficial", f'{snapshot["soil_water"]:.1f} mm', f'{snapshot["soil_water_fraction"]:.0%} Wmax')
metric_columns[4].metric("TT desde primer pico", f'{snapshot["thermal_time"]:.0f} °Cd', f'{parameters.tt_limite:.0f} °Cd límite')

tab_state, tab_observations, tab_scenarios, tab_audit = st.tabs(
    ["Estado del lote", "Observaciones", "Escenarios", "Trazabilidad"]
)

with tab_state:
    st.plotly_chart(trajectory_chart(twin_trajectory, observations, as_of), width="stretch")
    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Lectura agronómica")
        if snapshot["next_cohort_start"]:
            cohort = (
                f'{pd.Timestamp(snapshot["next_cohort_start"]).strftime("%d/%m")}–'
                f'{pd.Timestamp(snapshot["next_cohort_end"]).strftime("%d/%m")}'
            )
        else:
            cohort = "No detectada en el horizonte"
        st.write(
            f'El gemelo estima **{snapshot["emergence"]:.0%}** de la emergencia potencial y '
            f'**{snapshot["remaining"]:.0%}** remanente. La próxima cohorte probable es **{cohort}**. '
            f'La termoinhibición está **{"activa" if snapshot["thermoinhibited"] else "inactiva"}**.'
        )
        st.info(
            "La salida es soporte para decisión. Debe interpretarse junto con el monitoreo "
            "del lote y el criterio del profesional responsable."
        )
    with right:
        st.subheader("Hitos proyectados")
        milestone_table = pd.DataFrame(
            {
                "Hito": ["25 %", "50 %", "75 %", "95 %"],
                "Fecha": [milestones["d25"], milestones["d50"], milestones["d75"], milestones["d95"]],
            }
        )
        st.dataframe(milestone_table, hide_index=True, width="stretch")

with tab_observations:
    st.subheader("Cerrar el circuito con el campo")
    st.markdown("#### Carga de observaciones")
    st.caption(
        "Admite FECHA + PLM2 (flujo por intervalo) o FECHA + "
        "EMERGENCIA_ACUMULADA/OBSERVADO (0–1 o 0–100 %). También reconoce "
        "tres repeticiones (1, 2, 3) y una columna media por m²."
    )
    uploaded_observations = st.file_uploader(
        "Archivo de emergencia observada",
        type=["xlsx", "xls", "csv", "tsv"],
        key="observed_emergence_upload",
    )
    upload_columns = st.columns([1.5, 1])
    upload_mode_label = upload_columns[0].selectbox(
        "Formato de los valores",
        [
            "Detectar automáticamente",
            "Flujo por intervalo (PLM2)",
            "Acumulada (%)",
        ],
    )
    upload_uncertainty_pct = upload_columns[1].number_input(
        "Incertidumbre si no hay repeticiones (%)",
        min_value=1.0,
        max_value=30.0,
        value=8.0,
        step=1.0,
    )
    mode_map = {
        "Detectar automáticamente": "auto",
        "Flujo por intervalo (PLM2)": "flujo",
        "Acumulada (%)": "acumulado",
    }
    if uploaded_observations is not None:
        try:
            raw_observations, file_metadata = read_observation_file(uploaded_observations)
            prepared_observations, import_metadata = prepare_observations(
                raw_observations,
                base_trajectory,
                mode=mode_map[upload_mode_label],
                uncertainty=upload_uncertainty_pct / 100.0,
                source_name=(
                    f'{file_metadata["archivo"]} · hoja {file_metadata["hoja"]}'
                ),
            )
            st.success(
                f'{import_metadata["filas"]} observaciones válidas. '
                f'Modo detectado: {import_metadata["modo"]}.'
            )
            if import_metadata["modo"] == "flujo":
                has_repetitions = "n_repeticiones" in import_metadata
                summary_columns = st.columns(4 if has_repetitions else 3)
                summary_columns[0].metric(
                    "Total observado",
                    f'{import_metadata["total_observado_plm2"]:.1f} plantas/m²',
                )
                summary_columns[1].metric(
                    "Potencial estacional usado",
                    f'{import_metadata["potencial_estacional_plm2"]:.1f} plantas/m²',
                )
                summary_columns[2].metric(
                    "Progreso simulado en última fecha",
                    f'{import_metadata["progreso_modelo_ultima_fecha"]:.0%}',
                )
                if has_repetitions:
                    summary_columns[3].metric(
                        "Repeticiones",
                        f'{import_metadata["n_repeticiones"]} por fecha',
                    )
                st.caption(import_metadata["metodo_normalizacion"].capitalize() + ".")
                if has_repetitions:
                    factor = import_metadata["factor_conversion_repeticiones"]
                    area = import_metadata["area_cuadrante_inferida_m2"]
                    st.info(
                        f"Repeticiones detectadas automáticamente. Factor de conversión "
                        f"a m²: ×{factor:.2f} (área inferida: {area:.2f} m²). "
                        f"Incertidumbre: {import_metadata['metodo_incertidumbre']} "
                        f"({import_metadata['incertidumbre_minima']:.1%}–"
                        f"{import_metadata['incertidumbre_maxima']:.1%})."
                    )

            preview_columns = [
                "Fecha",
                "Valor_original",
                "Unidad_original",
                "Observado",
                "Incertidumbre",
            ]
            if "Acumulado_PLM2" in prepared_observations:
                preview_columns.insert(2, "Acumulado_PLM2")
            repetition_preview = [
                column
                for column in prepared_observations.columns
                if column.startswith("Repeticion_")
                and column.endswith("_original")
            ]
            if repetition_preview:
                preview_columns[2:2] = repetition_preview + ["EE_repeticiones_PLM2"]
            st.dataframe(
                prepared_observations[preview_columns],
                hide_index=True,
                width="stretch",
                column_config={
                    "Observado": st.column_config.NumberColumn(
                        "Emergencia acumulada", format="percent"
                    ),
                    "Incertidumbre": st.column_config.NumberColumn(
                        "Incertidumbre", format="percent"
                    ),
                },
            )
            if st.button(
                "Incorporar observaciones al gemelo",
                type="primary",
                key="save_observation_upload",
            ):
                store.upsert_observations(site_id, prepared_observations)
                st.success(
                    f'Se incorporaron {len(prepared_observations)} fechas al lote {site_id}.'
                )
                st.rerun()
        except Exception as error:
            st.error(f"No fue posible procesar las observaciones: {error}")

    st.divider()
    st.markdown("#### Registro manual")
    st.caption("Registre emergencia acumulada normalizada (0–100 %). Un registro por fecha y lote.")
    with st.form("observation_form", clear_on_submit=True):
        columns = st.columns([1, 1, 1, 2])
        observation_date = columns[0].date_input("Fecha", value=as_of, key="obs_date")
        observation_pct = columns[1].number_input("Emergencia acumulada (%)", 0.0, 100.0, 50.0, 1.0)
        observation_uncertainty = columns[2].number_input("Incertidumbre (%)", 1.0, 30.0, 8.0, 1.0)
        observation_note = columns[3].text_input("Nota", placeholder="Método, cuadrantes, condición del lote")
        submitted = st.form_submit_button("Guardar y actualizar gemelo", type="primary")
    if submitted:
        store.upsert_observation(
            site_id,
            observation_date,
            observation_pct / 100.0,
            observation_uncertainty / 100.0,
            observation_note,
            raw_value=observation_pct,
            raw_unit="% acumulado",
            source_name="Registro manual",
        )
        st.success("Observación registrada. El estado se actualizará con la nueva evidencia.")
        st.rerun()
    st.markdown("#### Observaciones guardadas")
    st.dataframe(
        observations,
        hide_index=True,
        width="stretch",
        column_config={
            "Observado": st.column_config.NumberColumn(
                "Emergencia acumulada", format="percent"
            ),
            "Incertidumbre": st.column_config.NumberColumn(
                "Incertidumbre", format="percent"
            ),
        },
    )

with tab_scenarios:
    st.subheader("¿Qué pasa si…?")
    scenario_columns = st.columns(3)
    extra_rain = scenario_columns[0].slider("Lluvia adicional (mm)", 0, 80, 30, 5)
    rain_days = scenario_columns[1].slider("Distribuida en días", 1, 7, 3)
    temperature_delta = scenario_columns[2].slider("Cambio de temperatura (°C)", -5.0, 5.0, 0.0, 0.5)
    scenario_weather = apply_scenario(weather, as_of, extra_rain, rain_days, temperature_delta)
    scenario_base = run_predweem(scenario_weather, model, parameters)
    scenario_twin, _ = assimilate_observations(
        scenario_base,
        observations,
        model_uncertainty=model_uncertainty,
    )
    scenario_snapshot = build_twin_snapshot(
        scenario_twin, site_id, as_of, "Escenario", len(assimilation_audit)
    )
    scenario_milestones = milestone_dates(scenario_twin)
    comparison = pd.DataFrame(
        {
            "Indicador": ["Incremento próximos 7 días", "Riesgo", "d50", "d75", "d95"],
            "Escenario base": [
                f'{snapshot["increment_7d"]:.1%}', snapshot["risk_7d"],
                milestones["d50"], milestones["d75"], milestones["d95"],
            ],
            "Escenario simulado": [
                f'{scenario_snapshot["increment_7d"]:.1%}', scenario_snapshot["risk_7d"],
                scenario_milestones["d50"], scenario_milestones["d75"], scenario_milestones["d95"],
            ],
        }
    )
    st.dataframe(comparison, hide_index=True, width="stretch")
    comparison_figure = go.Figure()
    comparison_figure.add_trace(go.Scatter(x=twin_trajectory["Fecha"], y=twin_trajectory["EMERAC_TWIN"] * 100, name="Base", line=dict(color="#155d3e", width=4)))
    comparison_figure.add_trace(go.Scatter(x=scenario_twin["Fecha"], y=scenario_twin["EMERAC_TWIN"] * 100, name="Escenario", line=dict(color="#df7f34", width=3, dash="dash")))
    comparison_figure.update_layout(height=390, yaxis_title="Emergencia acumulada (%)", hovermode="x unified", plot_bgcolor="white", margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(comparison_figure, width="stretch")
    st.caption("Los escenarios son contrafactuales exploratorios; no modifican el estado guardado del lote.")

with tab_audit:
    st.subheader("Trazabilidad científica")
    audit_summary = pd.DataFrame(
        {
            "Variable": ["Lote", "Fuente meteorológica", "Cobertura", "Wmax", "Incertidumbre modelo", "Observaciones asimiladas"],
            "Valor": [site_id, source_label, f"{coverage} %", f"{w_max:.1f} mm", f"{model_uncertainty:.0%}", str(len(assimilation_audit))],
        }
    )
    st.dataframe(audit_summary, hide_index=True, width="stretch")
    if assimilation_audit.empty:
        st.info("Aún no hay observaciones de campo asimiladas. La curva Twin coincide con PREDWEEM base.")
    else:
        st.dataframe(assimilation_audit, hide_index=True, width="stretch")
    export_columns = [
        "Fecha", "TMAX", "TMIN", "Prec", "EMERREL", "EMERAC_NORMALIZADA",
        "EMERREL_TWIN", "EMERAC_TWIN", "W_superficial", "Humedad_Relativa",
        "Termoinhibida", "TT_DESDE_PICO",
    ]
    st.download_button(
        "Descargar trayectoria auditable (CSV)",
        twin_trajectory[export_columns].to_csv(index=False).encode("utf-8"),
        f"{site_id}_predweem_twin.csv",
        "text/csv",
    )
