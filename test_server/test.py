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
    "rx": {"progress": 0},
    "tx": {"progress": 0},
    # экран «Идёт подключение…»
    "attempt": 1,
    # общая индикация
    "system": "pending",          # pending|ok|warn|err|off
    "modem_off_temp": False,
    # углы
    "angles": {
        "tilt_current": 123,
        "tilt_required": 456,
        "rotate_current": 1860,
        "rotate_required": 1860
    },
    # новые поля под скрин
    "beam_number": 34,            # Номер луча
    "rf_cluster_polarization": "31/A",
    # пароль Wi-Fi храним открыто
    "wifi_password": "12345678",
    # логи (макс 10)
    "logs": [
        "Автовыключение — Сработало из-за повышенной температуры\n25.09.2025, 12:41",
        "Температура модема — Высокая: 85℃, Выше нормальной на 56℃\n25.09.2025, 12:34"
    ]
}

# ===== CORS/Cache =====
# Разрешаем фронт с Go Live и file:// (Origin: null) — для DEV.
ALLOWED_ORIGINS = {
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "null",  # когда страница открыта как file://…
}

@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get("Origin")
    # Разрешаем, если origin явный и в списке, либо Origin отсутствует (некоторые простые GET)
    if origin in ALLOWED_ORIGINS or origin is None:
        resp.headers["Access-Control-Allow-Origin"] = origin or "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        # эхоим запрошенные заголовки, чтобы preflight не падал
        req_hdrs = request.headers.get("Access-Control-Request-Headers", "Content-Type")
        resp.headers["Access-Control-Allow-Headers"] = req_hdrs
        resp.headers["Vary"] = "Origin"
    # no-cache для демо-API
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

# Универсальный preflight для /api/*
@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return ("", 204)

# ===== утилиты =====
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
    for k in ["power", "wifi_on", "modem_off_temp"]:
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

    # РЧ кластер / поляризация -> сохраняем как одну строку "X/Y"
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

# ===== HTML демо-страница =====
@app.route("/", methods=["GET"])
def index():
    return render_template_string("""<!doctype html>
<meta charset="utf-8">
<title>Демо-сервер состояния</title>
<style>
  :root { --b:#cfd3da; --fg:#111; --muted:#666; }
  *{box-sizing:border-box}
  body{font:16px/1.5 system-ui, Segoe UI, Roboto, Arial; margin:24px; color:var(--fg)}
  h1{margin:0 0 16px}
  .grid{display:grid; grid-template-columns: repeat(3, 1fr); gap:16px}
  .card{border:1px solid var(--b); border-radius:12px; padding:16px; background:#fff}
  .row{display:flex; gap:10px; align-items:center; margin:8px 0}
  .row.split{gap:6px}
  label{font-size:13px; color:var(--muted); min-width:180px}
  input[type="text"],input[type="number"],input[type="password"],select{
    width:100%; height:40px; padding:8px 12px; font-size:16px; line-height:1.2;
    border:1px solid var(--b); border-radius:10px;
  }
  .switch{display:flex; align-items:center; gap:8px}
  .muted{color:var(--muted); font-size:13px}
  button{padding:10px 14px; border:1px solid var(--b); border-radius:10px; background:#f7f8fb; cursor:pointer}
  .footer{display:flex; gap:12px; margin-top:16px}
  ul{margin:0; padding-left:18px; font-size:14px}
  .log-line{white-space:pre-line}
  .slash{min-width:16px; text-align:center; font-weight:600}
  .mini{width:140px; min-width:120px}
  .mini-sm{width:110px; min-width:96px; font-size:18px;}
  #rf_cluster, #polarization{ text-align:center; }
</style>
<h1>Демо-сервер состояния</h1>
<p class="muted">Текущая температура по API: <b id="cur">{{ state.temp_c }}</b> ℃ (обновляется раз в секунду)</p>
<form action="{{ url_for('set_all_form') }}" method="post">
  <div class="grid">
    <div class="card">
      <h3>Питание и сеть</h3>
      <div class="row switch">
        <input id="power" name="power" type="checkbox" {% if state.power %}checked{% endif %}>
        <label for="power">Питание модема (power)</label>
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
        <input id="modem_off_temp" name="modem_off_temp" type="checkbox" {% if state.modem_off_temp %}checked{% endif %}>
        <label for="modem_off_temp">Выключать автоматически при опасных температурах (modem_off_temp)</label>
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
      <div class="row">
        <label for="beam_number">Номер луча в РЧ кластере</label>
        <input id="beam_number" name="beam_number" class="mini" type="number" step="1" value="{{ state.beam_number }}">
      </div>
      {% set parts = (state.rf_cluster_polarization or '').split('/') %}
      <div class="row split">
        <label for="rf_cluster">РЧ кластер / поляризация</label>
        <input id="rf_cluster" name="rf_cluster" class="mini-sm" type="number" step="1" value="{{ parts[0] if parts|length>0 else '' }}">
        <div class="slash">/</div>
        <input id="polarization" name="polarization" class="mini-sm" type="text" maxlength="2" placeholder="A/B" value="{{ parts[1] if parts|length>1 else '' }}">
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
      <h4>TX</h4>
      <div class="row">
        <label for="tx.progress">Прогресс TX, %</label>
        <input id="tx.progress" name="tx.progress" type="number" min="0" max="100" step="1" value="{{ state.tx.progress }}">
      </div>
    </div>

    <div class="card">
      <h3>Экран «Идёт подключение…»</h3>
      <div class="row">
        <label for="attempt">Попытка</label>
        <input id="attempt" name="attempt" type="number" step="1" value="{{ state.attempt }}">
      </div>
    </div>

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
/* ===== Помощники ===== */
function setIfIdle(el, value) {
  // Не перезаписываем, если пользователь редактирует
  if (!el) return;
  if (el.matches(':focus')) return;
  if (el.dataset.userEditing === '1') return;

  if (el.type === 'checkbox') {
    el.checked = Boolean(value);
  } else if (el.tagName === 'SELECT') {
    el.value = value ?? '';
  } else if (el.tagName === 'INPUT') {
    // Сравнение, чтобы не дёргать DOM понапрасну
    const v = value ?? '';
    if (el.value !== String(v)) el.value = v;
  } else {
    el.textContent = value ?? '';
  }
}

function bindUserEditingGuards() {
  // Помечаем поля как "редактируемые пользователем"
  const controls = document.querySelectorAll('input, select, textarea');
  controls.forEach(el => {
    // Любое изменение — ставим метку
    el.addEventListener('input', () => { el.dataset.userEditing = '1'; });
    el.addEventListener('change', () => { el.dataset.userEditing = '1'; });
    // Потеря фокуса — снимаем метку
    el.addEventListener('blur', () => { delete el.dataset.userEditing; });
  });

  // При отправке формы снимаем метки со всех полей (чтобы после POST всё снова подтягивалось)
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', () => {
      document.querySelectorAll('[data-user-editing="1"]').forEach(el => {
        delete el.dataset.userEditing;
      });
    });
  }
}

async function refreshState() {
  try {
    const resp = await fetch('/api/state', { cache: 'no-store' });
    const data = await resp.json();

    // Температура в шапке
    setIfIdle(document.getElementById('cur'), data.temp_c);

    // Простые корневые поля с id совпадающими с ключами
    const simpleIds = ['power','wifi_on','wifi_password','mac','modem_off_temp','system','temp_c','attempt','beam_number','coords_status','gps_status','inet_status'];
    simpleIds.forEach(id => setIfIdle(document.getElementById(id), data[id]));

    // coords
    if (data.coords) {
      setIfIdle(document.getElementById('coords.lat'), data.coords.lat);
      setIfIdle(document.getElementById('coords.lng'), data.coords.lng);
    }

    // rx/tx progress
    if (data.rx) setIfIdle(document.getElementById('rx.progress'), data.rx.progress);
    if (data.tx) setIfIdle(document.getElementById('tx.progress'), data.tx.progress);

    // углы
    if (data.angles) {
      setIfIdle(document.getElementById('angles.tilt_current'),  data.angles.tilt_current);
      setIfIdle(document.getElementById('angles.tilt_required'), data.angles.tilt_required);
      setIfIdle(document.getElementById('angles.rotate_current'),  data.angles.rotate_current);
      setIfIdle(document.getElementById('angles.rotate_required'), data.angles.rotate_required);
    }

    // РЧ кластер / поляризация: ожидаем строку вида "31/A"
    if (typeof data.rf_cluster_polarization === 'string') {
      const [cluster = '', pol = ''] = data.rf_cluster_polarization.split('/');
      setIfIdle(document.getElementById('rf_cluster'), cluster);
      setIfIdle(document.getElementById('polarization'), pol);
    }

    // Логи (если на странице только один <ul> с логами — как в макете)
    const ul = document.querySelector('ul');
    if (ul) {
      // Не перетираем, если пользователь прямо сейчас печатает новый лог в инпуте
      const newLogInput = document.getElementById('new_log');
      const userBusy = newLogInput && (newLogInput.matches(':focus') || newLogInput.dataset.userEditing === '1');

      if (!userBusy) {
        ul.innerHTML = '';
        if (Array.isArray(data.logs) && data.logs.length) {
          data.logs.forEach(line => {
            const li = document.createElement('li');
            li.className = 'log-line';
            li.textContent = String(line);
            ul.appendChild(li);
          });
        } else {
          ul.innerHTML = '<li><i>Нет логов</i></li>';
        }
      }
    }

  } catch (e) {
    console.error('refreshState failed', e);
  }
}

// Инициализация
bindUserEditingGuards();
refreshState();
setInterval(refreshState, 2000);
</script>

""", state=state, status3=STATUS3, system_states=SYSTEM_STATES)

@app.route("/set_all", methods=["POST"])
def set_all_form():
    apply_form_to_state(request.form)
    return redirect(url_for('index'))

# ===== JSON API =====
@app.route("/api/state", methods=["GET", "POST"])
def api_state():
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

# ===== Эндпоинты, которые дергает фронт (GET с query) =====
@app.route("/api/wifi", methods=["GET"])
def api_wifi():
    v = (request.args.get("state") or "").lower()
    state["wifi_on"] = (v == "on")
    return jsonify({"ok": True, "wifi_on": state["wifi_on"]})

@app.route("/api/coords/save", methods=["GET"])
def api_coords_save():
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if lat is not None:
        vv = _to_float(lat, None)
        if vv is not None: state["coords"]["lat"] = vv
    if lng is not None:
        vv = _to_float(lng, None)
        if vv is not None: state["coords"]["lng"] = vv
    return jsonify({"ok": True, "coords": state["coords"]})

@app.route("/api/wifi/password", methods=["GET"])
def api_wifi_password():
    pwd = request.args.get("password", "")
    state["wifi_password"] = pwd
    return jsonify({"ok": True, "wifi_password": state["wifi_password"]})

@app.route("/api/modem/power", methods=["GET"])
def api_modem_power():
    v = (request.args.get("state") or "").lower()
    state["power"] = (v == "on")
    return jsonify({"ok": True, "power": state["power"]})

@app.route("/api/modem/off-temp", methods=["GET"])
def api_modem_off_temp():
    v = (request.args.get("state") or "").lower()
    state["modem_off_temp"] = (v == "on")
    return jsonify({"ok": True, "modem_off_temp": state["modem_off_temp"]})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
