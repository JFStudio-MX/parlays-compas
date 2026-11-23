# Asistente de parlays

Abre **Parlays** desde Inicio (o doble clic en `VER PARLAYS.bat`):
1. Baja los partidos que vienen:
   - fútbol: 8 días (la jornada completa con Champions y Europa League);
   - NFL: hasta el siguiente lunes;
   - NCAA americano: 7 días;
   - NBA, NHL y NCAA básquet: hoy y mañana.

   Se cambia en `dias_por_deporte` de `datos/config.json`.
2. Califica lo del día anterior.
3. Abre la página.

**Deja abierta la ventanita negra mientras la uses**: así se guardan tus apuestas.

Ligas: NBA, NFL, NHL, Liga MX, Premier, LaLiga, Serie A, Bundesliga, Ligue 1, Champions, Europa League, NCAA básquet y NCAA americano (en NCAA solo partidos con equipos del top 25).
Datos gratis de ESPN: momios de DraftKings, resultados, jugadas, lesiones, pronóstico de ESPN, clima y árbitros.

## Pestañas

- **Candados**: se cumplió 9 de 10 veces o más, no falló en los últimos 5 y paga mejor que -650 (los de -700 para abajo no salen). Sale la línea más alta que se sigue cumpliendo.
- **Joyitas** (lo que nadie ve):
  - *valor*: la casa da menos probabilidad de la que dice la historia.
  - *sin la estrella*: un jugador rinde más cuando falta el lesionado.
  - *rol nuevo*: más minutos o más balones.
  - *matchup*: el rival permite mucho más de lo normal en esa estadística o posición.
  - *árbitro*: en fútbol, si pita uno que saca muchas tarjetas.
  - *línea típica*: en fútbol.
  - Abajo, **combinadas del mismo partido** que pegaron juntas y se refuerzan.
- **Parlays armados**: se arman al abrir la página con la hora del momento (lo que ya empezó no entra) y respetan los filtros.
  - **Lotería**: 18 patas de varias ligas y días; $10 que hagan $20,000 o más.
  - **Escalera de candados**: 10 favoritos de -250 a -600.
  - **Corto**: busca +160.
  - **Mediano**: busca +500.
  - **Bombazo**: busca +2000.
  - Cada pata dice **por qué** entró (promedio contra la línea, cuántas veces pegó, lo que da la casa, PA, rival, alertas) y arriba un resumen con la pata más floja. Con **×** la quitas y el parlay se rearma.
- **⚡ Armar parlay de hoy**: los mismos parlays, solo con lo que queda de hoy.
- **⚙ Filtrar**: buscar equipo o jugador, tipo de apuesta (ganador, totales, puntos, yardas…), rango de momio, probabilidad mínima, solo momio real, solo con PA de tu casa, sin alertas, ligas y orden. Aplica a todas las pestañas y a los parlays armados.
- **🔄 Actualizar**: vuelve a bajar momios y lesiones sin cerrar la página.
- **Mi parlay → Completar / Armármelo**: pones cuánto quieres cobrar y le agrega las patas que más pagan por el riesgo hasta llegar.
- **Stats e IA**:
  - *Stats de TeamRankings* (gratis): buscas una estadística en español ("yardas por tierra que permite") y sale la tabla de toda la liga con los equipos de la semana resaltados. TeamRankings pide 10 s entre consultas; lo que baja se guarda.
  - *Pregúntale a la IA*: preguntas libres; busca en TeamRankings y en el historial de ESPN y contesta con números. Necesita el paquete `anthropic` y una clave (ver Configuración). Cuesta unos centavos de dólar por pregunta y lo muestra en cada respuesta.
- **Por partido**:
  - Momios y cómo se movió la línea, forma de los últimos 5 y lesionados que sí estaban jugando.
  - Contexto: pronóstico de ESPN, enfrentamientos directos, descanso ("2 noches seguidas", "semana corta"), portero probable (NHL), clima (NFL al aire libre) y árbitro.
  - Combinadas del partido y todas las apuestas con 70% o más.
- **Mis apuestas**:
  - Lo que registras con **"Lo metí"** se califica solo cada vez que corres Parlays, incluido el Pago Anticipado.
  - Ganancia neta, cuántas pegaron, lo que tienes en juego y el tope del mes.
  - Calculadora de **cobertura** (cuánto apostar al otro lado de tu última pata para asegurar ganancia).
- **Historial**: si la página atina. Lo que recomendó cada día se califica solo; ves el porcentaje real contra lo que decía, por tipo, deporte y nivel de confianza, y cuánto habrías ganado con cada parlay armado.

## Casa y Pago Anticipado (selector amarillo de arriba)

- "A ganar" se paga si tu equipo llega a ir arriba por la ventaja, aunque luego pierda:

  | Casa | Pago Anticipado |
  |---|---|
  | **Playdoit** | NBA 20, NFL 17, NHL 3 goles, fútbol 2 goles |
  | **Draftea** | NBA 20, NFL 17, NHL 3 goles, fútbol 2 goles |
  | **Caliente** | NBA 20, NFL 17, fútbol 2 goles (sin NHL) |
  | **Stake** | no se cuenta: sus reglas no están claras |

  Fuentes: [Playdoit NFL](https://www.playdoit.mx/promociones/modals/pago-anticipado-nfl), [legalbet (Playdoit NHL)](https://legalbet.mx/bonos/playdoit-pagos-anticipados-en-apuestas-deportivas/), [Draftea](https://help.draftea.com/support/solutions/articles/150000212088--c%C3%B3mo-funciona-el-pago-anticipado-pa-), [Caliente](https://www.caliente.mx/mas/promociones/pago-anticipado/).
- La probabilidad de esos "gana" lo toma en cuenta según la casa elegida. Tus apuestas se califican con el PA de la casa donde las metiste.
- **Súper PA (fútbol, 1 gol):** sale como "Gana X (Súper PA)". Su momio es aproximado: pon el de tu casa si lo ofrece en ese partido.

## Cómo leer los números

- Momios con **≈** son aproximados: cámbialos por los de tu casa en Mi parlay.
- **Momio justo**: lo que debería pagar según la historia. Si tu casa paga más, conviene.
- La probabilidad mezcla la historia con lo que dice la casa (y en jugadores, con su promedio y lo que permite el rival). No es garantía.

## Configuración (`datos/config.json`)

| Campo | Para qué |
|---|---|
| `casa` | Tu casa por defecto (Playdoit). En la página la cambias con el selector. |
| `anthropic_api_key` | Clave de https://console.anthropic.com para "Pregúntale a la IA". También hay que instalar el paquete: `python -m pip install anthropic`. `ia_modelo`: Claude Opus 5.5 por defecto. |
| `dias_por_deporte` | Cuántos días hacia adelante revisa cada deporte. |
| `pago_anticipado` | `true`/`false`. |
| `tope_mensual` | Lo máximo que quieres apostar al mes (0 = sin tope). Sale una barra en Mis apuestas. |
| `odds_api_key` | Clave gratis de https://the-odds-api.com (500 créditos al mes) para **momios reales de jugadores**. `odds_api_max_creditos` limita lo que gasta cada corrida (40 por defecto). |
| `telegram_token` / `telegram_chat_id` | Para que te lleguen los parlays de hoy por Telegram con `python parlays.py --avisar` (cómo sacarlos: ver `avisos.py`). |

## Pasarle apuestas a Claude por el chat

Mándale el parlay como lo metiste (casa, monto, momio total y cada pata). Lo agrega a `datos/apuestas.json` y se califica solo.

## Archivos

| Archivo | Qué hace |
|---|---|
| `parlays.py` | Lo principal (corre todo y arma la página). |
| `nucleo.py` | Descargas de ESPN, lectura de partidos y reglas para calificar. |
| `mercados.py` | Apuestas, candados, joyitas, combinadas y armado de parlays. |
| `contexto.py` | Descanso, enfrentamientos, clima, porteros, árbitros y lo que permite cada rival. |
| `historial.py` | Calificación automática y tus apuestas. |
| `props_odds.py` | Momios reales de jugadores (The Odds API). |
| `avisos.py` | Telegram. |
| `servidor.py` | Servidor local: guarda apuestas, Stats/IA y el botón Actualizar. |
| `estadisticas.py` | TeamRankings (respeta 10 s entre consultas). |
| `ia.py` | Pregúntale a la IA (Claude). |
| `plantilla.html` | La página. |

Carpetas:
- `cache/`: partidos guardados para no volver a bajarlos.
- `datos/`: historial, apuestas y configuración. **No la borres.**
- `salida/`: copia de cada corrida.
