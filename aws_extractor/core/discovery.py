from __future__ import annotations

import re
import time
import unicodedata
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def normalize_module_lookup(text: str) -> str:
    """
    Normaliza títulos copiados desde Canvas:
    - Unicode NFKC
    - NBSP y otros espacios -> espacio normal
    - múltiples espacios -> uno
    - ignora mayúsculas/minúsculas
    - tolera comillas o markdown
    """
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip('"\'`* ').strip()
    return text.casefold()


def evaluation_reason(item: dict) -> str | None:
    """
    Decide si un ítem debe OMITIRSE porque corresponde a una
    evaluación / assignment / quiz que debe completarse online.
    """
    item_type = str(item.get("type") or "").strip().casefold()
    graded = str(item.get("graded") or "").strip()
    title = unicodedata.normalize(
        "NFKC", str(item.get("title") or "")
    ).replace("\u00a0", " ")
    title_norm = re.sub(r"\s+", " ", title).strip().casefold()
    classes = str(item.get("classes") or "").casefold()

    if "quiz" in item_type or "quiz" in classes:
        return f"tipo Canvas: {item_type or 'quiz'}"

    if "assignment" in item_type or "assignment" in classes:
        return f"tipo Canvas: {item_type or 'assignment'}"

    if "external_tool" in item_type or "external_tool" in classes or "lti" in classes:
        return f"herramienta externa / laboratorio: {item_type or 'external_tool'}"

    if graded == "1":
        return "ítem calificable (graded=1)"

    evaluation_patterns = (
        r"\bevaluaci[oó]n\b",
        r"\bassessment\b",
        r"\bknowledge\s+check\b",
        r"\bquiz\b",
        r"\bexamen\b",
        r"\bexam\b",
    )

    for pattern in evaluation_patterns:
        if re.search(pattern, title_norm, flags=re.IGNORECASE):
            return "título identificado como evaluación/quiz"

    lab_patterns = (
        r"\blaboratorio\b",
        r"\bhands-on\s+lab\b",
        r"\bguided\s+lab\b",
        r"\bchallenge\s+lab\b",
        r"\bsandbox\b",
        r"\blearner\s+lab\b",
        r"\blab\s+\d+\b",
        r"\blab:\b",
        r"\bpr[aá]ctica\b",
    )

    for pattern in lab_patterns:
        if re.search(pattern, title_norm, flags=re.IGNORECASE):
            return "laboratorio práctico online (requiere consola AWS manual)"

    return None


def extract_canvas_modules_tree(page) -> list[dict]:
    """
    Evalúa el DOM de la página de módulos de Canvas y devuelve la lista de
    módulos con sus ítems.
    """
    modules = page.evaluate(
        """() => {
            const clean = value =>
                String(value || '')
                    .replace(/\\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim();

            return [...document.querySelectorAll('.context_module')]
                .map(module => {
                    const titleSelectors = [
                        '.ig-header-title .name',
                        '.context_module_header .name',
                        '.ig-header .name',
                        '[data-testid="module-title"]',
                        'h2 .name',
                        'h2'
                    ];

                    let title = '';

                    for (const selector of titleSelectors) {
                        const el = module.querySelector(selector);

                        if (el) {
                            const candidate = clean(
                                el.getAttribute('title') ||
                                el.textContent
                            );

                            if (candidate) {
                                title = candidate;
                                break;
                            }
                        }
                    }

                    const items = [
                        ...module.querySelectorAll(
                            'li.context_module_item'
                        )
                    ].map((li, sourceIndex) => {
                        const anchor = li.querySelector(
                            'a.ig-title.item_link, ' +
                            'a.ig-title, a.item_link'
                        );

                        const typeEl = li.querySelector(
                            '.module_item_icons .type'
                        );
                        const gradedEl = li.querySelector(
                            '.module_item_icons .graded'
                        );
                        const positionEl = li.querySelector(
                            '.item_name .position, .position'
                        );
                        const pointsEl = li.querySelector(
                            '.item_name .points_possible, ' +
                            '.points_possible'
                        );

                        const itemTitle = clean(
                            anchor?.getAttribute('title') ||
                            anchor?.textContent ||
                            li.querySelector(
                                '.item_name .title'
                            )?.textContent ||
                            ''
                        );

                        let href = '';

                        if (anchor) {
                            try {
                                href = new URL(
                                    anchor.getAttribute('href') || '',
                                    location.href
                                ).href;
                            } catch (e) {
                                href = anchor.href || '';
                            }
                        }

                        return {
                            title: itemTitle,
                            href,
                            type: clean(typeEl?.textContent),
                            graded: clean(gradedEl?.textContent),
                            position: clean(positionEl?.textContent),
                            points: clean(pointsEl?.textContent),
                            classes: clean(li.className),
                            sourceIndex: sourceIndex + 1
                        };
                    });

                    return {
                        title,
                        id: module.id || '',
                        items
                    };
                })
                .filter(module => module.title);
        }"""
    )
    return modules or []


def fetch_all_modules(page, home_url: str, log_fn=None) -> list[str]:
    """
    Navega a la página de módulos y devuelve una lista con todos los nombres de módulos disponibles.
    """
    log = log_fn or (lambda msg: None)
    log("Consultando lista de módulos en Canvas...")

    try:
        page.goto(home_url, wait_until="domcontentloaded", timeout=90_000)
    except PlaywrightTimeoutError:
        log("La página superó el timeout de carga; buscando en el DOM disponible.")

    try:
        page.wait_for_selector(".context_module", timeout=20_000)
    except Exception:
        pass

    time.sleep(1.0)
    modules = extract_canvas_modules_tree(page)
    titles = [
        str(m.get("title") or "").strip()
        for m in modules
        if str(m.get("title") or "").strip()
    ]
    log(f"Módulos encontrados: {len(titles)}")
    return titles


def discover_module_items(
    page,
    home_url: str,
    module_title: str,
    log_fn=None,
) -> dict:
    """
    Abre la página /modules, localiza el módulo por título y obtiene
    sus URLs en el orden de Canvas.
    """
    log = log_fn or (lambda msg: None)
    requested = (module_title or "").strip()

    if not requested:
        raise RuntimeError("No se indicó el título del módulo.")

    log(f'Buscando módulo en Canvas: "{requested}"')

    try:
        page.goto(home_url, wait_until="domcontentloaded", timeout=90_000)
    except PlaywrightTimeoutError:
        log(
            "La página de módulos superó 90 s de carga; "
            "continúo buscando en el DOM disponible."
        )

    try:
        page.wait_for_selector(".context_module", timeout=30_000)
    except Exception:
        pass

    time.sleep(1.5)
    modules = extract_canvas_modules_tree(page)

    if not modules:
        current_url = ""
        try:
            current_url = page.url
        except Exception:
            pass

        raise RuntimeError(
            "No pude encontrar módulos en la página de AWS Academy. "
            "La sesión puede haber vencido. Usá primero "
            "«Abrir AWS Academy / iniciar sesión» y guardá la sesión."
            + (f" URL actual: {current_url}" if current_url else "")
        )

    target_key = normalize_module_lookup(requested)

    exact_matches = [
        m for m in modules
        if normalize_module_lookup(m.get("title", "")) == target_key
    ]

    available_titles = [
        str(m.get("title") or "").strip()
        for m in modules
        if str(m.get("title") or "").strip()
    ]

    if not exact_matches:
        preview = "\n".join(f"- {title}" for title in available_titles[:20])
        if len(available_titles) > 20:
            preview += f"\n- ... y {len(available_titles) - 20} más"

        raise RuntimeError(
            "No encontré una coincidencia exacta para el módulo:\n"
            f"{requested}\n\n"
            "Módulos detectados en Canvas:\n"
            f"{preview}"
        )

    if len(exact_matches) > 1:
        raise RuntimeError(
            f'Encontré más de un módulo con exactamente el mismo título: "{requested}".'
        )

    selected = exact_matches[0]
    raw_items = selected.get("items") or []

    downloadables = []
    skipped = []

    for item in raw_items:
        href = str(item.get("href") or "").strip()
        if not href:
            skipped.append({**item, "reason": "sin URL utilizable"})
            continue

        reason = evaluation_reason(item)
        if reason:
            skipped.append({**item, "reason": reason})
            continue

        downloadables.append(item)

    if not downloadables:
        raise RuntimeError(
            "Encontré el módulo, pero no detecté materiales "
            "descargables después de filtrar evaluaciones."
        )

    items = [
        (index, item["href"])
        for index, item in enumerate(downloadables, start=1)
    ]

    found_title = str(selected.get("title") or requested).strip()

    log(f'Módulo encontrado: "{found_title}"')
    log(
        f"Ítems detectados: {len(raw_items)} | "
        f"descargables: {len(downloadables)} | "
        f"omitidos: {len(skipped)}"
    )

    for index, item in enumerate(downloadables, start=1):
        log(f"  {index}. {item.get('title') or item.get('href')}")

    for item in skipped:
        log(
            "  OMITIDO: "
            f"{item.get('title') or item.get('href') or 'Ítem'} "
            f"[{item.get('reason', 'filtrado')}]"
        )

    return {
        "module_title": found_title,
        "items": items,
        "downloadables": downloadables,
        "skipped": skipped,
        "available_modules": available_titles,
    }

