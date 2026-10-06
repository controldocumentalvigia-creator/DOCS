
import io
import re
import unicodedata
from typing import Iterable

import numpy as np
import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="RCN Data Factory",
    page_icon="🏭",
    layout="wide",
)

st.markdown("""
<style>
html,body,[class*="css"]{font-family:"Segoe UI",Arial,sans-serif;color:#1F1F1F!important}
.block-container{padding-top:1rem;padding-left:1.2rem;padding-right:1.2rem}
h1,h2,h3{color:#003B75!important;font-weight:800!important}
.kpi{background:#fff;border:1px solid #DDE3EE;border-radius:12px;padding:10px 12px;min-height:88px;
box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:8px}
.kpi-title{color:#003B75;font-size:.72rem;font-weight:800;text-transform:uppercase}
.kpi-value{color:#101828;font-size:1.12rem;font-weight:800;line-height:1.2;margin-top:4px}
.kpi-note{font-size:.72rem;color:#667085;margin-top:4px}
[data-testid="stDataFrame"] div[role="columnheader"]{
background-color:#003B75!important;color:#fff!important;font-weight:800!important;
justify-content:center!important;text-align:center!important}
[data-testid="stDataFrame"] div[role="gridcell"]{
justify-content:center!important;text-align:center!important;color:#1F1F1F!important}
</style>
""", unsafe_allow_html=True)


def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(texto))
        if not unicodedata.combining(c)
    )


def normalizar_columna(valor) -> str:
    texto = sin_acentos(str(valor)).upper().strip()
    texto = re.sub(r"[^A-Z0-9]+", "_", texto)
    return texto.strip("_")


def normalizar_texto(valor) -> str:
    if pd.isna(valor):
        return ""
    return sin_acentos(str(valor)).upper().strip()


def normalizar_id(valor) -> str:
    texto = normalizar_texto(valor).replace(" ", "")
    if texto.endswith(".0"):
        texto = texto[:-2]
    invalidos = {"", "NAN", "NONE", "NULL", "0", "-", "SINREMESA", "SIN_REMESA"}
    return "" if texto in invalidos else texto


def convertir_fecha(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, errors="coerce", dayfirst=True)


def convertir_numero(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").fillna(0)
    texto = serie.astype(str).str.upper().str.strip()
    texto = texto.str.replace("COP", "", regex=False)
    texto = texto.str.replace("$", "", regex=False)
    texto = texto.str.replace(" ", "", regex=False)
    tiene_coma = texto.str.contains(",", regex=False)
    texto.loc[tiene_coma] = (
        texto.loc[tiene_coma]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    texto.loc[~tiene_coma] = texto.loc[~tiene_coma].str.replace(",", "", regex=False)
    return pd.to_numeric(texto, errors="coerce").fillna(0)


def buscar_columna(df: pd.DataFrame, candidatos):
    mapa = {normalizar_columna(c): c for c in df.columns}
    for candidato in candidatos:
        clave = normalizar_columna(candidato)
        if clave in mapa:
            return mapa[clave]
    return None


def llave_fecha_orden(fecha, orden) -> str:
    f = pd.to_datetime(fecha, errors="coerce")
    fecha_txt = f.strftime("%Y-%m-%d") if pd.notna(f) else ""
    return f"{fecha_txt}|{normalizar_id(orden)}"


def entero(valor) -> str:
    try:
        return f"{int(round(float(valor))):,}".replace(",", ".")
    except Exception:
        return "0"


def porcentaje(valor) -> str:
    try:
        return f"{float(valor):.2f}%".replace(".", ",")
    except Exception:
        return "0,00%"


def kpi(titulo, valor, nota=""):
    st.markdown(
        f'<div class="kpi"><div class="kpi-title">{titulo}</div>'
        f'<div class="kpi-value">{valor}</div><div class="kpi-note">{nota}</div></div>',
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def leer_mejor_hoja(archivo_bytes: bytes, preferidas: tuple, claves: tuple):
    bio = io.BytesIO(archivo_bytes)
    xls = pd.ExcelFile(bio)
    orden = [h for h in preferidas if h in xls.sheet_names] + [
        h for h in xls.sheet_names if h not in preferidas
    ]
    claves_norm = {normalizar_columna(c) for c in claves}
    mejor_hoja, mejor_df, mejor_puntaje = None, None, -1

    for hoja in orden:
        try:
            bio.seek(0)
            df = pd.read_excel(bio, sheet_name=hoja)
            if df.empty:
                continue
            cols = {normalizar_columna(c) for c in df.columns}
            puntaje = sum(c in cols for c in claves_norm)
            # La preferencia solo desempata; nunca debe ganar una hoja por nombre
            # si otra contiene más columnas clave.
            if puntaje > mejor_puntaje or (puntaje == mejor_puntaje and hoja in preferidas):
                mejor_hoja, mejor_df, mejor_puntaje = hoja, df, puntaje
        except Exception:
            continue

    if mejor_df is None:
        raise ValueError("No se encontró una hoja compatible.")
    return mejor_hoja, mejor_df


def preparar_data(df: pd.DataFrame) -> pd.DataFrame:
    columnas = {
        "fecha": buscar_columna(df, ["Fecha Servicio"]),
        "orden": buscar_columna(
            df,
            [
                "No. Orden Servicio",
                "No.OrdenServicio",
                "No Orden Servicio",
                "NoOrdenServicio",
                "Orden Servicio",
                "SERVICIO",
            ],
        ),
        "estado": buscar_columna(df, ["Estado Servicio"]),
        "centro": buscar_columna(df, ["Centro / Orden Costo"]),
        "modalidad_servicio": buscar_columna(df, ["Modalidad de Servicio"]),
        "vehiculo": buscar_columna(df, ["Tipo de vehículo", "Tipo Vehiculo"]),
        "modalidad": buscar_columna(df, ["Modalidad"]),
        "origen": buscar_columna(df, ["Origen"]),
        "destino": buscar_columna(df, ["Destino"]),
    }
    faltantes = [k for k in ["fecha", "orden", "estado"] if columnas[k] is None]
    if faltantes:
        encabezados = ", ".join(str(c) for c in df.columns[:30])
        raise ValueError(
            f"DATA no contiene columnas obligatorias: {', '.join(faltantes)}. "
            f"Encabezados detectados: {encabezados}"
        )

    out = pd.DataFrame({
        "DATA_FECHA_SERVICIO": convertir_fecha(df[columnas["fecha"]]),
        "DATA_ORDEN_SERVICIO": df[columnas["orden"]].astype(str).str.strip(),
        "DATA_ESTADO_SERVICIO": df[columnas["estado"]].astype(str).str.strip(),
        "DATA_CENTRO_ORDEN_COSTO": df[columnas["centro"]].astype(str).str.strip() if columnas["centro"] else "",
        "DATA_MODALIDAD_SERVICIO": df[columnas["modalidad_servicio"]].astype(str).str.strip() if columnas["modalidad_servicio"] else "",
        "DATA_TIPO_VEHICULO": df[columnas["vehiculo"]].astype(str).str.strip() if columnas["vehiculo"] else "",
        "DATA_MODALIDAD": df[columnas["modalidad"]].astype(str).str.strip() if columnas["modalidad"] else "",
        "DATA_ORIGEN": df[columnas["origen"]].astype(str).str.strip() if columnas["origen"] else "",
        "DATA_DESTINO": df[columnas["destino"]].astype(str).str.strip() if columnas["destino"] else "",
    })
    out = out.dropna(subset=["DATA_FECHA_SERVICIO"]).copy()
    out["LLAVE_DATA_PAT"] = [
        llave_fecha_orden(f, o)
        for f, o in zip(out["DATA_FECHA_SERVICIO"], out["DATA_ORDEN_SERVICIO"])
    ]
    out["DATA_CANCELADO"] = out["DATA_ESTADO_SERVICIO"].apply(
        lambda x: "CANCEL" in normalizar_texto(x)
    )
    return out


def preparar_pat(df: pd.DataFrame) -> pd.DataFrame:
    columnas = {
        "fecha": buscar_columna(df, ["Fecha Servicio"]),
        "orden": buscar_columna(
            df,
            [
                "No. Orden Servicio",
                "No.OrdenServicio",
                "No Orden Servicio",
                "NoOrdenServicio",
                "SERVICIO",
            ],
        ),
        "remesa": buscar_columna(df, ["REMESAS", "REMESA"]),
        "estado": buscar_columna(df, ["Estado"]),
        "centro": buscar_columna(df, ["Centro / Orden Costo"]),
        "modalidad": buscar_columna(df, ["Modalidad"]),
        "modalidad_tarifa": buscar_columna(df, ["Modalidad.1"]),
        "origen": buscar_columna(df, ["ORIGEN"]),
        "destino": buscar_columna(df, ["DESTINO"]),
    }
    faltantes = [k for k in ["fecha", "orden", "remesa", "estado"] if columnas[k] is None]
    if faltantes:
        raise ValueError(f"PAT no contiene columnas obligatorias: {', '.join(faltantes)}")

    out = pd.DataFrame({
        "PAT_FECHA_SERVICIO": convertir_fecha(df[columnas["fecha"]]),
        "PAT_ORDEN_SERVICIO": df[columnas["orden"]].astype(str).str.strip(),
        "PAT_REMESA": df[columnas["remesa"]].astype(str).str.strip(),
        "PAT_ESTADO": df[columnas["estado"]].astype(str).str.strip(),
        "PAT_CENTRO_ORDEN_COSTO": df[columnas["centro"]].astype(str).str.strip() if columnas["centro"] else "",
        "PAT_MODALIDAD": df[columnas["modalidad"]].astype(str).str.strip() if columnas["modalidad"] else "",
        "PAT_MODALIDAD_TARIFA": df[columnas["modalidad_tarifa"]].astype(str).str.strip() if columnas["modalidad_tarifa"] else "",
        "PAT_ORIGEN": df[columnas["origen"]].astype(str).str.strip() if columnas["origen"] else "",
        "PAT_DESTINO": df[columnas["destino"]].astype(str).str.strip() if columnas["destino"] else "",
    })
    out = out.dropna(subset=["PAT_FECHA_SERVICIO"]).copy()
    out["PAT_REMESA_NORM"] = out["PAT_REMESA"].apply(normalizar_id)
    out["LLAVE_DATA_PAT"] = [
        llave_fecha_orden(f, o)
        for f, o in zip(out["PAT_FECHA_SERVICIO"], out["PAT_ORDEN_SERVICIO"])
    ]
    return out


def preparar_trayectos(df: pd.DataFrame) -> pd.DataFrame:
    remesa_col = buscar_columna(df, ["REMESA", "REMESAS", "TRAYECTO"])
    carga_col = buscar_columna(df, ["CARGA", "FECHA SERVICIO", "FECHA R"])
    estado_col = buscar_columna(df, ["ESTADO OP", "ESTADO OPER", "ESTADO OPERATIVO"])
    if not all([remesa_col, carga_col, estado_col]):
        raise ValueError("TRAYECTOS debe contener identificador de remesa/trayecto, CARGA y ESTADO OPER/ESTADO OP.")

    out = df.copy()
    out["ASTRANS_REMESA_NORM"] = out[remesa_col].apply(normalizar_id)
    out["ASTRANS_CARGA_FECHA"] = convertir_fecha(out[carga_col])
    out["ASTRANS_ESTADO_OP_NORM"] = out[estado_col].apply(normalizar_texto)

    vcliente = buscar_columna(out, ["V.CLIENTE", "V CLIENTE"])
    vconduct = buscar_columna(out, ["V.CONDUCT", "V CONDUCT", "V.CONDUCTOR", "V CONDUCTOR"])
    if vcliente:
        out["V_CLIENTE_NUM"] = convertir_numero(out[vcliente])
    else:
        out["V_CLIENTE_NUM"] = 0
    if vconduct:
        out["V_CONDUCT_NUM"] = convertir_numero(out[vconduct])
    else:
        out["V_CONDUCT_NUM"] = 0

    out["MARGEN_CALCULADO"] = out["V_CLIENTE_NUM"] - out["V_CONDUCT_NUM"]
    return out


def primer_valido(serie: pd.Series):
    for valor in serie:
        if pd.notna(valor) and str(valor).strip() != "":
            return valor
    return ""


def unir_unicos(serie: pd.Series):
    valores = []
    for valor in serie:
        if pd.notna(valor):
            txt = str(valor).strip()
            if txt and txt not in valores:
                valores.append(txt)
    return " | ".join(valores)


def consolidar(data: pd.DataFrame, pat: pd.DataFrame, tray: pd.DataFrame):
    """
    Regla histórica RCN:
    1) CRUCE_DATA_PAT conserva TODOS los registros de DATA (base operativa).
    2) DATA -> PAT se cruza por Fecha Servicio + No. Orden Servicio normalizados.
    3) PAT -> ASTRANS se cruza por remesa exacta normalizada, sin restringir por fecha.
    4) BASE_MAESTRA_RCN conserva TODOS los registros de TRAYECTOS (base financiera/ejecutada).
    """

    # PAT puede traer más de un registro para una misma Fecha + Orden.
    # Se consolida solo para evitar multiplicar filas de DATA; NO se borran los duplicados,
    # que se reportan aparte.
    pat_por_llave = (
        pat.groupby("LLAVE_DATA_PAT", as_index=False)
        .agg(
            PAT_REGISTROS_LLAVE=("LLAVE_DATA_PAT", "size"),
            PAT_FECHA_SERVICIO=("PAT_FECHA_SERVICIO", "min"),
            PAT_ORDEN_SERVICIO=("PAT_ORDEN_SERVICIO", unir_unicos),
            PAT_REMESA=("PAT_REMESA", unir_unicos),
            PAT_ESTADO=("PAT_ESTADO", unir_unicos),
            PAT_CENTRO_ORDEN_COSTO=("PAT_CENTRO_ORDEN_COSTO", unir_unicos),
            PAT_MODALIDAD=("PAT_MODALIDAD", unir_unicos),
            PAT_MODALIDAD_TARIFA=("PAT_MODALIDAD_TARIFA", unir_unicos),
            PAT_ORIGEN=("PAT_ORIGEN", unir_unicos),
            PAT_DESTINO=("PAT_DESTINO", unir_unicos),
        )
    )

    # IMPORTANTE: DATA queda a la izquierda. Así enero, febrero, mayo o cualquier mes
    # siguen apareciendo aunque PAT no tenga evidencia para ese periodo.
    cruce_data_pat = data.merge(pat_por_llave, on="LLAVE_DATA_PAT", how="left")
    cruce_data_pat["COINCIDE_DATA_PAT"] = cruce_data_pat["PAT_REGISTROS_LLAVE"].fillna(0).gt(0)
    cruce_data_pat["DIF_DIAS_DATA_PAT"] = (
        cruce_data_pat["PAT_FECHA_SERVICIO"] - cruce_data_pat["DATA_FECHA_SERVICIO"]
    ).dt.days

    # Estado agrupado gerencial: TODO lo que no sea cancelación se considera PROGRAMADO.
    # Conservamos el estado detallado original de DATA sin alterarlo.
    cruce_data_pat["ESTADO_DETALLADO"] = cruce_data_pat["DATA_ESTADO_SERVICIO"]
    cruce_data_pat["ESTADO_AGRUPADO"] = np.where(
        cruce_data_pat["DATA_CANCELADO"], "CANCELADO", "PROGRAMADO"
    )
    cruce_data_pat["ANO_MES"] = cruce_data_pat["DATA_FECHA_SERVICIO"].dt.strftime("%Y-%m")

    # Para ASTRANS, PAT sí se consolida por remesa exacta.
    pat_valid = pat[pat["PAT_REMESA_NORM"].ne("")].copy()
    # Recuperar información DATA a nivel llave antes de agrupar por remesa.
    data_por_llave = (
        data.groupby("LLAVE_DATA_PAT", as_index=False)
        .agg(
            DATA_REGISTROS=("LLAVE_DATA_PAT", "size"),
            DATA_FECHA_SERVICIO=("DATA_FECHA_SERVICIO", "min"),
            DATA_ORDEN_SERVICIO=("DATA_ORDEN_SERVICIO", unir_unicos),
            DATA_ESTADO_SERVICIO=("DATA_ESTADO_SERVICIO", unir_unicos),
            DATA_CENTRO_ORDEN_COSTO=("DATA_CENTRO_ORDEN_COSTO", unir_unicos),
            DATA_MODALIDAD_SERVICIO=("DATA_MODALIDAD_SERVICIO", unir_unicos),
            DATA_TIPO_VEHICULO=("DATA_TIPO_VEHICULO", unir_unicos),
            DATA_MODALIDAD=("DATA_MODALIDAD", unir_unicos),
            DATA_ORIGEN=("DATA_ORIGEN", unir_unicos),
            DATA_DESTINO=("DATA_DESTINO", unir_unicos),
            DATA_CANCELADO=("DATA_CANCELADO", "max"),
        )
    )
    pat_data = pat_valid.merge(data_por_llave, on="LLAVE_DATA_PAT", how="left")
    pat_data["COINCIDE_DATA_PAT"] = pat_data["DATA_REGISTROS"].fillna(0).gt(0)

    pat_remesa = (
        pat_data.groupby("PAT_REMESA_NORM", as_index=False)
        .agg(
            PAT_REGISTROS=("PAT_REMESA_NORM", "size"),
            PAT_FECHA_SERVICIO=("PAT_FECHA_SERVICIO", "min"),
            PAT_FECHA_SERVICIO_MAX=("PAT_FECHA_SERVICIO", "max"),
            PAT_ORDEN_SERVICIO=("PAT_ORDEN_SERVICIO", unir_unicos),
            PAT_REMESA=("PAT_REMESA", primer_valido),
            PAT_ESTADO=("PAT_ESTADO", unir_unicos),
            PAT_CENTRO_ORDEN_COSTO=("PAT_CENTRO_ORDEN_COSTO", unir_unicos),
            PAT_MODALIDAD=("PAT_MODALIDAD", unir_unicos),
            PAT_MODALIDAD_TARIFA=("PAT_MODALIDAD_TARIFA", unir_unicos),
            PAT_ORIGEN=("PAT_ORIGEN", unir_unicos),
            PAT_DESTINO=("PAT_DESTINO", unir_unicos),
            COINCIDE_DATA_PAT=("COINCIDE_DATA_PAT", "max"),
            DATA_FECHA_SERVICIO=("DATA_FECHA_SERVICIO", "min"),
            DATA_ORDEN_SERVICIO=("DATA_ORDEN_SERVICIO", unir_unicos),
            DATA_ESTADO_SERVICIO=("DATA_ESTADO_SERVICIO", unir_unicos),
            DATA_CENTRO_ORDEN_COSTO=("DATA_CENTRO_ORDEN_COSTO", unir_unicos),
            DATA_MODALIDAD_SERVICIO=("DATA_MODALIDAD_SERVICIO", unir_unicos),
            DATA_TIPO_VEHICULO=("DATA_TIPO_VEHICULO", unir_unicos),
            DATA_MODALIDAD=("DATA_MODALIDAD", unir_unicos),
            DATA_ORIGEN=("DATA_ORIGEN", unir_unicos),
            DATA_DESTINO=("DATA_DESTINO", unir_unicos),
            DATA_CANCELADO=("DATA_CANCELADO", "max"),
        )
    )

    consolidado = tray.merge(
        pat_remesa, left_on="ASTRANS_REMESA_NORM", right_on="PAT_REMESA_NORM", how="left"
    )
    consolidado["COINCIDE_REMESA_PAT_ASTRANS"] = consolidado["PAT_REGISTROS"].fillna(0).gt(0)
    consolidado["DIF_DIAS_PAT_ASTRANS"] = (
        consolidado["ASTRANS_CARGA_FECHA"] - consolidado["PAT_FECHA_SERVICIO"]
    ).dt.days
    consolidado["ANO_MES_ASTRANS"] = consolidado["ASTRANS_CARGA_FECHA"].dt.strftime("%Y-%m")

    consolidado["ESTADO_TRAZABILIDAD"] = np.select(
        [
            consolidado["COINCIDE_REMESA_PAT_ASTRANS"] & consolidado["COINCIDE_DATA_PAT"].fillna(False),
            consolidado["COINCIDE_REMESA_PAT_ASTRANS"] & ~consolidado["COINCIDE_DATA_PAT"].fillna(False),
            ~consolidado["COINCIDE_REMESA_PAT_ASTRANS"],
        ],
        [
            "CONCILIADO DATA + PAT + ASTRANS",
            "CONCILIADO PAT + ASTRANS / DATA NO ENCONTRADA",
            "REMESA ASTRANS SIN REGISTRO PAT",
        ],
        default="REVISAR",
    )

    consolidado["RESULTADO_SERVICIO"] = np.select(
        [
            consolidado["DATA_CANCELADO"].fillna(False) & consolidado["COINCIDE_REMESA_PAT_ASTRANS"],
            consolidado["COINCIDE_REMESA_PAT_ASTRANS"],
        ],
        [
            "CANCELADO EN DATA, PERO EJECUTADO CON REMESA",
            "EJECUTADO Y CONCILIADO",
        ],
        default="EJECUTADO EN ASTRANS SIN EVIDENCIA PAT",
    )

    remesas_astrans = set(tray.loc[tray["ASTRANS_REMESA_NORM"].ne(""), "ASTRANS_REMESA_NORM"])
    pat_sin_astrans = pat_remesa[~pat_remesa["PAT_REMESA_NORM"].isin(remesas_astrans)].copy()

    llaves_pat = set(pat["LLAVE_DATA_PAT"])
    data_sin_pat = data[~data["LLAVE_DATA_PAT"].isin(llaves_pat)].copy()

    duplicados_pat = (
        pat[pat["PAT_REMESA_NORM"].ne("")]
        .groupby("PAT_REMESA_NORM", as_index=False).size()
        .rename(columns={"size": "CANTIDAD_PAT"})
    )
    duplicados_pat = duplicados_pat[duplicados_pat["CANTIDAD_PAT"] > 1]

    duplicados_astrans = (
        tray[tray["ASTRANS_REMESA_NORM"].ne("")]
        .groupby("ASTRANS_REMESA_NORM", as_index=False).size()
        .rename(columns={"size": "CANTIDAD_ASTRANS"})
    )
    duplicados_astrans = duplicados_astrans[duplicados_astrans["CANTIDAD_ASTRANS"] > 1]

    return consolidado, cruce_data_pat, pat_sin_astrans, data_sin_pat, duplicados_pat, duplicados_astrans


def crear_excel(resultados: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="dd/mm/yyyy hh:mm") as writer:
        formato_header = writer.book.add_format({
            "bold": True,
            "font_color": "white",
            "bg_color": "#003B75",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
        })

        for nombre, df in resultados.items():
            hoja = nombre[:31]
            df.to_excel(writer, index=False, sheet_name=hoja)
            ws = writer.sheets[hoja]
            ws.freeze_panes(1, 0)
            if len(df.columns):
                ws.autofilter(0, 0, len(df), len(df.columns) - 1)
                for col_idx, col in enumerate(df.columns):
                    ws.write(0, col_idx, col, formato_header)
                    ancho = min(max(len(str(col)) + 3, 14), 32)
                    ws.set_column(col_idx, col_idx, ancho)
    return buffer.getvalue()


st.title("🏭 RCN Data Factory")
st.caption("Consolida históricos DATA, PAT y TRAYECTOS en una Base Maestra RCN.")

with st.sidebar:
    st.header("Cargar históricos")
    f_data = st.file_uploader("DATA histórico", type=["xlsx"], key="data")
    f_pat = st.file_uploader("SERVICIO PAT histórico", type=["xlsx"], key="pat")
    f_tray = st.file_uploader("TRAYECTOS histórico", type=["xlsx"], key="tray")

if not all([f_data, f_pat, f_tray]):
    st.warning("Carga los tres históricos para generar la Base Maestra.")
    st.stop()

try:
    hoja_data, raw_data = leer_mejor_hoja(
        f_data.getvalue(),
        ("Sheet1",),
        (
            "Fecha Servicio",
            "No. Orden Servicio",
            "No.OrdenServicio",
            "Estado Servicio",
        ),
    )
    hoja_pat, raw_pat = leer_mejor_hoja(
        f_pat.getvalue(),
        ("ACTUALIZADO", "BASE"),
        (
            "Fecha Servicio",
            "No. Orden Servicio",
            "No.OrdenServicio",
            "SERVICIO",
            "REMESAS",
            "Estado",
        ),
    )
    hoja_tray, raw_tray = leer_mejor_hoja(
        f_tray.getvalue(),
        ("Sheet1",),
        ("REMESA", "TRAYECTO", "CARGA", "ESTADO OPER", "ESTADO OP"),
    )

    data = preparar_data(raw_data)
    pat = preparar_pat(raw_pat)
    tray = preparar_trayectos(raw_tray)

    # Control visible de lectura histórica
    st.success(
        f"Lectura OK | DATA: {hoja_data} ({len(data):,} registros) | "
        f"PAT: {hoja_pat} ({len(pat):,} registros) | "
        f"TRAYECTOS: {hoja_tray} ({len(tray):,} registros)"
    )

    (
        consolidado,
        cruce_data_pat,
        pat_sin_astrans,
        data_sin_pat,
        duplicados_pat,
        duplicados_astrans,
    ) = consolidar(data, pat, tray)

except Exception as exc:
    st.error(f"No fue posible procesar los archivos: {exc}")
    st.stop()

total = len(consolidado)
conciliadas = int(consolidado["COINCIDE_REMESA_PAT_ASTRANS"].sum())
sin_pat = total - conciliadas
cancelados_ejecutados = int(
    (consolidado["RESULTADO_SERVICIO"] == "CANCELADO EN DATA, PERO EJECUTADO CON REMESA").sum()
)

cols = st.columns(6)
with cols[0]:
    kpi("Registros ASTRANS", entero(total), "Base central")
with cols[1]:
    kpi("Conciliados PAT–ASTRANS", entero(conciliadas), porcentaje(conciliadas / total * 100 if total else 0))
with cols[2]:
    kpi("ASTRANS sin PAT", entero(sin_pat))
with cols[3]:
    kpi("PAT sin ASTRANS", entero(len(pat_sin_astrans)))
with cols[4]:
    kpi("DATA sin PAT", entero(len(data_sin_pat)))
with cols[5]:
    kpi("Cancelados ejecutados", entero(cancelados_ejecutados))

tabs = st.tabs([
    "Base Maestra",
    "Cruce DATA–PAT",
    "Diferencias",
    "Duplicados",
])

with tabs[0]:
    st.subheader("Base Maestra RCN")
    st.info(
        "TRAYECTOS es la base central. PAT se relaciona por remesa exacta en toda la base. "
        "DATA se relaciona con PAT por Fecha Servicio + No. Orden Servicio."
    )
    st.dataframe(consolidado, use_container_width=True, hide_index=True)

with tabs[1]:
    st.dataframe(cruce_data_pat, use_container_width=True, hide_index=True)

with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### PAT sin ASTRANS")
        st.dataframe(pat_sin_astrans, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("### DATA sin PAT")
        st.dataframe(data_sin_pat, use_container_width=True, hide_index=True)

with tabs[3]:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Duplicados PAT")
        st.dataframe(duplicados_pat, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("### Duplicados ASTRANS")
        st.dataframe(duplicados_astrans, use_container_width=True, hide_index=True)

excel = crear_excel({
    "BASE_MAESTRA_RCN": consolidado,
    "CRUCE_DATA_PAT": cruce_data_pat,
    "PAT_SIN_ASTRANS": pat_sin_astrans,
    "DATA_SIN_PAT": data_sin_pat,
    "DUPLICADOS_PAT": duplicados_pat,
    "DUPLICADOS_ASTRANS": duplicados_astrans,
})

st.download_button(
    "📥 Descargar Base Maestra RCN",
    data=excel,
    file_name="BASE_MAESTRA_RCN.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
