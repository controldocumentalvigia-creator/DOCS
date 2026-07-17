from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import unicodedata

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Control documental semanal", page_icon="📋", layout="wide")

VEHICLE_DOCS = {
    "V. SOAT": "SOAT",
    "V. TECNO": "Revisión técnico-mecánica",
    "T.O VEN": "Tarjeta de operación",
    "V. INSPECC": "Inspección",
    "V. P. CONTR": "Póliza contractual",
    "V. P. EXTRA": "Póliza extracontractual",
}
DRIVER_DOCS = {
    "V. LICENCIA": "Licencia de conducción",
    "V. EXAMEN": "Examen médico",
    "V. SEG SOC": "Seguridad social",
    "V. VACUNAS": "Vacunas",
    "V. FORMATO": "Formato",
    "V. CTROL IN": "Control interno",
    "V. MECANIC": "Mecánica básica",
    "V. PRIM AUX": "Primeros auxilios",
    "V. CMDPC": "CMDPC",
}
STATUS_ORDER = ["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER", "VIGENTE", "SIN FECHA"]
STATUS_ICON = {
    "VENCIDO": "🔴",
    "ALERTA SEMANAL": "🟠",
    "PRÓXIMO A VENCER": "🟡",
    "VIGENTE": "🟢",
    "SIN FECHA": "⚪",
}


def clean_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.strip().upper())


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [clean_name(c) for c in out.columns]
    return out


def classify(days: object, has_date: bool) -> str:
    if not has_date:
        return "SIN FECHA"
    days = int(days)
    if days < 0:
        return "VENCIDO"
    if days <= 7:
        return "ALERTA SEMANAL"
    if days <= 30:
        return "PRÓXIMO A VENCER"
    return "VIGENTE"


def prepare_alerts(
    df: pd.DataFrame,
    docs: dict[str, str],
    reference_date: pd.Timestamp,
    entity_type: str,
) -> pd.DataFrame:
    df = normalize_columns(df)
    resolved_docs = {clean_name(k): v for k, v in docs.items()}
    available_docs = {col: label for col, label in resolved_docs.items() if col in df.columns}
    if not available_docs:
        raise ValueError("No se encontraron las columnas documentales esperadas.")

    id_col = "PLACA" if entity_type == "Vehículo" else "CC/NIT"
    name_col = "POSEEDOR.1" if entity_type == "Vehículo" else "NOMBRE CO"
    state_col = "ESTADO" if entity_type == "Vehículo" else "ESTADO CO"
    phone_col = "CELULAR" if "CELULAR" in df.columns else None

    base_cols = [c for c in [id_col, name_col, state_col, phone_col, "TIPO VEHIC", "MARCA", "AFILIADORA"] if c]
    base_cols = [c for c in base_cols if c in df.columns]
    long = df[base_cols + list(available_docs)].melt(
        id_vars=base_cols,
        value_vars=list(available_docs),
        var_name="COLUMNA_DOCUMENTO",
        value_name="FECHA_VENCIMIENTO",
    )
    long["DOCUMENTO"] = long["COLUMNA_DOCUMENTO"].map(available_docs)
    long["FECHA_VENCIMIENTO"] = pd.to_datetime(long["FECHA_VENCIMIENTO"], errors="coerce").dt.normalize()
    long["DIAS_RESTANTES"] = (long["FECHA_VENCIMIENTO"] - reference_date).dt.days
    long["CLASIFICACION"] = [
        classify(days, pd.notna(date))
        for days, date in zip(long["DIAS_RESTANTES"], long["FECHA_VENCIMIENTO"])
    ]
    long["TIPO_REGISTRO"] = entity_type
    long["IDENTIFICACION"] = long[id_col].astype("string").fillna("SIN IDENTIFICACIÓN").str.strip()
    long["RESPONSABLE"] = long.get(name_col, pd.Series(index=long.index, dtype="string")).astype("string").fillna("SIN RESPONSABLE").str.strip()
    long["ESTADO_REGISTRO"] = long.get(state_col, pd.Series(index=long.index, dtype="string")).astype("string").fillna("SIN ESTADO").str.strip()
    long["CELULAR_CONTACTO"] = (
        long[phone_col].astype("string").str.replace(r"\.0$", "", regex=True).fillna("")
        if phone_col and phone_col in long.columns else ""
    )
    return long


def summary_by_entity(alerts: pd.DataFrame) -> pd.DataFrame:
    relevant = alerts[alerts["CLASIFICACION"].isin(["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER", "SIN FECHA"])].copy()
    if relevant.empty:
        return pd.DataFrame()
    grouped = (
        relevant.groupby(["TIPO_REGISTRO", "IDENTIFICACION", "RESPONSABLE", "ESTADO_REGISTRO", "CELULAR_CONTACTO"], dropna=False)
        .agg(
            DOCUMENTOS_EN_ALERTA=("DOCUMENTO", "count"),
            VENCIDOS=("CLASIFICACION", lambda s: (s == "VENCIDO").sum()),
            ALERTA_7_DIAS=("CLASIFICACION", lambda s: (s == "ALERTA SEMANAL").sum()),
            PROXIMOS_30_DIAS=("CLASIFICACION", lambda s: (s == "PRÓXIMO A VENCER").sum()),
            SIN_FECHA=("CLASIFICACION", lambda s: (s == "SIN FECHA").sum()),
            PRIMER_VENCIMIENTO=("FECHA_VENCIMIENTO", "min"),
        )
        .reset_index()
    )
    grouped["PRIORIDAD"] = grouped.apply(
        lambda r: "CRÍTICA" if r["VENCIDOS"] > 0 else ("ALTA" if r["ALERTA_7_DIAS"] > 0 else "MEDIA"), axis=1
    )
    return grouped.sort_values(["VENCIDOS", "ALERTA_7_DIAS", "PROXIMOS_30_DIAS"], ascending=False)


def build_messages(alerts: pd.DataFrame, reference_date: pd.Timestamp) -> pd.DataFrame:
    rows = []
    weekly = alerts[alerts["CLASIFICACION"].isin(["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER"])].copy()
    for keys, group in weekly.groupby(["TIPO_REGISTRO", "IDENTIFICACION", "RESPONSABLE", "ESTADO_REGISTRO", "CELULAR_CONTACTO"], dropna=False):
        entity_type, identification, responsible, record_state, phone = keys
        lines = []
        for _, row in group.sort_values(["CLASIFICACION", "FECHA_VENCIMIENTO"]).iterrows():
            date_text = row["FECHA_VENCIMIENTO"].strftime("%d/%m/%Y") if pd.notna(row["FECHA_VENCIMIENTO"]) else "sin fecha"
            days = row["DIAS_RESTANTES"]
            if row["CLASIFICACION"] == "VENCIDO":
                detail = f"vencido hace {abs(int(days))} día(s)"
            elif row["CLASIFICACION"] == "ALERTA SEMANAL":
                detail = "vence hoy" if int(days) == 0 else f"vence en {int(days)} día(s)"
            else:
                detail = f"vence en {int(days)} día(s)"
            lines.append(f"• {row['DOCUMENTO']}: {date_text} ({detail})")
        intro = f"Buen día, {responsible}." if responsible and responsible != "SIN RESPONSABLE" else "Buen día."
        subject = f"la placa {identification}" if entity_type == "Vehículo" else f"el conductor identificado con {identification}"
        message = (
            f"{intro}\n\nMi nombre es Carolina Rodríguez, Coordinadora de Vigía Servicio Especial.\n\n"
            f"El presente mensaje tiene como finalidad generar una alerta sobre el estado documental de {subject}.\n"
            f"Estado actual del registro: {record_state}.\n\n"
            + "\n".join(lines)
            + "\n\nAgradecemos realizar la renovación o actualización de los documentos relacionados y enviarlos a la mayor brevedad posible para actualizar nuestro sistema.\n\n"
            + "Esta solicitud se realiza para mantener actualizado el control documental y evitar novedades, bloqueos o restricciones que puedan afectar la operación.\n\nMuchas gracias por su colaboración."
        )
        rows.append({
            "TIPO_REGISTRO": entity_type,
            "IDENTIFICACION": identification,
            "RESPONSABLE": responsible,
            "ESTADO_REGISTRO": record_state,
            "CELULAR": phone,
            "FECHA_GENERACION": reference_date.strftime("%d/%m/%Y"),
            "MENSAJE": message,
        })
    return pd.DataFrame(rows)


def to_excel(alerts: pd.DataFrame, summary: pd.DataFrame, messages: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        alerts.to_excel(writer, sheet_name="Detalle alertas", index=False)
        summary.to_excel(writer, sheet_name="Resumen responsables", index=False)
        messages.to_excel(writer, sheet_name="Mensajes", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                max_length = min(max((len(str(cell.value)) if cell.value is not None else 0) for cell in column) + 2, 45)
                sheet.column_dimensions[column[0].column_letter].width = max(12, max_length)
    return output.getvalue()


@st.cache_data(show_spinner=False)
def load_workbook(file_bytes: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    book = pd.ExcelFile(BytesIO(file_bytes))
    normalized_sheets = {clean_name(s): s for s in book.sheet_names}
    vehicle_sheet = normalized_sheets.get("VEHICULOS")
    driver_sheet = normalized_sheets.get("CONDUCTORES")
    if not vehicle_sheet or not driver_sheet:
        raise ValueError("El archivo debe contener las hojas 'vehiculos' y 'conductores'.")
    return pd.read_excel(BytesIO(file_bytes), sheet_name=vehicle_sheet), pd.read_excel(BytesIO(file_bytes), sheet_name=driver_sheet)


st.title("📋 Dashboard semanal de control documental")
st.caption("Control de vencimientos de vehículos y conductores, con alertas descargables y mensajes semanales.")

with st.sidebar:
    st.header("Configuración")
    uploaded = st.file_uploader("Cargar archivo Excel", type=["xlsx", "xls"])
    reference_date = pd.Timestamp(st.date_input("Fecha de corte", value=pd.Timestamp.today().date())).normalize()
    operational_status_filter = st.multiselect(
        "Estados de registro incluidos",
        ["ACTIVO", "SUSPENDIDO", "INACTIVO", "SIN ESTADO"],
        default=["ACTIVO", "SUSPENDIDO", "INACTIVO"],
        help="Puedes analizar todos los estados o seleccionar únicamente los que necesites para el seguimiento semanal.",
    )
    selected_statuses = st.multiselect(
        "Clasificaciones",
        STATUS_ORDER,
        default=["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER", "SIN FECHA"],
    )

if uploaded is None:
    st.info("Carga el archivo de control documental para iniciar el análisis.")
    st.stop()

try:
    vehicles, drivers = load_workbook(uploaded.getvalue())
    vehicle_alerts = prepare_alerts(vehicles, VEHICLE_DOCS, reference_date, "Vehículo")
    driver_alerts = prepare_alerts(drivers, DRIVER_DOCS, reference_date, "Conductor")
    all_alerts = pd.concat([vehicle_alerts, driver_alerts], ignore_index=True)
except Exception as exc:
    st.error(f"No fue posible procesar el archivo: {exc}")
    st.stop()

all_alerts["ESTADO_NORMALIZADO"] = all_alerts["ESTADO_REGISTRO"].map(clean_name)
if operational_status_filter:
    all_alerts = all_alerts[all_alerts["ESTADO_NORMALIZADO"].isin(operational_status_filter)]

filtered = all_alerts[all_alerts["CLASIFICACION"].isin(selected_statuses)].copy()

entity_options = sorted(filtered["TIPO_REGISTRO"].dropna().unique())
state_options = sorted(filtered["ESTADO_REGISTRO"].dropna().unique())
col1, col2, col3 = st.columns(3)
with col1:
    entity_filter = st.multiselect("Tipo de registro", entity_options, default=entity_options)
with col2:
    state_filter = st.multiselect("Estado operativo", state_options, default=state_options)
with col3:
    search = st.text_input("Buscar placa, cédula o nombre")

filtered = filtered[filtered["TIPO_REGISTRO"].isin(entity_filter) & filtered["ESTADO_REGISTRO"].isin(state_filter)]
if search.strip():
    needle = clean_name(search)
    filtered = filtered[
        filtered["IDENTIFICACION"].map(clean_name).str.contains(needle, na=False)
        | filtered["RESPONSABLE"].map(clean_name).str.contains(needle, na=False)
    ]

metrics = {
    "Vencidos": int((filtered["CLASIFICACION"] == "VENCIDO").sum()),
    "Vencen en 7 días": int((filtered["CLASIFICACION"] == "ALERTA SEMANAL").sum()),
    "Vencen en 30 días": int((filtered["CLASIFICACION"] == "PRÓXIMO A VENCER").sum()),
    "Sin fecha": int((filtered["CLASIFICACION"] == "SIN FECHA").sum()),
    "Responsables con alerta": int(filtered["IDENTIFICACION"].nunique()),
}
metric_cols = st.columns(5)
for col, (label, value) in zip(metric_cols, metrics.items()):
    col.metric(label, f"{value:,}".replace(",", "."))

summary = summary_by_entity(filtered)
messages = build_messages(filtered, reference_date)

chart_data = (
    filtered.groupby(["DOCUMENTO", "CLASIFICACION"], observed=True).size().reset_index(name="CANTIDAD")
)
if not chart_data.empty:
    fig = px.bar(
        chart_data,
        x="DOCUMENTO",
        y="CANTIDAD",
        color="CLASIFICACION",
        barmode="group",
        category_orders={"CLASIFICACION": STATUS_ORDER},
        title="Alertas por tipo de documento",
    )
    fig.update_layout(xaxis_title="Documento", yaxis_title="Cantidad", legend_title="Clasificación")
    st.plotly_chart(fig, use_container_width=True)

vehicle_tab, driver_tab, messages_tab, detail_tab = st.tabs([
    "🚐 Vehículos por placa", "👤 Conductores", "💬 Mensajes semanales", "🔎 Detalle completo"
])

with vehicle_tab:
    vehicle_view = summary[summary["TIPO_REGISTRO"] == "Vehículo"] if not summary.empty else summary
    st.dataframe(vehicle_view, use_container_width=True, hide_index=True)

with driver_tab:
    driver_view = summary[summary["TIPO_REGISTRO"] == "Conductor"] if not summary.empty else summary
    st.dataframe(driver_view, use_container_width=True, hide_index=True)

with messages_tab:
    st.caption("Los vehículos usan el celular disponible en la hoja. La hoja de conductores no contiene una columna de teléfono.")
    st.dataframe(messages, use_container_width=True, hide_index=True, column_config={"MENSAJE": st.column_config.TextColumn(width="large")})
    if not messages.empty:
        selected_id = st.selectbox("Vista previa del mensaje", messages["IDENTIFICACION"].astype(str).tolist())
        preview = messages.loc[messages["IDENTIFICACION"].astype(str) == str(selected_id), "MENSAJE"].iloc[0]
        st.text_area("Mensaje listo para WhatsApp", preview, height=260)

with detail_tab:
    display_cols = [
        "TIPO_REGISTRO", "IDENTIFICACION", "RESPONSABLE", "ESTADO_REGISTRO", "DOCUMENTO",
        "FECHA_VENCIMIENTO", "DIAS_RESTANTES", "CLASIFICACION", "CELULAR_CONTACTO"
    ]
    detail = filtered[display_cols].sort_values(["CLASIFICACION", "DIAS_RESTANTES"], na_position="last")
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config={"FECHA_VENCIMIENTO": st.column_config.DateColumn(format="DD/MM/YYYY")},
    )

st.divider()
excel_bytes = to_excel(filtered, summary, messages)
st.download_button(
    "⬇️ Descargar reporte semanal en Excel",
    data=excel_bytes,
    file_name=f"alertas_documentales_{reference_date.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
