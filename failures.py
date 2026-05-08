import os
import json
import string
import requests
import sys
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from openpyxl import Workbook
from flask import Flask

# 1. IMPORTACIÓN DE TUS MODELOS
from models import db, PingFailure

# ==========================================
# 2. CONFIGURACIÓN INTEGRADA (Solo mfte_crm)
# ==========================================
class Config:
    SECRET_KEY = 'change-me'
    # Establecemos mfte_crm como la base de datos principal
    SQLALCHEMY_DATABASE_URI = 'postgresql://guillermo:mfte@10.121.161.225:5432/mfte_crm'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # FusionEye Configuración Directa
    FUSION_BASE = "http://10.121.186.180"
    FUSION_USERNAME = "aurora_alvarez"
    FUSION_PASSWORD = "Auroris1234"
    RACKS_A_FILTRAR = ["POD", "POD2"]

app = Flask(__name__)
app.config.from_object(Config)

# Inicializamos la DB con la configuración de mfte_crm
db.init_app(app)

# ==========================================
# 3. LÓGICA DE TIEMPO Y SCRAPING
# ==========================================
def get_time_range(periodo="semana", start_custom=None, end_custom=None):
    ahora = datetime.now()
    if periodo == "dia":
        if ahora.hour < 6:
            start = (ahora - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            end = ahora.replace(hour=5, minute=59, second=59)
        else:
            start = ahora.replace(hour=6, minute=0, second=0, microsecond=0)
            end = (ahora + timedelta(days=1)).replace(hour=5, minute=59, second=59)
    elif periodo == "semana":
        lunes_actual = ahora - timedelta(days=ahora.weekday())
        start = lunes_actual.replace(hour=6, minute=0, second=0, microsecond=0)
        domingo = start + timedelta(days=6)
        end = domingo.replace(hour=6, minute=0, second=0, microsecond=0)
    elif periodo == "rango" and start_custom and end_custom:
        start = datetime.strptime(start_custom, "%Y-%m-%d %H:%M")
        end = datetime.strptime(end_custom, "%Y-%m-%d %H:%M")
    else:
        start = (ahora - timedelta(days=7)).replace(hour=6, minute=0, second=0)
        end = ahora
    return start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")

def create_fusion_session():
    try:
        s = requests.Session()
        
        # 1. Agregamos el User-Agent al GET inicial
        headers_get = {"User-Agent": "Mozilla/5.0"}
        r = s.get(f"{Config.FUSION_BASE}/member/login/", headers=headers_get, timeout=15)
        
        soup = BeautifulSoup(r.text, "html.parser")
        csrf_token = soup.find("input", {"name": "csrfmiddlewaretoken"})["value"]
        
        data = {
            "csrfmiddlewaretoken": csrf_token,
            "username": Config.FUSION_USERNAME,
            "password": Config.FUSION_PASSWORD,
            "next": "/search/",
        }
        
        # 2. Agregamos el Referer al POST de login
        headers_post = {"Referer": f"{Config.FUSION_BASE}/member/login/"}
        s.post(f"{Config.FUSION_BASE}/member/login/", data=data, headers=headers_post)
        
        return s, s.cookies.get("csrftoken") or csrf_token
    except Exception as e:
        print(f"❌ Error en auth: {e}")
        return None, None

def fetch_ping_data(start_time, end_time):
    session, csrf = create_fusion_session()
    if not session: return []
    
    # 3. Restauramos los HEADERS completos de tu código original
    headers = {
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": Config.FUSION_BASE,
        "Referer": f"{Config.FUSION_BASE}/search/",
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }

    form_data = {
        "part_number": "",
        "serial_number": "",
        "tester_sn": "",
        "stage": "",
        "start_time": start_time, 
        "end_time": end_time,
        "error_code": "",
        "test_status": "failed", 
        "page_length": "150000",
        "queryTestRecordId": "0",
        "queryCompare": ">",
        "csrfmiddlewaretoken": csrf,
    }
    
    try:
        # Pasamos los headers a la petición
        resp = session.post(f"{Config.FUSION_BASE}/search/search_action/", data=form_data, headers=headers, timeout=45)
        resp.raise_for_status() # Asegura que si hay error 500 brinque al except
        return resp.json().get("ret_lis") or []
    except Exception as e:
        print(f"❌ Error al consultar FusionEye: {e}")
        return []

# ==========================================
# 4. EXCEL Y BASE DE DATOS (ORM)
# ==========================================
def generate_validation_excel(records):
    """Genera un excel y una lista filtrada de las unidades deseadas (Lógica Original Restaurada)"""
    filename = "Reporte_Racks.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Review_Failures"

    # Cabeceras originales completas
    headers = [
        "TestType", "TestStatus", "ProductName", "PartNumber", "ModelName", 
        "WorkOrder", "SkuName", "SerialNumber", "Stage", "EthernetIP", 
        "BMCIP", "OperatorID", "Location", "StartTime", "EndTime", 
        "ErrorCode", "ErrorDescription"
    ]
    ws.append(headers)

    filtered_list = []
    yield_stats = {}
    for r in records:
        status_raw = str(r.get("TestStatus", "")).strip().lower()
        stage_raw = str(r.get("Stage", "")).strip().lower()
        
        rack = str(r.get("Rack", "")).strip()
        bay = str(r.get("Bay", "")).strip()
        
        # Filtro de racks deseados
        if rack not in Config.RACKS_A_FILTRAR:
            continue

        # --- LÓGICA DE YIELD ORIGINAL ---
        rack_key = f"{rack}_{bay}" 
        if rack_key not in yield_stats:
            yield_stats[rack_key] = {"pass": 0, "fail": 0}

        # Restaurado el filtro stage == "installation"
        if status_raw == "passed" and stage_raw == "installation":
            yield_stats[rack_key]["pass"] += 1
        elif status_raw == "failed":
            yield_stats[rack_key]["fail"] += 1

        # --- LÓGICA DE EXCEL/DB (Solo para fallas) ---
        if status_raw == "failed":
            slot = r.get("Slot", "")
            location_str = f"R:{rack} B:{bay} S:{slot}" if rack else ""
            
            row = [
                r.get("TestType", ""), r.get("TestStatus", ""),
                r.get("ProductName", ""), r.get("PartNumber", ""),
                r.get("ModelName", ""), r.get("WorkOrder", ""),
                r.get("SkuName", ""), r.get("SerialNumber", ""),
                r.get("Stage", ""), r.get("EthernetIP", ""), 
                r.get("BMCIP", ""), r.get("OperatorID", ""), 
                location_str, r.get("StartTime", ""), 
                r.get("EndTime", ""), r.get("ErrorCode", ""), 
                r.get("ErrorDescription", "")
            ]
            ws.append(row)
            filtered_list.append(r)

    try:
        wb.save(filename)
        print(f"✅ Excel actualizado: {filename}")
    except PermissionError:
        print(f"❌ Error: El Excel está abierto. Ciérralo para actualizar.")
    
    return filtered_list, yield_stats

def save_to_db(filtered_records):
    """Guarda los datos en mfte_crm (Ahora con logs de error)"""
    if not filtered_records:
        print("⚠️ No hay datos filtrados (fallas) para guardar en DB.")
        return

    with app.app_context():
        count = 0
        for r in filtered_records:
            try:
                start_str = r.get("StartTime")
                if not start_str:
                    continue # Si no hay fecha de inicio, no lo podemos guardar
                
                # Convertimos el string a objeto datetime
                st_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                
                # Verificamos duplicados antes de insertar
                exists = PingFailure.query.filter_by(
                    serial_number=r.get("SerialNumber"), 
                    start_time=st_dt
                ).first()
                
                if not exists:
                    new_fail = PingFailure(
                        model_name=r.get("ModelName"),
                        product_name=r.get("ProductName"),
                        serial_number=r.get("SerialNumber"),
                        location=f"R:{r.get('Rack')} B:{r.get('Bay')} S:{r.get('Slot')}",
                        start_time=st_dt,
                        end_time=r.get("EndTime"),
                        error_code=r.get("ErrorCode")
                    )
                    db.session.add(new_fail)
                    count += 1
            except Exception as e:
                # ¡AQUÍ ESTABA EL PROBLEMA! Ahora sabremos por qué falla
                print(f"⚠️ Error al guardar el SN {r.get('SerialNumber')}: {e}")
                continue
                
        db.session.commit()
        print(f"💾 {count} registros NUEVOS insertados en mfte_crm.")

def summarize_failures_from_db(start_time, end_time, current_yield_stats):
    """Genera resumen por Top Fallas + PING (Lógica Original Restaurada)"""
    with app.app_context():
        query = PingFailure.query.filter(
            PingFailure.start_time >= start_time, 
            PingFailure.start_time <= end_time
        )
        df = pd.read_sql(query.statement, db.engine)
        
        if df.empty:
            print(f"⚠️ No hay datos en DB para el rango {start_time} - {end_time}")
            return None

        # 1. Procesamiento de ubicación
        regex = r'R:(?P<Cuarto>\w+)\s+B:(?P<Bay>\d+)\s+S:(?P<Slot>[a-zA-Z])'
        extracted = df['location'].str.extract(regex)
        df['Cuarto'] = extracted['Cuarto']
        df['Bay_Num'] = pd.to_numeric(extracted['Bay'], errors='coerce')
        df['Slot'] = extracted['Slot'].str.upper()

        # 2. Configuración de Cuartos
        config_cuartos = [
            ("POD", 1, 6),   # Bahías 1-6, Racks 1-36
            ("POD2", 7, 9)   # Bahías 7-9, Racks 37-54
        ]

        # 2.5: PRE-CÁLCULO DE YIELD GLOBAL
        yield_global_map = {}
        for pod_name, b_inicio, b_fin in config_cuartos:
            pod_clean = str(pod_name).strip()
            for b in range(b_inicio, b_fin + 1):
                r_inicio, r_fin = (b - 1) * 6 + 1, b * 6
                for r in range(r_inicio, r_fin + 1):
                    nombre_r_key = f"{pod_clean}_{r}"
                    stats = current_yield_stats.get(nombre_r_key, {"pass": 0, "fail": 0})
                    
                    tp = stats.get("pass", 0)
                    tf = stats.get("fail", 0)
                    total = tp + tf
                    
                    yp = (tp / total * 100) if total > 0 else 100
                    yield_global_map[nombre_r_key] = {
                        "yield": round(yp, 2),
                        "total_pass": tp,
                        "total_fail": tf
                    }

        # 3. Identificar Categorías
        df_ping = df[df['error_code'].str.contains('ping', case=False, na=False)]
        df_others = df[~df['error_code'].str.contains('ping', case=False, na=False)]
        top_error_codes = df_others['error_code'].value_counts().head(9).index.tolist()

        categorias_a_procesar = ["PING"] + top_error_codes
        import string
        slots_posibles = list(string.ascii_uppercase[:23])
        
        reporte_final = {
            "start_time": start_time,
            "end_time": end_time,
            "ultima_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "resumen_top": {},
            "fallas": {}
        }

        # 4. Construcción del reporte por categoría
        for cat in categorias_a_procesar:
            df_cat = df_ping if cat == "PING" else df[df['error_code'] == cat]
            reporte_final["resumen_top"][cat] = len(df_cat)
            reporte_final["fallas"][cat] = {"total": len(df_cat), "detalles": {}}

            for pod_name, b_inicio, b_fin in config_cuartos:
                df_pod = df_cat[df_cat['Cuarto'] == pod_name]
                reporte_final["fallas"][cat]["detalles"][pod_name] = {"total": len(df_pod), "bahias": {}}
                
                for b in range(b_inicio, b_fin + 1):
                    r_inicio, r_fin = (b - 1) * 6 + 1, b * 6
                    df_bahia = df_pod[(df_pod['Bay_Num'] >= r_inicio) & (df_pod['Bay_Num'] <= r_fin)]
                    nombre_b = f"Bahia_{b}"
                    reporte_final["fallas"][cat]["detalles"][pod_name]["bahias"][nombre_b] = {"total": len(df_bahia), "racks": {}}

                    for r in range(r_inicio, r_fin + 1):
                        df_rack = df_bahia[df_bahia['Bay_Num'] == r]
                        nombre_r = f"Rack_{r}"
                        conteo_slots = {s: int(len(df_rack[df_rack['Slot'] == s])) for s in slots_posibles}
                        
                        pod_clean = str(pod_name).strip()
                        key = f"{pod_clean}_{r}"
                        rack_stats = yield_global_map.get(key, {"yield": 100, "total_pass": 0, "total_fail": 0})

                        reporte_final["fallas"][cat]["detalles"][pod_name]["bahias"][nombre_b]["racks"][nombre_r] = {
                            "total": len(df_rack),
                            "total_pass": rack_stats["total_pass"],
                            "total_fail": rack_stats["total_fail"],
                            "yield": rack_stats["yield"],
                            "slots": conteo_slots
                        }

        print(f"✅ Reporte JSON generado exitosamente.")
        return reporte_final

# ==========================================
# 5. EJECUCIÓN
# ==========================================
def run_process(periodo="semana", start_custom=None, end_custom=None):
    st, et = get_time_range(periodo, start_custom, end_custom)
    print(f"🚀 Iniciando proceso en mfte_crm: {st} - {et}")
    
    raw = fetch_ping_data(st, et)
    if raw:
        filtered, yield_st = generate_validation_excel(raw)
        save_to_db(filtered)
        reporte = summarize_failures_from_db(st, et, yield_st)
        
        if reporte:
            with open('data_kpi.json', 'w', encoding='utf-8') as f:
                json.dump(reporte, f, indent=4)
            print("✅ Proceso terminado exitosamente.")
    else:
        print("⚠️ No se obtuvieron datos de FusionEye.")

if __name__ == "__main__":
    # Cambiamos al directorio del script para evitar problemas de rutas
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    if len(sys.argv) > 1:
        run_process(periodo=sys.argv[1])
    else:
        run_process(periodo="semana")