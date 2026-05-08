# rack_monitor.py
import requests
import json
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

USER = "jose_castaneda"
PASS = "Paramore12"

LOGIN_URL = "http://10.121.186.180/member/login/"
API_URL = "http://10.121.186.180/"


def get_session():
    """Creates authenticated session"""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s


def login_session(s):
    """Login into external system"""

    login_page = s.get(LOGIN_URL)
    soup = BeautifulSoup(login_page.text, "html.parser")

    csrf = soup.select_one('input[name="csrfmiddlewaretoken"]')
    csrf_token = csrf["value"] if csrf else ""

    payload = {
        "username": USER,
        "password": PASS,
        "csrfmiddlewaretoken": csrf_token,
        "next": "/"
    }

    r = s.post(LOGIN_URL, data=payload, headers={"Referer": LOGIN_URL})
    r.raise_for_status()

    return s


def fetch_raw_data(s):
    """Get JSON from API"""

    csrf_api = s.cookies.get("csrftoken") or s.cookies.get("CSRF-TOKEN")

    headers = {
        "Referer": API_URL,
        "Origin": API_URL,
        "X-CSRFToken": csrf_api,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
    }

    resp = s.post(API_URL, json={"page": 1}, headers=headers)
    resp.raise_for_status()

    return resp.json()


def extract_sku_names(obj, result=None):
    """Recursive extractor"""
    if result is None:
        result = []

    if isinstance(obj, dict):
        if "SkuName" in obj:
            result.append(str(obj["SkuName"]))

        for v in obj.values():
            extract_sku_names(v, result)

    elif isinstance(obj, list):
        for i in obj:
            extract_sku_names(i, result)

    return result


def analyze_config_counts(data):
    """Counts configs from SkuName"""

    config_counts = {
        "Config1": 0,
        "Config2": 0,
        "Config3": 0,
        "Config4": 0,
        "Config5": 0,
        "Config6": 0,
        "ConfigB": 0,
        "ConfigF": 0,
    }

    sku_names = extract_sku_names(data)

    for sku in sku_names:
        if not sku:
            continue

        for k in config_counts.keys():
            if k in sku:
                config_counts[k] += 1
                break

    return config_counts


def get_server_data():
    """Main function for rack monitor"""

    try:
        s = get_session()
        s = login_session(s)
        data = fetch_raw_data(s)

        records = []
        loc_data = data.get("loc_data", {})
        location_info = data.get("location_info_data", {})

        valid_racks = {"POD2", "POD"}
        
        for location_id, unit in loc_data.items():

            rack = str(unit.get("Rack", "")).strip().upper()

            if rack not in valid_racks:
                continue

            # =========================
            # TAGS
            # =========================

            loc_info = location_info.get(location_id, {})

            tags = loc_info.get("Tags", [])

            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = [tags]

            tags_text = [
                t["text"]
                for t in tags
                if isinstance(t, dict) and "text" in t
            ]

            tags_text_str = ", ".join(tags_text)

            # =========================
            # EXPECTED OUTPUT
            # =========================

            calc = calculate_expected_output(
                unit.get("StartTime", ""),
                unit.get("StageDisplay", "")
            )

            expected_output = None
            time_remaining = None

            if calc:
                expected_output = calc["expected_output"]

                try:
                    now = datetime.now()

                    output_time = datetime.strptime(expected_output, "%H:%M")
                    output_time = datetime.combine(now.date(), output_time.time())

                    if output_time < now:
                        output_time += timedelta(days=1)

                    time_remaining = round(
                        (output_time - now).total_seconds() / 3600,
                        2
                    )
                except:
                    time_remaining = None

            # =========================
            # RECORD
            # =========================

            record = {
                "TestType": unit.get("TestType", "MP"),
                "TestStatus": unit.get("TestStatusName", ""),
                "ProductName": unit.get("DeviceTag", ""),
                "PartNumber": unit.get("PartNumber", ""),
                "ModelName": unit.get("ModelName", ""),
                "WorkOrder": unit.get("WorkOrder", ""),
                "SkuName": unit.get("SkuName", ""),
                "Tags": tags_text_str,
                "SerialNumber": unit.get("SerialNumber", f"SN_{location_id}"),
                "Stage": unit.get("StageDisplay", "INIT"),
                "Rack": rack,
                "Bay": unit.get("Bay", ""),
                "Slot": unit.get("Slot", ""),
                "StartTime": unit.get("StartTime", ""),
                "EndTime": unit.get("EndTime", ""),
                "ErrorCode": unit.get("ErrorCode", ""),
                "ErrorDescription": unit.get("ErrorDescription", ""),
                "WaitingTime": 0,

                # NUEVO
                "ExpectedOutput": expected_output,
                "TimeRemaining": time_remaining
            }

            records.append(record)
            

        df = pd.DataFrame(records)

        config_counts = analyze_config_counts(data)
        summary = build_output_summary(df)
        bay_view = build_bay_view(df)

        return {
            "data": df.to_dict(orient="records"),
            "configs": config_counts,
            "summary": summary,
            "bay_view": bay_view
        }

    except Exception as e:
        print("rack_monitor error:", e)

        return {
            "data": [],
            "configs": {}
        }
    
from datetime import datetime, timedelta

# ============================================================================
# STAGE DURATIONS
# ============================================================================

STAGE_DURATIONS = {
    "FLA": 45,
    "FLC": 40,
    "Pretest": 35,
    "FCT": 120,
    "FINT": 90,
    "INSTALLATION": 39.4,
}

STAGE_ORDER = [
    "FLA",
    "FLC",
    "Pretest",
    "FCT",
    "FINT",
    "INSTALLATION"
]

TOTAL_PROCESS_TIME = sum(STAGE_DURATIONS.values())


# ============================================================================
# CALCULATE EXPECTED OUTPUT
# ============================================================================

def calculate_expected_output(start_time_str, current_stage):

    try:

        if not start_time_str:
            return None

        now = datetime.now()

        start_time = pd.to_datetime(start_time_str)

        stage_lookup = {
            stage.lower(): stage
            for stage in STAGE_ORDER
        }

        normalized_stage = stage_lookup.get(
            str(current_stage).lower(),
            current_stage
        )

        elapsed_minutes = (
            now - start_time
        ).total_seconds() / 60

        expected_output = start_time + timedelta(
            minutes=TOTAL_PROCESS_TIME
        )

        expected_output_str = expected_output.strftime("%H:%M")

        return {
            "expected_output": expected_output_str,
            "elapsed_minutes": elapsed_minutes
        }

    except Exception as e:
        print("calculate_expected_output error:", e)
        return None


# ============================================================================
# BUILD OUTPUT SUMMARY
# ============================================================================

def build_output_summary(df):

    summary_data = []

    for _, row in df.iterrows():

        if row["TestStatus"] != "Testing":
            continue

        calc = calculate_expected_output(
            row["StartTime"],
            row["Stage"]
        )

        if not calc:
            continue

        try:

            now = datetime.now()

            output_time = datetime.strptime(
                calc["expected_output"],
                "%H:%M"
            )

            output_time = datetime.combine(
                now.date(),
                output_time.time()
            )

            if output_time < now:
                output_time += timedelta(days=1)

            hours_until = (
                output_time - now
            ).total_seconds() / 3600

            config = "Unknown"

            serial = str(row["SerialNumber"])

            config_map = {
                "0J94NW": "Config 1",
                "JJ3MGW": "Config 6",
                "7JFH9W": "Config 2",
                "KR7T5W": "Config 4",
                "6TGR7W": "Config B1",
            }

            if len(serial) >= 9:
                key = serial[3:9]
                config = config_map.get(key, "Config F1")

            summary_data.append({
                "hours_until": hours_until,
                "config": config,
                "output_time": calc["expected_output"]
            })

        except Exception as e:
            print("summary row error:", e)

    # ============================================================================
    # GROUP WINDOWS
    # ============================================================================

    windows = {
        "< 1 hour": [],
        "1-2 hours": [],
        "2-3 hours": [],
        "3-4 hours": [],
        "4-5 hours": [],
        "5-6 hours": [],
        "> 6 hours": [],
    }

    for item in summary_data:

        h = item["hours_until"]

        if h < 1:
            windows["< 1 hour"].append(item)

        elif h < 2:
            windows["1-2 hours"].append(item)

        elif h < 3:
            windows["2-3 hours"].append(item)

        elif h < 4:
            windows["3-4 hours"].append(item)

        elif h < 5:
            windows["4-5 hours"].append(item)

        elif h < 6:
            windows["5-6 hours"].append(item)

        else:
            windows["> 6 hours"].append(item)

    rows = []

    for window_name, units in windows.items():

        if not units:
            continue

        config_counts = {}

        for u in units:
            cfg = u["config"]
            config_counts[cfg] = config_counts.get(cfg, 0) + 1

        rows.append({
            "window": window_name,
            "total": len(units),
            "configs": config_counts,
            "times": [u["output_time"] for u in units]
        })

    return rows

def build_bay_view(df):

    bays = {i: [] for i in range(1, 55)}

    for _, row in df.iterrows():

        try:
            bay = int(row["Bay"])
        except:
            continue

        if 1 <= bay <= 54:
            bays[bay].append(row.to_dict())

    return bays