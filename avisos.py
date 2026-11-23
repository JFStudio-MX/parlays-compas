# -*- coding: utf-8 -*-
"""Avisos por Telegram (gratis). Se activan con telegram_token y telegram_chat_id en datos/config.json.
Cómo sacarlos (2 minutos):
  1. En Telegram busca @BotFather, escribe /newbot y ponle un nombre: te da el token.
  2. Mándale cualquier mensaje a tu bot nuevo.
  3. Abre https://api.telegram.org/bot<TOKEN>/getUpdates y copia el número de "chat":{"id": ...}."""
import json
import urllib.parse
import urllib.request


def enviar(cfg, texto):
    token, chat = (cfg.get("telegram_token") or "").strip(), str(cfg.get("telegram_chat_id") or "").strip()
    if not token or not chat:
        return False
    partes = [texto[i:i + 3800] for i in range(0, len(texto), 3800)]
    try:
        for t in partes:
            data = urllib.parse.urlencode({"chat_id": chat, "text": t, "disable_web_page_preview": "true"}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
            with urllib.request.urlopen(req, timeout=20) as r:
                if not json.loads(r.read().decode()).get("ok"):
                    return False
        return True
    except Exception as e:
        print(f"   (Telegram falló: {e})")
        return False
