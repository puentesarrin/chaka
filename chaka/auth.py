from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from chaka import application

security = HTTPBasic()


def require_admin(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings: application.Settings = request.app.state.settings
    user_ok = secrets.compare_digest(credentials.username.encode(), settings.admin_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid credentials',
            headers={'WWW-Authenticate': 'Basic'},
        )
    else:
        return credentials.username
