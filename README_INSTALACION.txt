DASHBOARD SEMANAL DE CONTROL DOCUMENTAL

ARCHIVOS
- app.py
- requirements.txt

EJECUCIÓN LOCAL
1. Instale Python 3.11.
2. Abra una terminal en la carpeta del proyecto.
3. Ejecute: pip install -r requirements.txt
4. Ejecute: streamlit run app.py
5. En el navegador, cargue el archivo Excel de control documental.

PUBLICACIÓN EN STREAMLIT CLOUD
1. Suba app.py y requirements.txt a la raíz del repositorio de GitHub.
2. En Streamlit Cloud seleccione app.py como Main file path.
3. La aplicación solicitará cargar el Excel cada vez que se abra.

ESTADOS DE REGISTRO
El panel permite incluir y filtrar:
- ACTIVO
- SUSPENDIDO
- INACTIVO
- SIN ESTADO

Por defecto se incluyen ACTIVO, SUSPENDIDO e INACTIVO. Los mensajes de WhatsApp muestran claramente el estado actual del vehículo o conductor.

REGLAS DE ALERTA
- VENCIDO: fecha anterior al corte.
- ALERTA SEMANAL: vence entre hoy y 7 días.
- PRÓXIMO A VENCER: vence entre 8 y 30 días.
- VIGENTE: faltan más de 30 días.
- SIN FECHA: no hay una fecha válida registrada.

NOTA
El archivo no contiene una relación directa entre cada conductor y una placa. Por ello, el dashboard presenta las alertas de vehículos y conductores en vistas separadas.
