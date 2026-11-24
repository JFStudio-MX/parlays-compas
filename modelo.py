# -*- coding: utf-8 -*-
"""Mercado estimado: con el momio del ganador y del total (lo único que da ESPN) se calcula cuánto
debería dar la casa en las demás apuestas del partido (+1.5, 1er tiempo, ambos anotan, goles de un equipo…).

- Fútbol y NHL: goles de cada equipo como Poisson; se buscan los promedios que reproducen el 1X2 y el total.
- NBA, NFL y NCAA: margen y total como normales alrededor del spread y del total de la casa.

Sirve para dos cosas: un momio aproximado realista (no uno sacado de nuestra propia probabilidad) y
encontrar valor: donde la historia de los equipos le gana a lo que la casa debería dar."""
import math
from functools import lru_cache
from statistics import NormalDist

from nucleo import americano_de_decimal, momio_prob, sin_vig

GMAX = 11                                    # goles por equipo que se cuentan (0..10)
LAMS = [round(0.05 * i, 2) for i in range(2, 101)]   # promedios de goles posibles: 0.10 .. 5.00
VIG = 1.05                                   # lo que se queda la casa en mercados secundarios (~5%)
K_MERCADO = 20                               # cuánto pesa el mercado estimado (como 20 partidos)

# desviaciones típicas (margen, total, margen 1a mitad, total 1a mitad) y qué parte del total cae en la 1a mitad
NORMAL = {"nfl": (13.5, 13.5, 9.5, 10.0, 0.48), "ncaaf": (15.5, 15.5, 11.0, 11.0, 0.48),
          "nba": (12.0, 18.5, 8.5, 12.0, 0.505), "ncaab": (11.0, 16.0, 8.0, 11.0, 0.48)}
POISSON = {"futbol": {"mitad": 0.45, "prom": 2.7}, "nhl": {"mitad": 0.31, "prom": 6.0}}


def _pmf(lam):
    out = [math.exp(-lam)]
    for k in range(1, GMAX):
        out.append(out[-1] * lam / k)
    return out


_PMF = {lam: _pmf(lam) for lam in LAMS}
_TABLA = None


def _tabla():
    """Para cada par de promedios: P(gana local), P(empate). Se calcula una vez."""
    global _TABLA
    if _TABLA is None:
        _TABLA = {}
        for a in LAMS:
            pa = _PMF[a]
            cum_a = [sum(pa[:k + 1]) for k in range(GMAX)]
            for b in LAMS:
                pb = _PMF[b]
                emp = sum(pa[k] * pb[k] for k in range(GMAX))
                # gana A: A anota más que B
                gana = sum(pb[k] * (1 - cum_a[k]) for k in range(GMAX))
                _TABLA[(a, b)] = (gana, emp)
    return _TABLA


@lru_cache(maxsize=None)
def _p_over(lam_tot, x):
    """P(total > x) con total ~ Poisson(lam_tot)."""
    k = math.floor(x)
    p, acum = math.exp(-lam_tot), 0.0
    for i in range(k + 1):
        acum += p
        p *= lam_tot / (i + 1)
    return 1 - acum


def ajustar(j):
    """Modelo del partido a partir de los momios de la casa (o None si no hay con qué)."""
    m = j.get("momios") or {}
    tipo = j["tipo"]
    if tipo in POISSON:
        cfg = POISSON[tipo]
        if tipo == "futbol":
            pL, pE, pV = sin_vig(m.get("ml_L"), m.get("ml_E"), m.get("ml_V"))
        else:
            pL, pV = sin_vig(m.get("ml_L"), m.get("ml_V"))
        if not pL:
            return None
        T = m.get("total")
        po = None
        if T is not None:
            po = sin_vig(m.get("over_m"), m.get("under_m"))[0] or 0.5
        best, berr = None, 9.0
        for (a, b), (gana, emp) in _tabla().items():
            pierde = 1 - gana - emp
            if tipo == "nhl":  # el empate en tiempo regular se va a prórroga: mitad y mitad
                e = (gana + emp / 2 - pL) ** 2
            else:
                e = (gana - pL) ** 2 + (pierde - pV) ** 2
            if T is not None:
                over = _p_over(round(a + b, 2), T)
                f0 = math.floor(T)
                if tipo == "nhl" and f0 % 2 == 0 and f0 // 2 < GMAX:  # empate en regular + gol de prórroga = over
                    over += _PMF[a][f0 // 2] * _PMF[b][f0 // 2]
                e += (over - po) ** 2
            else:
                e += 0.02 * ((a + b) - cfg["prom"]) ** 2 / cfg["prom"] ** 2  # sin total: cerca del promedio de la liga
            if e < berr:
                best, berr = (a, b), e
        a, b = best
        f = cfg["mitad"]
        return {"tipo": "poisson", "nhl": tipo == "nhl", "lam": (a, b),
                "full": _matriz(a, b), "half": _matriz(a * f, b * f)}
    if tipo in NORMAL:
        sd, sdT, sd1, sdT1, frac1 = NORMAL[tipo]
        s, T = m.get("sp_L"), m.get("total")
        if s is not None:
            mu = -s  # spread del local: -7 = favorito por 7
        else:
            pL, pV = sin_vig(m.get("ml_L"), m.get("ml_V"))
            if not pL:
                return None
            mu = NormalDist(0, sd).inv_cdf(min(max(pL, 0.01), 0.99))
        return {"tipo": "normal", "mu": mu, "T": T, "sd": sd, "sdT": sdT, "sd1": sd1, "sdT1": sdT1, "frac1": frac1}
    return None


def _matriz(a, b):
    pa, pb = _pmf(a), _pmf(b)
    return [[pa[i] * pb[k] for k in range(GMAX)] for i in range(GMAX)]


def _cumple(v, op, x):
    return {">": v > x, "<": v < x, ">=": v >= x, "==": v == x}[op]


def prob_regla(r, j, mod):
    """Probabilidad de que se cumpla la regla de una apuesta de equipo según el modelo (None si no aplica)."""
    if r.get("k") != "eq":
        return None
    m, op, x = r["m"], r["op"], r["x"]
    yo_local = r.get("tid") in (None, j["L"]["id"])
    if mod["tipo"] == "poisson":
        if m in ("margen", "total", "pf", "btts"):
            M = mod["full"]
        elif m in ("m1", "m1mg"):
            M = mod["half"]
        else:
            return None  # córners, tarjetas, Súper PA: la casa no da con qué estimarlos
        prob = 0.0
        for i in range(GMAX):
            for k in range(GMAX):
                pij = M[i][k]
                if pij < 1e-9:
                    continue
                # NHL: si empatan en tiempo regular, la prórroga la gana cualquiera (por 1 y un gol más al total)
                finales = [(i, k, 1.0)]
                if mod["nhl"] and m in ("margen", "total", "pf") and i == k:
                    finales = [(i + 1, k, 0.5), (i, k + 1, 0.5)]
                for gL, gV, w in finales:
                    yo, el = (gL, gV) if yo_local else (gV, gL)
                    v = {"margen": yo - el, "m1mg": yo - el, "total": gL + gV, "m1": gL + gV, "pf": yo,
                         "btts": 1 if gL > 0 and gV > 0 else 0}[m]
                    if _cumple(v, op, x):
                        prob += pij * w
        return prob
    # normal (NBA, NFL, NCAA)
    lado = 1 if yo_local else -1
    T = mod["T"]
    if m == "margen":
        mu, sd = lado * mod["mu"], mod["sd"]
    elif m == "m1mg":
        mu, sd = lado * mod["mu"] / 2, mod["sd1"]
    elif m == "total" and T:
        mu, sd = T, mod["sdT"]
    elif m == "m1" and T:
        mu, sd = T * mod["frac1"], mod["sdT1"]
    elif m == "pf" and T:
        mu, sd = (T + lado * mod["mu"]) / 2, mod["sdT"] * 0.62
    else:
        return None
    d = NormalDist(mu, sd)
    entero = float(x).is_integer()
    if op == ">":
        return 1 - d.cdf(x + 0.5 if entero else x)
    if op == "<":
        return d.cdf(x - 0.5 if entero else x)
    if op == ">=":
        return 1 - d.cdf(x - 0.5 if entero else x)
    if op == "==":
        return d.cdf(x + 0.5) - d.cdf(x - 0.5)
    return None


def aplicar(j, picks):
    """A las apuestas de equipo sin momio real les pone el mercado estimado (p_mkt), un momio aproximado
    de la casa (m_est) y su probabilidad mezclando la historia con ese mercado."""
    mod = ajustar(j)
    if not mod:
        return 0
    # equipos de ligas distintas (Champions, copas…): su historial viene de otro nivel, la casa pesa el doble
    entre_ligas = j["L"].get("liga_hist") != j["V"].get("liga_hist")
    k = K_MERCADO * (2 if entre_ligas else 1)
    # el muy inferior según la casa (+400 o más): en partidos entre ligas su historial viene de dominar otra liga
    m = j.get("momios") or {}
    debil = next((l for l in ("L", "V") if (m.get(f"ml_{l}") or 0) >= 400), None) if entre_ligas else None
    n = 0
    for p in picks:
        if p["clase"] != "equipo":
            continue
        r = p["regla"]
        if debil and r.get("k") == "eq" and r.get("m") in ("margen", "m1mg", "pf") and r.get("op") in (">", ">="):
            p["sesgo_liga"] = (r.get("tid") == j[debil]["id"])
        if p.get("momio") is not None:
            continue
        q = prob_regla(p["regla"], j, mod)
        if q is None or not 0.02 < q < 0.995:
            continue
        p["p_mkt"] = round(q, 3)
        p["mkt_est"] = True
        p["m_est"] = americano_de_decimal(max(1.01, 1 / (min(q, 0.985) * VIG)))
        p["est"] = round((p["hits"] + k * q) / (p["n"] + k), 3)
        p["justo"] = momio_prob(p["est"])
        if p.get("pa"):  # el Pago Anticipado suma lo mismo que antes sobre la nueva base
            p["pa"]["est"] = round(min(0.99, p["est"] + p["pa"]["extra"]), 3)
        n += 1
    return n
