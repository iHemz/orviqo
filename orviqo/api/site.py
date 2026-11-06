"""The public website: a landing page with a live, in-browser demo of Orviqo.

WhatsApp is the product's real interface, but a visitor (a recruiter, a curious
owner) shouldn't need a phone or an allowlisted number to see it work. The demo
chat posts to ``/demo/message``, which runs the real intake service (see
``DemoService``) under a private ``demo:<session>`` business.
"""

from __future__ import annotations

import logging
from functools import cache
from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from orviqo.config import settings
from orviqo.domain.demo import demo_business_id
from orviqo.services.demo_service import DemoService

log = logging.getLogger("orviqo.site")
router = APIRouter()

BUSY_REPLY = "Sorry, the AI behind this demo is busy right now. Please try again in a minute."

_WHATSAPP_CTA = '<a class="btn btn-secondary" href="/start">Chat on WhatsApp</a>'


# When the privacy policy last changed: bump it with any edit to privacy.html.
PRIVACY_EFFECTIVE = "6 November 2026"


@cache
def _page(name: str) -> str:
    return (Path(__file__).parent / name).read_text(encoding="utf-8")


class DemoMessage(BaseModel):
    session: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=2000)


@router.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    # The WhatsApp button only appears once a public number is configured.
    cta = _WHATSAPP_CTA if settings.whatsapp_display_number else ""
    page = _page("site.html").replace("{{whatsapp_cta}}", cta)
    page = page.replace("{{session_limit}}", escape(str(settings.demo_session_limit)))
    return HTMLResponse(page)


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    """The privacy policy: Meta needs its URL before the app can go Live."""
    page = _page("privacy.html").replace("{{effective_date}}", PRIVACY_EFFECTIVE)
    return HTMLResponse(page.replace("{{contact}}", _privacy_contact()))


def _privacy_contact() -> str:
    email, number = settings.orviqo_contact_email, settings.whatsapp_display_number
    if email:
        safe = escape(email)
        return f'Email <a href="mailto:{safe}">{safe}</a> with any question or request.'
    if number:
        return f"Message Orviqo on WhatsApp at {escape(number)} with any question or request."
    return 'Open an issue at <a href="https://github.com/iHemz/orviqo">github.com/iHemz/orviqo</a>.'


@router.post("/demo/message")
async def demo_message(body: DemoMessage, request: Request) -> JSONResponse:
    try:
        business_id = demo_business_id(body.session)
    except ValueError:
        return JSONResponse({"error": "invalid session"}, status_code=400)

    demo: DemoService = request.app.state.demo
    try:
        replies = await demo.chat(business_id, body.text.strip())
    except Exception:
        # Usually the free LLM tier rate-limiting us. Say so plainly; never a 500 page.
        log.exception("demo message failed")
        return JSONResponse({"replies": [BUSY_REPLY]}, status_code=503)
    return JSONResponse({"replies": replies})
