# -*- coding: utf-8 -*-
"""
Asistente de parlays de Josh.
Datos gratis de ESPN (momios de DraftKings, resultados, lesiones, jugadas y estadísticas por partido).
Solo usa la librería estándar de Python.

Uso:
    python parlays.py                 # hoy y mañana (NFL hasta el siguiente lunes, NCAA americano 7 días)
    python parlays.py --dias 3        # ventana más larga
    python parlays.py --ligas nba,nhl # solo algunas ligas
    python parlays.py --avisar        # además manda los parlays de hoy por Telegram
"""
import argparse
import json
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import arbitros as fd_arbitros
import avisos
import contexto
import historial
import mercados
import modelo
import props_odds
from mercados import PICKS
import ufc
from nucleo import (AQUI, B, BASE, BLOQUEO, CACHE, CASAS_PA, COPAS, DATOS, DEPORTE, DIAS_ES, INDIVIDUALES, LIGAS,
                    LIGAS_DOMESTICAS,
                    MESES_ES, MX, NCAA, SALIDA, VERSION_PARTIDO, a_mx, americano_de_decimal, calendario,
                    cargar_partido, casa_cubre, escribir_json, etiqueta_dia, get_json, leer_json, leer_momios,
                    est_de, momio_pata, rasgos, ultimos_ids)

N_PARTIDOS = 10  # historial por equipo
HILOS = 4
CONFIG = DATOS / "config.json"
CONFIG_DEF = {
    "casa": "Playdoit",               # Playdoit, Caliente, Draftea o Stake (cambia el Pago Anticipado que se cuenta)
    # cuántos días hacia adelante revisa cada deporte (fútbol: la jornada completa con Champions y Europa League)
    "dias_por_deporte": {"futbol": 8, "nfl": 9, "ncaaf": 7, "nba": 2, "nhl": 2, "ncaab": 2, "ufc": 14},
    "pago_anticipado": True,          # cuenta el Pago Anticipado de Caliente en los "gana"
    "tope_mensual": 0,                # tope de lo que quieres apostar al mes (0 = sin tope)
    "odds_api_key": "",               # clave gratis de https://the-odds-api.com (momios reales de jugadores)
    "odds_api_max_creditos": 40,      # máximo de créditos a gastar por corrida (el plan gratis trae 500 al mes)
    "odds_api_casas": "draftkings,fanduel",
    "telegram_token": "",             # ver avisos.py
    "telegram_chat_id": "",
    "anthropic_api_key": "",          # para "Pregúntale a la IA" (ver ia.py)
    "ia_modelo": "claude-opus-5-5",
}
FUERA = ("out", "injured reserve", "doubtful", "suspension", "ir")
TRAD = {"Out": "Fuera", "Day-To-Day": "Duda (día a día)", "Questionable": "Duda", "Doubtful": "Casi seguro fuera",
        "Injured Reserve": "Lista de lesionados", "Probable": "Probable", "Suspension": "Suspendido"}


def cargar_config():
    cfg = leer_json(CONFIG, None)
    if cfg is None:
        cfg = dict(CONFIG_DEF)
        escribir_json(CONFIG, cfg)
    elif any(k not in cfg for k in CONFIG_DEF):
        cfg = {**CONFIG_DEF, **cfg}
        escribir_json(CONFIG, cfg)
    return cfg


# --------------------------------------------------------------------------- 1. partidos próximos

def buscar_partidos(ligas, dias, ahora, cfg):
    hoy = ahora.date()
    por_deporte = {**CONFIG_DEF["dias_por_deporte"], **(cfg.get("dias_por_deporte") or {})}

    def scoreboard(liga):
        sport, nombre, tipo = LIGAS[liga]
        nd = max(dias or 0, int(por_deporte.get(tipo) or 2))
        fin = hoy + timedelta(days=nd - 1)
        evs = []
        for k in range(-1, nd + 1):
            d = hoy + timedelta(days=k)
            sb = get_json(f"{B}/{sport}/{liga}/scoreboard?dates={d:%Y%m%d}", ttl=15 * 60)
            evs += (sb or {}).get("events", [])
        res, vistos = [], set()
        for e in evs:
            if e["id"] in vistos:
                continue
            vistos.add(e["id"])
            comp = e["competitions"][0]
            if comp["status"]["type"].get("state") != "pre":
                continue
            dt = a_mx(e["date"])
            if dt < ahora or dt.date() > fin:
                continue
            cs = {c["homeAway"]: c for c in comp["competitors"]}
            if "home" not in cs or "away" not in cs:
                continue
            rank = lambda c: (c.get("curatedRank") or {}).get("current") or 99
            if liga in NCAA and min(rank(cs["home"]), rank(cs["away"])) > 25:
                continue  # NCAA: solo partidos con equipos del top 25

            def eq(c):
                t = c["team"]
                return {"id": str(t["id"]), "abbr": t.get("abbreviation") or t["displayName"][:3].upper(),
                        "corto": t.get("shortDisplayName") or t.get("name") or t.get("displayName"),
                        "nombre": t.get("displayName"),
                        "logo": t.get("logo") or ((t.get("logos") or [{}])[0].get("href")),
                        "color": t.get("color"), "color2": t.get("alternateColor"),
                        "rank": rank(c) if rank(c) <= 25 else None}
            venue = comp.get("venue") or {}
            res.append({
                "id": e["id"], "liga": liga, "liga_nombre": nombre, "tipo": tipo, "base": BASE[tipo],
                "sport": sport, "fecha": e["date"], "hora": f"{dt:%H:%M}", "dia": etiqueta_dia(dt, hoy),
                "dl": f"{DIAS_ES[dt.weekday()]} {dt.day} {MESES_ES[dt.month - 1]}",
                "orden": dt.isoformat(), "L": eq(cs["home"]), "V": eq(cs["away"]),
                "neutral": comp.get("neutralSite", False), "momios": leer_momios(comp),
                "indoor": venue.get("indoor"), "clima_txt": contexto.clima_texto((e.get("weather") or {}).get("displayValue")),
            })
        return res

    with ThreadPoolExecutor(HILOS) as ex:
        juegos = [g for lista in ex.map(scoreboard, [l for l in ligas if l not in INDIVIDUALES]) for g in lista]
    juegos.sort(key=lambda g: g["orden"])
    return juegos


# --------------------------------------------------------------------------- 2. historial de equipos

def bajar_historial(juegos):
    mapa_domestico = {}
    if any(g["liga"] in COPAS for g in juegos):
        def equipos_liga(lg):
            d = get_json(f"{B}/soccer/{lg}/teams", ttl=7 * 86400)
            try:
                return lg, [str(t["team"]["id"]) for t in d["sports"][0]["leagues"][0]["teams"]]
            except Exception:
                return lg, []
        with ThreadPoolExecutor(HILOS) as ex:
            for lg, ids in ex.map(equipos_liga, LIGAS_DOMESTICAS):
                for i in ids:
                    mapa_domestico.setdefault(i, lg)

    tareas = {}  # (liga_hist, tid) -> (sport, base)
    for g in juegos:
        for lado in ("L", "V"):
            tid = g[lado]["id"]
            # copas europeas: historial de su liga; si ESPN no cubre su liga, todos sus partidos (fases previas incluidas)
            lh = (mapa_domestico.get(tid) or "all") if g["liga"] in COPAS else g["liga"]
            g[lado]["liga_hist"] = lh
            tareas[(lh, tid)] = (g["sport"], g["base"])

    def cal(k):
        (lh, tid), (sport, base) = k, tareas[k]
        return k, calendario(lh, sport, tid)

    with ThreadPoolExecutor(HILOS) as ex:
        calendarios = dict(ex.map(cal, tareas))
    ids_por_equipo = {k: ultimos_ids(v, N_PARTIDOS, k[0]) for k, v in calendarios.items()}

    pendientes = {}
    for (lh, tid), ids in ids_por_equipo.items():
        sport, base = tareas[(lh, tid)]
        for liga_ev, eid in ids:
            pendientes[(liga_ev, eid)] = (sport, base)

    def al_dia(lh, eid):
        r = leer_json(CACHE / "partidos" / lh / f"{eid}.json", None)
        return bool(r and r.get("v") == VERSION_PARTIDO)
    nuevos = sum(1 for (lh, eid) in pendientes if not al_dia(lh, eid))
    print(f"   {len(pendientes)} partidos jugados ({nuevos} por descargar"
          f"{'; tarda unos minutos' if nuevos > 100 else ''})")
    hechos = [0]

    def bajar(k):
        lh, eid = k
        sport, base = pendientes[k]
        r = cargar_partido(lh, sport, base, eid)
        hechos[0] += 1
        if nuevos > 100 and hechos[0] % 100 == 0:
            print(f"   … {hechos[0]}/{len(pendientes)}")
        return k, r

    with ThreadPoolExecutor(HILOS) as ex:
        partidos = dict(ex.map(bajar, pendientes))
    return calendarios, ids_por_equipo, partidos


# --------------------------------------------------------------------------- 3. lesiones

def bajar_lesiones(juegos):
    lesiones = {}

    def una(liga):
        if LIGAS[liga][2] in ("futbol", "ncaab", "ncaaf"):
            return []
        d = get_json(f"{B}/{LIGAS[liga][0]}/{liga}/injuries", ttl=3600) or {}
        return d.get("injuries", [])

    import re
    with ThreadPoolExecutor(HILOS) as ex:
        for lista in ex.map(una, sorted({g["liga"] for g in juegos})):
            for t in lista:
                tid = str(t.get("id", ""))
                for i in t.get("injuries", []):
                    a = i.get("athlete", {})
                    estado = i.get("status") or ""
                    if estado.lower() in ("active", ""):
                        continue  # ESPN a veces lista jugadores que ya están sanos
                    aid = str(a.get("id") or "")
                    if not aid:
                        for l in a.get("links", []):
                            mm = re.search(r"/id/(\d+)", l.get("href", ""))
                            if mm:
                                aid = mm.group(1)
                                break
                    lesiones.setdefault(tid, []).append({
                        "id": aid, "nombre": a.get("displayName"), "estado": TRAD.get(estado, estado),
                        "fuera": estado.lower() in FUERA, "nota": i.get("shortComment") or ""})
    return lesiones


# --------------------------------------------------------------------------- contexto en los picks

def poner_contexto(g, picks, arbitros, prom_tarjetas):
    pv = g.get("previo") or {}
    base = g["base"]
    for lado in ("L", "V"):
        d = g[lado].get("descanso")
        etiqueta = None
        if base in ("nba", "nhl") and d == 1:
            etiqueta = "⚠ 2 noches seguidas"
        elif base == "nfl" and d is not None and d <= 4:
            etiqueta = "⚠ semana corta"
        if etiqueta:
            g[lado]["cansado"] = etiqueta.replace("⚠ ", "")
            for p in picks:
                if p.get("lado") == lado:
                    p["tags"] = list(p["tags"]) + [etiqueta]
    clima = pv.get("clima")
    if clima and not g.get("indoor"):
        avisos_clima = []
        if (clima.get("rafaga_kmh") or 0) >= 32:
            avisos_clima.append(f"ráfagas {clima['rafaga_kmh']} km/h")
        if (clima.get("lluvia") or 0) >= 50:
            avisos_clima.append(f"lluvia {clima['lluvia']:.0f}%")
        if clima.get("temp_c") is not None and clima["temp_c"] <= -4:
            avisos_clima.append(f"{clima['temp_c']}°C")
        if avisos_clima:
            g["clima_alerta"] = " · ".join(avisos_clima)
            for p in picks:
                if p["fam"].split(":")[0] in ("tot_o", "tot_u", "m1_o", "m1_u") or p.get("stat") in ("pyd", "rey", "recs", "ptd"):
                    p["tags"] = list(p["tags"]) + ["🌬 " + g["clima_alerta"]]
    espn = pv.get("espn")
    for p in picks:
        if p["fam"] in ("ml_L", "ml_V"):
            lado = p["fam"][-1]
            if espn and espn.get(lado) is not None and p.get("p_mkt"):
                dif = espn[lado] - p["p_mkt"] * 100
                if abs(dif) >= 7:
                    p["tags"] = list(p["tags"]) + [f"ESPN le da {espn[lado]:.0f}%"]
            if p.get("pa") and p["pa"]["extra"] >= 0.01:
                p["tags"] = list(p["tags"]) + ["PA Caliente"]
    # portero probable (NHL): las atajadas de un portero que no va a abrir no sirven
    por = pv.get("porteros") or {}
    for p in picks:
        if p.get("stat") == "sv":
            prob = por.get(p["lado"])
            if prob and prob["id"] != p["pid"]:
                p["alerta"] = True
                p["tags"] = list(p["tags"]) + [f"⚠ el probable es {prob['nombre']}"]
    if base != "futbol":
        return
    # tarjetas esperadas: lo que recibe cada equipo y lo que reciben sus rivales
    tL, tV = g["L"].get("tarjetas"), g["V"].get("tarjetas")
    esperado = None
    if tL and tV:
        aL = media([tL["rec"], tV["riv"]])  # lo que suele recibir el local y lo que le sacan a los rivales del visitante
        aV = media([tV["rec"], tL["riv"]])
        esperado = round(aL + aV, 1)
        g["tarjetas_txt"] = (f"{g['L']['corto']} recibe {tL['rec']:.1f}" + (f" (sus rivales {tL['riv']:.1f})" if tL["riv"] is not None else "")
                             + f" · {g['V']['corto']} recibe {tV['rec']:.1f}" + (f" (sus rivales {tV['riv']:.1f})" if tV["riv"] is not None else "")
                             + f" · esperado ≈ {esperado:.1f} por partido")
        g["tarjetas_esp"] = esperado
    # árbitro: football-data (Inglaterra/Escocia) y, si no, lo poco que traiga ESPN
    fd = g.get("arbitro") or {}
    arb, avg, n, base_liga, o45 = None, None, 0, prom_tarjetas, None
    if fd.get("prom") is not None:
        arb, avg, n, base_liga, o45 = fd["nombre"], fd["prom"], fd["n"], fd.get("liga_prom"), fd.get("o45")
        g["arbitro_txt"] = (f"{arb}: {avg:.1f} tarjetas por partido ({n} partidos"
                            + (f", esta temporada {fd['prom_act']:.1f}" if fd.get("prom_act") is not None and fd.get("n_act", 0) >= 3 else "")
                            + ")" + (f" · promedio de la liga {base_liga:.1f}" if base_liga else "")
                            + (f" · más de 4.5 en {o45:.0%}" if o45 is not None else ""))
    elif fd.get("nombre"):
        g["arbitro_txt"] = f"{fd['nombre']} (todavía sin suficientes partidos para promedio)"
    elif pv.get("arbitro") in arbitros and arbitros[pv["arbitro"]][1] >= 3:
        arb = pv["arbitro"]
        avg, n = arbitros[arb]
        g["arbitro_txt"] = f"{arb}: {avg:.1f} tarjetas por partido ({n} partidos)"
    for p in picks:
        if p["fam"] in ("tar_o", "tar_u"):
            extra = []
            if esperado is not None:
                extra.append(f"esperado {esperado:.1f} tarj")
            if avg is not None:
                extra.append(f"árbitro {avg:.1f} tarj/partido")
            p["tags"] = list(p["tags"]) + extra
    if avg is None or not base_liga or n < 5:
        return
    dif = avg - base_liga
    # joyita: árbitro muy tarjetero -> más de X; muy permisivo -> menos de X (y que el historial de ambos lo respalde)
    if dif >= 0.8:
        cands = [p for p in picks if p["fam"] == "tar_o" and p["orden"] <= avg - 0.5 and p["hits"] / p["n"] >= 0.6]
        q = max(cands, key=lambda p: p["orden"]) if cands else None
        quien = "saca"
    elif dif <= -0.8:
        cands = [p for p in picks if p["fam"] == "tar_u" and -p["orden"] >= avg + 0.5 and p["hits"] / p["n"] >= 0.6]
        q = min(cands, key=lambda p: -p["orden"]) if cands else None
        quien = "solo saca"
    else:
        q = None
    if q:
        q.update(joya="arbitro", score=abs(dif) / 3,
                 razon=(f"Pita {arb}, que {quien} {avg:.1f} tarjetas por partido ({n} partidos) contra "
                        f"{base_liga:.1f} del promedio de la liga"
                        + (f"; con estos equipos se esperan {esperado:.1f}" if esperado is not None else "")
                        + f". Se cumplió {q['hits']}/{q['n']} en los partidos de ambos."))


# --------------------------------------------------------------------------- Telegram

def texto_telegram(parlays, juegos, ahora, cfg, usar_pa, joyas):
    J = {g["id"]: g for g in juegos}
    lineas = [f"🎯 Parlays de hoy · {DIAS_ES[ahora.weekday()]} {ahora.day} {MESES_ES[ahora.month - 1]}"]
    for pl in parlays:
        legs = sorted(pl["legs_picks"], key=lambda p: J[p["juego"]]["orden"])
        lineas.append(f"\n{pl['nombre']} · {len(legs)} patas · {americano_de_decimal(pl['dec']):+d} · "
                      f"prob. {pl['prob'] * 100:.0f}%")
        for p in legs:
            j = J[p["juego"]]
            m = momio_pata(p, usar_pa)
            lineas.append(f"• {j['hora']} {p['texto']} ({m:+d}{'' if p.get('real') else ' ≈'})")
    if joyas:
        lineas.append("\n💎 Joyitas de hoy")
        for p in joyas[:5]:
            lineas.append(f"• {J[p['juego']]['hora']} {p['texto']} — {p.get('razon', '')[:110]}")
    lineas.append("\nMomios con ≈ son aproximados: revisa los de tu casa.")
    return "\n".join(lineas)


# --------------------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=0, help="mínimo de días a revisar en todos los deportes "
                    "(si no, usa dias_por_deporte de datos/config.json)")
    ap.add_argument("--ligas", default=",".join(LIGAS), help="ligas separadas por coma")
    ap.add_argument("--no-abrir", action="store_true")
    ap.add_argument("--avisar", action="store_true", help="manda los parlays de hoy por Telegram")
    ap.add_argument("--publico", action="store_true",
                    help="también arma la versión cifrada para los compas en publico/index.html (clave: CLAVE_PARLAYS)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ligas = [l for l in args.ligas.split(",") if l in LIGAS]
    cfg = cargar_config()
    usar_pa = bool(cfg.get("pago_anticipado", True))
    ahora = datetime.now(MX)
    print(f"Asistente de parlays · {ahora:%d/%m/%Y %H:%M}")

    print("1/6 Buscando partidos…")
    juegos = buscar_partidos(ligas, args.dias, ahora, cfg)
    cuenta = {}
    for g in juegos:
        cuenta[g["liga_nombre"]] = cuenta.get(g["liga_nombre"], 0) + 1
    print("   " + (", ".join(f"{k}: {v}" for k, v in cuenta.items()) or "ninguno"))

    print("2/6 Historial de equipos…")
    calendarios, ids_por_equipo, partidos = bajar_historial(juegos)

    print("3/6 Lesiones…")
    lesiones = bajar_lesiones(juegos)

    print("4/6 Contexto (descanso, enfrentamientos, porteros, clima, árbitros)…")
    with ThreadPoolExecutor(HILOS) as ex:
        previos = dict(zip([g["id"] for g in juegos], ex.map(contexto.previo, juegos)))
    recs_equipo = {}
    for g in juegos:
        for lado in ("L", "V"):
            tid, lh = g[lado]["id"], g[lado]["liga_hist"]
            rs = [partidos.get(k) for k in ids_por_equipo.get((lh, tid), [])]
            recs_equipo[(lh, tid)] = [r for r in rs if r and tid in r["eq"]]
    por_liga = {}
    for (lh, tid), rs in recs_equipo.items():
        por_liga.setdefault(lh, {})[tid] = rs
    base_liga = {g[l]["liga_hist"]: g["base"] for g in juegos for l in ("L", "V")}
    dvp = {lh: contexto.defensa_rival(base_liga[lh], eqs) for lh, eqs in por_liga.items()
           if lh not in NCAA and lh != "all"}
    recs_futbol = {r["id"]: r for (lh, _), rs in recs_equipo.items() if base_liga.get(lh) == "futbol" for r in rs}
    arbitros, prom_tarjetas = contexto.tarjetas_por_arbitro(recs_futbol.values())
    try:  # quién pita y su promedio (football-data: Premier, Championship, Escocia)
        arb_fd = fd_arbitros.asignar(juegos, ahora)
    except Exception as e:
        print(f"   (árbitros football-data: {e})")
        arb_fd = {}

    print("5/6 Calculando candados, joyitas y combinadas…")
    todos, combos = [], []
    for g in juegos:
        g["previo"] = previos.get(g["id"]) or {}
        if arb_fd.get(g["id"]):
            g["arbitro"] = arb_fd[g["id"]]
        recs, hist = {}, {}
        for lado in ("L", "V"):
            tid, lh = g[lado]["id"], g[lado]["liga_hist"]
            recs[lado] = recs_equipo[(lh, tid)]
            hist[lado] = [f for f in (rasgos(r, tid, g["base"]) for r in recs[lado]) if f]
            g[lado]["forma"] = "".join("G" if f["margen"] > 0 else ("P" if f["margen"] < 0 else "E") for f in hist[lado][:5])
            g[lado]["n_hist"] = len(hist[lado])
            g[lado]["descanso"] = contexto.descanso(calendarios.get((lh, tid), []), g["fecha"])
            if g["base"] == "futbol":  # tarjetas por partido: las suyas y las de sus rivales
                tf = [f["tarf"] for f in hist[lado] if f.get("tarf") is not None]
                tc = [f["tarc"] for f in hist[lado] if f.get("tarc") is not None]
                if len(tf) >= 3:
                    g[lado]["tarjetas"] = {"rec": round(media(tf), 1), "n": len(tf),
                                           "riv": round(media(tc), 1) if len(tc) >= 3 else None}
            if g["base"] == "nhl":
                abridores, cuenta_p = contexto.porteros_historial(recs[lado], tid)
                prob = (g["previo"].get("porteros") or {}).get(lado)
                if prob:
                    g[lado]["portero"] = {"nombre": prob["nombre"], "abrio": cuenta_p.get((prob["id"], prob["nombre"]), 0),
                                          "n": len(abridores)}
        # lesionados que sí estaban jugando
        les_por_lado = {}
        for lado in ("L", "V"):
            tid = g[lado]["id"]
            jugaron = {}
            for r in recs[lado]:
                for pid, st in (r["jug"].get(tid) or {}).items():
                    jugaron[pid] = jugaron.get(pid, 0) + 1
                    jugaron[st.get("n")] = jugaron.get(st.get("n"), 0) + 1
            ls = [dict(l, pj=jugaron.get(l["id"]) or jugaron.get(l["nombre"]) or 0) for l in lesiones.get(tid, [])]
            ls = [l for l in ls if l["pj"] >= 2]
            ls.sort(key=lambda l: (not l["fuera"], -l["pj"]))
            les_por_lado[lado] = ls
        g["lesiones"] = les_por_lado

        picks = mercados.mercados_equipo(g, hist["L"], hist["V"])
        for lado, otro in (("L", "V"), ("V", "L")):
            idx = {}
            for l in les_por_lado[lado]:
                idx[l["id"]] = l
                idx[l["nombre"]] = l
            f_otro = dvp.get(g[otro]["liga_hist"])
            fr = (lambda s, pos, f=f_otro, o=g[otro]["id"]: f(o, s, pos)) if f_otro else None
            picks += mercados.mercados_jugadores(g, lado, recs[lado], idx, fr)
            picks += mercados.joyitas_jugadores(g, lado, recs[lado], les_por_lado[lado])
        picks += mercados.joyitas_matchup(picks)
        modelo.aplicar(g, picks)  # momio estimado de la casa para lo que ESPN no trae
        for p in picks:  # el Pago Anticipado solo cuenta si tu casa lo tiene en ese deporte
            if p.get("pa"):
                p["pa_ok"] = casa_cubre(cfg.get("casa"), p["deporte"])
        poner_contexto(g, picks, arbitros, prom_tarjetas)
        for lado in ("L", "V"):
            combos += mercados.combinadas(g, lado, recs[lado], picks)
        g["picks"] = [p["id"] for p in picks]
        todos += picks

    # ---- UFC (peleadores, no equipos: su propio módulo)
    if "ufc" in ligas:
        dias_ufc = int({**CONFIG_DEF["dias_por_deporte"], **(cfg.get("dias_por_deporte") or {})}.get("ufc") or 14)
        peleas, picks_ufc = ufc.buscar(ahora, max(dias_ufc, args.dias or 0))
        for p in picks_ufc:
            p["pa_ok"] = False
        juegos += peleas
        todos += picks_ufc
        juegos.sort(key=lambda g: g["orden"])
        if peleas:
            print(f"   UFC: {len(peleas)} peleas")

    # ---- candados
    candados = mercados.mejor_por_familia(todos, mercados.cumple_candado)
    cand_final, por_juego = [], {}
    for p in sorted(candados, key=lambda p: -mercados.valor_candado(p)):
        k = (p["juego"], p["clase"])
        if por_juego.get(k, 0) < (4 if p["clase"] == "equipo" else 8):
            cand_final.append(p)
            por_juego[k] = por_juego.get(k, 0) + 1
    for p in cand_final:
        p["candado"] = True
    # partidos sin candado: lo más seguro de ese partido, marcado como "casi candado"
    con_cand = {p["juego"] for p in cand_final}
    for g in juegos:
        if g["id"] in con_cand or a_mx(g["fecha"]) <= ahora:
            continue
        cs = [p for p in todos if p["juego"] == g["id"] and mercados.casi_candado(p)]
        if cs:
            p = max(cs, key=mercados.valor_candado)
            p["candado"] = "casi"
            cand_final.append(p)

    # ---- joyitas
    joy_j = [p for p in todos if p.get("joya") in ("sin_estrella", "rol", "matchup")]
    joy_j = mercados.uno_por_jugador(mercados.mejor_por_familia(joy_j, lambda p: True), lambda p: p["score"])
    joy_eq = mercados.mejor_por_familia([p for p in todos if mercados.es_joyita_equipo(p, usar_pa)
                                         or p.get("joya") == "arbitro"], lambda p: True)
    joy_final, por_juego = [], {}
    for p in sorted(joy_j + joy_eq, key=lambda p: -p["score"]):
        if por_juego.get(p["juego"], 0) < 3:
            joy_final.append(p)
            por_juego[p["juego"]] = por_juego.get(p["juego"], 0) + 1
    # partidos sin joyita: la mejor ventaja contra lo que da (o debería dar) la casa, aunque sea chica
    con_joya = {p["juego"] for p in joy_final}
    for g in juegos:
        if g["id"] in con_joya or a_mx(g["fecha"]) <= ahora:
            continue
        cs = [p for p in todos if p["juego"] == g["id"] and p.get("p_mkt") and not p.get("joya")
              and not p.get("alerta") and p["n"] >= 8 and momio_pata(p) >= -300 and p["est"] >= 0.45
              and mercados.ventaja(p, usar_pa) <= mercados.MAX_VENTAJA]
        if not cs:
            continue
        p = max(cs, key=lambda p: mercados.ventaja(p, usar_pa))
        edge = mercados.ventaja(p, usar_pa)
        if edge < 0.03:
            continue
        p.update(joya="partido", score=edge * 0.5,
                 razon=(f"La mejor ventaja que encontré en este partido: la casa {'da' if p.get('real') else 'debería dar'} "
                        f"~{p['p_mkt'] * 100:.0f}% y la historia dice {p['hits']}/{p['n']}. Ventaja chica "
                        f"({edge * 100:.0f} puntos): úsala como pata, no como base."))
        joy_final.append(p)

    # ---- momios reales de jugadores (si hay clave)
    pool = mercados.pool_parlays(todos)
    odds_txt = props_odds.aplicar(cfg, juegos, list({p["id"]: p for p in pool + cand_final + joy_final}.values()), ahora)
    if odds_txt:
        print("   " + odds_txt)

    # ---- parlays de hoy (para el historial y Telegram; en la página se arman al abrirla)
    J = {g["id"]: g for g in juegos}
    pool_hoy = [p for p in pool if a_mx(J[p["juego"]]["fecha"]).date() == ahora.date() and a_mx(J[p["juego"]]["fecha"]) > ahora]
    parlays_hoy = mercados.armar_parlays(pool_hoy, usar_pa)
    parlays_hoy = [pl for pl in parlays_hoy if pl["nombre"] != "Lotería"]
    # la lotería usa todos los días (18 partidos de varias ligas)
    pool_vivo = [p for p in pool if a_mx(J[p["juego"]]["fecha"]) > ahora]
    equipos = {g["id"]: (g["L"]["id"], g["V"]["id"]) for g in juegos}
    parlays_hoy += mercados.armar_parlays(pool_vivo, usar_pa, solo={"Lotería"}, equipos=equipos)
    for pl in parlays_hoy:
        pl["legs_picks"] = [PICKS[i] for i in pl["legs"]]

    print("6/6 Historial y página…")
    n_cal = historial.calificar(ahora)
    cats = {}
    for p in cand_final:
        cats.setdefault(p["id"], set()).add("casi_candado" if p["candado"] == "casi" else "candado")
    for p in joy_final:
        cats.setdefault(p["id"], set()).add(f"joyita:{p['joya']}")
    for pl in parlays_hoy:
        for i in pl["legs"]:
            cats.setdefault(i, set()).add(f"parlay:{pl['nombre']}")
    historial.guardar([(PICKS[i], c) for i, c in cats.items()], J, parlays_hoy, ahora)
    resumen = historial.resumen(usar_pa)
    apuestas, estado_ap = historial.apuestas_y_estado()

    # picks que van en la página
    usados = {p["id"] for p in cand_final + joy_final + pool}
    for c in combos:
        usados |= {c["a"], c["b"]}
    for g in juegos:
        ps = [PICKS[i] for i in g["picks"]]
        mejores = mercados.mejor_por_familia(ps, lambda p: p["hits"] / p["n"] >= 0.7 and p["n"] >= 5)
        mejores.sort(key=lambda p: (-(p["clase"] == "equipo"), -p["est"]))
        g["picks"] = [p["id"] for p in mejores[:45]]
        usados |= set(g["picks"])
    for i, c in enumerate(combos):
        c["id"] = f"c{i}"

    cortos = sorted({g[l]["abbr"] for g in juegos for l in ("L", "V") if g[l]["n_hist"] < 5})
    aviso = ""
    if BLOQUEO["activo"]:
        aviso = "ESPN frenó las descargas a la mitad: algunos equipos tienen historial incompleto. Vuelve a correrlo en un rato."
    elif cortos:
        aviso = f"Con poco historial (menos de 5 partidos): {', '.join(cortos)}. Tómalos con calma."

    datos = {
        "generado": ahora.isoformat(),
        "titulo": f"{DIAS_ES[ahora.weekday()]} {ahora.day} {MESES_ES[ahora.month - 1]} · {ahora:%H:%M}",
        "juegos": juegos,
        "picks": {i: PICKS[i] for i in usados},
        "candados": [p["id"] for p in sorted(cand_final, key=lambda p: (p["candado"] == "casi", -mercados.valor_candado(p)))],
        "joyitas": [p["id"] for p in joy_final],
        "pool": [p["id"] for p in pool],
        "combos": combos,
        "aviso": aviso,
        "odds_txt": odds_txt or "",
        "deportes": DEPORTE,
        "config": {"casa": cfg.get("casa") or "Playdoit", "pa": usar_pa, "tope": cfg.get("tope_mensual") or 0,
                   "casas_pa": CASAS_PA, "odds_api": bool(cfg.get("odds_api_key")),
                   "telegram": bool(cfg.get("telegram_token"))},
        "historial": resumen,
        "apuestas": apuestas,
        "estado_ap": estado_ap,
    }
    # lo que puede consultar "Pregúntale a la IA" (partidos, contexto y dónde está el historial de cada equipo)
    escribir_json(DATOS / "contexto_ia.json", {
        "generado": ahora.isoformat(),
        "juegos": [{
            **{k: g.get(k) for k in ("id", "liga", "liga_nombre", "tipo", "base", "fecha", "momios", "previo")},
            "L": {k: g["L"].get(k) for k in ("id", "nombre", "corto", "abbr", "liga_hist", "forma", "descanso")},
            "V": {k: g["V"].get(k) for k in ("id", "nombre", "corto", "abbr", "liga_hist", "forma", "descanso")},
            "lesiones": {l: [f"{x['nombre']} ({x['estado']})" for x in g["lesiones"][l][:8]] for l in ("L", "V")},
            "picks": [f"{PICKS[i]['texto']} · se cumplió {PICKS[i]['hits']}/{PICKS[i]['n']} · prob {PICKS[i]['est']:.0%}"
                      for i in g["picks"][:12]],
        } for g in juegos],
        "historial": {f"{lh}|{tid}": [list(x) for x in ids] for (lh, tid), ids in ids_por_equipo.items()},
    })
    plantilla = (AQUI / "plantilla.html").read_text("utf-8")
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    html = plantilla.replace("/*__DATOS__*/null", js)
    SALIDA.mkdir(exist_ok=True)
    (SALIDA / f"parlays_{ahora:%Y-%m-%d_%H%M}.html").write_text(html, "utf-8")
    ultimo = AQUI / "PARLAYS.html"
    ultimo.write_text(html, "utf-8")
    if args.publico:
        import publicar
        print(f"   Versión para los compas (cifrada): {publicar.publicar(datos, plantilla)}")
    print(f"\nListo: {len(juegos)} partidos · {len(cand_final)} candados · {len(joy_final)} joyitas · "
          f"{len(combos)} combinadas · {n_cal} apuestas calificadas")

    if args.avisar:
        joyas_hoy = [p for p in joy_final if a_mx(J[p["juego"]]["fecha"]).date() == ahora.date()]
        if avisos.enviar(cfg, texto_telegram(parlays_hoy, juegos, ahora, cfg, usar_pa, joyas_hoy)):
            print("   Aviso mandado por Telegram.")
        elif not cfg.get("telegram_token"):
            print("   (Telegram no está configurado: ver avisos.py)")
    if not args.no_abrir:
        webbrowser.open(ultimo.as_uri())


if __name__ == "__main__":
    main()
