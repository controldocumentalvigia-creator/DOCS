from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import re
import unicodedata

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Alertas documentales semanales", page_icon="📄", layout="wide")

VEHICLE_DOCS = {
    "V. SOAT": "SOAT",
    "V. TECNO": "Revisión tecnomecánica",
    "T.O VEN": "Tarjeta de operación",
    "V. INSPECC": "Inspección del vehículo",
    "V. P. CONTR": "Póliza contractual",
    "V. P. EXTRA": "Póliza extracontractual",
    "V. POLIZA T": "Póliza todo riesgo",
}

DRIVER_DOCS = {
    "V. LICENCIA": "Licencia de conducción",
    "V. EXAMEN": "Examen médico",
    "V. SEG SOC": "Seguridad social",
    "V. VACUNAS": "Vacunas",
    "V. FORMATO": "Formato documental",
    "V. CTROL IN": "Control interno",
    "V. MECANIC": "Curso de mecánica básica",
    "V. PRIM AUX": "Curso de primeros auxilios",
    "V. CMDPC": "Curso de manejo defensivo",
}


def normalize(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.strip().upper())


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize(col): col for col in df.columns}
    for candidate in candidates:
        key = normalize(candidate)
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        key = normalize(candidate)
        for normalized_name, original in normalized.items():
            if key in normalized_name or normalized_name in key:
                return original
    return None


def map_document_columns(df: pd.DataFrame, configured: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for expected, label in configured.items():
        found = find_column(df, [expected])
        if found:
            result[found] = label
    return result


def safe_text(value: object, fallback: str = "SIN DATO") -> str:
    if pd.isna(value):
        return fallback
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or fallback


def classify(expiry: object, today: date, weekly_days: int, upcoming_days: int) -> tuple[str, int | None, pd.Timestamp | None]:
    parsed = pd.to_datetime(expiry, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return "SIN FECHA", None, None
    parsed = pd.Timestamp(parsed).normalize()
    days = (parsed.date() - today).days
    if days < 0:
        return "VENCIDO", days, parsed
    if days <= weekly_days:
        return "ALERTA SEMANAL", days, parsed
    if days <= upcoming_days:
        return "PRÓXIMO A VENCER", days, parsed
    return "VIGENTE", days, parsed


def status_line(document: str, status: str, days: int | None, expiry: pd.Timestamp | None) -> str:
    formatted = expiry.strftime("%d/%m/%Y") if expiry is not None else "fecha no registrada"
    if status == "VENCIDO":
        elapsed = abs(days or 0)
        wording = "venció hoy" if elapsed == 0 else f"vencido hace {elapsed} día{'s' if elapsed != 1 else ''}"
        return f"• {document}: {wording} ({formatted})."
    if status == "ALERTA SEMANAL":
        if days == 0:
            wording = "vence hoy"
        elif days == 1:
            wording = "vence mañana"
        else:
            wording = f"vence en {days} días"
        return f"• {document}: {wording} ({formatted})."
    if status == "PRÓXIMO A VENCER":
        return f"• {document}: próximo a vencer en {days} días ({formatted})."
    return f"• {document}: sin fecha de vencimiento registrada."


def build_message(entity_type: str, entity_name: str, details: list[dict]) -> str:
    groups = {
        "VENCIDO": [],
        "ALERTA SEMANAL": [],
        "PRÓXIMO A VENCER": [],
        "SIN FECHA": [],
    }
    for item in details:
        if item["Estado"] in groups:
            groups[item["Estado"]].append(
                status_line(item["Documento"], item["Estado"], item["Días"], item["Fecha vencimiento"])
            )

    if entity_type == "Vehículo":
        intro = (
            f"El presente mensaje tiene como finalidad generar una alerta sobre el estado documental "
            f"del vehículo con placa *{entity_name}*."
        )
    else:
        intro = (
            f"El presente mensaje tiene como finalidad generar una alerta sobre su estado documental como conductor(a): "
            f"*{entity_name}*."
        )

    sections = []
    titles = [
        ("VENCIDO", "🔴 *DOCUMENTOS VENCIDOS*"),
        ("ALERTA SEMANAL", "🟠 *ALERTAS DE VENCIMIENTO (0 A 7 DÍAS)*"),
        ("PRÓXIMO A VENCER", "🟡 *PRÓXIMOS A VENCER*"),
        ("SIN FECHA", "⚪ *DOCUMENTOS SIN FECHA REGISTRADA*"),
    ]
    for key, title in titles:
        if groups[key]:
            sections.append(title + "\n" + "\n".join(groups[key]))

    return (
        "📢 *VIGÍA SERVICIO ESPECIAL S.A.S.*\n\n"
        "Hola, mucho gusto.\n\n"
        "Mi nombre es *Carolina Rodríguez*, Coordinadora de Vigía Servicio Especial.\n\n"
        f"{intro}\n\n"
        + "\n\n".join(sections)
        + "\n\nAgradecemos realizar la renovación o actualización de los documentos relacionados y enviarlos "
          "a la mayor brevedad posible para actualizar nuestro sistema.\n\n"
          "Esta solicitud se realiza para mantener actualizado el control documental y evitar novedades, "
          "bloqueos o restricciones que puedan afectar la operación.\n\n"
          "Muchas gracias por su colaboración.\n\n"
          "*Carolina Rodríguez*\n"
          "Coordinadora de Operaciones\n"
          "*Vigía Servicio Especial S.A.S.*"
    )


def process_sheet(
    df: pd.DataFrame,
    entity_type: str,
    id_candidates: list[str],
    name_candidates: list[str],
    phone_candidates: list[str],
    configured_docs: dict[str, str],
    today: date,
    weekly_days: int,
    upcoming_days: int,
    include_no_date: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    id_col = find_column(df, id_candidates)
    name_col = find_column(df, name_candidates)
    phone_col = find_column(df, phone_candidates)
    state_col = find_column(df, ["ESTADO", "ESTADO CO"])
    doc_columns = map_document_columns(df, configured_docs)

    if not id_col and not name_col:
        raise ValueError(f"No se encontró una columna identificadora para {entity_type.lower()}.")
    if not doc_columns:
        raise ValueError(f"No se encontraron columnas documentales en la hoja de {entity_type.lower()}.")

    detail_rows = []
    message_rows = []

    for _, row in df.iterrows():
        entity_id = safe_text(row[id_col], "") if id_col else ""
        entity_name = safe_text(row[name_col], "") if name_col else ""
        label = entity_id if entity_type == "Vehículo" else (entity_name or entity_id)
        if not label:
            continue

        details = []
        for col, document_name in doc_columns.items():
            status, days, expiry = classify(row[col], today, weekly_days, upcoming_days)
            if status == "VIGENTE" or (status == "SIN FECHA" and not include_no_date):
                continue
            item = {
                "Tipo": entity_type,
                "Identificación": entity_id,
                "Nombre / Placa": label,
                "Estado registro": safe_text(row[state_col], "") if state_col else "",
                "Documento": document_name,
                "Columna origen": col,
                "Fecha vencimiento": expiry,
                "Días": days,
                "Estado": status,
                "Celular": safe_text(row[phone_col], "") if phone_col else "",
            }
            details.append(item)
            detail_rows.append(item)

        if details:
            counts = pd.Series([x["Estado"] for x in details]).value_counts().to_dict()
            message_rows.append({
                "Tipo": entity_type,
                "Identificación": entity_id,
                "Nombre / Placa": label,
                "Celular": safe_text(row[phone_col], "") if phone_col else "",
                "Vencidos": counts.get("VENCIDO", 0),
                "Alertas semanales": counts.get("ALERTA SEMANAL", 0),
                "Próximos": counts.get("PRÓXIMO A VENCER", 0),
                "Sin fecha": counts.get("SIN FECHA", 0),
                "Mensaje WhatsApp": build_message(entity_type, label, details),
            })

    return pd.DataFrame(detail_rows), pd.DataFrame(message_rows)


def to_excel(details: pd.DataFrame, vehicle_messages: pd.DataFrame, driver_messages: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        details.to_excel(writer, index=False, sheet_name="Detalle alertas")
        vehicle_messages.to_excel(writer, index=False, sheet_name="Mensajes vehículos")
        driver_messages.to_excel(writer, index=False, sheet_name="Mensajes conductores")
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = cell.font.copy(bold=True)
            for col_cells in sheet.columns:
                max_len = min(max(len(str(c.value or "")) for c in col_cells) + 2, 60)
                sheet.column_dimensions[col_cells[0].column_letter].width = max(12, max_len)
    return output.getvalue()


st.title("📄 Control documental y mensajes semanales")
st.caption("Carga cada semana el archivo actualizado. El sistema genera un mensaje por vehículo y por conductor, listo para copiar y pegar en WhatsApp.")

with st.sidebar:
    st.header("Configuración semanal")
    uploaded = st.file_uploader("Archivo Excel", type=["xlsx", "xls"])
    reference_date = st.date_input("Fecha de revisión", value=date.today(), format="DD/MM/YYYY")
    weekly_days = st.number_input("Días para alerta semanal", min_value=1, max_value=15, value=7)
    upcoming_days = st.number_input("Días para próximo a vencer", min_value=8, max_value=120, value=45)
    include_no_date = st.checkbox("Incluir documentos sin fecha", value=False)
    only_active = st.checkbox("Mostrar únicamente registros activos", value=True)

if uploaded is None:
    st.info("Carga el archivo de control documental para generar las alertas y mensajes.")
    st.stop()

try:
    excel = pd.ExcelFile(uploaded)
    sheet_lookup = {normalize(name): name for name in excel.sheet_names}
    vehicle_sheet = next((original for key, original in sheet_lookup.items() if "VEHIC" in key), None)
    driver_sheet = next((original for key, original in sheet_lookup.items() if "CONDUCT" in key), None)
    if not vehicle_sheet or not driver_sheet:
        st.error("El archivo debe contener una hoja de vehículos y una hoja de conductores.")
        st.stop()

    vehicles = pd.read_excel(excel, sheet_name=vehicle_sheet)
    drivers = pd.read_excel(excel, sheet_name=driver_sheet)

    if only_active:
        vehicle_state = find_column(vehicles, ["ESTADO"])
        driver_state = find_column(drivers, ["ESTADO CO", "ESTADO"])
        if vehicle_state:
            vehicles = vehicles[vehicles[vehicle_state].astype(str).map(normalize).eq("ACTIVO")]
        if driver_state:
            drivers = drivers[drivers[driver_state].astype(str).map(normalize).eq("ACTIVO")]

    vehicle_details, vehicle_messages = process_sheet(
        vehicles, "Vehículo", ["PLACA"], ["POSEEDOR.1", "POSEEDOR"],
        ["CELULAR", "TELEFONO", "WHATSAPP", "MOVIL"], VEHICLE_DOCS,
        reference_date, int(weekly_days), int(upcoming_days), include_no_date,
    )
    driver_details, driver_messages = process_sheet(
        drivers, "Conductor", ["CC/NIT", "CEDULA", "DOCUMENTO"], ["NOMBRE CO", "NOMBRE", "CONDUCTOR"],
        ["CELULAR", "TELEFONO", "WHATSAPP", "MOVIL"], DRIVER_DOCS,
        reference_date, int(weekly_days), int(upcoming_days), include_no_date,
    )
    all_details = pd.concat([vehicle_details, driver_details], ignore_index=True)

except Exception as exc:
    st.exception(exc)
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Documentos vencidos", int((all_details["Estado"] == "VENCIDO").sum()) if not all_details.empty else 0)
c2.metric("Alertas semanales", int((all_details["Estado"] == "ALERTA SEMANAL").sum()) if not all_details.empty else 0)
c3.metric("Próximos a vencer", int((all_details["Estado"] == "PRÓXIMO A VENCER").sum()) if not all_details.empty else 0)
c4.metric("Mensajes generados", len(vehicle_messages) + len(driver_messages))

if all_details.empty:
    st.success("No se encontraron documentos vencidos ni próximos a vencer con la configuración seleccionada.")
    st.stop()

st.subheader("Resumen de alertas")
summary = all_details.groupby(["Tipo", "Estado"]).size().reset_index(name="Cantidad")
st.bar_chart(summary, x="Estado", y="Cantidad", color="Tipo")

vehicle_tab, driver_tab, detail_tab = st.tabs(["🚐 Mensajes vehículos", "👤 Mensajes conductores", "📊 Detalle consolidado"])

with vehicle_tab:
    st.caption("Cada bloque de mensaje incluye el botón de copiar incorporado por Streamlit.")
    if vehicle_messages.empty:
        st.success("No hay alertas de vehículos para esta semana.")
    else:
        search_vehicle = st.text_input("Buscar placa", key="vehicle_search").strip().upper()
        shown = vehicle_messages
        if search_vehicle:
            shown = shown[shown["Nombre / Placa"].astype(str).str.upper().str.contains(search_vehicle, na=False)]
        for _, item in shown.iterrows():
            title = f"Placa {item['Nombre / Placa']}"
            if item["Celular"]:
                title += f" · Celular: {item['Celular']}"
            with st.expander(title, expanded=False):
                st.code(item["Mensaje WhatsApp"], language=None)

with driver_tab:
    if driver_messages.empty:
        st.success("No hay alertas de conductores para esta semana.")
    else:
        if "Celular" in driver_messages and driver_messages["Celular"].replace("", pd.NA).isna().all():
            st.warning("La hoja de conductores no contiene una columna de celular. Los mensajes están listos para copiar, pero debes buscar el contacto manualmente. Agrega una columna CELULAR para automatizarlo.")
        search_driver = st.text_input("Buscar conductor o cédula", key="driver_search").strip().upper()
        shown = driver_messages
        if search_driver:
            mask = (
                shown["Nombre / Placa"].astype(str).str.upper().str.contains(search_driver, na=False)
                | shown["Identificación"].astype(str).str.upper().str.contains(search_driver, na=False)
            )
            shown = shown[mask]
        for _, item in shown.iterrows():
            title = f"{item['Nombre / Placa']} · CC/NIT {item['Identificación']}"
            if item["Celular"]:
                title += f" · Celular: {item['Celular']}"
            with st.expander(title, expanded=False):
                st.code(item["Mensaje WhatsApp"], language=None)

with detail_tab:
    status_filter = st.multiselect(
        "Filtrar estado documental",
        ["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER", "SIN FECHA"],
        default=["VENCIDO", "ALERTA SEMANAL", "PRÓXIMO A VENCER"],
    )
    detail_view = all_details[all_details["Estado"].isin(status_filter)].copy()
    st.dataframe(detail_view, use_container_width=True, hide_index=True)

excel_bytes = to_excel(all_details, vehicle_messages, driver_messages)
st.download_button(
    "⬇️ Descargar reporte semanal con mensajes",
    data=excel_bytes,
    file_name=f"alertas_documentales_{reference_date.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
