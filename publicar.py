# -*- coding: utf-8 -*-
"""Versión para los compas: la misma página, sin tus apuestas, con los datos CIFRADOS.
Solo se ve con la clave del grupo (variable de entorno CLAVE_PARLAYS; en GitHub es un "secret").
Cifrado: AES-256-GCM con llave derivada por PBKDF2-SHA256; el navegador lo abre con WebCrypto.
Lo usa la GitHub Action (python parlays.py --publico) y deja publico/index.html, que Vercel publica."""
import base64
import gzip
import hashlib
import json
import os
import re

from nucleo import AQUI

ITERACIONES = 310_000
SALIDA_PUBLICA = AQUI / "publico" / "index.html"

CANDADO = """<div id="candado" style="position:fixed;inset:0;z-index:100;background:#0b0d12;display:grid;place-items:center;padding:20px;font:15px/1.45 'Segoe UI',system-ui,-apple-system,Roboto,sans-serif;color:#e9ecf3">
  <form id="cform" style="width:min(360px,100%);display:grid;gap:12px;text-align:center">
    <div style="font-size:42px">🔒</div>
    <div style="font-size:21px;font-weight:700">Parlays de los compas</div>
    <div style="color:#8a93a8;font-size:13px">Pon la clave del grupo</div>
    <input id="cclave" type="password" autocomplete="current-password" style="background:#1a1f2b;border:1px solid #272e40;border-radius:12px;padding:12px 14px;color:#e9ecf3;font-size:16px;text-align:center">
    <button id="cboton" style="background:#ffc94d;color:#1d1500;border:0;border-radius:12px;padding:12px;font-weight:700;font-size:16px;cursor:pointer">Entrar</button>
    <div id="cerr" style="color:#ff5c6c;font-size:13px;min-height:18px"></div>
  </form>
</div>
<script>
const CAJA = __CAJA__;
async function abrirCaja(clave){
  const b = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(clave), 'PBKDF2', false, ['deriveKey']);
  const llave = await crypto.subtle.deriveKey({name: 'PBKDF2', salt: b(CAJA.sal), iterations: CAJA.iter, hash: 'SHA-256'},
    base, {name: 'AES-GCM', length: 256}, false, ['decrypt']);
  const comprimido = await crypto.subtle.decrypt({name: 'AES-GCM', iv: b(CAJA.nonce)}, llave, b(CAJA.datos));
  const txt = await new Response(new Blob([comprimido]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  window.__D = JSON.parse(txt);
  localStorage.setItem('parlays_clave', clave);
  document.getElementById('candado').remove();
  const s = document.createElement('script');
  s.textContent = document.getElementById('app').textContent;
  document.body.appendChild(s);
}
async function intentar(clave, silencioso){
  const err = document.getElementById('cerr'), btn = document.getElementById('cboton');
  btn.disabled = true; btn.textContent = 'Abriendo…'; err.textContent = '';
  try { await abrirCaja(clave); }
  catch (e) {
    btn.disabled = false; btn.textContent = 'Entrar';
    if (!silencioso) err.textContent = 'Clave incorrecta';
    localStorage.removeItem('parlays_clave');
  }
}
document.getElementById('cform').addEventListener('submit', e => { e.preventDefault(); intentar(document.getElementById('cclave').value.trim()); });
const guardada = localStorage.getItem('parlays_clave');
if (guardada) intentar(guardada, true);
</script>
"""


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def cifrar(texto, clave):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # pip install cryptography (en la Action)
    sal, nonce = os.urandom(16), os.urandom(12)
    llave = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES, 32)
    datos = AESGCM(llave).encrypt(nonce, gzip.compress(texto.encode("utf-8"), 9), None)
    return {"sal": _b64(sal), "nonce": _b64(nonce), "datos": _b64(datos), "iter": ITERACIONES}


def publicar(datos, plantilla):
    clave = (os.environ.get("CLAVE_PARLAYS") or "").strip()
    if len(clave) < 6:
        raise SystemExit("Falta la clave del grupo: define CLAVE_PARLAYS (mínimo 6 caracteres).")
    pub = dict(datos)
    pub["apuestas"], pub["estado_ap"] = [], {}
    pub["config"] = {**datos["config"], "publico": True, "odds_api": False, "telegram": False}
    caja = cifrar(json.dumps(pub, ensure_ascii=False), clave)
    html, n = re.subn(r"<script>\r?\nconst D = /\*__DATOS__\*/null;",
                      lambda m: CANDADO.replace("__CAJA__", json.dumps(caja))
                      + '<script type="text/plain" id="app">\nconst D = window.__D;', plantilla, count=1)
    if n != 1:
        raise SystemExit("No encontré dónde poner los datos en plantilla.html.")
    # para que se pueda instalar como app en el cel (manifest, íconos y service worker viven en publico/)
    html = html.replace("<title>", '<link rel="manifest" href="/manifest.webmanifest">'
                        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
                        '<link rel="icon" href="/icono-192.png">'
                        "<script>if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');</script><title>", 1)
    SALIDA_PUBLICA.parent.mkdir(exist_ok=True)
    SALIDA_PUBLICA.write_text(html, "utf-8")
    return SALIDA_PUBLICA
