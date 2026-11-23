# -*- coding: utf-8 -*-
"""Estadísticas de equipos de TeamRankings (lo que permite cada defensa, ritmo, pérdidas, etc.).
Respeta su robots.txt: al menos 10 segundos entre consultas. Todo se guarda en cache/tr para no repetir:
el índice de estadísticas una semana, cada tabla 6 horas."""
import hashlib
import html
import re
import threading
import time
import unicodedata
import urllib.request

from nucleo import CACHE

TR = "https://www.teamrankings.com"
DEP_TR = {"nfl": "nfl", "nba": "nba", "nhl": "nhl", "ncaaf": "college-football", "ncaab": "ncaa-basketball"}
PAUSA_TR = 11  # su robots.txt pide Crawl-delay: 10
_candado = threading.Lock()
_ultimo = [0.0]


def _get(path, ttl):
    url = TR + path
    p = CACHE / "tr" / (hashlib.md5(url.encode()).hexdigest() + ".html")
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        return p.read_text("utf-8")
    txt = None
    with _candado:
        espera = _ultimo[0] + PAUSA_TR - time.time()
        if espera > 0:
            time.sleep(espera)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "asistente-parlays (uso personal)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"   (TeamRankings no respondió: {e})")
        finally:
            _ultimo[0] = time.time()
    if txt is None:
        return p.read_text("utf-8") if p.exists() else None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, "utf-8")
    return txt


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


# --------------------------------------------------------------------------- traducción para mostrar

_TRAD = [
    ("Rushing Yards", "yardas por tierra"), ("Passing Yards", "yardas por pase"), ("Rushing Attempts", "acarreos"),
    ("Passing Attempts", "pases intentados"), ("Rushing Touchdowns", "touchdowns por tierra"),
    ("Passing Touchdowns", "touchdowns por pase"), ("Rushing First Downs", "primeros downs por tierra"),
    ("Passing First Downs", "primeros downs por pase"), ("Yards per Rush Attempt", "yardas por acarreo"),
    ("Yards per Pass Attempt", "yardas por pase intentado"), ("Three Point Pct", "% de triples"),
    ("Free Throw Pct", "% de tiros libres"), ("Shooting Pct", "% de tiro"),
    ("Opponent ", "Rival: "), ("per Game", "por partido"), ("Per Game", "por partido"), ("per Play", "por jugada"),
    ("per Possession", "por posesión"), ("Rushing", "por tierra"), ("Passing", "por pase"), ("Yards", "yardas"),
    ("Points", "puntos"), ("Attempts", "intentos"), ("Percentage", "%"), ("Pct", "%"), ("Average", "promedio"),
    ("Scoring Margin", "margen de puntos"), ("Turnovers", "pérdidas"), ("Takeaways", "robos de balón"),
    ("Rebounds", "rebotes"), ("Assists", "asistencias"), ("Three Point", "triples"), ("Three Pointers", "triples"),
    ("Free Throw", "tiros libres"), ("Shots", "tiros"), ("Shooting", "tiro"), ("Goals", "goles"), ("Saves", "atajadas"),
    ("Penalties", "castigos"), ("Penalty Kill", "penalty kill"), ("Power Play", "power play"), ("Sacks", "capturas"),
    ("Interceptions", "intercepciones"), ("First Downs", "primeros downs"), ("Red Zone", "zona roja"),
    ("Third Down", "tercera oportunidad"), ("Fourth Down", "cuarta oportunidad"), ("Possessions", "posesiones"),
    ("Steals", "robos"), ("Blocks", "bloqueos"), ("Fouls", "faltas"), ("Offensive", "ofensivos"),
    ("Defensive", "defensivos"), ("1st Half", "1a mitad"), ("2nd Half", "2a mitad"), ("1st Quarter", "1er cuarto"),
    ("1st Period", "1er periodo"), ("Win", "victoria"), ("Margin", "margen"), ("Total", "total"),
    ("Touchdowns", "touchdowns"), ("Field Goal", "gol de campo"), ("Completions", "pases completos"),
    ("Plays", "jugadas"), ("Play", "jugada"), ("Time of Possession", "tiempo de posesión"),
]
COLUMNAS = {"Last 3": "Últimos 3", "Last 1": "Último", "Home": "Casa", "Away": "Visita"}


def traducir(nombre):
    t = nombre
    for a, b in _TRAD:
        t = t.replace(a, b)
    return t.strip()


# --------------------------------------------------------------------------- catálogo y búsqueda

def catalogo(tipo):
    dep = DEP_TR.get(tipo)
    if not dep:
        return []
    txt = _get(f"/{dep}/stats/", 7 * 86400)
    if not txt:
        return []
    vistos, out = set(), []
    patron = rf'href="(?:https://www\.teamrankings\.com)?/{re.escape(dep)}/stat/([a-z0-9\-]+)"[^>]*>([^<]+)</a>'
    for slug, nombre in re.findall(patron, txt):
        if slug in vistos:
            continue
        vistos.add(slug)
        n = html.unescape(nombre).strip()
        out.append({"slug": slug, "nombre": n, "es": traducir(n)})
    return out


SINONIMOS = {
    "yardas": "yards", "yarda": "yards", "tierra": "rushing", "carrera": "rushing", "carreras": "rushing",
    "corren": "rushing", "acarreos": "rushing", "terrestre": "rushing", "pase": "passing", "pases": "passing",
    "aire": "passing", "aereo": "passing", "puntos": "points", "anotan": "points", "permite": "opponent",
    "permiten": "opponent", "permitidos": "opponent", "permitidas": "opponent", "defensa": "opponent",
    "rival": "opponent", "rivales": "opponent", "reciben": "opponent", "recibe": "opponent", "contra": "opponent",
    "rebotes": "rebounds", "asistencias": "assists", "triples": "three", "tres": "three", "libres": "free throw",
    "robos": "steals", "bloqueos": "blocks", "tapones": "blocks", "perdidas": "turnovers", "faltas": "fouls",
    "posesiones": "possessions", "ritmo": "possessions", "tiros": "shots", "disparos": "shots", "goles": "goals",
    "atajadas": "saves", "porcentaje": "pct", "promedio": "average", "margen": "margin", "anotacion": "scoring",
    "td": "touchdowns", "touchdown": "touchdowns", "intercepciones": "interceptions", "capturas": "sacks",
    "castigos": "penalties", "penalidades": "penalties", "roja": "red zone", "tercera": "third down",
    "terceras": "third down", "cuarta": "fourth down", "intentos": "attempts", "primera": "1st",
    "primer": "1st", "mitad": "half", "cuarto": "quarter", "periodo": "period", "casa": "home", "local": "home",
    "visita": "away", "jugada": "play", "jugadas": "plays", "partido": "game", "juego": "game",
    "victorias": "win", "derrotas": "loss", "ganar": "win", "completos": "completions",
}
VACIAS = {"de", "la", "el", "los", "las", "que", "cuantas", "cuantos", "por", "x", "en", "a", "al", "del", "y", "su",
          "sus", "equipo", "equipos", "stat", "stats", "tiene", "hace", "mete", "cual", "como", "es", "un", "una",
          "lo", "le", "da", "dan", "mas", "menos", "the", "of", "per", "and"}


def buscar(tipo, texto, n=12):
    """Busca estadísticas por palabras en español o inglés ('yardas por tierra que permite')."""
    cat = catalogo(tipo)
    terms = set()
    for w in _norm(texto).split():
        if w in VACIAS:
            continue
        terms.update(SINONIMOS.get(w, w).split())
    if not terms:
        return []
    rival = "opponent" in terms

    def puntaje(s):
        nombre = _norm(s["nombre"])
        toks = set(nombre.split())
        sc = sum(2 if t in toks else (1 if t in nombre else 0) for t in terms)
        if rival != ("opponent" in toks):
            sc -= 1.5
        if "per game" in nombre:
            sc += 0.3
        return sc - 0.03 * len(toks)

    res = sorted(cat, key=puntaje, reverse=True)
    return [s for s in res if puntaje(s) > 0.5][:n]


def leer(tipo, slug):
    """La tabla de una estadística: posición, equipo y valores (temporada, últimos 3, último, casa, visita, pasada)."""
    dep = DEP_TR.get(tipo)
    if not dep or not re.fullmatch(r"[a-z0-9\-]+", slug or ""):
        return None
    txt = _get(f"/{dep}/stat/{slug}", 6 * 3600)
    if not txt:
        return None
    t0 = txt.find('<table class="tr-table')
    t1 = txt.find("</table>", t0)
    if t0 < 0 or t1 < 0:
        return None
    tabla = txt[t0:t1]
    limpiar = lambda c: html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
    cols = [limpiar(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", tabla, re.S)]
    filas = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tabla, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 3:
            continue
        m = re.search(r"/team/([a-z0-9\-]+)", tds[1])
        filas.append({"rank": limpiar(tds[0]), "equipo": limpiar(tds[1]), "slug": m.group(1) if m else "",
                      "valores": [limpiar(c) for c in tds[2:]]})
    nombre = next((s["nombre"] for s in catalogo(tipo) if s["slug"] == slug), slug.replace("-", " ").title())
    return {"tipo": tipo, "slug": slug, "nombre": nombre, "es": traducir(nombre),
            "columnas": [COLUMNAS.get(c, c) for c in cols[2:]], "filas": filas, "url": f"{TR}/{dep}/stat/{slug}"}


def es_equipo(fila, nombre_espn):
    """¿Esta fila de TeamRankings es este equipo de ESPN? (compara el slug de TeamRankings con el nombre completo)"""
    a = set(_norm(fila.get("slug", "").replace("-", " ")).split())
    b = set(_norm(nombre_espn).split())
    return bool(a) and (a == b or (len(a & b) >= 2 and len(a & b) >= min(len(a), len(b)) - 1))
