"""HMCZ Truck Modification — seguimiento de la modificación de 12 camiones EH5000.

Ejecutar con:  streamlit run app.py
"""

from __future__ import annotations

import time

import streamlit as st

from core import config
from core.auth import (USERS_PATH, User, authenticate, check_password, dump_users, emergency_admin, hash_password,
                       load_users, stamp, validate_new)
from core.events import initialize, is_initialized
from core.i18n import translator
from core.project import build_project
from storage import StorageError, local_dir, make_store
from ui import admin, supervisor
from ui.common import Ctx, note, show_flash
from ui.theme import footer, header, inject_css, sidebar_logo

st.set_page_config(page_title="HMCZ Truck Modification", page_icon=str(config.LOGO_PATH), layout="wide",
                   initial_sidebar_state="expanded")
inject_css()
ss = st.session_state
ss.setdefault("lang", "en")
t = translator(ss.lang)


# ─── Datos ────────────────────────────────────────────────────────────────
def _secrets() -> dict:
    try:
        return {k: dict(v) if hasattr(v, "keys") else v for k, v in st.secrets.items()}
    except Exception:  # sin archivo de secretos → modo local
        return {}


@st.cache_resource(show_spinner=False)
def get_store(_secrets_dict: dict, local_path: str):
    # local_path forma parte de la clave del caché: si cambia la carpeta local, se crea otro almacenamiento
    return make_store(_secrets_dict)


@st.cache_data(show_spinner=False, max_entries=4)
def load_state(_store, version: int, bucket: int):
    """Lee los datos (una descarga) y calcula el estado del proyecto.
    Se renueva al guardar (version) o cada 30 s (bucket) para ver lo que
    guardan los demás usuarios."""
    snapshot = _store.snapshot()
    project = build_project(snapshot) if is_initialized(snapshot) else None
    return snapshot, project


store = get_store(_secrets(), str(local_dir()))
try:
    with st.spinner(t("loading")):
        snapshot, project = load_state(store, store.version, int(time.time() // 30))
except StorageError as exc:
    header(config.PROJECT_NAME, config.FLEET)
    st.error(f"{t('load_failed')} {exc}", icon=":material/cloud_off:")
    if st.button(t("retry"), icon=":material/refresh:"):
        load_state.clear()
        st.rerun()
    st.stop()

users = load_users(snapshot)
emergency = emergency_admin(_secrets())


def language_picker(where) -> None:
    choice = where.segmented_control(t("language"), list(config.LANGUAGES), default=ss.lang,
                                     format_func=lambda k: config.LANGUAGES[k], key="lang_pick")
    if choice and choice != ss.lang:
        ss.lang = choice
        st.rerun()


# ─── Primer uso: crear el primer administrador ────────────────────────────
def first_admin_page() -> None:
    header(config.PROJECT_NAME, t("setup_subtitle"))
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        language_picker(st)
        note(t("setup_help", where=store.label))
        with st.form("setup"):
            username = st.text_input(t("username"), help=t("username_help")).strip().lower()
            name = st.text_input(t("full_name"))
            pw = st.text_input(t("password"), type="password", help=t("password_help"))
            pw2 = st.text_input(t("confirm_password"), type="password")
            if st.form_submit_button(t("create_admin"), type="primary", width="stretch"):
                err = validate_new(username, pw)
                if err or not name.strip():
                    st.error(t(err or "err_name"))
                elif pw != pw2:
                    st.error(t("err_password_match"))
                else:
                    try:
                        with st.spinner(t("saving")):
                            user = stamp(User(username, name.strip(), "admin", hash_password(pw)))
                            store.write(USERS_PATH, dump_users({username: user}), f"[app] primer administrador · {username}")
                            if not is_initialized(snapshot):
                                initialize(store, username)
                    except StorageError as exc:
                        st.error(f"{t('save_failed')} {exc}")
                        return
                    ss.user = user
                    st.rerun()


# ─── Inicio de sesión ─────────────────────────────────────────────────────
def login_page() -> None:
    header(config.PROJECT_NAME, t("login_subtitle"))
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        language_picker(st)
        with st.form("login"):
            username = st.text_input(t("username"))
            pw = st.text_input(t("password"), type="password")
            if st.form_submit_button(t("login"), type="primary", width="stretch", icon=":material/login:"):
                user = authenticate(users, username, pw, emergency)
                if user:
                    ss.user = user
                    ss.pop("login_fail", None)
                    st.rerun()
                ss.login_fail = ss.get("login_fail", 0) + 1
                time.sleep(min(ss.login_fail, 5))  # frena intentos repetidos
                st.error(t("login_failed"))
        st.caption(t("login_help"))


if "user" not in ss:
    if not users and not emergency:
        first_admin_page()
    else:
        login_page()
    st.stop()

# La sesión se valida contra el archivo de usuarios en cada carga: si un
# administrador desactiva a alguien, pierde el acceso en el siguiente clic.
user: User = ss.user
if user.username in users:
    current = users[user.username]
    if not current.active:
        ss.clear()
        st.rerun()
    user = ss.user = current
elif not (emergency and user.username == emergency[0]):
    ss.clear()
    st.rerun()
is_emergency = bool(emergency and user.username == emergency[0] and user.username not in users)

# ─── Barra lateral ────────────────────────────────────────────────────────
with st.sidebar:
    sidebar_logo()
    st.markdown(f'<div class="side-user">{user.name}</div><span class="side-role">{t("role_" + user.role)}</span>',
                unsafe_allow_html=True)
    st.write("")
    language_picker(st)
    view = "admin" if user.is_admin else "supervisor"
    if user.is_admin:
        view = st.segmented_control(t("view"), ["admin", "supervisor"], default="admin", key="view_pick",
                                    format_func=lambda v: t("view_" + v)) or "admin"
    st.divider()
    if st.button(t("refresh"), icon=":material/refresh:", width="stretch", help=t("refresh_help")):
        load_state.clear()
        st.rerun()
    if not is_emergency:
        with st.expander(t("change_password"), icon=":material/key:"):
            with st.form("chg_pw", clear_on_submit=True):
                old = st.text_input(t("current_password"), type="password")
                new = st.text_input(t("new_password"), type="password", help=t("password_help"))
                if st.form_submit_button(t("save")):
                    if not check_password(old, user.hash):
                        st.error(t("err_current_password"))
                    elif len(new) < 8:
                        st.error(t("err_password_short"))
                    else:
                        updated = dict(users)
                        updated[user.username] = stamp(User(**{**vars(user), "hash": hash_password(new)}))
                        try:
                            store.write(USERS_PATH, dump_users(updated), f"[app] cambio de contraseña · {user.username}")
                            st.success(t("password_changed"))
                        except StorageError as exc:
                            st.error(f"{t('save_failed')} {exc}")
    if st.button(t("logout"), icon=":material/logout:", width="stretch"):
        lang = ss.lang
        ss.clear()
        ss.lang = lang
        st.rerun()
    st.caption(f"{t('data_source')}: {store.label}")
    if project is not None:
        st.caption(f"{t('today')}: {project.today:%d-%b-%Y} ({project.settings.get('timezone')})")

# ─── Contenido ────────────────────────────────────────────────────────────
show_flash()
subtitle = t("subtitle_admin") if view == "admin" else t("subtitle_supervisor")
header(config.PROJECT_NAME, f"{config.FLEET} · {subtitle}")
if is_emergency:
    st.warning(t("emergency_mode"), icon=":material/shield:")

if project is None:
    if user.is_admin:
        note(t("init_help"))
        if st.button(t("init_button"), type="primary", icon=":material/rocket_launch:"):
            try:
                with st.spinner(t("saving")):
                    initialize(store, user.username)
            except StorageError as exc:
                st.error(f"{t('save_failed')} {exc}")
            else:
                st.rerun()
    else:
        note(t("not_initialized"))
    st.stop()

ctx = Ctx(store=store, project=project, user=user, users=users, lang=ss.lang, t=t, emergency=is_emergency)
if view == "admin":
    admin.render(ctx)
else:
    supervisor.render(ctx)

footer(f"LANDCROS · {config.PROJECT_NAME}", f"{len(project.trucks)} trucks · {config.FLEET}")
