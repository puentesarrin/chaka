from __future__ import annotations

import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from chaka import auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=['session'])

LOGIN_PATH = '/login'


async def _form(request: Request) -> dict:
    """Decode an ``application/x-www-form-urlencoded`` body into a flat dict."""
    body = await request.body()
    return {key: values[0] for key, values in parse_qs(body.decode('utf-8', 'replace')).items() if values}


def _safe_next(value: str) -> str:
    """Keep only same-site absolute paths; anything else falls back to ``/``."""
    if value.startswith('/') and not value.startswith('//'):
        return value
    return '/'


@router.get(LOGIN_PATH, response_class=HTMLResponse)
async def login_form(request: Request, next: str = '/'):
    target = _safe_next(next)
    if await auth.session_user(request) is not None:
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        'login.html', {'request': request, 'next': target, 'error': None}
    )


@router.post(LOGIN_PATH, response_class=HTMLResponse)
async def login(request: Request):
    fields = await _form(request)
    username = fields.get('username', '')
    password = fields.get('password', '')
    target = _safe_next(fields.get('next', '/'))
    user = await auth.authenticate(request, username, password)
    if user is None:
        ip = request.client.host if request.client else 'unknown'
        logger.warning('Login failed: user=%s ip=%s', username, ip)
        return request.app.state.templates.TemplateResponse(
            'login.html',
            {'request': request, 'next': target, 'error': 'Invalid username or password'},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    auth.issue_session(response, user, request.app.state.settings)
    logger.info('Login: user=%s', user.username)
    return response


@router.post('/logout')
async def logout(request: Request):
    response = RedirectResponse(LOGIN_PATH, status_code=status.HTTP_303_SEE_OTHER)
    auth.clear_session(response, request.app.state.settings)
    return response
