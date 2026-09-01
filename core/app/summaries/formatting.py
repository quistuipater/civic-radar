"""Jinja filter shared by the dashboard (FastAPI's Jinja2Templates) and
email (render.py's plain jinja2.Environment) renders of summary_report.html
-- highlights standalone numbers in the AI-written Overview prose, matching
the reference artifact's colored-figure treatment (e.g. "242 new documents
landed"). Escapes the input itself rather than relying on the caller/
template to do it first, since this returns pre-escaped markup.Markup that
Jinja will render unescaped.
"""

import re

from markupsafe import Markup, escape

_NUMBER_RE = re.compile(r"\b\d[\d,]*\b")


def highlight_figures(text: str) -> Markup:
    escaped = str(escape(text))
    highlighted = _NUMBER_RE.sub(lambda m: f'<span class="figure">{m.group(0)}</span>', escaped)
    return Markup(highlighted)
