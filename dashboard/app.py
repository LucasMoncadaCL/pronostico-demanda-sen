"""Public UI demonstration using synthetic data only."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from data_access import daily_metrics, load_demo_data


st.set_page_config(
    page_title="Pronóstico SEN · demostración sintética",
    page_icon="⚡",
    layout="wide",
)

data = load_demo_data()
daily = daily_metrics(data)
all_errors = {
    "Benchmark": data["benchmark_prediction"] - data["observed"],
    "Candidato": data["candidate_prediction"] - data["observed"],
}

st.title("Explorador de pronósticos · SEN de Chile")
st.info(
    "Demostración pública con datos 100 % sintéticos. Las curvas, fechas y métricas de esta aplicación "
    "no corresponden a observaciones ni resultados del CEN."
)
st.caption("La evaluación real y sus datos fuente se conservan en el archivo científico privado.")

view = st.radio(
    "Vista",
    ["Resultado general", "Días especiales", "Errores", "Sensibilidad"],
    horizontal=True,
)

if view == "Resultado general":
    st.subheader("Comparación de ejemplo")
    left, right = st.columns(2)
    for column, method, error in [
        (left, "Benchmark", all_errors["Benchmark"]),
        (right, "Extensión ilustrativa", all_errors["Candidato"]),
    ]:
        with column:
            st.metric(f"MAE sintético · {method}", f"{error.abs().mean():,.1f}")
            st.metric(f"RMSE sintético · {method}", f"{(error.pow(2).mean() ** 0.5):,.1f}")
    st.caption("Indicadores calculados en la serie ficticia generada por el código; no representan el experimento 2025.")
    compare = go.Figure(
        [
            go.Bar(name="Benchmark", x=["Serie sintética"], y=[all_errors["Benchmark"].abs().mean()]),
            go.Bar(name="Extensión ilustrativa", x=["Serie sintética"], y=[all_errors["Candidato"].abs().mean()]),
        ]
    )
    compare.update_layout(barmode="group", yaxis_title="MAE sintético", height=360)
    st.plotly_chart(compare, use_container_width=True, config={"displaylogo": False})

elif view == "Días especiales":
    st.subheader("Ejemplos de fechas sintéticas")
    special = data[data["is_demo_event"]]["target_date"].drop_duplicates().sort_values()
    if special.empty:
        st.write("No hay fechas especiales sintéticas en este ejemplo.")
    else:
        selected = st.selectbox("Fecha de ejemplo", special.tolist(), format_func=lambda date: date.strftime("%d %b %Y"))
        profile = data[data["target_date"] == selected]
        frame = profile.melt(
            id_vars="period_index",
            value_vars=["observed", "benchmark_prediction", "candidate_prediction"],
            var_name="series",
            value_name="value",
        )
        frame["series"] = frame["series"].map(
            {"observed": "Observada sintética", "benchmark_prediction": "Benchmark sintético", "candidate_prediction": "Extensión sintética"}
        )
        fig = px.line(frame, x="period_index", y="value", color="series", markers=True, labels={"period_index": "Índice de período", "value": "Valor sintético", "series": "Serie"})
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
        st.caption("Fecha ficticia generada para demostrar el selector y el gráfico; no es un feriado chileno ni un dato real.")

elif view == "Errores":
    st.subheader("Exploración de perfiles y errores sintéticos")
    dates = daily.sort_values("benchmark_mae", ascending=False)["target_date"].tolist()
    selected = st.selectbox("Fecha de ejemplo", dates[:30], format_func=lambda date: date.strftime("%d %b %Y"))
    profile = data[data["target_date"] == selected]
    frame = profile.melt(
        id_vars="period_index",
        value_vars=["observed", "benchmark_prediction", "candidate_prediction"],
        var_name="series",
        value_name="value",
    )
    frame["series"] = frame["series"].map(
        {"observed": "Observada sintética", "benchmark_prediction": "Benchmark sintético", "candidate_prediction": "Extensión sintética"}
    )
    st.plotly_chart(px.line(frame, x="period_index", y="value", color="series", labels={"period_index": "Índice de período", "value": "Valor sintético", "series": "Serie"}), use_container_width=True, config={"displaylogo": False})
    st.caption("Las anomalías de este ejemplo son deterministas y sintéticas; no representan eventos del SEN.")

else:
    st.subheader("Sensibilidad ilustrativa")
    # Scenario filters are UI examples only and are not inferential analyses.
    no_special = data[~data["is_demo_event"]]
    compare_rows = []
    for label, frame in [("Año sintético completo", data), ("Sin fechas especiales sintéticas", no_special)]:
        for name, prediction in [("Benchmark", "benchmark_prediction"), ("Extensión ilustrativa", "candidate_prediction")]:
            error = frame[prediction] - frame["observed"]
            compare_rows.append({"Escenario": label, "Método": name, "MAE sintético": error.abs().mean()})
    fig = px.bar(
        pd.DataFrame(compare_rows),
        x="Escenario",
        y="MAE sintético",
        color="Método",
        barmode="group",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    st.caption("Comparaciones de muestra únicamente; no son intervalos de confianza ni análisis de robustez del estudio real.")

with st.expander("Metodología del estudio real y límites de esta demostración"):
    st.markdown(
        """
        El estudio real compara un benchmark de medias por día de semana e índice de período con una regla que,
        en feriados nacionales hábiles, sustituye el perfil por el promedio histórico de domingo. La demostración
        pública no carga esas observaciones ni reproduce sus curvas. El resumen agregado del estudio está en el README.
        El resultado no demuestra utilidad operacional ni estabilidad entre años.
        """
    )
