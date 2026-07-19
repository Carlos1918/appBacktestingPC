# Roadmap de Monetización — BacktestICT

## Diagnóstico actual

Tu app **ya tiene** lo más difícil:
- Conexión en vivo a MT5
- Replay ciego con SL/TP arrastrables
- Detección completa de FVG, Order Blocks, MSS/CHoCH, Liquidez, Premium/Discount, OTE, Killzones
- Journal persistente con estadísticas
- Fibonacci, R:R boxes, líneas, rectángulos, EMAs
- Empaquetado a .exe listo

Desde el punto de vista técnico, el producto está **80% listo**. Lo que falta es pulir la experiencia y darle razones al usuario para pagar.

---

## Priorización (Impacto Comercial × Esfuerzo)

| # | Feature | Impacto | Esfuerzo | Por qué |
|---|---------|---------|----------|---------|
| **P0** | **Exportar journal a CSV/PDF** | 🔥 Alto | ~3h | Sin exportación, el journal está atrapado en la app. Los traders necesitan mostrar resultados a mentores, compartir en Discord, o llevar registro personal. Es LA feature que convierte un juguete en herramienta seria. |
| **P0** | **Guardar/Cargar sesiones completas** | 🔥 Alto | ~8h | Poder cerrar la app, volver a abrir, y retomar exactamente donde quedaste (con dibujos, replay, operaciones abiertas). Sin esto, el usuario pierde todo si cierra la app durante un backtest — frustrante. |
| **P1** | **Equity Curve + Drawdown chart** | Alto | ~6h | El journal muestra números fríos. Una curva de equity con drawdown máximo es lo primero que un trader quiere ver. Es también lo más sharable en redes sociales → marketing gratis. |
| **P1** | **Screenshot con marca de agua** | Alto | ~4h | Un botón que saque captura del gráfico + stats con la marca "BacktestICT" superpuesta. Cada screenshot que un usuario publique en Twitter/Discord es un anuncio gratuito. |
| **P1** | **Modo Examen (Exam Mode)** | Alto | ~5h | "Fijar inicio" + reproducir automáticamente sin poder pausar ni retroceder, registrando nota al final. Los retos de "100 trades ciegos" son virales en la comunidad ICT. |
| **P1** | **Estadísticas avanzadas** | Alto | ~8h | Sharpe ratio, profit factor, max consecutive wins/losses, average R, expectancy por setup (FVG vs OB vs MSS). Esto diferencia la app de cualquier hoja de cálculo. |
| **P2** | **Multi-timeframe sincronizado** | Medio | ~12h | Ver M5, M15 y H1 lado a lado. Los ICT traders viven del multi-timeframe. Es la feature más pedida, pero requiere más arquitectura. |
| **P2** | **Alarma de confluencia** | Medio | ~5h | "📢 FVG + OB + OTE alineados en XAUUSD M15" — alerta visual cuando múltiples conceptos ICT coinciden en la misma zona. Ahorra horas de escaneo manual. |
| **P2** | **Perfiles de sesión guardables** | Medio | ~3h | Guardar/Cargar configuraciones de EMAs, visualización ICT, ratio R:R, etc. "Perfil ICT clásico", "Perfil Scalper", etc. |
| **P2** | **Timer de sesión + Pomodoro** | Medio | ~2h | Los ICT traders pasan horas backtesteando. Un timer que registre cuánto tiempo llevan y les recuerde tomar pausas. Buenos hábitos = mejor retention. |
| **P3** | **Themes / Personalización visual** | Bajo | ~3h | Poder cambiar colores de velas, fondos, líneas ICT. Los traders pasan horas mirando el gráfico — la estética importa. |
| **P3** | **Sonidos de ejecución** | Bajo | ~2h | "Ding" cuando se ejecuta una orden, "buzz" si se pierde el SL. Feedback auditivo que hace la app más inmersiva. |
| **P3** | **Atajos de teclado configurables** | Bajo | ~4h | Power users odian el mouse. Atajos para BUY/SELL/Step/Play/Pause/Borrar dibujos. |

---

## Estrategia de monetización (Freemium)

### Capa gratuita (Free)
- Hasta 3 símbolos guardados
- Journal básico (sin exportar)
- Sin equity curve
- Sin modo examen

### Capa Pro ($47 one-time o $9/mes)
- Símbolos ilimitados
- Exportación CSV/PDF del journal
- Equity curve + drawdown + estadísticas avanzadas
- Modo examen
- Screenshot con marca de agua
- Guardar sesiones
- Multi-timeframe (cuando esté listo)
- Alertas de confluencia

---

## Roadmap sugerido (próximos 60 días)

### Semana 1-2 (fundaciones de monetización)
1. Exportar journal a CSV/PDF
2. Guardar/Cargar sesiones completas
3. Screenshot con marca de agua

### Semana 3-4 (estadísticas)
4. Equity curve + drawdown chart
5. Estadísticas avanzadas (Sharpe, drawdown, streaks)
6. Modo examen

### Semana 5-6 (retención)
7. Perfiles de sesión guardables
8. Atajos de teclado
9. Timer de sesión

### Semana 7-8 (diferenciación)
10. Alarma de confluencia ICT
11. Multi-timeframe (empieza con 2 paneles)

---

## Lo que NO debes hacer ahora (distracciones)

- ❌ App mobile / web — tu fuerte es escritorio, apaláncate en eso
- ❌ Más indicadores (RSI, MACD) — no es lo que busca la comunidad ICT
- ❌ Automatización / trading bots — riesgo legal, soporte infinito
- ❌ Soportar más brokers — MT5 cubre >90% del mercado ICT

---

## Próximo paso concreto

¿Quieres que empiece a implementar alguno de estos features? Recomiendo empezar por **Exportar journal a CSV/PDF** — es rápido (~3h), impacto inmediato, y te permite poner "EXPORT" en tu landing page el primer día.
