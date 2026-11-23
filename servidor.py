# -*- coding: utf-8 -*-
"""Servidor local (solo en tu compu, 127.0.0.1) para que la página pueda:
  - guardar tus apuestas (datos/apuestas.json),
  - consultar TeamRankings y preguntarle a la IA,
  - volver a bajar los datos con el botón Actualizar.
Lo abre el acceso directo después de bajar los datos. Mientras la ventanita negra esté abierta, todo eso funciona."""
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import estadisticas
import ia
from historial import APUESTAS, ESTADO_AP
from nucleo import AQUI, DATOS, escribir_json, leer_json

PUERTO = 8765
URL = f"http://127.0.0.1:{PUERTO}/PARLAYS.html"
_candado = threading.Lock()
_actualizando = threading.Lock()


def _cfg():
    return leer_json(DATOS / "config.json", {})


class Manejador(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        cuerpo = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def end_headers(self):
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/api/apuestas":
            return self._json({"apuestas": leer_json(APUESTAS, []), "estado": leer_json(ESTADO_AP, {})})
        if u.path == "/api/ping":
            return self._json({"ok": True})
        if u.path == "/api/tr/buscar":
            if q.get("dep") not in estadisticas.DEP_TR:
                return self._json({"error": "deporte"}, 400)
            return self._json({"stats": estadisticas.buscar(q["dep"], q.get("q", ""), 15)})
        if u.path == "/api/tr/catalogo":
            if q.get("dep") not in estadisticas.DEP_TR:
                return self._json({"error": "deporte"}, 400)
            return self._json({"stats": estadisticas.catalogo(q["dep"])})
        if u.path == "/api/tr/stat":
            st = estadisticas.leer(q.get("dep"), q.get("slug", ""))
            return self._json(st or {"error": "No se pudo leer esa estadística de TeamRankings."}, 200 if st else 502)
        if u.path == "/api/ia/estado":
            return self._json(ia.estado(_cfg()))
        if u.path.startswith(("/datos/", "/cache/")) or u.path.endswith(".py"):
            return self._json({"error": "no"}, 404)
        return super().do_GET()

    def do_POST(self):
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(largo).decode("utf-8") or "{}")
        except Exception:
            return self._json({"error": "json"}, 400)
        u = urllib.parse.urlparse(self.path).path
        if u == "/api/preguntar":
            return self._json(ia.preguntar(body.get("pregunta"), body.get("previas"), _cfg()))
        if u == "/api/actualizar":
            if not _actualizando.acquire(blocking=False):
                return self._json({"error": "Ya se está actualizando."}, 409)
            try:
                r = subprocess.run([sys.executable, "-X", "utf8", str(AQUI / "parlays.py"), "--no-abrir"],
                                   cwd=str(AQUI), capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=1200)
                lineas = [l for l in (r.stdout or "").splitlines() if l.strip()]
                return self._json({"ok": r.returncode == 0, "salida": lineas[-3:], "error": (r.stderr or "")[-400:]})
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "error": "Tardó demasiado."})
            finally:
                _actualizando.release()
        with _candado:
            aps = leer_json(APUESTAS, [])
            if u == "/api/apuestas":  # nueva
                body["id"] = body.get("id") or f"a{int(time.time() * 1000)}"
                aps.append(body)
            elif u == "/api/apuestas/actualizar":
                for a in aps:
                    if a["id"] == body.get("id"):
                        for k, v in (body.get("campos") or {}).items():
                            if v is None:
                                a.pop(k, None)
                            else:
                                a[k] = v
            elif u == "/api/apuestas/borrar":
                aps = [a for a in aps if a["id"] != body.get("id")]
            else:
                return self._json({"error": "ruta"}, 404)
            escribir_json(APUESTAS, aps)
        return self._json({"apuestas": aps, "estado": leer_json(ESTADO_AP, {})})


def en_uso():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PUERTO)) == 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if en_uso():  # ya hay uno abierto: solo abre la página
        webbrowser.open(URL)
        return
    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), partial(Manejador, directory=str(AQUI)))
    print(f"\nPágina: {URL}")
    print("Deja esta ventana abierta mientras usas la página (así se guardan tus apuestas, funcionan")
    print("Stats/IA y el botón Actualizar). Ciérrala cuando termines.")
    threading.Timer(0.6, lambda: webbrowser.open(URL)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
