import base64
import glob
import os

# Buscar el archivo HTML automáticamente (sin importar el nombre exacto)
html_files = glob.glob("*.html")
if not html_files:
    raise FileNotFoundError("No se encontró ningún archivo .html en el repositorio")

html_file = html_files[0]
print(f"HTML encontrado: {html_file}")

with open(html_file, "rb") as f:
    data = f.read()

b64 = base64.b64encode(data).decode()

with open("html_embedded.py", "w", encoding="utf-8") as f:
    f.write("HTML_B64 = \"" + b64 + "\"\n")

print("HTML embebido OK -", len(data), "bytes")
