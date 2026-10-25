# HMCZ Truck Modification

App web (Streamlit) para controlar la ejecución de las modificaciones de **12 camiones EH5000 (RD 220 a RD 231)**. La interfaz está en **inglés y japonés**.

- **Supervisores:** registran el avance por tarea de los SOP, las horas-hombre, el supervisor, los técnicos, comentarios y notas de atraso.
- **Administradores:** ven el resumen y las alertas, el Gantt interactivo, ajustan las fechas del pronóstico, revisan los atrasos, descargan reportes y gestionan usuarios.

---

## Cómo funciona

| Tema | Regla |
|---|---|
| **Actividades ↔ SOP** | High arch → SOP 23 & 24 · Nose cone → SOP 4 · RHS seat screw → SOP 18 · LHS seat screw → SOP 16 **+** SOP 19. Trailing arm lowering/assembly y Trunnion cap/modification no tienen SOP: avance manual en % |
| **Avance de una actividad** | Tareas terminadas ÷ tareas aplicables. Las tareas condicionales (p. ej. reparación de grietas) se pueden marcar **N/A** y dejan de contar |
| **Avance de un camión** | Promedio simple de sus actividades. Del proyecto: promedio de los 12 camiones |
| **Avance importado** | Mientras una actividad no tenga registros en la app, se usa el % del Gantt (RD220 y RD221 aparecen completos) |
| **Puntos HOLD** | Una tarea HOLD solo puede quedar *Done* con el resultado de QC *Accepted* |
| **Fechas** | **Plan original** fijo (del Gantt) + **pronóstico** editable. El atraso se mide en días hábiles entre ambos |
| **Calendario** | Lunes a viernes. Sábado y domingo solo si el administrador los habilita para ese camión. Los festivos se configuran |
| **Visibilidad** | Un camión aparece (y su plan se puede editar) cuando faltan **14 días** o menos para su inicio (configurable). Antes queda oculto |
| **Límite de 5 días** | Se cuentan los días hábiles con trabajo propio programado (sin la espera por el trabajo externo de trunnion). Más de 5 genera una alerta |
| **Alerta de trunnion** | Cuando un camión se activa, el administrador ve una alerta para coordinar con el contratista externo el *Trunnion cap machining* y la *Trunnion modification*. Se marca como atendida con una nota |

Todas las reglas están en `core/project.py`. Los valores por defecto están en `core/config.py`.

---

## Estructura

```text
App-Modification-HMCZ-/
├── app.py                    ← Punto de entrada: inicio de sesión, barra lateral y rutas
├── core/                     ← Lógica del negocio (sin interfaz)
│   ├── config.py             ← Actividades, SOP, colores y valores por defecto
│   ├── project.py            ← Calcula el estado actual: avance, estados, atrasos y alertas
│   ├── events.py             ← Registro de cambios (un archivo JSON por acción)
│   ├── workdays.py           ← Calendario laboral (días hábiles, fines de semana, festivos)
│   ├── catalog.py            ← Catálogo de tareas de los SOP
│   ├── auth.py               ← Usuarios y contraseñas (bcrypt)
│   ├── reports.py            ← Reporte en Excel y CSV
│   └── i18n.py               ← Textos en inglés y japonés
├── storage/                  ← Dónde se guardan los datos
│   ├── github_store.py       ← Rama `data` del repositorio (producción)
│   └── local_store.py        ← Carpeta local_data/ (pruebas, sin token)
├── ui/                       ← Interfaz de Streamlit
│   ├── supervisor.py         ← Vista del supervisor
│   ├── admin.py              ← Vista del administrador (7 pestañas)
│   ├── gantt.py              ← Gantt interactivo (Plotly)
│   ├── common.py             ← Piezas compartidas
│   └── theme.py              ← Estilo LANDCROS
├── seed/                     ← Datos de origen
│   ├── *.xlsx                ← Gantt y SOP originales
│   ├── build_seed.py         ← Convierte los Excel en los CSV de abajo
│   ├── activities_seed.csv   ← Plan original por camión y actividad
│   ├── tasks_catalog.csv     ← 97 tareas de los 5 SOP (EN/JP)
│   └── sop_notes.csv         ← Notas de ingeniería de cada SOP
├── assets/                   ← Logo LANDCROS e imagen del EH5000
├── scripts/hash_password.py  ← Hash para el administrador de emergencia
└── tests/                    ← Pruebas automáticas (pytest)
```

### Rama `data` (la escribe la app, no se edita a mano)

```text
plan/baseline.csv             ← Plan original (se copia una vez desde seed/)
plan/settings.json            ← Configuración inicial
users/users.json              ← Usuarios con contraseña cifrada
log/task/AAAA-MM/…json        ← Avance de tareas (un archivo por guardado)
log/delay/…  log/plan/…  log/ack/…  log/settings/…
reports/                      ← Reportes publicados desde la app
```

Cada acción crea un archivo nuevo, que nunca se modifica después. Así, dos personas pueden guardar al mismo tiempo sin conflictos y queda el historial completo de quién hizo qué y cuándo. El estado actual se calcula leyendo esos archivos en orden.

---

## Ejecutar en tu Mac (modo local, sin token)

```bash
cd ~/Proyectos/App-Modification-HMCZ-
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py
```

Sin archivo de secretos, la app guarda todo en `local_data/` (está en `.gitignore`). Al abrirla por primera vez pide crear el **primer administrador** y carga el plan desde el Gantt.

Pruebas: `pytest -q`

Para empezar de cero en modo local, borra la carpeta `local_data/`.

---

## Conectar con GitHub (producción)

1. El dueño del repositorio crea un **token fine-grained**: *Settings → Developer settings → Personal access tokens → Fine-grained tokens*.
   - **Repository access:** *Only select repositories* → este repositorio.
   - **Permissions → Repository → Contents:** *Read and write*.
   - **Expiration:** 1 año (GitHub avisa por correo antes de que venza).
2. Copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml` y pega el token.
3. En Streamlit Community Cloud, pega el mismo contenido en *App settings → Secrets*.

El token **nunca** se sube al repositorio: `.streamlit/secrets.toml` está en `.gitignore`.

Si el token vence, la app muestra un aviso al guardar. Se genera uno nuevo y se reemplaza en los secretos.

---

## Usuarios

- El primer administrador se crea desde la app al abrirla por primera vez.
- Los demás los crea un administrador en **Settings & users**.
- **Contraseña olvidada:** un administrador la restablece en *Edit user*.
- **Alguien deja el proyecto:** se desactiva y no se borra, para conservar su historial.
- **Administrador de emergencia** (opcional): se define en los secretos con `scripts/hash_password.py`. Sirve para entrar si el archivo de usuarios se daña.

---

## Cómo adaptar

| Quiero cambiar… | Archivo |
|---|---|
| Días de anticipación, límite de días hábiles, zona horaria o festivos | Desde la app: **Settings & users** |
| Textos en inglés o japonés | `core/i18n.py` |
| Actividades o asociación con los SOP | `core/config.py` |
| Reglas de avance, estados o alertas | `core/project.py` |
| SOP actualizados | Reemplazar el Excel en `seed/` y ejecutar `python seed/build_seed.py` |
| Fechas de un camión en curso | Desde la app: pestaña **Plan** (el plan original ya cargado no cambia al reemplazar el Gantt) |
