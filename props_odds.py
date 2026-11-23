# -*- coding: utf-8 -*-
"""Momios reales de jugadores con The Odds API (plan gratis: 500 créditos al mes).
Se activa poniendo tu clave en datos/config.json -> "odds_api_key".
Cada mercado de jugador por partido cuesta 1 crédito (región us); por eso solo se piden
los partidos de las próximas 36 h y solo los mercados de los jugadores que van en la página."""
import time
import unicodedata
import urllib.parse
from datetime import timedelta

from nucleo import DATOS, a_mx, escribir_json, get_externo, leer_json, prob_momio, sin_vig

API = "https://api.the-odds-api.com/v4"
SPORT_KEY = {"nba": "basketball_nba", "nfl": "americanfootball_nfl", "nhl": "icehockey_nhl",
             "ncaab": "basketball_ncaab", "ncaaf": "americanfootball_ncaaf"}
# stat -> (mercado principal, mercado de líneas alternas)
MERCADOS = {
    "nba": {"pts": ("player_points", "player_points_alternate"), "reb": ("player_rebounds", "player_rebounds_alternate"),
            "ast": ("player_assists", "player_assists_alternate"), "tpm": ("player_threes", "player_threes_alternate"),
            "pra": ("player_points_rebounds_assists", "player_points_rebounds_assists_alternate")},
    "nhl": {"pto": ("player_points", None), "sog": ("player_shots_on_goal", "player_shots_on_goal_alternate"),
            "gol": ("player_goal_scorer_anytime", None), "sv": ("player_total_saves", None)},
    "nfl": {"pyd": ("player_pass_yds", "player_pass_yds_alternate"), "ptd": ("player_pass_tds", None),
            "ruy": ("player_rush_yds", "player_rush_yds_alternate"),
            "recs": ("player_receptions", "player_receptions_alternate"),
            "rey": ("player_reception_yds", "player_reception_yds_alternate"), "td": ("player_anytime_td", None)},
}
CACHE_PROPS = DATOS / "odds_props_cache.json"


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for x in (".", "'", ",", " jr", " sr", " iii", " ii"):
        s = s.replace(x, "")
    return " ".join(s.split())


def aplicar(cfg, juegos, picks, ahora):
    """Busca momios reales para las props de jugador. Devuelve un texto para mostrar."""
    key = (cfg.get("odds_api_key") or "").strip()
    if not key:
        return None
    limite = int(cfg.get("odds_api_max_creditos") or 40)
    libros = cfg.get("odds_api_casas") or "draftkings,fanduel"
    cache = leer_json(CACHE_PROPS, {})
    usados, restantes, n_asignados = 0, None, 0

    por_juego = {}
    for p in picks:
        if p["clase"] == "jugador" and p.get("stat"):
            por_juego.setdefault(p["juego"], []).append(p)
    candidatos = [j for j in juegos if j["id"] in por_juego and j["tipo"] in SPORT_KEY
                  and a_mx(j["fecha"]) - ahora < timedelta(hours=36)]
    candidatos.sort(key=lambda j: j["fecha"])
    eventos = {}
    for tipo in sorted({j["tipo"] for j in candidatos}):
        d, h = get_externo(f"{API}/sports/{SPORT_KEY[tipo]}/events?apiKey={urllib.parse.quote(key)}")
        if d is None:
            return "The Odds API no respondió (¿clave correcta?)."
        for e in d:
            eventos[(tipo, _norm(e.get("home_team")), _norm(e.get("away_team")))] = e["id"]

    for j in candidatos:
        base = j["base"]
        eid = eventos.get((j["tipo"], _norm(j["L"]["nombre"]), _norm(j["V"]["nombre"])))
        if not eid:
            continue
        stats = sorted({p["stat"] for p in por_juego[j["id"]] if p["stat"] in MERCADOS.get(base, {})})
        mercados = [m for s in stats for m in MERCADOS[base][s] if m]
        if not mercados:
            continue
        ck = f"{eid}|{','.join(mercados)}"
        datos = cache.get(ck)
        if not datos or time.time() - datos["t"] > 3 * 3600:
            if usados + len(mercados) > limite:
                break
            url = (f"{API}/sports/{SPORT_KEY[j['tipo']]}/events/{eid}/odds?apiKey={urllib.parse.quote(key)}"
                   f"&regions=us&bookmakers={libros}&oddsFormat=american&markets={','.join(mercados)}")
            d, h = get_externo(url)
            if d is None:  # si un mercado alterno no existe, intenta solo los principales
                principales = [MERCADOS[base][s][0] for s in stats]
                url = url.split("&markets=")[0] + "&markets=" + ",".join(principales)
                d, h = get_externo(url)
                if d is None:
                    continue
                usados += len(principales)
            else:
                usados += len(mercados)
            restantes = (h or {}).get("x-requests-remaining", restantes)
            datos = {"t": time.time(), "d": d}
            cache[ck] = datos
        # precios: (jugador, stat, umbral) -> (momio, casa, prob sin vig si hay Over y Under)
        precios = {}
        inv = {m: s for s, ms in MERCADOS[base].items() for m in ms if m}
        for bk in datos["d"].get("bookmakers", []):
            for mk in bk.get("markets", []):
                stat = inv.get(mk.get("key"))
                if not stat:
                    continue
                por_linea = {}
                for o in mk.get("outcomes", []):
                    jugador = _norm(o.get("description") or o.get("name"))
                    lado = (o.get("name") or "").lower()
                    pt = o.get("point")
                    x = 1 if pt is None else int(round(pt + 0.5))
                    por_linea.setdefault((jugador, x), {})[lado] = o.get("price")
                for (jugador, x), pr in por_linea.items():
                    over = pr.get("over") or pr.get("yes") or (pr.get(jugador) if len(pr) == 1 else None)
                    if over is None:
                        continue
                    pmk = sin_vig(over, pr["under"])[0] if pr.get("under") else prob_momio(over) * 0.95
                    k = (jugador, stat, x)
                    if k not in precios or over > precios[k][0]:  # el mejor precio entre casas
                        precios[k] = (int(over), bk.get("title"), pmk)
        for p in por_juego[j["id"]]:
            hit = precios.get((_norm(p["quien"]), p["stat"], p["umbral"]))
            if not hit:
                continue
            momio, casa, pmk = hit
            p.update(momio=momio, real=True, p_mkt=round(pmk, 3), casa_prop=casa,
                     est=round((2 * p["est"] + pmk) / 3, 3))
            p["tags"] = list(p.get("tags", [])) + [f"momio real {casa}"]
            n_asignados += 1
    escribir_json(CACHE_PROPS, {k: v for k, v in cache.items() if time.time() - v["t"] < 24 * 3600})
    txt = f"Momios reales de jugadores: {n_asignados} props con precio de casa ({usados} créditos usados"
    return txt + (f", te quedan {restantes} este mes)." if restantes else ").")
