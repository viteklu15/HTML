# server.py
from flask import Flask, request, jsonify, redirect, url_for, render_template_string, abort

app = Flask(__name__)

# "память" сервера (вместо БД)
state = {
    "power": True,
    "wifi_on": True,
    "mac": "12.34.56.78",
    "temp_c": 45,
    "coords": {"lat": 55.73, "lng": 37.61},
    # верхняя линейка статусов
    "coords_status": "pending",   # pending|ok|err
    "gps_status": "pending",      # pending|ok|err
    "inet_status": "pending",     # pending|ok|err
    "rx": {"progress": 0},        # качество/RSSI убраны
    "tx": {"progress": 0},        # качество/RSSI убраны
    # экран «Идёт подключение…»
    "attempt": 1,
    # общая индикация
    "system": "pending",          # pending|ok|warn|err|off
    "modem_off": False,
    # углы
    "angles": {
        "tilt_current": 123,
        "tilt_required": 456,
        "rotate_current": 1860,
        "rotate_required": 1860
    },
    # новые поля под скрин
    "beam_number": 34,            # Номер луча
    # РЧ кластер + поляризация вместе (например: "31/A")
    "rf_cluster_polarization": "31/A",
    # пароль Wi-Fi храним открыто
    "wifi_password": "",
    # логи (макс 10)
    "logs": [
        "Автовыключение — Сработало из-за повышенной температуры\n25.09.2025, 12:41",
        "Температура модема — Высокая: 85℃, Выше нормальной на 56℃\n25.09.2025, 12:34"
    ]
}

# CORS
ALLOWED_ORIGIN = "http://127.0.0.1:5500"

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# --------- утилиты ---------
STATUS3 = ["pending", "ok", "err"]
SYSTEM_STATES = ["pending", "ok", "warn", "err", "off"]

def _to_int(v, default=None):
    try:
        return int(float(v))
    except Exception:
        return default

def _to_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default

def add_log(line: str):
    state["logs"].append(line)
    if len(state["logs"]) > 10:
        state["logs"] = state["logs"][-10:]

def apply_form_to_state(form):
    # булевы
    for k in ["power", "wifi_on", "modem_off"]:
        state[k] = (k in form)

    # строки/числа
    if "mac" in form:
        state["mac"] = form.get("mac", "").strip()

    if "temp_c" in form:
        v = _to_int(form.get("temp_c"), state["temp_c"])
        if v is not None:
            state["temp_c"] = v

    # попытка
    if "attempt" in form:
        v = _to_int(form.get("attempt"), state["attempt"])
        if v is not None:
            state["attempt"] = v

    # статусы
    if form.get("coords_status") in STATUS3:
        state["coords_status"] = form.get("coords_status")
    if form.get("gps_status") in STATUS3:
        state["gps_status"] = form.get("gps_status")
    if form.get("inet_status") in STATUS3:
        state["inet_status"] = form.get("inet_status")
    if form.get("system") in SYSTEM_STATES:
        state["system"] = form.get("system")

    # coords
    if "coords.lat" in form:
        v = _to_float(form.get("coords.lat"), state["coords"]["lat"])
        if v is not None:
            state["coords"]["lat"] = v
    if "coords.lng" in form:
        v = _to_float(form.get("coords.lng"), state["coords"]["lng"])
        if v is not None:
            state["coords"]["lng"] = v

    # rx/tx progress
    if "rx.progress" in form:
        v = _to_int(form.get("rx.progress"), state["rx"]["progress"])
        if v is not None:
            state["rx"]["progress"] = max(0, min(100, v))
    if "tx.progress" in form:
        v = _to_int(form.get("tx.progress"), state["tx"]["progress"])
        if v is not None:
            state["tx"]["progress"] = max(0, min(100, v))

    # углы
    for k in ("angles.tilt_current","angles.tilt_required","angles.rotate_current","angles.rotate_required"):
        if k in form:
            v = _to_int(form.get(k), None)
            if v is not None:
                state["angles"][k.split(".",1)[1]] = v

    # новые поля (как на скрине)
    if "beam_number" in form:
        v = _to_int(form.get("beam_number"), state["beam_number"])
        if v is not None:
            state["beam_number"] = v

    # РЧ кластер / поляризация -> сохраняем как одну строку "31/A"
    # Если прислали хотя бы одно из двух полей — пересобираем значение
    if ("rf_cluster" in form) or ("polarization" in form):
        cluster = form.get("rf_cluster", "").strip()
        pol = form.get("polarization", "").strip()
        if cluster or pol:
            state["rf_cluster_polarization"] = f"{cluster}/{pol}"

    # Wi-Fi пароль — сохраняем как есть
    if "wifi_password" in form:
        state["wifi_password"] = form.get("wifi_password", "")

    # новый лог из формы
    if form.get("new_log", "").strip():
        add_log(form.get("new_log").strip())

# --------- страницы ---------
@app.route("/", methods=["GET"])
def index():
    return render_template_string("""
<!doctype html>
<meta charset="utf-8">
<title>Демо-сервер состояния</title>
<style>
  :root { --b:#cfd3da; --fg:#111; --muted:#666; }
  *{box-sizing:border-box}
  body{font:16px/1.5 system-ui, Segoe UI, Roboto, Arial; margin:24px; color:var(--fg)}
  h1{margin:0 0 16px}

  /* Фиксированная сетка 3×3 */
  .grid{
    display:grid;
    grid-template-columns: repeat(3, 1fr); /* всегда 3 колонки */
    gap:16px;
  }

  .card{border:1px solid var(--b); border-radius:12px; padding:16px; background:#fff}
  .row{display:flex; gap:10px; align-items:center; margin:8px 0}
  .row.split{gap:6px}
  label{font-size:13px; color:var(--muted); min-width:180px}

  /* Общие поля ввода — повышаем читабельность */
  input[type="text"],
  input[type="number"],
  input[type="password"],
  select{
    width:100%;
    height:40px;
    padding:8px 12px;
    font-size:16px;
    line-height:1.2;
    border:1px solid var(--b);
    border-radius:10px;
  }

  .switch{display:flex; align-items:center; gap:8px}
  .muted{color:var(--muted); font-size:13px}
  button{padding:10px 14px; border:1px solid var(--b); border-radius:10px; background:#f7f8fb; cursor:pointer}
  .footer{display:flex; gap:12px; margin-top:16px}
  ul{margin:0; padding-left:18px; font-size:14px}
  .log-line{white-space:pre-line}

  /* Маленькие поля + разделитель */
  .slash{min-width:16px; text-align:center; font-weight:600}
  .mini{width:140px; min-width:120px}
  .mini-sm{width:110px; min-width:96px; font-size:18px;} /* крупнее шрифт у коротких полей */
  #rf_cluster, #polarization{ text-align:center; }
</style>

<h1>Демо-сервер состояния</h1>
<p class="muted">Текущая температура по API: <b id="cur">{{ state.temp_c }}</b> ℃ (обновляется раз в секунду)</p>

<form action="{{ url_for('set_all_form') }}" method="post">
  <div class="grid">
    <!-- Питание и сеть -->
    <div class="card">
      <h3>Питание и сеть</h3>
      <div class="row switch">
        <input id="power" name="power" type="checkbox" {% if state.power %}checked{% endif %}>
        <label for="power">Питание (power)</label>
      </div>
      <div class="row switch">
        <input id="wifi_on" name="wifi_on" type="checkbox" {% if state.wifi_on %}checked{% endif %}>
        <label for="wifi_on">Wi-Fi включён (wifi_on)</label>
      </div>

      <div class="row">
        <label for="wifi_password">Пароль Wi-Fi</label>
        <input id="wifi_password" name="wifi_password" type="text" value="{{ state.wifi_password }}" placeholder="Пароль сети">
      </div>

      <div class="row">
        <label for="mac">MAC / ID</label>
        <input id="mac" name="mac" type="text" value="{{ state.mac }}">
      </div>

      <div class="row switch">
        <input id="modem_off" name="modem_off" type="checkbox" {% if state.modem_off %}checked{% endif %}>
        <label for="modem_off">Модем выключен (modem_off)</label>
      </div>

      <div class="row">
        <label for="system">Состояние системы</label>
        <select id="system" name="system">
          {% for opt in system_states %}
            <option value="{{ opt }}" {% if state.system==opt %}selected{% endif %}>{{ opt }}</option>
          {% endfor %}
        </select>
      </div>
    </div>

    <!-- Координаты и статусы -->
    <div class="card">
      <h3>Координаты и статусы</h3>
      <div class="row">
        <label for="coords.lat">Широта (lat)</label>
        <input id="coords.lat" name="coords.lat" type="number" step="0.000001" value="{{ state.coords.lat }}">
      </div>
      <div class="row">
        <label for="coords.lng">Долгота (lng)</label>
        <input id="coords.lng" name="coords.lng" type="number" step="0.000001" value="{{ state.coords.lng }}">
      </div>
      <div class="row">
        <label for="coords_status">Статус координат</label>
        <select id="coords_status" name="coords_status">
          {% for opt in status3 %}
            <option value="{{ opt }}" {% if state.coords_status==opt %}selected{% endif %}>{{ opt }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="row">
        <label for="gps_status">Связь со спутником</label>
        <select id="gps_status" name="gps_status">
          {% for opt in status3 %}
            <option value="{{ opt }}" {% if state.gps_status==opt %}selected{% endif %}>{{ opt }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="row">
        <label for="inet_status">Статус интернета</label>
        <select id="inet_status" name="inet_status">
          {% for opt in status3 %}
            <option value="{{ opt }}" {% if state.inet_status==opt %}selected{% endif %}>{{ opt }}</option>
          {% endfor %}
        </select>
      </div>

      <!-- Номер луча -->
      <div class="row">
        <label for="beam_number">Номер луча в радио-частотном (РЧ) кластере</label>
        <input id="beam_number" name="beam_number" class="mini" type="number" step="1" value="{{ state.beam_number }}">
      </div>

      <!-- РЧ кластер / поляризация (редактируем по отдельности, сохраняем как "X/Y") -->
      {% set parts = (state.rf_cluster_polarization or '').split('/') %}
      <div class="row split">
        <label for="rf_cluster">РЧ кластер / поляризация</label>
        <input id="rf_cluster" name="rf_cluster" class="mini-sm" type="number" step="1" value="{{ parts[0] if parts|length>0 else '' }}">
        <div class="slash">/</div>
        <input id="polarization" name="polarization" class="mini-sm" type="text" maxlength="2" placeholder="A/B" value="{{ parts[1] if parts|length>1 else '' }}">
      </div>
    </div>

    <!-- Температура и подключение -->
    <div class="card">
      <h3>Температура и подключение</h3>
      <div class="row">
        <label for="temp_c">Температура, ℃</label>
        <input id="temp_c" name="temp_c" type="number" step="1" value="{{ state.temp_c }}">
      </div>

      <h4>RX</h4>
      <div class="row">
        <label for="rx.progress">Прогресс RX, %</label>
        <input id="rx.progress" name="rx.progress" type="number" min="0" max="100" step="1" value="{{ state.rx.progress }}">
      </div>

      <h4>TX</h4>
      <div class="row">
        <label for="tx.progress">Прогресс TX, %</label>
        <input id="tx.progress" name="tx.progress" type="number" min="0" max="100" step="1" value="{{ state.tx.progress }}">
      </div>
    </div>

    <!-- Экран «Идёт подключение…» -->
    <div class="card">
      <h3>Экран «Идёт подключение…»</h3>
      <div class="row">
        <label for="attempt">Попытка</label>
        <input id="attempt" name="attempt" type="number" step="1" value="{{ state.attempt }}">
      </div>
    </div>

    <!-- Углы -->
    <div class="card">
      <h3>Углы антенного поста</h3>
      <div class="row">
        <label for="angles.tilt_current">Угол наклона — текущий</label>
        <input id="angles.tilt_current" name="angles.tilt_current" type="number" step="1" value="{{ state.angles.tilt_current }}">
      </div>
      <div class="row">
        <label for="angles.tilt_required">Угол наклона — требуемый</label>
        <input id="angles.tilt_required" name="angles.tilt_required" type="number" step="1" value="{{ state.angles.tilt_required }}">
      </div>
      <div class="row">
        <label for="angles.rotate_current">Угол поворота — текущий</label>
        <input id="angles.rotate_current" name="angles.rotate_current" type="number" step="1" value="{{ state.angles.rotate_current }}">
      </div>
      <div class="row">
        <label for="angles.rotate_required">Угол поворота — требуемый</label>
        <input id="angles.rotate_required" name="angles.rotate_required" type="number" step="1" value="{{ state.angles.rotate_required }}">
      </div>
    </div>

    <!-- Логи -->
    <div class="card">
      <h3>Логи</h3>
      <ul>
        {% for line in state.logs %}
          <li class="log-line">{{ line }}</li>
        {% else %}
          <li><i>Нет логов</i></li>
        {% endfor %}
      </ul>
      <div class="row">
        <label for="new_log">Добавить лог</label>
        <input id="new_log" name="new_log" type="text" placeholder="Текст лога">
      </div>
    </div>
  </div>

  <div class="footer">
    <button type="submit">Сохранить все изменения</button>
    <a href="{{ url_for('index') }}"><button type="button">Сброс формы (перезагрузить)</button></a>
  </div>
</form>

<p class="muted" style="margin-top:16px">
  API: <code>GET /api/state</code>, <code>POST /api/state</code>,
  <code>GET /api/logs</code>, <code>POST /api/log {"line":"..."}</code>
</p>

<script>
  // Пассивное обновление температуры
  setInterval(async () => {
    try {
      const r = await fetch("{{ url_for('get_state') }}");
      const d = await r.json();
      document.getElementById('cur').textContent = (d && d.temp_c != null) ? d.temp_c : '-';
    } catch (e) {}
  }, 1000);
</script>
""", state=state, status3=STATUS3, system_states=SYSTEM_STATES)

@app.route("/set_all", methods=["POST"])
def set_all_form():
    apply_form_to_state(request.form)
    return redirect(url_for('index'))

# ---- JSON API ----
@app.route("/api/state", methods=["GET", "POST", "OPTIONS"])
def get_state():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for k, v in data.items():
            if k in ("rx", "tx", "coords", "angles") and isinstance(v, dict):
                state[k].update(v)
            elif k == "logs" and isinstance(v, list):
                for line in v:
                    add_log(str(line))
            else:
                state[k] = v
    return jsonify(state)

@app.route("/api/logs", methods=["GET"])
def get_logs():
    return jsonify({"logs": state["logs"]})

@app.route("/api/log", methods=["POST"])
def add_log_api():
    data = request.get_json(silent=True) or {}
    line = data.get("line")
    if not line:
        abort(400, "no 'line'")
    add_log(str(line))
    return jsonify({"logs": state["logs"]})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
