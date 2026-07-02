from typing import List

from fastapi import APIRouter, Depends, Request

from chaka import auth, schemas

router = APIRouter(tags=['clients'])


@router.get('/clients', response_model=List[schemas.ClientInfo])
async def list_clients(request: Request, _: str = Depends(auth.require_admin)):
    clients = await request.app.state.manager.get_clients()
    return [
        schemas.ClientInfo(
            ws_id=c.ws_id,
            token_id=c.token_id,
            token_name=c.token_name,
            ip=c.ip,
            connected_at=c.connected_at,
            client=c.client,
            version=c.version,
            can_receive=c.can_receive,
        )
        for c in clients
    ]
