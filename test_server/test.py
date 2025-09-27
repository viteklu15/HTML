# server.py
from flask import Flask, request, jsonify, redirect, url_for, render_template_string

app = Flask(__name__)

# "память" сервера (вместо БД)
state = {
    "power": True,                          # питание есть
    "wifi_on": True,                        # тумблер Wi-Fi
    "mac": "12.34.56.78",
    "temp_c": 45,
    "coords": {"lat": 55.73, "lng": 37.61},
    # верхняя линейка статусов
    "coords_status": "pending",             # pending|ok|err
    "gps_status": "pending",                # pending|ok|err
    "inet_status": "pending",               # pending|ok|err
    "rx": {"progress": 0, "rssi_db": -10, "quality": "Подключаем"},
    "tx": {"progress": 0, "rssi_db": -10, "quality": "Подключаем"},
    # экран «Идёт подключение…»
    "attempt": 1,
    "attempt_total": 3,
    "eta_sec": 180,
    # общая индикация
    "system": "pending",                    # pending|ok|warn|err|off
    "modem_off": False
}

# CORS для вашего сайта на :5500
ALLOWED_ORIGIN = "http://127.0.0.1:5500"

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# --------- утилиты парсинга формы ---------
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

def _norm_bool(val):
    # для чекбоксов: "on" или "1" -> True, отсутствие поля -> False
    return str(val).lower() in ("1", "true", "on", "yes")

def apply_form_to_state(form):
    """
    Обновляет state из request.form.
    Поддерживает простые поля, чекбоксы и вложенные словари coords/rx/tx.
    """
    # булевы поля управляем наличием чекбокса
    bool_keys = ["power", "wifi_on", "modem_off"]
    for k in bool_keys:
        state[k] = (k in form)

    # строки
    if "mac" in form:
        state["mac"] = form.get("mac", "").strip()

    # числа
    if "temp_c" in form:
        v = _to_int(form.get("temp_c"), state["temp_c"])
        if v is not None:
            state["temp_c"] = v

    if "attempt" in form:
        v = _to_int(form.get("attempt"), state["attempt"])
        if v is not None:
            state["attempt"] = v

    if "attempt_total" in form:
        v = _to_int(form.get("attempt_total"), state["attempt_total"])
        if v is not None:
            state["attempt_total"] = v

    if "eta_sec" in form:
        v = _to_int(form.get("eta_sec"), state["eta_sec"])
        if v is not None:
            state["eta_sec"] = v

    # селекты-статусы
    if "coords_status" in form:
        val = form.get("coords_status")
        if val in STATUS3:
            state["coords_status"] = val

    if "gps_status" in form:
        val = form.get("gps_status")
        if val in STATUS3:
            state["gps_status"] = val

    if "inet_status" in form:
        val = form.get("inet_status")
        if val in STATUS3:
            state["inet_status"] = val

    if "system" in form:
        val = form.get("system")
        if val in SYSTEM_STATES:
            state["system"] = val

    # вложенные: coords
    if "coords.lat" in form:
        v = _to_float(form.get("coords.lat"), state["coords"].get("lat"))
        if v is not None:
            state["coords"]["lat"] = v

    if "coords.lng" in form:
        v = _to_float(form.get("coords.lng"), state["coords"].get("lng"))
        if v is not None:
            state["coords"]["lng"] = v

    # вложенные: rx
    if "rx.progress" in form:
        v = _to_int(form.get("rx.progress"), state["rx"].get("progress"))
        if v is not None:
            state["rx"]["progress"] = max(0, min(100, v))
    if "rx.rssi_db" in form:
        v = _to_int(form.get("rx.rssi_db"), state["rx"].get("rssi_db"))
        if v is not None:
            state["rx"]["rssi_db"] = v
    if "rx.quality" in form:
        state["rx"]["quality"] = form.get("rx.quality", "").strip() or state["rx"]["quality"]

    # вложенные: tx
    if "tx.progress" in form:
        v = _to_int(form.get("tx.progress"), state["tx"].get("progress"))
        if v is not None:
            state["tx"]["progress"] = max(0, min(100, v))
    if "tx.rssi_db" in form:
        v = _to_int(form.get("tx.rssi_db"), state["tx"].get("rssi_db"))
        if v is not None:
            state["tx"]["rssi_db"] = v
    if "tx.quality" in form:
        state["tx"]["quality"] = form.get("tx.quality", "").strip() or state["tx"]["quality"]

@app.route("/", methods=["GET"])
def index():
    return render_template_string("""
<!doctype html>
<meta charset="utf-8">
<title>Демо-сервер состояния</title>
<style>
  :root { --b:#cfd3da; --r:12px; --fg:#111; --muted:#666; }
  *{box-sizing:border-box}
  body{font:16px/1.5 system-ui, Segoe UI, Roboto, Arial; margin:24px; color:var(--fg)}
  h1{margin:0 0 16px}
  .grid{display:grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr)); gap:16px;}
  .card{border:1px solid var(--b); border-radius:16px; padding:16px; background:#fff}
  .row{display:flex; gap:10px; align-items:center; margin:8px 0}
  label{font-size:13px; color:var(--muted); min-width:140px}
  input[type="text"],input[type="number"],select,textarea{
    width:100%; padding:8px 10px; border:1px solid var(--b); border-radius:10px
  }
  .switch{display:flex; align-items:center; gap:8px}
  .muted{color:var(--muted); font-size:13px}
  button{padding:10px 14px; border:1px solid var(--b); border-radius:12px; background:#f7f8fb; cursor:pointer}
  .footer{display:flex; gap:12px; margin-top:16px}
  code{background:#f5f6f8; padding:2px 6px; border-radius:6px}
</style>

<h1>Демо-сервер состояния</h1>
<p class="muted">Текущая температура по API: <b id="cur">{{ state.temp_c }}</b> ℃ (обновляется раз в секунду)</p>

<form action="{{ url_for('set_all_form') }}" method="post">
  <div class="grid">
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
        <label for="gps_status">Статус GPS</label>
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
    </div>

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
      <div class="row">
        <label for="rx.rssi_db">RX RSSI, dB</label>
        <input id="rx.rssi_db" name="rx.rssi_db" type="number" step="1" value="{{ state.rx.rssi_db }}">
      </div>
      <div class="row">
        <label for="rx.quality">RX качество</label>
        <input id="rx.quality" name="rx.quality" type="text" value="{{ state.rx.quality }}">
      </div>

      <h4>TX</h4>
      <div class="row">
        <label for="tx.progress">Прогресс TX, %</label>
        <input id="tx.progress" name="tx.progress" type="number" min="0" max="100" step="1" value="{{ state.tx.progress }}">
      </div>
      <div class="row">
        <label for="tx.rssi_db">TX RSSI, dB</label>
        <input id="tx.rssi_db" name="tx.rssi_db" type="number" step="1" value="{{ state.tx.rssi_db }}">
      </div>
      <div class="row">
        <label for="tx.quality">TX качество</label>
        <input id="tx.quality" name="tx.quality" type="text" value="{{ state.tx.quality }}">
      </div>
    </div>

    <div class="card">
      <h3>Экран «Идёт подключение…»</h3>
      <div class="row">
        <label for="attempt">Попытка</label>
        <input id="attempt" name="attempt" type="number" step="1" value="{{ state.attempt }}">
      </div>
      <div class="row">
        <label for="attempt_total">Всего попыток</label>
        <input id="attempt_total" name="attempt_total" type="number" step="1" value="{{ state.attempt_total }}">
      </div>
      <div class="row">
        <label for="eta_sec">Осталось, сек</label>
        <input id="eta_sec" name="eta_sec" type="number" step="1" value="{{ state.eta_sec }}">
      </div>
    </div>
  </div>

  <div class="footer">
    <button type="submit">Сохранить все изменения</button>
    <a href="{{ url_for('index') }}"><button type="button">Сброс формы (перезагрузить)</button></a>
  </div>
</form>

<p class="muted" style="margin-top:16px">
  API: <code>GET /api/state</code>, <code>POST /api/state {"temp_c":число, ...}</code>
</p>

<script>
  // Пассивное обновление температуры, чтобы видеть, что API живет
  setInterval(async () => {
    try {
      const r = await fetch("{{ url_for('get_state') }}");
      const d = await r.json();
      document.getElementById('cur').textContent = (d && d.temp_c != null) ? d.temp_c : '-';
    } catch (e) {}
  }, 1000);
</script>
""", state=state, status3=STATUS3, system_states=SYSTEM_STATES)

@app.route("/set", methods=["POST"])
def set_temp_form():
    # (этот маршрут остаётся для совместимости — меняет только temp_c)
    try:
        v = float(request.form.get("temp_c"))
        state["temp_c"] = int(v)
    except Exception:
        pass
    return redirect(url_for('index'))

@app.route("/set_all", methods=["POST"])
def set_all_form():
    apply_form_to_state(request.form)
    return redirect(url_for('index'))

# ---- JSON API ----
@app.route("/api/state", methods=["GET", "POST", "OPTIONS"])
def get_state():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        # Разрешим менять любые известные поля для тестов (включая вложенные)
        for k, v in data.items():
            if k in ("rx", "tx", "coords") and isinstance(v, dict):
                state[k].update(v)
            else:
                state[k] = v
    return jsonify(state)

# совместимость со старым демо (только температура)
@app.route("/api/temp", methods=["GET", "POST", "OPTIONS"])
def get_temp():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "temp_c" in data:
            try:
                state["temp_c"] = int(float(data["temp_c"]))
            except Exception:
                pass
    return jsonify({"temp_c": state["temp_c"]})

if __name__ == "__main__":
    app.add_url_rule("/set_all", view_func=set_all_form, methods=["POST"])
    app.run(host="127.0.0.1", port=8000, debug=True)
