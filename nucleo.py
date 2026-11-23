# -*- coding: utf-8 -*-
"""Núcleo compartido: descargas de ESPN (con pausas y caché), utilidades, lectura de partidos
y las reglas con las que se califica cualquier apuesta después del partido."""
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CACHE = AQUI / "cache"
DATOS = AQUI / "datos"
SALIDA = AQUI / "salida"
MX = timezone(timedelta(hours=-6))  # CDMX, sin horario de verano
B = "https://site.api.espn.com/apis/site/v2/sports"
VERSION_PARTIDO = 2  # sube cuando cambia lo que se guarda de cada partido (se vuelve a bajar)

# liga ESPN -> (deporte ESPN, nombre, tipo)
LIGAS = {
    "nba": ("basketball", "NBA", "nba"),
    "nfl": ("football", "NFL", "nfl"),
    "nhl": ("hockey", "NHL", "nhl"),
    "mex.1": ("soccer", "Liga MX", "futbol"),
    "eng.1": ("soccer", "Premier League", "futbol"),
    "esp.1": ("soccer", "LaLiga", "futbol"),
    "ita.1": ("soccer", "Serie A", "futbol"),
    "ger.1": ("soccer", "Bundesliga", "futbol"),
    "fra.1": ("soccer", "Ligue 1", "futbol"),
    "uefa.champions": ("soccer", "Champions League", "futbol"),
    "uefa.europa": ("soccer", "Europa League", "futbol"),
    "uefa.europa.conf": ("soccer", "Conference League", "futbol"),
    "ned.1": ("soccer", "Eredivisie", "futbol"),
    "por.1": ("soccer", "Liga Portugal", "futbol"),
    "tur.1": ("soccer", "Superliga Turquía", "futbol"),
    "bel.1": ("soccer", "Liga Bélgica", "futbol"),
    "sco.1": ("soccer", "Premiership Escocia", "futbol"),
    "eng.2": ("soccer", "Championship", "futbol"),
    "bra.1": ("soccer", "Brasileirão", "futbol"),
    "arg.1": ("soccer", "Liga Argentina", "futbol"),
    "usa.1": ("soccer", "MLS", "futbol"),
    "ksa.1": ("soccer", "Liga Saudí", "futbol"),
    "jpn.1": ("soccer", "J-League", "futbol"),
    "conmebol.libertadores": ("soccer", "Libertadores", "futbol"),
    "conmebol.sudamericana": ("soccer", "Sudamericana", "futbol"),
    "esp.copa_del_rey": ("soccer", "Copa del Rey", "futbol"),
    "eng.fa": ("soccer", "FA Cup", "futbol"),
    "ita.coppa_italia": ("soccer", "Coppa Italia", "futbol"),
    "ger.dfb_pokal": ("soccer", "Copa de Alemania", "futbol"),
    "ufc": ("mma", "UFC", "ufc"),
    "mens-college-basketball": ("basketball", "NCAA Básquet", "ncaab"),
    "college-football": ("football", "NCAA Americano", "ncaaf"),
}
NCAA = {"mens-college-basketball", "college-football"}
# copas: el historial de cada equipo sale de su liga (o de todos sus partidos si ESPN no cubre su liga)
COPAS = {"uefa.champions", "uefa.europa", "uefa.europa.conf", "conmebol.libertadores", "conmebol.sudamericana",
         "esp.copa_del_rey", "eng.fa", "ita.coppa_italia", "ger.dfb_pokal"}
INDIVIDUALES = {"ufc"}  # no van por equipos: tienen su propio módulo
# de aquí sale el historial de los equipos que juegan Champions / Europa League
LIGAS_DOMESTICAS = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "por.1", "ned.1", "mex.1", "bel.1", "sco.1",
                    "tur.1", "aut.1", "sui.1", "gre.1", "cze.1", "den.1", "nor.1", "swe.1", "cro.1", "srb.1",
                    "ukr.1", "pol.1", "isr.1", "cyp.1", "rou.1", "hun.1", "bul.1", "aze.1", "kaz.1", "svk.1",
                    "eng.2", "esp.2", "ita.2", "ger.2", "fra.2", "bra.1", "arg.1", "col.1", "chi.1", "uru.1",
                    "par.1", "ecu.1", "per.1", "bol.1", "ven.1"]
# NCAA usa la misma lógica que NBA / NFL
BASE = {"nba": "nba", "ncaab": "nba", "nfl": "nfl", "ncaaf": "nfl", "nhl": "nhl", "futbol": "futbol", "ufc": "ufc"}
DEPORTE = {"nba": "NBA", "nfl": "NFL", "nhl": "NHL", "futbol": "Fútbol", "ncaab": "NCAA Básquet",
           "ncaaf": "NCAA Americano", "ufc": "UFC"}
# Pago Anticipado ("a ganar", apuesta antes del partido): ventaja que lo da por ganado aunque luego pierda
PA_UMBRAL = {"nba": 20, "nfl": 17, "nhl": 3, "futbol": 2}
# Qué deportes tienen PA en cada casa (fuentes en LEEME.md). Stake: sus reglas no están claras, no se cuenta.
CASAS_PA = {
    "Playdoit": {"nba": 20, "nfl": 17, "nhl": 3, "futbol": 2},
    "Caliente": {"nba": 20, "nfl": 17, "futbol": 2},
    "Draftea": {"nba": 20, "nfl": 17, "nhl": 3, "futbol": 2},
    "Stake": {},
}


def casa_cubre(casa, tipo):
    """¿La casa tiene Pago Anticipado en ese deporte?"""
    for nombre, deps in CASAS_PA.items():
        if (casa or "").strip().lower() == nombre.lower():
            return tipo in deps
    return False

# --------------------------------------------------------------------------- red

_candado_red = threading.Lock()
_ultimo = [0.0]
PAUSA = 0.25  # segundos entre peticiones a ESPN: si vas muy rápido te bloquea un rato
BLOQUEO = {"activo": False}


def _ruta_cache(url):
    return CACHE / "http" / (hashlib.md5(url.encode()).hexdigest() + ".json")


def _leer(p):
    try:
        return json.loads(Path(p).read_text("utf-8-sig"))  # -sig: aguanta archivos guardados con el Bloc de notas
    except Exception:
        return None


def leer_json(p, defecto=None):
    d = _leer(p)
    return defecto if d is None else d


def escribir_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(p)


def get_json(url, ttl=0):
    """GET a ESPN con pausas y reintentos. ttl>0: guarda en disco y reusa durante ttl segundos.
    Si ESPN bloquea (403/429), deja de pedir y usa lo guardado aunque esté viejo."""
    p = _ruta_cache(url)
    if ttl and p.exists() and time.time() - p.stat().st_mtime < ttl:
        d = _leer(p)
        if d is not None:
            return d
    data = None
    if not BLOQUEO["activo"]:
        for intento in range(3):
            with _candado_red:
                espera = _ultimo[0] + PAUSA - time.time()
                if espera > 0:
                    time.sleep(espera)
                _ultimo[0] = time.time()
            if BLOQUEO["activo"]:
                break
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    return None
                if e.code in (403, 429):
                    if intento == 2:
                        if not BLOQUEO["activo"]:
                            print("   ESPN pidió bajarle el ritmo; sigo con lo que ya está guardado.")
                        BLOQUEO["activo"] = True
                        break
                    time.sleep(15 * (intento + 1))
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)
    if data is None:
        return _leer(p) if (ttl and p.exists()) else None
    if ttl:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), "utf-8")
    return data


def get_externo(url, headers=None, timeout=30):
    """GET a otros servicios (The Odds API). Devuelve (json, headers) o (None, None)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "asistente-parlays", **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            cuerpo = e.read().decode("utf-8")[:200]
        except Exception:
            cuerpo = ""
        print(f"   (servicio externo respondió {e.code}: {cuerpo})")
    except Exception as e:
        print(f"   (servicio externo falló: {e})")
    return None, None


# --------------------------------------------------------------------------- utilidades

def num(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").replace("+", ""))
    except ValueError:
        return None


def americano(s):
    if s is None:
        return None
    s = str(s).strip().upper()
    if s in ("EVEN", "EV", "PK"):
        return 100
    try:
        v = int(round(float(s.replace("+", ""))))
    except ValueError:
        return None
    return v if abs(v) >= 100 else None


def prob_momio(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def momio_prob(p):
    p = min(max(p, 0.01), 0.99)
    return round(100 * (1 - p) / p) if p < 0.5 else -round(100 * p / (1 - p))


def decimal(a):
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def americano_de_decimal(d):
    return round((d - 1) * 100) if d >= 2 else -round(100 / (d - 1))


def sin_vig(*momios):
    ps = [prob_momio(a) if a else None for a in momios]
    if any(p is None for p in ps):
        return [None] * len(ps)
    s = sum(ps)
    return [p / s for p in ps]


def media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def mins(t):
    if not t or ":" not in str(t):
        return num(t)
    m, s = str(t).split(":")[:2]
    return int(m) + int(s) / 60


def a_mx(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(MX)


def momio_pata(p, usar_pa=False):
    """Momio real si existe; si no, uno aproximado (lo justo menos ~6% que se queda la casa)."""
    if p.get("momio"):
        return p["momio"]
    d = max(1.02, 1 / (min(est_de(p, usar_pa), 0.97) * 1.06))
    return americano_de_decimal(d)


def est_de(p, usar_pa=False):
    if usar_pa and p.get("pa") and p.get("pa_ok", True):
        return p["pa"]["est"]
    return p["est"]


DIAS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def etiqueta_dia(dt, hoy):
    d = (dt.date() - hoy).days
    if d == 0:
        return "Hoy"
    if d == 1:
        return "Mañana"
    return f"{DIAS_ES[dt.weekday()]} {dt.day}"


# --------------------------------------------------------------------------- momios del partido

def leer_momios(comp):
    o = next((x for x in comp.get("odds") or [] if isinstance(x, dict)), None)
    if not o:
        return None

    def cur(d, cual="close"):
        d = d or {}
        return d.get(cual) or d.get("open" if cual == "close" else "close") or {}

    ml, ps, tot = o.get("moneyline") or {}, o.get("pointSpread") or {}, o.get("total") or {}
    return {
        "casa": (o.get("provider") or {}).get("name"),
        "ml_L": americano(cur(ml.get("home")).get("odds")),
        "ml_V": americano(cur(ml.get("away")).get("odds")),
        "ml_E": americano(cur(ml.get("draw")).get("odds")) or americano((o.get("drawOdds") or {}).get("moneyLine")),
        "ml_L_abrio": americano(cur(ml.get("home"), "open").get("odds")),
        "ml_V_abrio": americano(cur(ml.get("away"), "open").get("odds")),
        "sp_L": num(cur(ps.get("home")).get("line")),
        "sp_L_m": americano(cur(ps.get("home")).get("odds")),
        "sp_V_m": americano(cur(ps.get("away")).get("odds")),
        "sp_L_abrio": num(cur(ps.get("home"), "open").get("line")),
        "total": num(str(cur(tot.get("over")).get("line", "")).lstrip("ou") or None) or num(o.get("overUnder")),
        "over_m": americano(cur(tot.get("over")).get("odds")),
        "under_m": americano(cur(tot.get("under")).get("odds")),
        "total_abrio": num(str(cur(tot.get("over"), "open").get("line", "")).lstrip("ou") or None),
    }


# --------------------------------------------------------------------------- partidos jugados

POS_NBA = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C", "GF": "F", "FC": "F", "CF": "C"}


def _ventajas(s, base, home_id, pts_h, pts_a):
    """Ventaja máxima que tuvo cada equipo en algún momento (para el Pago Anticipado)."""
    seq = []
    if base in ("nba", "nhl"):
        for pl in s.get("plays") or []:
            h, a = num(pl.get("homeScore")), num(pl.get("awayScore"))
            if h is not None and a is not None:
                seq.append((h, a))
    elif base == "nfl":
        for pl in s.get("scoringPlays") or []:
            h, a = num(pl.get("homeScore")), num(pl.get("awayScore"))
            if h is not None and a is not None:
                seq.append((h, a))
    else:
        h = a = 0
        evs = [k for k in s.get("keyEvents") or [] if k.get("scoringPlay")
               and ((k.get("period") or {}).get("number") or 1) <= 4]  # sin tanda de penales
        evs.sort(key=lambda k: (k.get("clock") or {}).get("value") or 0)
        for k in evs:
            if str((k.get("team") or {}).get("id")) == home_id:
                h += 1
            else:
                a += 1
            seq.append((h, a))
        if not seq and pts_h == 0 and pts_a == 0:
            return 0, 0
    if not seq:
        return None, None
    return max(0, max(h - a for h, a in seq)), max(0, max(a - h for h, a in seq))


def parsear_partido(s, base):
    comp = s["header"]["competitions"][0]
    if not comp.get("status", {}).get("type", {}).get("completed"):
        return None
    rec = {"v": VERSION_PARTIDO, "id": s["header"]["id"], "fecha": comp["date"], "eq": {}, "jug": {},
           "arb": [o.get("displayName") for o in (s.get("gameInfo") or {}).get("officials") or [] if o.get("displayName")]}
    home_id = None
    for c in comp["competitors"]:
        tid = str(c.get("id") or c["team"]["id"])
        if c.get("homeAway") == "home":
            home_id = tid
        per = [num(l.get("displayValue", l.get("value"))) for l in c.get("linescores", []) or []]
        rec["eq"][tid] = {"abbr": c["team"].get("abbreviation"), "local": c.get("homeAway") == "home",
                          "pts": num(c.get("score")), "per": per, "st": {}}
    ids = list(rec["eq"])
    if home_id and len(ids) == 2:
        away_id = ids[0] if ids[1] == home_id else ids[1]
        mh, ma = _ventajas(s, base, home_id, rec["eq"][home_id]["pts"], rec["eq"][away_id]["pts"])
        rec["eq"][home_id]["ml"], rec["eq"][away_id]["ml"] = mh, ma
    box = s.get("boxscore", {})
    if base == "futbol":
        for t in box.get("teams", []):
            tid = str(t["team"]["id"])
            st = {x["name"]: num(x.get("displayValue")) for x in t.get("statistics", [])}
            if tid in rec["eq"]:
                tar = None
                if "yellowCards" in st:
                    tar = (st.get("yellowCards") or 0) + (st.get("redCards") or 0)
                rec["eq"][tid]["st"] = {"cor": st.get("wonCorners"), "tar": tar,
                                        "tap": st.get("shotsOnTarget"), "tir": st.get("totalShots")}
        for r in s.get("rosters", []) or []:
            tid = str(r["team"]["id"])
            out = rec["jug"].setdefault(tid, {})
            for p in r.get("roster", []) or []:
                st = {x["name"]: x.get("value") for x in p.get("stats", []) or []}
                if not (p.get("starter") or (st.get("subIns") or 0) > 0):
                    continue
                a = p["athlete"]
                out[str(a["id"])] = {"n": a.get("displayName"), "tit": bool(p.get("starter")),
                                     "tir": st.get("totalShots"), "tap": st.get("shotsOnTarget"),
                                     "gol": st.get("totalGoals"),
                                     "tar": (st.get("yellowCards") or 0) + (st.get("redCards") or 0)}
        return rec

    for team in box.get("players", []):
        tid = str(team["team"]["id"])
        out = rec["jug"].setdefault(tid, {})
        for cat in team.get("statistics", []):
            keys = cat.get("keys") or cat.get("names") or []
            cname = cat.get("name")
            for a in cat.get("athletes", []) or []:
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                d = dict(zip(keys, a["stats"]))
                pid = str(a["athlete"]["id"])
                j = out.setdefault(pid, {"n": a["athlete"].get("displayName")})
                if base == "nba":
                    m = num(d.get("minutes"))
                    if not m:
                        out.pop(pid, None)
                        continue
                    tp = str(d.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0")).split("-")[0]
                    pts, reb, ast = num(d.get("points")) or 0, num(d.get("rebounds")) or 0, num(d.get("assists")) or 0
                    pos = ((a["athlete"].get("position") or {}).get("abbreviation") or "").upper()
                    j.update(min=m, pts=pts, reb=reb, ast=ast, tpm=num(tp) or 0, pra=pts + reb + ast,
                             stl=num(d.get("steals")) or 0, blk=num(d.get("blocks")) or 0,
                             pos=POS_NBA.get(pos, pos[:1] or None))
                elif base == "nhl":
                    if cname == "goalies":
                        j.update(sv=num(d.get("saves")) or 0, ga=num(d.get("goalsAgainst")) or 0,
                                 min=mins(d.get("timeOnIce")), portero=True)
                    else:
                        g, asi = num(d.get("goals")) or 0, num(d.get("assists")) or 0
                        j.update(gol=g, asis=asi, pto=g + asi, sog=num(d.get("shotsTotal")) or 0,
                                 min=mins(d.get("timeOnIce")))
                elif base == "nfl":
                    if cname == "passing":
                        ca = str(d.get("completions/passingAttempts", "0/0")).split("/")
                        j.update(patt=num(ca[1]) if len(ca) > 1 else 0, pyd=num(d.get("passingYards")) or 0,
                                 ptd=num(d.get("passingTouchdowns")) or 0)
                    elif cname == "rushing":
                        j.update(ratt=num(d.get("rushingAttempts")) or 0, ruy=num(d.get("rushingYards")) or 0,
                                 rutd=num(d.get("rushingTouchdowns")) or 0)
                    elif cname == "receiving":
                        j.update(recs=num(d.get("receptions")) or 0, rey=num(d.get("receivingYards")) or 0,
                                 retd=num(d.get("receivingTouchdowns")) or 0, tgt=num(d.get("receivingTargets")) or 0)
        if base == "nfl":
            for j in out.values():
                for k in ("patt", "pyd", "ptd", "ratt", "ruy", "rutd", "recs", "rey", "retd", "tgt"):
                    j.setdefault(k, 0)
                j["td"] = j["rutd"] + j["retd"]
                j["uso"] = j["ratt"] + j["tgt"]
        if base == "nhl":
            for pid in [p for p, j in out.items() if "pto" not in j and not j.get("portero")]:
                out.pop(pid)
    return rec


def cargar_partido(liga, sport, base, eid):
    """Partido jugado (resumen compacto). Se guarda para siempre en cache/partidos."""
    p = CACHE / "partidos" / liga / f"{eid}.json"
    viejo = _leer(p) if p.exists() else None
    if viejo and viejo.get("v") == VERSION_PARTIDO:
        return viejo
    s = get_json(f"{B}/{sport}/{liga}/summary?event={eid}")
    if not s:
        return viejo
    try:
        rec = parsear_partido(s, base)
    except Exception as e:
        print(f"   (no pude leer el partido {eid}: {e})")
        return viejo
    if rec:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    return rec


def calendario(liga, sport, tid):
    sch = get_json(f"{B}/{sport}/{liga}/teams/{tid}/schedule", ttl=3 * 3600)
    return (sch or {}).get("events", [])


def ultimos_ids(eventos, n, liga):
    """[(liga del partido, id)] de los n más recientes ya jugados.
    Con liga 'all' (equipos de copas europeas cuya liga ESPN no cubre) cada partido trae su competición."""
    evs = [e for e in eventos if e["competitions"][0]["status"]["type"].get("completed")]
    evs.sort(key=lambda e: e["date"], reverse=True)
    res = []
    for e in evs[:n]:
        lg = ((e.get("league") or {}).get("slug") or liga) if liga == "all" else liga
        if lg != "all":
            res.append((lg, str(e["id"])))
    return res


def rasgos(rec, tid, base):
    """Un partido visto desde un equipo."""
    me = rec["eq"].get(tid)
    if not me or len(rec["eq"]) != 2:
        return None
    op = next(v for k, v in rec["eq"].items() if k != tid)
    if me["pts"] is None or op["pts"] is None:
        return None
    pf, pa = me["pts"], op["pts"]
    f = {"fecha": rec["fecha"], "rival": op["abbr"], "local": me["local"], "pf": pf, "pa": pa,
         "total": pf + pa, "margen": pf - pa, "mlf": me.get("ml"), "mlc": op.get("ml")}
    k = 2 if base in ("nba", "nfl") else 1
    if len(me["per"]) >= k and len(op["per"]) >= k and None not in me["per"][:k] + op["per"][:k]:
        f["m1f"], f["m1c"] = sum(me["per"][:k]), sum(op["per"][:k])
        f["m1"] = f["m1f"] + f["m1c"]
    if base == "futbol":
        for c in ("cor", "tar", "tap"):
            a, b = me["st"].get(c), op["st"].get(c)
            f[c + "f"], f[c + "c"] = a, b
            f[c] = a + b if a is not None and b is not None else None
    return f


# --------------------------------------------------------------------------- reglas para calificar

def evaluar_regla(r, rec, base, tid_def=None):
    """(resultado, valor real). resultado: True / False / None (anulada o sin dato)."""
    if r["k"] == "jug":
        st = (rec["jug"].get(r["tid"]) or {}).get(r["pid"])
        if not st or st.get(r["stat"]) is None:
            return None, None  # no jugó: la casa la anula
        v = st[r["stat"]]
        return v >= r["x"], v
    tid = r.get("tid") or tid_def or next(iter(rec["eq"]))
    f = rasgos(rec, tid, base)
    if not f:
        return None, None
    if r["m"] == "btts":
        v = 1 if (f["pf"] > 0 and f["pa"] > 0) else 0
    else:
        v = f.get(r["m"])
    if v is None:
        return None, None
    ok = {">": v > r["x"], "<": v < r["x"], ">=": v >= r["x"], "==": v == r["x"]}[r["op"]]
    return ok, v


def es_ganador(r):
    """¿La regla es 'gana tal equipo' (la que tiene Pago Anticipado)?"""
    return r.get("k") == "eq" and r.get("m") == "margen" and r.get("op") == ">" and r.get("x") == 0


def pago_anticipado(r, rec, base, tipo):
    """True si el equipo llegó a la ventaja del Pago Anticipado de Caliente."""
    if not es_ganador(r) or tipo not in PA_UMBRAL:
        return False
    f = rasgos(rec, r["tid"], base)
    return bool(f and f.get("mlf") is not None and f["mlf"] >= PA_UMBRAL[tipo])
