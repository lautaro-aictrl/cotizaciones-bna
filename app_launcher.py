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
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from html.parser import HTMLParser
import urllib.request

# ── HTML embebido (no requiere archivo externo) ────────────
from html_embedded import HTML_B64
HTML_BYTES = base64.b64decode(HTML_B64)

PORT = 8765
CACHE_SECONDS = 120

# ── Icono en bandeja del sistema (solo Windows) ─────────────
def setup_tray():
    """Ícono en system tray para cerrar la app desde ahí."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Crear ícono simple (círculo verde)
        img = Image.new("RGB", (64, 64), color=(15, 20, 30))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=(34, 197, 94))
        draw.text((20, 20), "$", fill=(255, 255, 255))

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
        # pystray no disponible — correr sin tray, igual funciona
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

    # Abrir navegador después de 1.5s (tiempo para que el server arranque)
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{PORT}/app")
        print(f"  ✓ App abierta en el navegador")

    threading.Thread(target=open_browser, daemon=True).start()

    # Iniciar ícono en bandeja en thread separado
    threading.Thread(target=setup_tray, daemon=True).start()

    # Iniciar servidor (bloqueante)
    server = HTTPServer(("localhost", PORT), Handler)
    print("  Minimizá esta ventana. Cerrá desde la bandeja del sistema.")
    print("  Presioná Ctrl+C para detener.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")

if __name__ == "__main__":
    main()
