#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, threading, mimetypes, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

# ---- pyserial может отсутствовать: безопасно обрабатываем ----
try:
    import serial
    import serial.serialutil
except Exception:
    serial = None

# ================== НАСТРОЙКИ (можно переопределять через ENV) ==================
IS_WIN      = (os.name == "nt")
SERIAL_PORT = os.environ.get("SERIAL_PORT", "COM3" if IS_WIN else "/dev/ttyS1")
BAUD_RATE   = int(os.environ.get("BAUD_RATE", "115200"))
HTTP_HOST   = os.environ.get("HTTP_HOST", "127.0.0.1")      # локально, чтобы Windows не ругался
HTTP_PORT   = int(os.environ.get("HTTP_PORT", "18080"))     # не 8080, чтобы реже конфликтовать
INDEX_FILE  = os.environ.get("INDEX_FILE", "index.html")
DOC_ROOT    = os.path.abspath(os.environ.get("DOC_ROOT", "."))

# Эмуляция температуры, если нет UART (или просто для теста).
FAKE_TEMP   = os.environ.get("FAKE_TEMP", "1") in ("1", "true", "True")
FAKE_PERIOD = float(os.environ.get("FAKE_PERIOD", "2.0"))

# ================== СОСТОЯНИЕ ==================
STATE_LOCK = threading.Lock()
STATE = {
    "power": True,
    "wifi_on": True,
    "mac": "12.34.56.78",
    "temp_c": 45.0,
    "coords": {"lat": 55.73, "lng": 37.61},
    "coords_status": "pending",
    "gps_status": "pending",
    "inet_status": "pending",
    "rx": {"progress": 57},
    "tx": {"progress": 0},
    "attempt": 1,
    "system": "pending",
    "modem_off_temp": False,
    "angles": {
        "tilt_current": 123,
        "tilt_required": 456,
        "rotate_current": 1860,
        "rotate_required": 1860,
    },
    "beam_number": 34,
    "rf_cluster_polarization": "31/A",
    "wifi_password": "12345678",
    "logs": ["log1", "log2"],
    "last_update": None,
}

# ================== ЛОГГЕР ==================
def log(*a):
    print("[srv]", *a, file=sys.stderr, flush=True)

# ================== UART ==================
SER = None
SER_LOCK = threading.Lock()

def ensure_serial():
    """Ленивая инициализация порта. Не падаем, если нет pyserial/порта."""
    global SER
    if serial is None:
        return False
    try:
        if SER is None or not SER.is_open:
            SER = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            log("UART opened:", SERIAL_PORT, BAUD_RATE)
        return True
    except Exception as e:
        log(f"serial open failed ({SERIAL_PORT}):", e)
        return False

def uart_reader():
    """Читает строки JSON вида {"TEMP": число} и обновляет STATE."""
    if serial is None:
        log("pyserial не установлен — поток UART выключен")
        return
    while True:
        try:
            if not ensure_serial():
                time.sleep(1.0)
                continue
            raw = SER.readline()
            if not raw:
                continue
            try:
                text = raw.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            # фильтр печатных символов
            text = "".join(ch for ch in text if ch in "\r\n\t" or (32 <= ord(ch) <= 126)).strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict) and "TEMP" in obj:
                try:
                    val = float(obj["TEMP"])
                except Exception:
                    continue
                with STATE_LOCK:
                    STATE["temp_c"] = val
                    STATE["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            log("uart_reader err:", e)
            # мягкая пауза, затем попытаемся снова
            time.sleep(0.5)

def fake_temp_generator():
    """Эмулятор температуры, если нет реального UART."""
    t = 45.0
    direction = +0.5
    while True:
        with STATE_LOCK:
            # лёгкая пила в пределах 35..65
            t += direction
            if t > 65: direction = -0.5
            if t < 35: direction = +0.5
            STATE["temp_c"] = round(t, 2)
            STATE["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(FAKE_PERIOD)

# ================== HTTP ==================
def safe_local_path(url_path: str) -> str:
    """Безопасное сопоставление URL → локальный путь в DOC_ROOT."""
    path = unquote(url_path)
    if path.startswith("/"):
        path = path[1:]
    full = os.path.abspath(os.path.join(DOC_ROOT, path))
    if not (full == DOC_ROOT or full.startswith(DOC_ROOT + os.sep)):
        return ""  # попытка выхода из каталога
    return full

class Handler(BaseHTTPRequestHandler):
    server_version = "HLK7688AHTTP/1.1"

    def _send(self, code:int, ctype:str, body:bytes=b""):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        # не кэшируем JSON/HTML в отладке
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            path = u.path

            # --- API
            if path == "/api/state":
                with STATE_LOCK:
                    body = json.dumps(STATE, ensure_ascii=False).encode("utf-8")
                return self._send(200, "application/json; charset=utf-8", body)

            if path == "/api/modem/power":
                q = parse_qs(u.query)
                state_val = (q.get("state", [""])[0] or "").lower()
                with STATE_LOCK:
                    if   state_val == "on":  STATE["power"] = True
                    elif state_val == "off": STATE["power"] = False
                return self._send(204, "text/plain; charset=utf-8")

            if path == "/api/modem/off-temp":
                q = parse_qs(u.query)
                state_val = (q.get("state", [""])[0] or "").lower()
                with STATE_LOCK:
                    if   state_val == "on":  STATE["modem_off_temp"] = True
                    elif state_val == "off": STATE["modem_off_temp"] = False
                return self._send(204, "text/plain; charset=utf-8")

            if path == "/api/wifi":
                q = parse_qs(u.query)
                state_val = (q.get("state", [""])[0] or "").lower()
                with STATE_LOCK:
                    if   state_val == "on":  STATE["wifi_on"] = True
                    elif state_val == "off": STATE["wifi_on"] = False
                return self._send(204, "text/plain; charset=utf-8")

            # --- Корень: строго index.html
            if path == "/":
                index_path = os.path.join(DOC_ROOT, INDEX_FILE)
                if os.path.isfile(index_path):
                    with open(index_path, "rb") as f:
                        data = f.read()
                    return self._send(200, "text/html; charset=utf-8", data)
                return self._send(404, "text/plain; charset=utf-8", b"index.html not found")

            # --- Раздача статики
            local = safe_local_path(path)
            if local and os.path.isfile(local):
                ctype, _ = mimetypes.guess_type(local)
                if not ctype:
                    ctype = "application/octet-stream"
                with open(local, "rb") as f:
                    data = f.read()
                return self._send(200, ctype, data)

            # --- Остальное
            return self._send(404, "text/plain; charset=utf-8", b"Not found")

        except Exception as e:
            log("GET err:", e)
            try: self._send(500, "text/plain; charset=utf-8", b"Server error")
            except: pass

    def do_POST(self):
        return self._send(404, "text/plain; charset=utf-8", b"Not found")

def bind_http_with_fallback(host:str, port:int):
    """Пробуем привязать HTTP. Если PermissionError — уходим на 127.0.0.1:0 (автопорт)."""
    try:
        httpd = HTTPServer((host, port), Handler)
        return httpd
    except PermissionError as e:
        log(f"bind PermissionError on {host}:{port} -> fallback to 127.0.0.1:0")
        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        return httpd
    except OSError as e:
        # например, недопустимый адрес или занят порт — тоже попробуем фолбэк
        log(f"bind OSError on {host}:{port} -> fallback to 127.0.0.1:0 ({e})")
        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        return httpd

def main():
    # UART поток (если pyserial есть)
    if serial is not None:
        threading.Thread(target=uart_reader, daemon=True).start()
    else:
        log("pyserial отсутствует — установите: pip install pyserial")

    # Эмуляция температуры (по умолчанию включена)
    if FAKE_TEMP:
        threading.Thread(target=fake_temp_generator, daemon=True).start()
        log("FAKE_TEMP активен — температура будет эмулироваться")

    # HTTP + фолбэк
    httpd = bind_http_with_fallback(HTTP_HOST, HTTP_PORT)
    bind_host, bind_port = httpd.server_address  # фактический адрес
    log(f"HTTP listening on {bind_host}:{bind_port} (docroot: {DOC_ROOT})")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
