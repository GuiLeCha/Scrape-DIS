from __future__ import annotations

import threading
import time
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def try_auto_login(page, username: str, password: str, log_fn=None) -> bool:
    """
    Intenta completar y enviar automáticamente el formulario de inicio de sesión
    en AWS Academy (Canvas LMS o página intermedia de LMS_Login).
    """
    if not username or not password:
        return False

    log = log_fn or (lambda msg: None)

    try:
        current_url = page.url or ""

        # 1. Página intermedia LMS_Login de AWS Academy
        if "LMS_Login" in current_url:
            student_btn = page.locator(
                "a[href*='login/canvas'], button:has-text('Student Login'), a:has-text('Student Login')"
            )
            if student_btn.count():
                log("Detectada página de acceso AWS Academy. Redirigiendo a Student Login...")
                student_btn.first.click()
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                time.sleep(2.0)

        # 2. Formulario estándar de Canvas LMS (input#username, input#password)
        user_field = page.locator(
            "input#username, input[name='pseudonym_session[unique_id]'], input[type='email']:visible, input[type='text']:visible"
        )
        pass_field = page.locator(
            "input#password, input[name='pseudonym_session[password]'], input[type='password']:visible"
        )

        if user_field.count() and pass_field.count():
            log("Formulario de login Canvas detectado. Autocompletando credenciales...")
            user_field.first.fill(username)
            pass_field.first.fill(password)

            # Recordar sesión si existe el checkbox
            checkbox = page.locator(
                "input[type='checkbox']:visible, input#pseudonym_session_remember_me"
            )
            if checkbox.count():
                try:
                    if not checkbox.first.is_checked():
                        checkbox.first.check()
                except Exception:
                    pass

            submit_btn = page.locator(
                "button[type='submit'], input[type='submit'], button:has-text('Log In'), button:has-text('Iniciar sesión')"
            )
            if submit_btn.count():
                submit_btn.first.click()
                log("Formulario de inicio de sesión enviado.")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                return True

        # 3. Formulario Amazon SSO / Training (ap_email, ap_password)
        amz_email = page.locator("input#ap_email, input[name='email']:visible")
        amz_pass = page.locator("input#ap_password, input[name='password']:visible")
        if amz_email.count():
            log("Formulario de autenticación Amazon detectado. Autocompletando credenciales...")
            amz_email.first.fill(username)
            if amz_pass.count():
                amz_pass.first.fill(password)
            amz_submit = page.locator("input#signInSubmit, button[type='submit']:visible")
            if amz_submit.count():
                amz_submit.first.click()
                log("Formulario Amazon enviado.")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                return True

    except Exception as exc:
        log(f"Aviso auto-login: {exc}")

    return False


def wait_or_auto_login(
    context,
    page,
    home_url: str,
    username: str = "",
    password: str = "",
    login_done_event: threading.Event | None = None,
    log_fn=None,
):
    """
    Gestiona el ciclo de login: si hay credenciales intenta auto-login,
    y espera confirmación del usuario o detección automática de sesión activa.
    """
    log = log_fn or (lambda msg: None)

    try:
        page.goto(home_url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        pass

    time.sleep(2.0)

    # Intentar auto-login si hay credenciales
    if username and password:
        try_auto_login(page, username, password, log_fn=log)

    log(
        "Verificando sesión en AWS Academy. Si es necesario, iniciá sesión manualmente. "
        "Cuando estés dentro, pulsá «Ya inicié sesión / guardar sesión»."
    )

    while True:
        if login_done_event and login_done_event.is_set():
            break

        try:
            open_pages = [pg for pg in context.pages if not pg.is_closed()]
            if not open_pages:
                break

            # Si detectamos que Canvas ya cargó los módulos, la sesión está activa
            if page.locator(".context_module").count() > 0:
                log("✓ Sesión activa detectada en Canvas LMS.")
                time.sleep(1.0)
                break
        except Exception:
            break

        time.sleep(0.5)
