# Backtest ICT/SMC — App de escritorio (Windows)

App de escritorio para backtesting manual con enfoque ICT/SMC: reproductor de
velas, multi-timeframe, Fibonacci, EMA, líneas horizontales, cajas R:R y journal
con estadísticas — todo local, conectado directamente a tu terminal MT5.

## Novedades de esta versión

**Precio en vivo siempre activo.** Ya no existe el botón "Saltar a En Vivo".
El precio en vivo es ahora el estado normal de la app: se activa solo al cargar
un símbolo desde MT5, y se mantiene activo aunque cambies de temporalidad. La
única forma de apagarlo es iniciar un replay con **"📍 Fijar inicio"**. Para
volver a vivo, el botón (antes "Saltar a En Vivo") ahora se llama
**"⏹ Finalizar Replay"** y aparece activo solo mientras estás en un replay:
al pulsarlo, termina el replay (comprobando el SL/TP de cualquier operación
abierta en las velas que faltaban) y el gráfico vuelve a vivo automáticamente.

**Correcciones de estabilidad (auditoría técnica):**
- Se serializó todo acceso a la librería `MetaTrader5` con un lock (evita que
  el sondeo en vivo y una carga de histórico llamen a MT5 al mismo tiempo).
- Los hilos de descarga (`FetchWorker`, `LiveTickWorker`, `CsvLoadWorker`)
  ahora capturan cualquier excepción inesperada en vez de dejar la interfaz
  "Cargando…" para siempre sin aviso.
- La lectura de CSV se movió a un hilo aparte: un archivo grande ya no congela
  la ventana.
- El journal se guarda con escritura atómica (archivo temporal + reemplazo),
  para no dejar `journal.json` a medio escribir si la app se cierra de golpe.
- Las EMAs usan ahora un caché incremental en vez de recalcularse desde el
  inicio del histórico en cada repintado — se nota sobre todo con varios
  miles de velas cargadas.
- Los precios se formatean con los dígitos reales del símbolo (consultados a
  MT5) en vez de adivinarlos por la magnitud del número.

**Reorganización del código** en módulos más pequeños y con una responsabilidad
cada uno (ver "Estructura del proyecto" abajo) — mismo comportamiento, más
fácil de mantener y de extender.

## Estructura del proyecto

```
BacktestICT/
├── main.py                 # Punto de entrada — ejecutar con: python main.py
├── requirements.txt
├── packaging/
│   ├── build_exe.bat        # Genera dist\BacktestICT.exe (correr en Windows)
│   └── installer.iss        # Script de Inno Setup -> instalador con asistente
├── core/
│   ├── mt5_data.py          # Llamadas a MetaTrader5 (con lock de concurrencia)
│   ├── mt5_workers.py       # Hilos: descarga histórico, sondeo en vivo, CSV
│   ├── data_utils.py        # Parseo de CSV y cálculo de EMA
│   ├── journal_store.py     # Persistencia del journal (JSON)
│   ├── trading_account.py   # Balance, equity, cálculo de R y P&L
│   └── formatting.py        # Formateo de precios por símbolo
├── ui/
│   ├── main_window.py       # Ventana principal (paneles, controles, journal)
│   └── styles.py            # Hoja de estilos (tema oscuro)
└── chart/
    └── chart_widget.py      # Gráfico de velas: pintado, zoom/pan, dibujos
```

## 1. Instalar (una sola vez)

Necesitas Python 3.10 o superior instalado (https://www.python.org/downloads/ —
al instalar, marca la casilla "Add Python to PATH").

Abre una terminal (CMD o PowerShell) **dentro de la carpeta `BacktestICT`** y corre:

```
pip install -r requirements.txt
```

## 2. Ejecutar la app

```
python main.py
```

Se abre la ventana de la aplicación.

### Opción A — Cargar en vivo desde tu MT5 (recomendado)

1. Abre y loguea tu terminal MT5 (Deriv-Demo o BridgeMarkets) en esta misma PC.
2. En la app, clic en **"🔌 Conectar a MT5"**. La app lee automáticamente todos
   los símbolos visibles en tu Market Watch.
3. Elige el símbolo (XAUUSD, EURJPY, USTEC, Boom 1000 Index, Crash 500 Index,
   lo que tengas visible), el timeframe real (M1/M5/M15/M30/H1/H4/D1) y cuántas
   velas traer.
4. Clic en **"📥 Cargar desde MT5"**. Trae las velas reales tal como las agrega
   el broker, y el gráfico queda **en vivo de inmediato**: el precio se
   actualiza solo cada 1.5s, igual que en MT5.
5. Puedes cambiar de símbolo o de timeframe en cualquier momento sin perder el
   vivo — solo se interrumpe si decides empezar un replay.

Si el símbolo no tiene historial descargado todavía, ábrelo manualmente una vez
en MT5 (para forzar la descarga desde el servidor) y vuelve a intentar.

### Opción B — Cargar un CSV manual

Solo si no tienes MT5 corriendo en esta PC. Exporta desde MT5: click derecho en
el gráfico → Historial de cotizaciones → pestaña Barras → Exportar. Con CSV no
hay modo en vivo (no hay conexión real que sondear) — el gráfico queda abierto
para navegar y puedes iniciar un replay igual que con datos de MT5.

### Uso general (ambas opciones)

1. El precio queda en vivo apenas cargas — no hace falta darle a ningún botón.
2. Cuando quieras practicar un setup de forma "ciega" (sin ver el futuro), dale
   a **"📍 Fijar inicio"** y haz clic en la vela exacta donde quieres empezar.
   Desde ahí, usa "Siguiente ⏭" o "▶ Reproducir" para avanzar vela por vela.
3. Cuando veas tu setup, BUY o SELL, con SL/TP arrastrables directamente sobre
   el gráfico.
4. La app detecta sola cuándo se toca el SL o el TP y lo registra en el journal
   de abajo, con estadísticas de winrate y expectancy.
5. Para volver al precio real en cualquier momento, dale a **"⏹ Finalizar
   Replay"** (solo aparece activo mientras estás en un replay). Adelanta las
   velas que faltaban comprobando el SL/TP de tu operación abierta (si tenías
   una) y retoma el vivo.

Tu journal se guarda automáticamente en:
`C:\Users\TU_USUARIO\BacktestICT\journal.json` (o `~/BacktestICT/journal.json`
en Mac/Linux) — persiste aunque cierres y vuelvas a abrir la app.

## 3. Generar un instalador (.exe) para repartir en otros ordenadores

**Importante:** esto tiene que hacerse en una PC Windows real — PyInstaller no
genera un `.exe` de Windows de forma confiable desde Mac/Linux, y no hay forma
de "cruzar" la compilación. Ya te dejé listos los scripts en `packaging\` para
que sea cuestión de un par de clics una vez que estés en Windows.

### Paso 1 — Generar el ejecutable

Doble clic en `packaging\build_exe.bat` (o córrelo desde CMD/PowerShell dentro
de esa carpeta). Instala automáticamente las dependencias y PyInstaller en un
entorno virtual aislado (`build_env`, no afecta tu Python normal) y genera:

```
dist\BacktestICT.exe
```

Ese archivo ya funciona solo en cualquier PC Windows — no necesita Python
instalado ahí. Puedes repartirlo tal cual si no necesitas un instalador con
asistente.

Nota: el primer arranque del `.exe` puede tardar unos segundos más de lo normal
(PyInstaller descomprime todo en memoria cada vez que abres el programa).

### Paso 2 (opcional) — Empaquetarlo como instalador tipo asistente

Si quieres algo más "profesional" — un `Setup.exe` con ventana de instalación,
acceso directo en el Escritorio y desinstalador — usa Inno Setup (gratis):

1. Instala Inno Setup: https://jrsoftware.org/isinfo.php
2. Abre `packaging\installer.iss` con "Inno Setup Compiler".
3. Presiona **Build → Compile** (o `F9`).
4. El instalador queda en `installer_output\BacktestICT_Setup.exe`.

Ese archivo (`BacktestICT_Setup.exe`) es el que compartes con otras personas:
lo ejecutan, siguen el asistente, y les queda instalada la app con su acceso
directo, sin tocar nada de Python ni de línea de comandos.

Si en el futuro cambias el código, repite el Paso 1 y luego recompila el
`.iss` — el número de versión (`MyAppVersion` en `installer.iss`) puedes
subirlo a mano para que el instalador lo refleje.


## Ventana con paneles movibles

La app se organiza en paneles acoplables (docks) alrededor del gráfico, que
ocupa todo el espacio central:

- **Controles** (arriba): conexión MT5, carga CSV, cuenta simulada, replay,
  herramientas de dibujo y EMAs.
- **Journal** (abajo): estadísticas y tabla de operaciones.

Puedes arrastrar cada panel por su título para moverlo a otro borde, apilarlo
en pestañas, o desacoplarlo como ventana flotante independiente. Todo se guarda
solo al cerrar la app (tamaño de ventana, posición de cada panel) y se restaura
la próxima vez que abras `python main.py`. Si algo queda en un estado raro,
usa **Ver → Restaurar diseño por defecto**.

## Controles siempre a la vista, sobre el propio gráfico

Directamente encima del gráfico (esquina inferior) tienes: ▲ BUY, ▼ SELL, y
los controles de reproducción (⏮ ▶ ⏭) — no hace falta ir al panel lateral,
aunque los mismos controles siguen ahí también por si los prefieres.

## Zoom, pan y edición de dibujos

- **Zoom**: rueda del mouse sobre el gráfico. Sobre la franja de precios (a la
  derecha), la rueda o arrastrar verticalmente ajusta el zoom vertical
  (doble clic ahí para volver al 100%).
- **Pan**: en modo Cursor, arrastra para mover el gráfico en X e Y a la vez.
  Funciona siempre, incluso sobre dibujos grandes — para mover un dibujo
  completo en vez de panear, mantén **Shift** mientras arrastras desde su
  interior.
- **Redimensionar/mover un dibujo**: acércate a un borde o extremo hasta que
  el cursor cambie de forma, y arrastra.
- **Editar un dibujo** (color, grosor, borrar): clic derecho sobre una línea
  horizontal, línea de tendencia o rectángulo. Fibonacci y cajas R:R todavía
  no tienen menú de edición individual — usa "Borrar dibujos" para quitar
  todo y volver a marcar.

## Cuenta simulada

Arriba tienes Balance, Equity (balance + P&L flotante de la operación abierta)
y el campo de Lotaje. El P&L en dinero usa el tamaño de contrato real del
símbolo consultado a MT5 — es una aproximación razonable (no incluye spread,
comisión ni conversión de divisa de la cuenta).

**Nota sobre el journal:** si una misma vela toca el SL y el TP a la vez (poco
frecuente, pero posible en velas de alta volatilidad), la app asume que el SL
se ejecutó primero. Los datos de velas (OHLC) no permiten saber el orden real
del movimiento intra-vela — es la misma simplificación conservadora que usan
la mayoría de plataformas de backtesting basadas en velas.

## Herramientas incluidas

- Conexión en vivo a tu terminal MT5 — cualquier símbolo de tu Market Watch, cualquier timeframe real
- Precio en vivo siempre activo, incluso al cambiar de símbolo o temporalidad
- Reproductor de velas (play/pausa/paso a paso/velocidad ajustable) para hacer backtest ciego
- Zoom (rueda del mouse) y pan (arrastrar en modo Cursor)
- Crosshair con OHLC en vivo, línea de precio actual persistente (como en MT5)
- Doble EMA superpuesta (período configurable)
- Líneas horizontales, líneas de tendencia, rectángulos (para marcar FVG/order blocks/killzones)
- Fibonacci retracement (clic-clic)
- **R:R Long / R:R Short**: dibuja la zona verde de beneficio y roja de riesgo con el ratio que definas
- Ejecución de mercado instantánea (BUY/SELL sin diálogo) con SL/TP arrastrables directamente sobre el gráfico
- Cuenta simulada (balance, equity, lotaje, P&L en dinero)
- Journal persistente con winrate, expectancy, suma de R y P&L

## Qué no incluye (por ahora)

Líneas de tendencia diagonales editables desde el menú de clic derecho para
Fibonacci/cajas R:R, panel de RSI, indicadores adicionales, y detección
automática de FVG/order blocks. Si alguno de estos te sirve de verdad, dile a
Claude cuál y te lo agrega.

## Nota sobre la librería MetaTrader5

Es la librería oficial de MetaQuotes. Solo funciona en Windows y solo si el
terminal MT5 está abierto y logueado en la misma PC donde corres esta app —
se conecta por IPC local, no por internet, así que no necesitas ninguna clave
de API.
