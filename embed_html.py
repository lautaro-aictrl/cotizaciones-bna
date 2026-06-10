import base64

with open("tc-monitor-bna.html", "rb") as f:
    data = f.read()

b64 = base64.b64encode(data).decode()

with open("html_embedded.py", "w", encoding="utf-8") as f:
    f.write("HTML_B64 = \"" + b64 + "\"\n")

print("HTML embebido OK -", len(data), "bytes")
