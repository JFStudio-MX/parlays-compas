# -*- coding: utf-8 -*-
"""Árbitros de fútbol con datos gratis de football-data.co.uk (Inglaterra y Escocia).

ESPN no publica el árbitro (la lista de oficiales viene vacía), así que de aquí sale:
- quién pita los próximos partidos (fixtures.csv, columna Referee), y
- el promedio de tarjetas de cada árbitro (temporada actual + anterior, columnas HY/AY/HR/AR).
Si algo falla (sin internet, cambió el formato), regresa vacío y la app sigue sin árbitros."""
import csv
import io
import time
import unicodedata
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher

from nucleo import CACHE, media

try:
    from zoneinfo import ZoneInfo
    LONDRES = ZoneInfo("Europe/London")
except Exception:  # sin base de zonas horarias: la fecha en UTC casi siempre coincide
    LONDRES = None

URL = "https://www.football-data.co.uk"
# liga ESPN -> división de football-data
DIVISION = {"eng.1": "E0", "eng.2": "E1", "sco.1": "SC0"}
# de estas divisiones sale el historial de cada árbitro (pitan en varias)
DIV_HIST = ("E0", "E1", "SC0")
MIN_PARTIDOS = 5  # menos que esto no es promedio confiable

# nombres cortos de football-data -> como los escribe ESPN
ALIAS = {
    "man city": "manchester city", "man united": "manchester united", "nott'm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers", "sheffield weds": "sheffield wednesday", "qpr": "queens park rangers",
    "west brom": "west bromwich albion", "brighton": "brighton hove albion", "hearts": "heart of midlothian",
    "spurs": "tottenham hotspur", "st mirren": "saint mirren", "st johnstone": "saint johnstone",
    "milton keynes dons": "mk dons",
}


def _temporada(hoy):
    """'2627' para la temporada 2026-27 (empieza en julio)."""
    a = hoy.year if hoy.month >= 7 else hoy.year - 1
    return f"{a % 100:02d}{(a + 1) % 100:02d}"


def _bajar_csv(ruta, ttl):
    """CSV de football-data, guardado en cache/fd y reusado durante ttl segundos."""
    p = CACHE / "fd" / ruta.replace("/", "_")
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        texto = p.read_text("utf-8")
    else:
        try:
            req = urllib.request.Request(f"{URL}/{ruta}", headers={"User-Agent": "asistente-parlays"})
            with urllib.request.urlopen(req, timeout=30) as r:
                texto = r.read().decode("utf-8-sig", errors="replace")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(texto, "utf-8")
        except Exception as e:
            print(f"   (football-data {ruta}: {e})")
            texto = p.read_text("utf-8") if p.exists() else ""
    return [r for r in csv.DictReader(io.StringIO(texto)) if r.get("Div")]


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def promedios(hoy):
    """({árbitro: {...}}, {división: promedio de tarjetas de la temporada})."""
    act, ant = _temporada(hoy), _temporada(hoy.replace(year=hoy.year - 1))
    por, liga = {}, {}
    for temp, ttl in ((act, 6 * 3600), (ant, 30 * 86400)):
        for div in DIV_HIST:
            for r in _bajar_csv(f"mmz4281/{temp}/{div}.csv", ttl):
                arb = (r.get("Referee") or "").strip()
                tar = [_int(r.get(k)) for k in ("HY", "AY", "HR", "AR")]
                if None in tar:
                    continue
                t = sum(tar)
                if temp == act:
                    liga.setdefault(div, []).append(t)
                if arb:
                    d = por.setdefault(arb, {"t": [], "act": []})
                    d["t"].append(t)
                    if temp == act:
                        d["act"].append(t)
    arbitros = {}
    for arb, d in por.items():
        t = d["t"]
        arbitros[arb] = {"nombre": arb, "n": len(t), "prom": round(media(t), 2),
                         "o45": round(sum(x > 4.5 for x in t) / len(t), 2),
                         "n_act": len(d["act"]), "prom_act": round(media(d["act"]), 2) if d["act"] else None}
    return arbitros, {div: round(media(v), 2) for div, v in liga.items()}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = ALIAS.get(s.strip(), s)
    s = s.replace("&", " ").replace("'", "").replace(".", " ").replace("-", " ")
    return " ".join(w for w in s.split() if w not in ("fc", "afc", "cf"))


def _parecido(fd, espn):
    a, b = _norm(fd), _norm(espn)
    if not a or not b:
        return 0
    # "Cardiff" = "Cardiff City", "Preston" = "Preston North End"; pero "Rangers" no es "Queens Park Rangers"
    if a == b or (set(a.split()) <= set(b.split()) and a.split()[0] == b.split()[0]):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _fecha_local(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt.astimezone(LONDRES) if LONDRES else dt).date()


def asignar(juegos, hoy):
    """{id del juego: datos del árbitro} para los partidos de Premier, Championship y Escocia."""
    mios = [g for g in juegos if g.get("liga") in DIVISION]
    if not mios:
        return {}
    try:
        fixtures = _bajar_csv("fixtures.csv", 3600)
        arbitros, liga = promedios(hoy)
    except Exception as e:
        print(f"   (árbitros: {e})")
        return {}
    out = {}
    for g in mios:
        div, dia = DIVISION[g["liga"]], _fecha_local(g["fecha"])
        mejor, score = None, 0.0
        for r in fixtures:
            if r.get("Div") != div or not (r.get("Referee") or "").strip():
                continue
            try:
                f = datetime.strptime(r["Date"], "%d/%m/%Y").date()
            except (KeyError, ValueError):
                continue
            if abs((f - dia).days) > 1:
                continue
            s = min(_parecido(r.get("HomeTeam"), g["L"]["nombre"]), _parecido(r.get("AwayTeam"), g["V"]["nombre"]))
            if s > score:
                mejor, score = r, s
        if not mejor or score < 0.6:
            continue
        nombre = mejor["Referee"].strip()
        info = {"nombre": nombre, "liga_prom": liga.get(div)}
        st = arbitros.get(nombre)
        if st and st["n"] >= MIN_PARTIDOS:
            info.update(st)
        out[g["id"]] = info
    return out
