#!/usr/bin/env python3
"""
Cotizaciones BNA - Launcher
Doble clic para iniciar. Abre la app en el navegador automáticamente.
"""
import sys
import os
import json
import time
import threading
import webbrowser
import base64
import tempfile
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from html.parser import HTMLParser
import urllib.request

# ── HTML embebido (no requiere archivo externo) ────────────
from html_embedded import HTML_B64
HTML_BYTES = base64.b64decode(HTML_B64)

PORT = 8765
CACHE_SECONDS = 120

# ── Auto-updater ───────────────────────────────────────────
VERSION = "1.0.0"
GITHUB_USER = "lautaro-aictrl"
GITHUB_REPO = "cotizaciones-bna"
GITHUB_API  = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/artifacts"

def check_for_update():
    """
    Verifica si hay un .exe más nuevo en GitHub Actions.
    Si lo hay, descarga y reemplaza el ejecutable actual.
    """
    try:
        print("[Updater] Verificando actualizaciones...")
        req = urllib.request.Request(
            GITHUB_API + "?per_page=1",
            headers={"User-Agent": "CotizacionesBNA-Updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        artifacts = data.get("artifacts", [])
        if not artifacts:
            print("[Updater] No hay artifacts disponibles")
            return

        latest = artifacts[0]
        artifact_id   = latest["id"]
        artifact_name = latest["name"]
        created_at    = latest["created_at"]

        # Guardar el último artifact visto
        state_file = os.path.join(tempfile.gettempdir(), "bna_last_artifact.txt")
        last_id = None
        if os.path.exists(state_file):
            with open(state_file) as f:
                last_id = f.read().strip()

        if str(artifact_id) == last_id:
            print(f"[Updater] Ya tenés la última versión (artifact {artifact_id})")
            return

        print(f"[Updater] Nueva versión disponible: {artifact_name} ({created_at})")

        # Notificar al usuario vía página web
        global UPDATE_AVAILABLE, UPDATE_INFO
        UPDATE_AVAILABLE = True
        UPDATE_INFO = {
            "artifact_id": artifact_id,
            "created_at": created_at,
            "download_url": f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/actions"
        }

        # Guardar nuevo ID
        with open(state_file, "w") as f:
            f.write(str(artifact_id))

    except Exception as e:
        print(f"[Updater] Error verificando actualizaciones: {e}")

UPDATE_AVAILABLE = False
UPDATE_INFO = {}

# ── Icono en bandeja del sistema (solo Windows) ─────────────
def setup_tray():
    """Ícono en system tray para cerrar la app desde ahí."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), color=(15, 20, 30))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=(34, 197, 94))

        def on_abrir(icon, item):
            webbrowser.open(f"http://localhost:{PORT}/app")

        def on_salir(icon, item):
            icon.stop()
            os._exit(0)

        icon = pystray.Icon(
            "BNA Cotizaciones",
            img,
            "Cotizaciones BNA",
            menu=pystray.Menu(
                pystray.MenuItem("Abrir app", on_abrir, default=True),
                pystray.MenuItem("Cerrar", on_salir),
            )
        )
        icon.run()
    except ImportError:
        pass

# ── Parser HTML del BNA ────────────────────────────────────
class BNAParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_row = []
        self.current_cell = ""
        self.in_cell = False
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "td":
            self.current_row.append(self.current_cell.strip())
            self.in_cell = False
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data

def parse_ar(s):
    if not s:
        return None
    s = s.strip().replace("\xa0", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None

def scrape_bna_divisas():
    url = "https://www.bna.com.ar/Cotizador/Monedas"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-AR,es;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    parser = BNAParser()
    parser.feed(html)
    for row in parser.rows:
        if len(row) >= 3 and "dolar u.s.a" in row[0].lower():
            for i in range(1, len(row) - 1):
                compra = parse_ar(row[i])
                venta = parse_ar(row[i + 1])
                if compra and venta and venta > compra and (venta - compra) < 100 and venta > 500:
                    return {"compra": compra, "venta": venta}
    return None

def fetch_dolarapi(casa):
    url = f"https://dolarapi.com/v1/dolares/{casa}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

# ── Cache ──────────────────────────────────────────────────
cache = {"data": None, "ts": 0, "lock": threading.Lock()}

def get_cotizaciones():
    with cache["lock"]:
        now = time.time()
        if cache["data"] and (now - cache["ts"]) < CACHE_SECONDS:
            return cache["data"]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Actualizando cotizaciones...")
    result = {}

    try:
        div = scrape_bna_divisas()
        if div:
            result["divisas"] = {**div, "fuente": "BNA directo", "ok": True}
            print(f"  ✓ Divisas: compra={div['compra']} venta={div['venta']}")
        else:
            print("  ✗ Divisas: no encontrado")
    except Exception as e:
        print(f"  ✗ Divisas error: {e}")

    for key, casa in {"oficial":"oficial","blue":"blue","mep":"bolsa","ccl":"contadoconliqui","cripto":"cripto"}.items():
        try:
            d = fetch_dolarapi(casa)
            result[key] = {"compra": d.get("compra"), "venta": d.get("venta"),
                           "fechaActualizacion": d.get("fechaActualizacion"), "ok": True}
            print(f"  ✓ {key}: venta={d.get('venta')}")
        except Exception as e:
            print(f"  ✗ {key}: {e}")
            result[key] = {"ok": False}

    result["_ts"] = datetime.now().isoformat()

    with cache["lock"]:
        cache["data"] = result
        cache["ts"] = time.time()
    return result

# ── HTTP Handler ───────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/cotizaciones":
            try:
                data = get_cotizaciones()
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path in ("/", "/app"):
            # Servir el HTML embebido directamente
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(HTML_BYTES)

        elif self.path == "/ping":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"pong")

        elif self.path == "/update-status":
            # La app consulta esto para saber si hay actualización
            body = json.dumps({
                "update_available": UPDATE_AVAILABLE,
                "info": UPDATE_INFO,
                "version": VERSION
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silenciar logs HTTP

# ── Main ───────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Cotizaciones BNA")
    print(f"  Iniciando en http://localhost:{PORT}")
    print("=" * 50)

    # Pre-cargar cotizaciones
    try:
        get_cotizaciones()
    except Exception as e:
        print(f"Advertencia carga inicial: {e}")

    # Verificar actualizaciones en background
    threading.Thread(target=check_for_update, daemon=True).start()
    # Re-verificar cada hora
    def update_loop():
        while True:
            time.sleep(3600)
            check_for_update()
    threading.Thread(target=update_loop, daemon=True).start()

# ── Main ───────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Cotizaciones BNA")
    print(f"  Iniciando en http://localhost:{PORT}")
    print("=" * 50)

    # Pre-cargar cotizaciones
    try:
        get_cotizaciones()
    except Exception as e:
        print(f"Advertencia carga inicial: {e}")

    # Verificar actualizaciones en background
    threading.Thread(target=check_for_update, daemon=True).start()
    def update_loop():
        while True:
            time.sleep(3600)
            check_for_update()
    threading.Thread(target=update_loop, daemon=True).start()

    # Iniciar servidor HTTP en thread separado
    server = HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  ✓ Servidor iniciado en puerto {PORT}")

    # Esperar que el servidor esté listo
    time.sleep(1.0)

    # Intentar abrir como ventana nativa con pywebview
    try:
        import webview
        print("  ✓ Abriendo ventana nativa...")
        window = webview.create_window(
            title="Cotizaciones BNA",
            url=f"http://localhost:{PORT}/app",
            width=420,
            height=820,
            resizable=True,
            min_size=(380, 600),
        )
        # Ícono en bandeja en thread separado
        threading.Thread(target=setup_tray, daemon=True).start()
        webview.start()  # bloqueante — cuando se cierra la ventana termina el programa

    except ImportError:
        # pywebview no disponible — fallback al navegador
        print("  ℹ pywebview no disponible, abriendo en navegador...")
        webbrowser.open(f"http://localhost:{PORT}/app")
        threading.Thread(target=setup_tray, daemon=True).start()
        # Mantener vivo
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCerrado.")

if __name__ == "__main__":
    main()
