import time
import requests
import xml.etree.ElementTree as ET

from sqlalchemy import text

from db import get_engine  # ajusta a tu proyecto
from typing import Dict, Tuple, Optional, Any
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import time

# =====================================================
# 🔍 EMR CHECK
# =====================================================
def _is_emr_station(station: str) -> bool:
    s = " ".join((station or "").strip().upper().split())
    return "EMR" in s


# =====================================================
# 🌐 SOAP - GET STAGE
# =====================================================
def get_stage_actual(serial_number: str) -> str:
    soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body>
        <GetUSNGenealogyBasic xmlns="http://localhost/Tester.WebService/WebService">
          <UnitSerialNumber>{serial_number}</UnitSerialNumber>
          <StageCode>NH</StageCode>
        </GetUSNGenealogyBasic>
      </soap:Body>
    </soap:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://localhost/Tester.WebService/WebService/GetUSNGenealogyBasic"
    }

    try:
        resp = requests.post(
            "http://10.49.168.125:5556/Tester.WebService/WebService.asmx",
            data=soap_body,
            headers=headers,
            timeout=8
        )

        root = ET.fromstring(resp.content)

        stage = ""
        for elem in root.iter():
            tag = elem.tag.lower()

            if "stageactual" in tag:
                stage = (elem.text or "").strip()
            elif "nextstage" in tag and not stage:
                stage = (elem.text or "").strip()

        return stage

    except Exception as e:
        print(f"[SOAP] get_stage_actual error: {e}")
        return ""


# =====================================================
# 🧠 DB CHECK
# =====================================================
def is_in_fae_queue(serial: str) -> bool:
    engine = get_engine()

    sql = text("""
        SELECT 1
        FROM fae_repair_queue
        WHERE serial_number = :sn
          AND status = 'PENDING'
        LIMIT 1
    """)

    with engine.begin() as conn:
        return conn.execute(sql, {"sn": serial}).scalar() is not None


def has_pending_fae(serial: str) -> bool:
    return is_in_fae_queue(serial)


# =====================================================
# 🔄 SYNC PENDING
# =====================================================
def sync_pending_for_serial(serial: str) -> int:
    serial = (serial or "").strip()
    if not serial:
        return 0

    engine = get_engine()

    sql = text("""
        SELECT *
        FROM fae_repair_queue
        WHERE serial_number = :sn
          AND status = 'PENDING'
        ORDER BY created_at ASC
    """)

    with engine.begin() as conn:
        rows = conn.execute(sql, {"sn": serial}).fetchall()

    return len(rows)


# =====================================================
# 🚀 SOAP SEND + CONFIRM
# =====================================================
FAE_TARGET_STAGE = "RN"
VERIFY_POLLS = 3
POLL_DELAY_SEC = 5
RETRY_DELAY_SEC = 0


def _send_to_fae_and_confirm(
    serial,
    employee_id,
    station,
    stage_code,
    error_code,
    error_desc
):

    last_stage = ""

    def _poll_for_rn():
        nonlocal last_stage

        for _ in range(VERIFY_POLLS):
            try:
                last_stage = (get_stage_actual(serial) or "").strip()
            except Exception as e:
                print(f"[VERIFY] error: {e}")
                last_stage = ""

            if last_stage == FAE_TARGET_STAGE:
                return True

            time.sleep(POLL_DELAY_SEC)

        return False


    # ---------------------
    # Attempt 1
    # ---------------------
    try:
        send_to_repair(
            serial=serial,
            employee_id=employee_id,
            station=station,
            stage_code=stage_code,
            error_code=error_code,
            error_desc=error_desc
        )
    except Exception as e:
        print(f"[SOAP attempt 1] {e}")

    if _poll_for_rn():
        return True, last_stage


    # ---------------------
    # Attempt 2
    # ---------------------
    time.sleep(RETRY_DELAY_SEC)

    try:
        send_to_repair(
            serial=serial,
            employee_id=employee_id,
            station=station,
            stage_code=stage_code,
            error_code=error_code,
            error_desc=error_desc
        )
    except Exception as e:
        print(f"[SOAP attempt 2] {e}")

    if _poll_for_rn():
        return True, last_stage

    return False, last_stage


# =====================================================
# 🧾 INSERT ISSUE
# =====================================================
def insert_issue(employee_id, serial_number, stage, station, error_code, error_desc):
    engine = get_engine()

    sql = text("""
        INSERT INTO open_fail_issues
            (employee_id, serial_number, stage, station, error_code, error_description)
        VALUES
            (:e, :s, :st, :sta, :ec, :ed)
    """)

    with engine.begin() as conn:
        conn.execute(sql, {
            "e": employee_id,
            "s": serial_number,
            "st": stage or "",
            "sta": station,
            "ec": error_code,
            "ed": error_desc,
        })


# =====================================================
# 📦 INSERT QUEUE
# =====================================================
def insert_fae_queue(serial, employee_id, stage, station, error_code, error_desc):
    engine = get_engine()

    sql_existing = text("""
        SELECT id_queue
        FROM fae_repair_queue
        WHERE serial_number = :s
          AND status = 'PENDING'
        ORDER BY created_at DESC
        LIMIT 1
    """)

    sql_insert = text("""
        INSERT INTO fae_repair_queue
            (serial_number, employee_id, stage, station, error_code, error_desc)
        VALUES
            (:s, :e, :st, :sta, :ec, :ed)
        RETURNING id_queue
    """)

    with engine.begin() as conn:
        existing = conn.execute(sql_existing, {"s": serial}).scalar()
        if existing:
            return existing

        return conn.execute(sql_insert, {
            "s": serial,
            "e": employee_id,
            "st": stage or "",
            "sta": station,
            "ec": error_code,
            "ed": error_desc,
        }).scalar()



# ==========================================
# FUSION CONFIG
# ==========================================
FUSION_BASE_URL = "http://10.121.186.180"

FUSION_USER = "jose_castaneda"
FUSION_PASS = "Paramore12"

CACHE_TTL_SECONDS = 600

_CACHE = {
    "session": None,
    "csrf": None,
    "ts": 0
}


# ==========================================
# CREATE SESSION
# ==========================================
def _create_fusion_session():
    try:
        sess = requests.Session()

        login_url = f"{FUSION_BASE_URL}/member/login/"

        r = sess.get(login_url, timeout=10)
        csrf_cookie = sess.cookies.get("csrftoken", "")

        soup = BeautifulSoup(r.text, "html.parser")

        csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})
        csrf = csrf["value"] if csrf else ""

        payload = {
            "username": FUSION_USER,
            "password": FUSION_PASS,
            "csrfmiddlewaretoken": csrf
        }

        headers = {
            "Referer": login_url,
            "User-Agent": "Mozilla/5.0"
        }
       
        r = sess.post(
            login_url,
            data=payload,
            headers=headers,
            timeout=10
        )

        if r.status_code == 200:
            return sess, csrf

        return None, None

    except Exception as e:
        print("[FusionEye] login error:", e)
        return None, None


# ==========================================
# CACHE SESSION
def _get_cached_client():
    now = time.time()

    if (
        _CACHE["session"]
        and _CACHE["csrf"]
        and (now - _CACHE["ts"] < CACHE_TTL_SECONDS)
    ):
        return _CACHE["session"], _CACHE["csrf"]

    sess, _ = _create_fusion_session()

    if not sess:
        return None, None

    csrf = sess.cookies.get("csrftoken")

    _CACHE["session"] = sess
    _CACHE["csrf"] = csrf
    _CACHE["ts"] = now

    return sess, csrf


# ==========================================
# SEARCH SERIAL
# ==========================================
def _fetch_test_records_by_serial(
    sess: requests.Session,
    serial_number: str,
    csrf_token: str
) -> Optional[Dict[str, Any]]:
    
 

    try:
        url = f"{FUSION_BASE_URL}/search/search_action/"

        form_data = {
            "part_number": "",
            "serial_number": serial_number,
            "tester_sn": "",
            "start_time": "",
            "end_time": "",
            "error_code": "",
            "error_description": "",
            "opid": "",
            "workOrder": "",
            "sku_name": "",
            "page_length": "300",
            "queryTestRecordId": "0",
            "queryCompare": ">",
            "csrfmiddlewaretoken": csrf_token
        }

        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": FUSION_BASE_URL,
            "Referer": f"{FUSION_BASE_URL}/search/",
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",

            # 🔥 ESTE ES EL QUE TE FALTABA DE VERDAD
            "X-CSRFToken": csrf_token
        }

        r = sess.post(
            url,
            data=form_data,
            headers=headers,
            timeout=12
        )

        
        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:
        print("[FusionEye] fetch error:", e)
        return None


# ==========================================
# DATE PARSER
# ==========================================
def _parse_fusion_dt(value):
    if not value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except:
            pass

    return None


# ==========================================
# PICK BEST
# ==========================================
def _pick_best_record_latest(ret_lis: list, prefer_failed: bool = True) -> Optional[dict]:

    if not ret_lis:
        return None

    def norm_status(r):
        return str(
            r.get("TestStatus")
            or r.get("test_status")
            or r.get("Status")
            or r.get("Result")
            or ""
        ).strip().lower()

    def key_dt(r):
        dt = (
            _parse_fusion_dt(r.get("EndTime"))
            or _parse_fusion_dt(r.get("StartTime"))
        )
        return dt or datetime.min

    # 🔥 1. SOLO FALLAS REALES
    failed = [
        r for r in ret_lis
        if "fail" in norm_status(r)
    ]

    if failed:
        return max(failed, key=key_dt)

    # 🔥 2. fallback: último registro (si no hay fallas)
    return max(ret_lis, key=key_dt)

# ==========================================
# NORMALIZE STATION
# ==========================================
def _normalize_station(rack, bay, slot):
    rack = (rack or "").strip()
    bay = (bay or "").strip()
    slot = (slot or "").strip()

    if rack and not rack.upper().startswith("POD"):
        rack = f"POD-{rack}"

    parts = [x for x in [rack, bay, slot] if x]

    return "-".join(parts)


# ==========================================
# PUBLIC AUTOFILL
# ==========================================
def fusion_autofill_by_sn(serial_number):
    sn = (serial_number or "").strip().replace(" ", "")
    if not sn:
        return {"station": "", "error_code": "", "error_description": ""}

    sess, csrf = _get_cached_client()
    if not sess:
        return {"station": "", "error_code": "", "error_description": ""}

    data = _fetch_test_records_by_serial(sess, sn, csrf)

    if not data:
        return {"station": "", "error_code": "", "error_description": ""}

    ret_lis = data.get("ret_lis") or []
    if not ret_lis:
        return {"station": "", "error_code": "", "error_description": ""}

    best = _pick_best_record_latest(ret_lis, True)
    if not best:
        return {"station": "", "error_code": "", "error_description": ""}

    # 🔥 STATION ROBUSTO
    station = (
        best.get("Station")
        or best.get("StationName")
        or best.get("station")
        or _normalize_station(
            best.get("Rack"),
            best.get("Bay"),
            best.get("Slot")
        )
        or ""
    )

    return {
        "station": station,
        "error_code": (
            best.get("ErrorCode")
            or best.get("error_code")
            or ""
        ).strip(),
        "error_description": (
            best.get("ErrorDescription")
            or best.get("error_description")
            or ""
        ).strip()
    }