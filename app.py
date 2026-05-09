from flask import Flask, render_template, request, jsonify, redirect, session, Response, send_file, flash, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from werkzeug.security import check_password_hash
from sqlalchemy.orm import contains_eager
from controllers.rack_monitor import get_server_data
from controllers.failures import run_process, get_time_range, get_data
import os
import json
import secrets
from sqlalchemy import or_


from controllers.rack_monitor import get_server_data
from controllers.user import get_all_users, toggle_user_status, create_user
from controllers.fae import _is_emr_station, get_stage_actual, sync_pending_for_serial, has_pending_fae, _send_to_fae_and_confirm, insert_issue, insert_fae_queue, fusion_autofill_by_sn


import io
from models import db, User, SlotRepair, PingFailure
app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.do')
app.secret_key = "super-secret-change-this"
DB_URL = 'postgresql://guillermo:mfte@10.121.161.225:5432/mfte_crm'
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

db.init_app(app)

@app.route("/", methods=["GET", "POST"])
def admin_login():
    return render_template("login.html")
    
@app.route("/login", methods=["POST"])
def login():

    username = request.form.get("username")
    password = request.form.get("password")

    user = User.query.filter_by(employee_number=username).first()

    if not user:
        flash("User does not exist")
        return redirect("/")

    # check if inactive
    if user.status != "active":
        flash("User is inactive")
        return redirect("/")

    # check lock status
    if user.locked_until and user.locked_until > datetime.utcnow():
        flash("Account is temporarily locked")
        return redirect("/")

    # validate password
    if not check_password_hash(user.password_hash, password):
        user.failed_attempts += 1

        # lock account after too many attempts
        if user.failed_attempts >= 5:
            user.locked_until = datetime.utcnow()

        db.session.commit()

        flash("Incorrect password")
        return redirect("/")

    # LOGIN SUCCESS
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()

    db.session.commit()

    session["user_id"] = user.id
    session["user_name"] = user.full_name
    session["employee_number"] = user.employee_number

    flash(f"Welcome {user.full_name}")

    return redirect("/index")

def login_required(f):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route("/index")
@login_required
def index():
    if "user_id" not in session:
        return redirect("/")

    data = get_server_data()

    # 👇 igual que failures
    try:
        processed = run_process(periodo="semana", save_json=False)

        data["resumen_top"] = processed.get("resumen_top", {})
        data["data_failures"] = processed  # opcional si quieres todo el payload

    except Exception as e:
        print(f"❌ Error index failures block: {e}")
        data["resumen_top"] = {}

    return render_template(
        "index.html",
        name=session["user_name"],
        data=data,
        config_counts=data.get("configs", {})
    )

@app.route("/logout")
def logout():
    session.clear()
    flash("Session closed")
    return redirect("/")

@app.route("/rack-monitor")
@login_required
def rack_monitor():

    data = get_server_data()

    bay_options = ["Bay 1", "Bay 2", "Bay 3"]
    rack_numbers = list(range(1, 11))

    return render_template(
    "rack_monitor/rack_monitor.html",
    bay_options=bay_options,
    rack_numbers=rack_numbers,
    rack_data=data["data"],
    config_counts=data["configs"],
    summary_data=data.get("summary", []),
    bay_view=data.get("bay_view", {})
)

@app.route("/api/rack-debug")
@login_required
def rack_debug():

    data = get_server_data()

    return jsonify(data)

#Papoi------------------------------------------------------------------
@app.route('/failures')
@login_required
def home_failures():
    periodo = request.args.get('periodo')
    start_custom = request.args.get('start_custom')
    end_custom = request.args.get('end_custom')

    if periodo:
        if periodo == 'rango' and start_custom and end_custom:
            if start_custom >= end_custom:
                periodo = 'semana' 

        st_clean = start_custom.replace("T", " ") if start_custom else None
        et_clean = end_custom.replace("T", " ") if end_custom else None
        
        try:
            data = run_process(periodo=periodo, start_custom=st_clean, end_custom=et_clean, save_json=False)
            session['last_data'] = data
            session['last_filters'] = {'periodo': periodo, 'start': start_custom, 'end': end_custom}
            if not data:
                data = get_data()
        except Exception as e:
            print(f"❌ Error en failures.py: {e}")
            data = get_data()
    else:
        data = get_data()
        session.pop('last_data', None)
        session.pop('last_filters', None)

    return render_template('failures/failures.html', data=data) 

@app.route('/failures/<error_type>/get_slot_details/<path:location>')
@login_required
def get_slot_details(error_type, location):
    periodo = request.args.get('periodo', 'semana')
    start_str = request.args.get('start_custom')
    end_str = request.args.get('end_custom')
    ahora = datetime.now()

    # Lógica de fechas (dejamos start_obj y end_obj como datetimes)
    if periodo == 'dia':
        if ahora.hour < 6:
            start_obj = (ahora - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        else:
            start_obj = ahora.replace(hour=6, minute=0, second=0, microsecond=0)
        end_obj = start_obj + timedelta(days=1)

    elif periodo == 'rango' and start_str and end_str and start_str != 'None' and end_str != 'None':
        # Parseamos el string del frontend a objeto datetime
        # Asumiendo que el formato de frontend llega como 'YYYY-MM-DD HH:MM' o similar
        start_clean = start_str.replace("T", " ")
        end_clean = end_str.replace("T", " ")
        # Si tu frontend manda segundos, agrega ':%S' al formato
        start_obj = datetime.strptime(start_clean, '%Y-%m-%d %H:%M') 
        end_obj = datetime.strptime(end_clean, '%Y-%m-%d %H:%M')

    else: # semana
        lunes_actual = ahora - timedelta(days=ahora.weekday())
        start_obj = lunes_actual.replace(hour=6, minute=0, second=0, microsecond=0)
        domingo = start_obj + timedelta(days=6)
        end_obj = domingo.replace(hour=6, minute=0, second=0, microsecond=0)

    try:
        # Consulta usando el ORM de SQLAlchemy
        fallas = PingFailure.query.filter(
            PingFailure.location == location,
            PingFailure.error_code.ilike(f"%{error_type}%"),
            PingFailure.start_time.between(start_obj, end_obj)
        ).order_by(PingFailure.start_time.desc()).all()
        
        # Formateamos la respuesta para el frontend
        data = []
        for falla in fallas:
            data.append({
                "product": falla.product_name,
                "sn": falla.serial_number,
                "loc": falla.location,
                "start": falla.start_time.strftime('%Y-%m-%d %H:%M:%S') if falla.start_time else '-',
                "end": falla.end_time.strftime('%Y-%m-%d %H:%M:%S') if falla.end_time else '-',
                "error": falla.error_code
            })
            
        return jsonify(data)

    except Exception as e:
        print(f"Error querying database: {e}")
        return jsonify({"error": "Database connection failed"}), 500

@app.route('/failures/save_repair', methods=['POST'])
@login_required
def save_repair():
    """
    Guardamos los comentarios usando el ORM de SQLAlchemy.
    """
    data = request.json
    print(f"📥 Recibiendo reparación: {data}")
    
    try:
        # Creamos una instancia del modelo
        nueva_reparacion = SlotRepair(
            location=data['location'],
            error_code=data.get('error_code'),
            comment=data['comment'],
            technician_id=data['tech_id']
        )
        
        # Guardamos en la base de datos
        db.session.add(nueva_reparacion)
        db.session.commit()
        
        print("✅ Guardado en mfte_crm exitosamente")
        return jsonify({"status": "success", "message": "Repair logged successfully"})
        
    except Exception as e:
        db.session.rollback() # Importante: revertir si hay error
        print(f"❌ Error al guardar reparación: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/failures/<error_type>/get_repairs/<path:location>')
@login_required
def get_repairs(error_type, location):
    """
    Obtenemos los comentarios usando el ORM de SQLAlchemy.
    """
    try:
        # Consulta con SQLAlchemy
        repairs = SlotRepair.query.filter(
            SlotRepair.location == location,
            SlotRepair.error_code.ilike(f"%{error_type}%")
        ).order_by(SlotRepair.repair_date.desc()).all()
        
        # Construimos el diccionario de respuesta
        data = [
            {
                "tech": r.technician_id, 
                "comment": r.comment, 
                "date": r.repair_date.strftime('%Y-%m-%d %H:%M')
            } for r in repairs
        ]
        
        return jsonify(data)
        
    except Exception as e:
        print(f"❌ Error al obtener historial: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/failures/falla/<error_type>/')
@login_required
def dashboard_slots(error_type):
    periodo = request.args.get('periodo', 'semana')
    start_custom = request.args.get('start_custom')
    end_custom = request.args.get('end_custom')

    data_all = session.get('last_data')
    filtros_sesion = session.get('last_filters', {})

    st_clean = start_custom.replace("T", " ") if start_custom else None
    et_clean = end_custom.replace("T", " ") if end_custom else None
    
    start_real, end_real = get_time_range(periodo, st_clean, et_clean)

    filtros_coinciden = (
        periodo == filtros_sesion.get('periodo') and
        start_custom == filtros_sesion.get('start') and
        end_custom == filtros_sesion.get('end')
    )

    if data_all and filtros_coinciden:
        print(f"🚀 Memoria Privada: Usando datos de sesión para {error_type}")
    else:
        if periodo:
            print(f"🔄 Procesando datos nuevos para {error_type} (save_json=False)...")
            data_all = run_process(periodo=periodo, start_custom=st_clean, end_custom=et_clean, save_json=False)
            session['last_data'] = data_all
            session['last_filters'] = {'periodo': periodo, 'start': start_custom, 'end': end_custom}
        else:
            data_all = get_data()

    falla_especifica = data_all.get('fallas', {}).get(error_type, {})
    if not falla_especifica:
        return f"Error: La categoría {error_type} no tiene registros en este periodo", 404

    racks_planos = {}
    detalles = falla_especifica.get('detalles', {})
    for pod_key in ['POD', 'POD2']:
        pod_data = detalles.get(pod_key, {})
        bahias = pod_data.get('bahias', {})
        for b_data in bahias.values():
            racks_en_bahia = b_data.get('racks', {})
            racks_planos.update(racks_en_bahia) 

    repaired_locations = []
    try:
        # Consulta de locaciones distintas con SQLAlchemy
        reparaciones = db.session.query(SlotRepair.location).filter(
            SlotRepair.error_code.ilike(f"%{error_type}%")
        ).distinct().all()
        
        # Extraemos el string de la tupla devuelta
        repaired_locations = [row[0] for row in reparaciones]
    except Exception as e:
        print(f"⚠️ Error al consultar iconos de reparación: {e}")

    return render_template('failures/dashboard_slots.html', 
                            error_type=error_type, 
                            data=falla_especifica, 
                            racks=racks_planos,
                            repaired_slots=repaired_locations,
                            filtros={
                                'periodo': periodo, 
                                'start': start_real, 
                                'end': end_real 
                            })
# ----------------------------------------------------------------------------

def clean(value):
    return value if value and value.strip() else None


@app.route("/users")
@login_required
def users():

    search = clean(request.args.get("search"))
    department = clean(request.args.get("department"))
    shift = clean(request.args.get("shift"))
    role = clean(request.args.get("role"))
    status = clean(request.args.get("status"))

    query = User.query

    if search:
        query = query.filter(
            or_(
                User.employee_number.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%")
            )
        )

    if department:
        query = query.filter(User.department == department)

    if shift:
        query = query.filter(User.shift == shift)

    if role:
        query = query.filter(User.role == role)

    if status:
        query = query.filter(User.status == status)

    users = query.order_by(User.id.desc()).all()

    return render_template("users/users.html", users=users)


@app.route("/users/create", methods=["POST"])
@login_required
def create_user_route():

    data = request.form.to_dict()
    create_user(data)

    return redirect("/users")


@app.route("/users/toggle/<int:user_id>", methods=["POST"])
@login_required
def toggle_user(user_id):

    toggle_user_status(user_id)
    return redirect("/users")

@app.route("/users/create", methods=["POST"])
@login_required
def users_create():

    data = request.form.to_dict()

    create_user(data)

    return redirect("/users")

@app.route("/wip/<module>")
@login_required
def wip(module):

    return render_template(
        "maintenance.html",
        module=module
    )

@app.route("/fail-units", methods=["GET", "POST"])
@login_required
def send_fae():

    if "user_id" not in session:
        return redirect("/")

    if request.method == "POST":

        serial = (request.form.get("serial_number") or "").strip()
        station = (request.form.get("station") or "").strip()
        error_code = (request.form.get("error_code") or "").strip()
        error_desc = (request.form.get("error_desc") or "").strip()

        employee = session.get("employee_number")
        stage_before = get_stage_actual(serial)

        if not all([serial, station, error_code, error_desc]):
            flash("All fields required")
            return redirect("/fail-units")

        if _is_emr_station(station):
            flash("EMR units cannot be sent to FAE")
            return redirect("/fail-units")

        sync_pending_for_serial(serial)

        if has_pending_fae(serial):
            flash(f"{serial} already pending in FAE")
            return redirect("/fail-units")

        confirmed, stage_after = _send_to_fae_and_confirm(
            serial=serial,
            employee_id=employee,
            station=station,
            stage_code=stage_before,
            error_code=error_code,
            error_desc=error_desc
        )

        if not confirmed:
            flash("Unit not confirmed in RN")
            return redirect("/fail-units")

        insert_issue(
            employee_id=employee,
            serial_number=serial,
            stage=stage_after,
            station=station,
            error_code=error_code,
            error_desc=error_desc
        )

        insert_fae_queue(
            serial=serial,
            employee_id=employee,
            stage=stage_after,
            station=station,
            error_code=error_code,
            error_desc=error_desc
        )

        flash("Unit sent successfully")
        return redirect("/fail-units")

    return render_template(
        "send_fae/send_unit.html",
        name=session["user_name"]
    )

@app.route("/api/stage")
@login_required
def api_stage():
    serial = request.args.get("serial", "")
    return jsonify({
        "stage": get_stage_actual(serial)
    })

@app.route("/api/fusion_autofill")
@login_required
def api_fusion_autofill():
    serial = request.args.get("serial", "")
    return jsonify(
        fusion_autofill_by_sn(serial)
    )

@app.route("/debug/fusion/<serial>")
@login_required
def debug_fusion(serial):
    result = fusion_autofill_by_sn(serial)

    print("DEBUG FUSION INPUT:", serial)
    print("DEBUG FUSION OUTPUT:", result)

    return jsonify({
        "input": serial,
        "output": result
    })
# RUN SERVER
# =========================
if __name__ == "__main__":

    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", debug=True, port=4321)