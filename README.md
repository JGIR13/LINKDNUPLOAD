# LinkedIn Poster — V5 (local, multiusuario)

App local que genera publicaciones de LinkedIn (infografía o solo texto) con
IA a partir de tus parámetros de estilo y ejemplos de inspiración, te deja
revisarlas/editarlas con una vista previa fiel a como se verán en LinkedIn, y
las publica en tu cuenta vía la API oficial de LinkedIn (OAuth — nunca se
pide usuario/contraseña). También puede planificar y generar tus posts del
día automáticamente, con o sin publicación sin supervisión, rotando entre
tus propias temáticas.

Es una **instalación compartida**: cada persona que la use entra con su
propia cuenta (email + contraseña) y solo ve sus propios posts, su propia
inspiración y su propia conexión de LinkedIn — perfecta para instalarla una
vez en un equipo y que varios colegas la prueben cada uno con lo suyo.

Coste estimado: **prácticamente $0/mes**, usando exclusivamente el nivel
gratuito de Gemini para el texto y el contenido de la infografía (el
renderizado de la imagen en sí es 100% local, con Pillow) y sin necesidad de
hosting.

## Novedades de la V5 (sobre la V4.1)

- **Cuentas reales, una instalación compartida**: en vez de una sola
  contraseña de administrador para toda la app, ahora cada persona tiene su
  propia cuenta (email + contraseña). Cada cuenta ve **solo** sus propios
  posts, su inspiración, su plan diario y su propia conexión de LinkedIn —
  aislados por completo del resto de cuentas de la misma instalación. La
  primera cuenta que se crea (al arrancar la app por primera vez) es la
  cuenta de **administrador**.
- **🛠️ Administración** (solo visible para cuentas con rol de administrador):
  reemplaza al antiguo panel de administración de la V4.1 (la URL especial
  `?admin=1` y la contraseña de administrador única ya no existen). Ahora es
  una pestaña más del menú, pero **solo aparece si tu cuenta es
  administradora** — el resto de personas ni la ve ni puede llegar a ella.
  Desde ahí gestionas las credenciales de la instalación (Client ID/Secret
  de LinkedIn, clave de Gemini) y las cuentas: crear una para cada colega,
  cambiarle el rol, desactivarla, resetearle la contraseña o borrarla junto
  con todos sus datos.
- **🎯 Temáticas para la generación automática**: dentro de "📅 Generación
  diaria" puedes definir una lista de temas (p. ej. Python, Seguridad,
  Cloud) y la generación automática (cola manual sin tema elegido, y sobre
  todo la "🤖 Automatización Total") rota entre ellos en orden — un día le
  toca a uno, el siguiente al otro — en vez de dejar que la IA improvise un
  tema libre cada vez. La IA sigue eligiendo un ángulo concreto y distinto
  dentro de cada tema, nunca repite el mismo post. Si no añades ninguna
  temática, la generación automática sigue funcionando exactamente igual que
  antes (tema libre propuesto por la IA).
- **Infografías con más carácter visual**: nuevo **lienzo oscuro** (además
  del claro, ambos seleccionables por publicación o como preferencia por
  defecto en ⚙️ Configuración) con una textura sutil de fondo, y el título
  ahora resalta en el color de acento su palabra o frase más impactante
  (p. ej. "El peligro de **any** en TypeScript") — más parecido a una
  portada profesional, menos a una lista plana.

## Novedades de esta ronda (sobre la V5)

- **Hora configurable en la 🤖 Automatización Total**: ya no se publica
  siempre a las 09:00 — elige la hora que quieras desde "📅 Generación
  diaria" → "🤖 Automatización Total (avanzado)". La tarea programada de
  Windows pasa a dispararse como un latido frecuente (cada 15 min, no una
  vez al día) y el propio script decide cuándo le toca a cada cuenta — ver
  la sección "🤖 Automatización Total" más abajo para el comando `schtasks`
  actualizado (si ya tenías la tarea antigua creada, hay que recrearla).
- **🚀 Subida masiva**: dentro de "📅 Generación diaria", genera una tanda
  de hasta 24 posts (mezcla configurable de infografías y solo texto) de
  golpe, no repartidos por hora — con su propia paleta, estilo (claro/
  oscuro) y, tal como se pidió explícitamente, un **checkbox** en el
  momento de generar para decidir tanda a tanda si se publican solos en
  LinkedIn nada más generarse o si se quedan como borrador a la espera de
  tu revisión. No interfiere con el plan diario ni con la Automatización
  Total (son caminos independientes).
- **Paletas de color personalizadas + swatches**: en cualquier selector de
  paleta de la infografía (asistente, modo rápido, ⚙️ Configuración, 🚀
  Subida masiva) ahora se ven los colores reales de cada paleta disponible
  de un vistazo, y puedes crear tu propia paleta a partir de solo dos
  colores (primario + acento, con selectores de color) — el resto de tonos
  (fondo, tarjetas, texto...) se calculan solos para que siempre haya buen
  contraste, tanto en modo claro como oscuro.
- **Infografía más pulida**: la referencia a tu marca personal al pie de la
  imagen se rediseñó por completo (anillo alrededor de la foto, sombra
  suave, el cargo como una "chip" redondeada, franja con degradado a
  juego con la cabecera) en vez de ser solo una foto y un nombre; las
  tarjetas llevan ahora una fina barra de color en el borde izquierdo por
  columna, y el fondo tiene un degradado sutil — más aire entre los
  elementos y más jerarquía visual.

## Novedades de la V4.1 (sobre la V4)

- **Contraste corregido en los dos temas**: varios elementos (pestañas de
  navegación no seleccionadas, insignias de estado, texto entre backticks,
  el interruptor ☀️/🌙) se volvían casi invisibles en modo oscuro (y algunos
  también en modo claro) porque el CSS anterior no cubría los componentes
  reales que usa Streamlit por debajo. Se reescribió el tema apuntando a la
  estructura real de cada componente (verificado inspeccionando la app
  renderizada) — ahora todo el texto es legible en los dos temas.
- **El aspecto Y la estructura de la app viven en archivos de verdad, no en
  Python**: en vez de HTML y colores incrustados en cadenas de Python,
  ahora hay:
  - `static/css/theme_claro.css` / `theme_oscuro.css` — solo los colores de
    cada tema, como variables CSS.
  - `static/css/base.css` — toda la estructura/estilo de los componentes,
    igual para los dos temas.
  - `static/html/` — las piezas de HTML que arma la propia app (el banner
    de cabecera, la ficha de marca de la barra lateral, la tarjeta de
    "así se verá en LinkedIn" y la caja de ayuda de LinkedIn), cada una en
    su propio archivo `.html` con comentarios explicando qué es cada cosa.
  Todo se puede editar con cualquier editor de texto — cambiar colores,
  tamaños, textos o incluso mover/añadir elementos de estructura — y los
  cambios se aplican en la siguiente interacción con la app, sin tocar
  Python ni reiniciar el servidor.
- **Conectar LinkedIn ya no requiere editar el `.env`**: la pestaña
  🔗 LinkedIn tiene ahora un primer paso ("1. Credenciales de tu app de
  LinkedIn") con un formulario para pegar el Client ID, Client Secret y
  Redirect URI directamente ahí — se guardan en tu base de datos local y
  tienen prioridad sobre las del `.env` si también las tuvieras puestas
  ahí. El botón de conectar (paso 2) solo se activa cuando hay credenciales
  disponibles, de una fuente o de la otra.
- **Barra lateral de ancho fijo, pero desplegable**: ya no se puede
  arrastrar el borde para cambiar su ancho (podía chocar con el
  contenido) — el ancho queda fijo en todo momento. Sigue pudiéndose
  ocultar/mostrar por completo con la flecha « de la esquina superior,
  exactamente igual que antes.
- **Se ocultó el botón "Deploy"** de la barra superior de Streamlit — es
  una app 100% local, ese botón (pensado para publicar en Streamlit
  Community Cloud) no aplica aquí y solo generaba confusión.
- Retoques visuales generales: cabecera de la barra lateral con el nombre
  de la app, pestañas de navegación con más presencia (grupo redondeado,
  estado activo con el color de acento), tarjetas y biseles más
  consistentes en los dos temas.

## Novedades de la V4

- **Solo dos formatos de post, los dos 100% gratuitos y sin cuota de
  imagen**: se eliminó por completo la "imagen ilustrativa" (el modo que
  dependía de los modelos de imagen de Gemini y, como respaldo, de
  Pollinations.ai) — esos modelos de imagen necesitan facturación activada
  para tener cuota real y el respaldo gratuito daba resultados de baja
  calidad. Ahora solo existen:
  - **📊 Infografía de lista**: la IA estructura tu tema en un título + N
    puntos (término + descripción breve) y el diseño completo — cabecera,
    tarjetas numeradas, iconos, franja de marca personal — se compone
    íntegramente en código con Pillow, eligiendo una de 5 paletas de
    colores. No depende de ningún modelo de generación de imagen, así que
    nunca falla por cuota.
  - **📝 Solo texto**: la publicación se genera sin ninguna imagen.
  - Se corrigió además un bug de desbordamiento: algunos títulos o términos
    largos e inquebrables (p. ej. "Autenticación/Autorización") podían salirse
    del borde de su tarjeta. Ahora cualquier línea que no quepa en el ancho
    disponible se recorta automáticamente con "…", tanto en el título como en
    cada término/descripción.
- **📅 Generación diaria** (nueva página): configura un **reparto fijo** de
  cuántas infografías y cuántos posts de solo texto quieres generar cada día
  (p. ej. 1 infografía + 2 de texto). La app crea el plan del día la primera
  vez que lo visitas y, por defecto, **tú decides cuándo generar cada item**
  (botón "▶️ Generar" por item, o "Generar todo lo pendiente de hoy") — nunca
  se publica nada sin que lo revises primero en esta cola manual. No hay
  ningún límite técnico real que obligue a un tope diario (el nivel gratuito
  de Gemini permite cientos de peticiones al día); el reparto es enteramente
  tu propia decisión de cuánto contenido quieres producir.
- **🤖 Automatización Total** (dentro de "📅 Generación diaria", opcional y
  explícita): activa un interruptor para permitir que un script aparte,
  `generar_diario.py` (sin depender de Streamlit), genere — y, si además
  activas "publicar directo", **publique en LinkedIn sin revisión manual**
  — los posts del reparto diario, **a la hora que tú elijas**. Pensado para
  dispararse solo, sin que tengas la app abierta, vía el **Programador de
  tareas de Windows**, como un latido frecuente (no un único disparo diario):
  1. Ve a "📅 Generación diaria" → expande "🤖 Automatización Total (avanzado)".
  2. Activa "Activar Automatización Total", elige la **hora de
     generación/publicación** y, si quieres publicación sin revisión,
     también "Publicar directo en LinkedIn sin revisión manual".
  3. Guarda — la app te muestra el comando `schtasks /create ...` exacto,
     listo para pegar en una consola (cmd, como administrador), que crea una
     tarea que se dispara **cada 15 minutos**.
  4. Esa tarea ejecuta `generar_diario.bat`, que activa el entorno virtual y
     corre `generar_diario.py`. En cada disparo, el script mira la hora
     configurada de cada cuenta: si aún no ha llegado, no hace nada (no-op
     seguro); en cuanto llega, genera el plan de esa cuenta la primera vez
     que el latido pasa ese día, y no lo repite en los siguientes disparos
     del mismo día. Si la Automatización Total está desactivada, tampoco
     hace nada — así que crear la tarea programada por adelantado es
     inofensivo.
  - Si ya tenías la tarea antigua (creada con `/sc daily`, una sola vez al
    día), bórrala primero con
    `schtasks /delete /tn "LinkedIn AI Poster - Generacion diaria" /f` y
    vuelve a crearla con el comando nuevo — si no, la hora que configures en
    la app no tendrá efecto porque la tarea solo se disparará una vez al día
    a la hora antigua.
  - Publicar sin revisión requiere haber conectado tu cuenta de LinkedIn al
    menos una vez de forma interactiva (pestaña 🔗 LinkedIn) — los tokens se
    guardan cifrados en tu base de datos local y se refrescan solos cuando
    hace falta, así que el script puede publicar sin que abras el navegador.
- **Tema claro/oscuro rediseñado**: nuevo interruptor ☀️/🌙 en la barra
  lateral, con dos paletas más sobrias — **modo claro**: gris claro + azul
  navy; **modo oscuro**: negro + amarillo con acentos resaltantes. Tu
  preferencia se guarda y se recupera sola en el siguiente arranque. Este
  rediseño afecta **solo a la interfaz de la app** — las 5 paletas de color
  de la infografía (Azul corporativo, Oscuro elegante, Verde tech, Morado
  creativo, Minimal gris) son independientes y no cambian con el tema de la UI.
- **🗂️ Historial**: los borradores (incluidos los generados por "📅
  Generación diaria") ahora tienen un botón "📤 Publicar en LinkedIn"
  directamente ahí, sin necesidad de volver a pasar por el asistente.

## Lo que ya traía la V3 (sigue disponible)

- **🧙 Asistente completo** (por defecto) y **⚡ Modo rápido**: el asistente
  te pregunta el origen del tema (nuevo, o desde un ejemplo guardado en
  ✨ Inspiración), un título/gancho opcional, el formato del post y, si
  eliges infografía, si quieres añadir tu **marca personal** (foto o
  iniciales + nombre + cargo). El modo rápido aplica tus preferencias
  guardadas automáticamente, sin preguntas.
- **Marca personal sobre la infografía**: sube tu foto de perfil en
  ⚙️ Configuración (se recorta en círculo automáticamente) y define si por
  defecto prefieres mostrarla con foto o solo con tus iniciales.
- **Vista previa en vivo** del post tal como se vería en LinkedIn (avatar,
  texto con hashtags resaltados, imagen, barra de "me gusta/comentar").
- **Inspiración con imágenes**: puedes subir imágenes de referencia visual,
  no solo texto — si subes una imagen sin describirla, la IA analiza su
  estilo automáticamente.
- **Configuración completa**: tono, sector, objetivo, audiencia objetivo,
  temas habituales, palabras clave a incluir, palabras/temas a evitar, firma
  habitual, formato de post por defecto y marca personal.
- **Más resiliente**: si el modelo de texto de Gemini que usa la app cambia
  de nombre o deja de estar disponible, prueba automáticamente varios
  modelos de respaldo antes de rendirse (ver `GEMINI_TEXT_MODEL` en
  `.env.example` si alguna vez quieres fijar uno a mano).

## 1. Instalación (primera vez)

**Windows:** haz doble clic en `setup_entorno.bat`. Crea el entorno virtual,
instala dependencias y, si no tienes `.env` todavía, te pide directamente en
la ventana que pegues tu `GEMINI_API_KEY` (si la dejas en blanco, o si ya
tenías un `.env` sin rellenar, te avisa claramente y te abre el archivo en
el Bloc de notas para que la añadas). Cuando termine, usa `iniciar_app.bat`
para arrancar la app.

**macOS/Linux** (o Windows manual):

```bash
cd linkedin-ai-poster
python3 -m venv .venv
source .venv/bin/activate    # en Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Después edita `.env` y rellena al menos `GEMINI_API_KEY` (paso 2 más abajo),
o pégala directamente desde 🛠️ Administración una vez dentro de la app (ver
"Cuentas y colegas" más abajo) — sin ella la generación con IA no funcionará.

### Si ya tenías una instalación anterior

**Importante:** sustituye los archivos dentro de tu carpeta de siempre — no
extraigas el zip nuevo dentro de una carpeta que ya se llame
`linkedin-ai-poster` (eso crea una carpeta duplicada anidada y una
instalación nueva y vacía, sin tu `.env` ni tus datos). Sustituye todos los
archivos `.py`, `.bat`, las carpetas `.streamlit/`, `static/css/` y
`static/html/`, y `requirements.txt` por los de este paquete, pero
**conserva tal cual** tu `.env` y tu carpeta `data/` (ahí vive tu base de
datos con tus posts e inspiración). Si ya habías editado tú mismo
`static/css/*.css` o `static/html/*.html` en tu copia anterior, revisa si
quieres conservar tus cambios o partir de los nuevos.
Al arrancar la app, la base de datos se actualiza sola para soportar los
campos nuevos — no se borra nada de lo que ya tenías. Si vienes de una
versión anterior a la V5 (usuario único, sin login), la migración es
automática y **conserva todo**: tu contraseña, tu conexión de LinkedIn, tus
posts, tu inspiración y tu plan diario se reasignan solos a una primera
cuenta de administrador (si nunca habías configurado una contraseña de
administrador, se crea con una temporal — la app te lo indica al entrar y
te pide cambiarla). El fichero `image_gen.py` de versiones anteriores ya no
existe — si lo ves en tu carpeta, puedes borrarlo, no se usa. Tampoco existe
ya `abrir_panel_admin.bat` (la URL especial `?admin=1` que abría se eliminó
— administrar la instalación es ahora una pestaña normal del menú, solo
visible si tu cuenta es administradora); si aún lo ves en tu carpeta después
de actualizar, puedes borrarlo.

```bash
pip install -r requirements.txt   # por si hay dependencias nuevas
streamlit run app.py
```

## 2. Consigue tu API key de Gemini (gratis)

1. Ve a https://aistudio.google.com/apikey
2. Inicia sesión con tu cuenta de Google y pulsa "Create API key". No pide tarjeta.
3. Pégala en tu `.env`:
   ```
   GEMINI_API_KEY=tu_clave_aqui
   ```
   o, si prefieres no tocar archivos, desde 🛠️ Administración una vez dentro
   de la app (ver "Cuentas y colegas" más abajo) — ahí tiene prioridad sobre
   la del `.env`.

Con esta única clave se genera tanto el texto de tus publicaciones como el
contenido estructurado de la infografía (título + puntos) y el análisis de
estilo de tus imágenes de inspiración. El **renderizado** de la infografía en
sí (colores, tarjetas, iconos, tipografía) es 100% local con Pillow y no
consume ninguna cuota de generación de imagen — de hecho, desde la V4 la app
ya no usa ningún modelo de generación de imagen (se eliminó por completo,
junto con el respaldo en Pollinations.ai).

## 3. Crea tu app de LinkedIn (para poder publicar) — esto lo hace quien ADMINISTRA la instalación

Esta parte la haces tú, una sola vez, como quien instala y administra la
app (tu cuenta, la primera que se crea, ya tiene rol de administrador — ver
"Cuentas y colegas" más abajo). El resto de personas que usen esta
instalación nunca ven ni necesitan hacer nada de esto — para ellas solo
existe un botón "Conectar con LinkedIn" en su propia pestaña 🔗 LinkedIn.

1. Ve a https://www.linkedin.com/developers/apps y pulsa "Create app".
2. Rellena el formulario (nombre, tu propia página de empresa/perfil, logo).
3. En la pestaña **Auth** de tu app, copia el **Client ID** y el
   **Client Secret** (los necesitarás en el siguiente paso), y en
   "Authorized redirect URLs for your app" añade exactamente:
   `http://localhost:8501`
4. En la pestaña **Products**, solicita **los dos** productos siguientes
   (en modo Development, tú mismo como creador de la app ya puedes usarlos
   sin esperar revisión) — **si falta cualquiera de los dos, LinkedIn
   rechaza la conexión con una pantalla de error genérica** ("Vaya, ha
   habido un problema") que no explica el motivo, así que revisa que ambos
   aparezcan como "Added":
   - **"Sign In with LinkedIn using OpenID Connect"** — activa los scopes
     `openid`/`profile` que usamos para identificar al usuario.
   - **"Share on LinkedIn"** — activa el scope `w_member_social` que usamos
     para publicar en su nombre.

**Estas credenciales se configuran desde 🛠️ Administración, no desde la app
normal** (ver "Cuentas y colegas" más abajo) — son **globales**: las
comparten todas las cuentas de esta instalación, así que solo hace falta
guardarlas una vez, y el resto de personas (pestaña 🔗 LinkedIn) nunca ven un
formulario de Client ID/Secret, solo un botón "Conectar con LinkedIn". Si
prefieres seguir usando el `.env` en vez del panel (por ejemplo para no
tener las claves ni siquiera en la base de datos local), sigue funcionando
igual:
```
LINKEDIN_CLIENT_ID=xxxx
LINKEDIN_CLIENT_SECRET=xxxx
LINKEDIN_REDIRECT_URI=http://localhost:8501
```
Si guardas las credenciales desde 🛠️ Administración, tienen prioridad sobre
las del `.env`; si las quitas de ahí (botón "🗑️ Quitar credenciales
guardadas"), la app vuelve a usar las del `.env` si las tienes.

> ⚠️ Si editas el `.env` desde el Bloc de notas o PowerShell en Windows, guarda
> como UTF-8. La app ya tolera el BOM que añade PowerShell por defecto, así
> que no deberías tener problemas, pero si alguna variable "no se lee", revisa
> que no falten espacios ni comillas alrededor del valor.

### Cuentas y colegas

La **primera cuenta que se crea** (la primera vez que abres la app, con tu
email y una contraseña que eliges tú) es automáticamente la cuenta
**administradora**, y es la única que ve la pestaña **🛠️ Administración**
en su menú — no hay ninguna URL especial ni contraseña aparte que recordar,
es tu login normal.

Desde 🛠️ Administración:
- Guardas el Client ID/Secret/Redirect URI de LinkedIn (paso 3 de arriba) y
  la clave de API de Gemini (paso 2) — una sola vez, compartidas por todas
  las cuentas.
- **Creas una cuenta para cada colega**: nombre, email y una contraseña
  temporal (se la compartes tú por el canal que uses habitualmente) — se le
  pedirá cambiarla la primera vez que inicie sesión. Puedes darle rol de
  "usuario" (normal) o "admin" (también podrá entrar a 🛠️ Administración).
- Puedes desactivar una cuenta (deja de poder entrar, sin borrar sus datos),
  resetearle la contraseña, o borrarla definitivamente junto con **todos**
  sus posts, inspiración y plan diario (esto último no se puede deshacer).

Cada persona que usa esta instalación entra por la misma URL
(`http://localhost:8501`) con su propio email y contraseña, y ve únicamente
lo suyo: sus posts en 🗂️ Historial, su inspiración, su propia conexión de
LinkedIn en 🔗 LinkedIn, su reparto diario y sus temáticas automáticas. Nada
de esto se comparte entre cuentas, salvo las credenciales globales de la
instalación (Client ID/Secret de LinkedIn y la clave de Gemini) que
configura quien administra.

## 4. Arrancar la app

```bash
streamlit run app.py
```

Se abrirá en `http://localhost:8501`. La primera vez, crea tu cuenta de
administrador (email + contraseña) — es tu login normal de ahí en adelante.
Configura las credenciales de LinkedIn desde 🛠️ Administración (ver
"Cuentas y colegas" arriba) si aún no lo has hecho, y luego ve a
**"🔗 LinkedIn"** y autoriza la app con el botón "Conectar con LinkedIn →"
(te lleva a la web oficial de LinkedIn, nunca a un formulario nuestro
pidiendo tu contraseña). Este paso es necesario tanto para publicar
manualmente como para que "🤖 Automatización Total" pueda publicar sin
supervisión más adelante. Después:

1. **⚙️ Configuración** — define tu tono, objetivo, audiencia, temas
   habituales, el **formato de post por defecto** (infografía o solo texto,
   con su paleta y número de puntos por defecto) y tu preferencia de marca
   personal (con foto o solo iniciales). Cuanto más completes, mejor te
   quedará el resultado.
2. **✨ Inspiración** — añade publicaciones que te gusten (texto) e imágenes
   de referencia visual. Marca como favoritas ⭐ las que mejor representen lo
   que buscas: se priorizan sobre el resto al generar.
3. **🚀 Generar** — por defecto se abre el **🧙 Asistente completo**: elige si
   el tema es nuevo (título + descripción) o parte de un ejemplo guardado,
   elige el **formato del post** (📊 infografía de lista o 📝 solo texto) y,
   si es infografía, decide si añadir tu marca personal. Después, como
   siempre: elige una de las 3 variantes de texto, edítala si quieres, genera
   la imagen (si aplica) y publica (o guarda como borrador). Si solo quieres
   ir rápido, cambia a **⚡ Modo rápido** arriba (usa tu formato y marca
   personal por defecto, sin preguntas).
4. **📅 Generación diaria** — configura tu reparto fijo diario, y opcionalmente
   una lista de **temáticas** que quieres que roten solas (p. ej. Python,
   Seguridad, Cloud — si no añades ninguna, la IA sigue proponiendo un tema
   libre como siempre). Cuando quieras, genera los posts pendientes de hoy
   con un clic (cola manual), o configura "🤖 Automatización Total" para que
   se generen y, si quieres, se publiquen solos según una tarea programada
   de Windows.

## 5. Estructura del proyecto

```
config.py               # flag modo_claves + credenciales + lista de modelos Gemini con respaldo + hashing de contraseñas
db.py                    # SQLite local: cuentas (multiusuario), config_global, parametros_default, temas_automaticos, inspiracion, posts_generados, generacion_diaria
llm.py                   # genera variantes de texto, contenido de la infografía (título + palabra resaltada + puntos), tema automático (libre o por temática) y análisis de estilo
image_compose.py         # utilidades de texto/tipografía e imagen compartidas por el renderer de la infografía
image_infografia.py      # formato "infografía de lista": diseño 100% en código (Pillow), lienzo claro u oscuro, sin depender de ningún proveedor de imagen
daily.py                 # núcleo de "Generación diaria" por cuenta: plan idempotente por fecha, rotación de temáticas, generación de un item, auto-publicación opcional
generar_diario.py        # script CLI standalone (sin Streamlit) para la Automatización Total: recorre TODAS las cuentas de la instalación, pensado para el Programador de tareas de Windows
generar_diario.bat       # wrapper de Windows que activa el entorno virtual y corre generar_diario.py sin pausas (uso desatendido)
logs/generar_diario.log  # registro con rotación de cada ejecución desatendida de generar_diario.py (se crea solo al primer uso)
linkedin_oauth.py        # login OAuth 2.0 con LinkedIn, por cuenta (state firmado con el cuenta_id embebido)
linkedin_publish.py      # publicación real vía la API ugcPosts de LinkedIn, con la conexión de la cuenta que publica
app.py                   # interfaz Streamlit (login/cuentas, tema claro/oscuro, asistente/modo rápido, generación diaria, vista previa, administración, todas las páginas)
.streamlit/config.toml   # tema base de Streamlit (modo claro) + toolbarMode="minimal" (oculta el botón "Deploy")
static/css/base.css      # CSS estructural, igual para los dos temas — edítalo para cambiar tamaños/espaciados/layout
static/css/theme_claro.css   # solo los COLORES del tema claro (variables CSS) — edítalo para cambiar la paleta clara
static/css/theme_oscuro.css  # solo los COLORES del tema oscuro (variables CSS) — edítalo para cambiar la paleta oscura
static/html/hero_banner.html   # HTML del banner de cabecera (título + texto de bienvenida)
static/html/sidebar_brand.html # HTML de la ficha de marca en la barra lateral (icono + nombre de la app)
static/html/li_preview.html    # HTML de la tarjeta "así se verá en LinkedIn" (con huecos {{...}} que rellena la app)
static/html/creds_hint.html    # HTML de la caja de ayuda para crear tu app de LinkedIn (paso 1 de la pestaña LinkedIn)
data/app.db              # base de datos (se crea/migra sola al arrancar) — también guarda las credenciales de LinkedIn si las metes desde la app
static/generated/        # infografías generadas para los posts
static/inspiracion/      # imágenes de inspiración que subes
static/perfil/           # tu foto de perfil para la marca personal
static/fonts/            # fuentes embebidas (Poppins + DejaVu Sans de respaldo) para el texto de la infografía
static/icons/emoji/      # set curado de ~80 iconos a color (Twemoji) para la infografía de lista
test_multiusuario.py         # regresión: cuentas, roles, aislamiento de datos entre cuentas, config global, OAuth state firmado
test_temas_rotativos.py      # regresión: rotación round-robin de temáticas y su fallback a tema libre
test_infografia_v5.py        # regresión: lienzo oscuro/claro y validación del título con palabra resaltada
test_app_smoke.py            # regresión end-to-end (sin credenciales reales): login, las 7 páginas, roles, aislamiento en la UI
test_automatizacion_hora.py  # regresión: hora configurable de la Automatización Total y su gate en generar_diario.py
test_subida_masiva.py        # regresión: daily.generar_lote (subida masiva) y paletas personalizadas de la infografía
```

### Ejecutar la suite de regresión

Antes de instalar una actualización sobre una instalación con datos reales,
puedes comprobar que todo sigue funcionando:

```
pip install pytest
pytest -v
```

Cada test usa su propia base de datos temporal — nunca tocan `data/app.db`.

Tanto los archivos `static/css/*.css` como los `static/html/*.html` se leen
del disco en cada interacción con la app (no están compilados dentro de
Python), así que puedes abrirlos con cualquier editor de texto — Bloc de
notas, VS Code, el que prefieras — y ver el resultado en el siguiente clic
o recarga del navegador, **sin reiniciar** `streamlit run`.

## 6. Personalización (colores, tamaños, textos)

La app no usa ningún framework de estilos "compilado": son archivos `.css`
y `.html` normales y corrientes, exactamente igual que en cualquier página
web. Estos son los tres archivos que vas a tocar casi siempre, con ejemplos
concretos de qué cambiar:

**Cambiar el color de acento (botones primarios, enlaces, elementos
resaltados)** — edita `static/css/theme_claro.css` (o `theme_oscuro.css`
para el modo oscuro) y busca la variable `--accent` cerca del principio del
archivo:
```css
--accent: #1B2A4E;   /* cambia este código de color por el que quieras */
```
Cualquier color se escribe como código hexadecimal (`#RRGGBB`) — puedes
usar un selector de color como https://htmlcolorcodes.com para encontrar el
código exacto que buscas.

**Cambiar un tamaño o espaciado** (ancho de la barra lateral, tamaño de
letra del título, separación entre tarjetas...) — todo eso vive en
`static/css/base.css`, que es el mismo para los dos temas. Busca el
selector del elemento que quieras cambiar (los nombres son descriptivos,
p. ej. `.hero-banner` para el banner de cabecera, `.sidebar-brand` para la
ficha de la barra lateral) y ajusta sus propiedades `font-size`, `padding`,
`margin`, `width`, etc. — son las mismas propiedades CSS de siempre.

**Cambiar un texto fijo de la interfaz** (el título del banner de cabecera,
el nombre en la barra lateral...) — edita directamente el `.html`
correspondiente en `static/html/`. Por ejemplo, para cambiar el título y el
subtítulo del banner de cabecera, abre `static/html/hero_banner.html` y
edita el texto entre las etiquetas `<h1>` y `<p>`:
```html
<h1>{{logo_html}} LinkedIn Poster</h1>
<p>Genera publicaciones con IA a partir de tu estilo...</p>
```
Cada archivo `.html` de `static/html/` empieza con un comentario que explica
qué es y, si tiene huecos `{{como_este}}`, para qué sirven — no borres esos
huecos (son los puntos donde la app inserta datos reales, como tu nombre o
la vista previa del post), pero todo el texto y las etiquetas HTML a su
alrededor son tuyas para editar libremente.

Para ver el cambio, basta con guardar el archivo y recargar la pestaña del
navegador donde tengas la app abierta (F5) — no hace falta parar ni volver
a arrancar `streamlit run`.

## 7. Sobre el diseño para el futuro (hosting compartido de pago)

Esta V5 ya es multiusuario (una instalación, varias cuentas — ver "Cuentas y
colegas" arriba), pensada para un equipo pequeño y de confianza que instala
la app en un único ordenador. Todo el código lee las credenciales de la
instalación a través de `config.get_credentials()`, nunca directamente de
variables de entorno. Esto es intencional: el día que se quiera montar un
hosting compartido con cobro por suscripción (varias instalaciones
independientes, no solo varias cuentas dentro de una), basta con implementar
el modo `"gestionado"` en `config.py` (leyendo de un backend propio en vez
del `.env`/`config_global`) sin tocar `llm.py`, `daily.py` ni los módulos de
LinkedIn.

## 8. Dejarlo corriendo sin supervisión (equipo dedicado)

Si quieres destinar un ordenador que ya no uses (un portátil viejo, por
ejemplo) a generar y publicar tus posts solo, todos los días, sin que
abras la app para nada, la "🤖 Automatización Total" (ver arriba, sección
"Novedades de la V5") ya está pensada para esto — el script
`generar_diario.py` no necesita la interfaz abierta, solo hace peticiones
salientes (a Gemini y a LinkedIn), así que **no hace falta IP pública, ni
dominio, ni abrir ningún puerto en tu router**. Solo tienes que dejar el
equipo encendido (o programado para despertarse) a la hora en que quieres
que se dispare.

Como la instalación es compartida, **una sola tarea programada sirve para
todo el mundo**: `generar_diario.py` recorre todas las cuentas de la
instalación y genera (y, si esa cuenta lo activó, publica) el plan de cada
una que tenga la Automatización Total encendida — no hace falta crear una
tarea programada por persona. Si un colega nunca activó la Automatización
Total en su cuenta, el script simplemente no hace nada para ella.

1. **Instala la app en ese equipo** igual que en el tuyo (`setup_entorno.bat`,
   rellena tu `GEMINI_API_KEY` y las credenciales de LinkedIn desde
   🛠️ Administración) y confirma que puedes generar/publicar un post de
   prueba a mano desde ahí antes de automatizar nada.
2. **Evita que se suspenda a media tarea:**
   - Configuración → Sistema → Energía y batería → "Pantalla y suspensión":
     pon "Nunca" para cuando esté conectado a la corriente (déjalo siempre
     enchufado).
   - Si es un portátil y lo vas a dejar con la tapa cerrada: Panel de
     control → Opciones de energía → "Elegir el comportamiento de los
     botones de inicio/apagado" → "Configuración de tapa" → "No hacer
     nada" (si no, Windows lo suspende al cerrarla).
3. **(Opcional) Si prefieres que se suspenda el resto del día y solo se
   despierte para generar los posts:** la tarea que te da la app se dispara
   cada 15 minutos (el propio script decide si a cada cuenta le toca ya
   según su hora configurada), lo que no combina bien con suspender el
   equipo el resto del día. Para ese caso, crea en su lugar una tarea con
   un único disparo diario a (o justo después de) la hora que hayas
   configurado en la app — por ejemplo, con la hora puesta a las 09:00:
   ```
   schtasks /create /tn "LinkedIn AI Poster - Generacion diaria" /tr "\"C:\ruta\a\generar_diario.bat\"" /sc daily /st 09:01
   ```
   (un minuto después de la hora configurada, para no arriesgarte a que el
   equipo despierte unos segundos antes de que toque y el script no haga
   nada hasta el día siguiente). Después, en el Programador de tareas de
   Windows (no desde `schtasks` por línea de comandos, hay que marcarlo en
   la interfaz gráfica) → pestaña "Condiciones" → activa "Reactivar el
   equipo para ejecutar esta tarea". También necesitas que la BIOS/UEFI del
   equipo permita temporizadores de reactivación (`powercfg /waketimers`
   desde una consola como administrador te dice si hay alguno programado).
4. **Crea la tarea programada** desde "📅 Generación diaria" →
   "🤖 Automatización Total (avanzado)" en la app, tal como describe la
   sección de arriba — copia y pega el comando `schtasks` que te muestra
   (o el de un único disparo diario del punto 3 si vas a suspender el equipo).
5. **Inicio de sesión:** por defecto, una tarea creada así solo se ejecuta
   si tu usuario de Windows está conectado (con sesión iniciada) en ese
   momento. Para un equipo dedicado, lo más simple es dejarlo con la
   sesión siempre iniciada (o configurar inicio de sesión automático:
   `netplwiz` → desmarca "los usuarios deben escribir su nombre..." →
   introduce tu contraseña). Alternativa más robusta (no requiere sesión
   iniciada): en el Programador de tareas, pestaña "General" de la tarea,
   marca "Ejecutar tanto si el usuario inició sesión como si no" — te
   pedirá tu contraseña de Windows una vez para guardarla de forma cifrada
   junto a la tarea.
6. **Comprobar que funcionó, sin estar delante:** cada ejecución queda
   registrada en dos sitios — (a) el "Plan de hoy"/historial reciente
   dentro de "📅 Generación diaria" en la propia app (ábrela cuando
   quieras, aunque sea desde otro equipo si tienes acceso remoto), y (b)
   un archivo de texto en `logs/generar_diario.log` en la carpeta de la
   app, con un resumen de cada ejecución (qué se generó, si se publicó, o
   el motivo exacto si algo falló) — rota automáticamente para no crecer
   sin límite, así que puedes abrirlo con el Bloc de notas en cualquier
   momento sin depender de una ventana de consola que nadie ve.

## 9. Notas importantes

- Con la cola manual (por defecto) nunca se publica nada automáticamente:
  siempre revisas y confirmas antes. La única forma de publicar sin
  supervisión es activar explícitamente "🤖 Automatización Total" **y**
  "Publicar directo en LinkedIn sin revisión manual" — ambos apagados por
  defecto.
- Los ejemplos de inspiración (texto e imagen) se usan solo como referencia de
  estilo — el sistema tiene instrucciones explícitas para no copiar frases
  literales ni imitar una imagen al pixel.
- No se generan imágenes con personas reales identificables ni logos de
  marcas ajenas.
