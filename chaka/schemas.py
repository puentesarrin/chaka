from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TokenCreate(BaseModel):
    name: str


class TokenRename(BaseModel):
    name: str


class TokenPermissions(BaseModel):
    can_send: bool
    can_receive: bool
    can_talk: bool
    can_hear: bool


class TokenResponse(BaseModel):
    id: int
    name: str
    token: str
    is_active: bool
    can_send: bool
    can_receive: bool
    can_talk: bool
    can_hear: bool
    created_at: datetime
    revoked_at: Optional[datetime] = None

    model_config = {'from_attributes': True}


class ClientInfo(BaseModel):
    ws_id: str
    token_id: int
    token_name: str
    ip: str
    connected_at: datetime
    client: str = ''
    version: str = ''
    can_receive: bool = True


class DeliveryInfo(BaseModel):
    id: int
    token_id: Optional[int]
    token_name: str
    sent_at: datetime
    acked_at: Optional[datetime] = None

    model_config = {'from_attributes': True}


class LogResponse(BaseModel):
    id: int
    token_id: Optional[int]
    token_name: Optional[str]
    msg_id: Optional[str]
    source: str
    received_at: datetime
    forwarded_at: datetime
    client_ip: str
    payload: Dict[str, Any]
    deliveries: List['DeliveryInfo'] = []


class PaginatedLogs(BaseModel):
    items: List[LogResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TokenDeliveryResponse(BaseModel):
    notification_id: int
    msg_id: Optional[str]
    sent_at: datetime
    acked_at: Optional[datetime] = None
    source: str
    received_at: datetime
    payload: Dict[str, Any]


class PaginatedTokenDeliveries(BaseModel):
    items: List['TokenDeliveryResponse']
    total: int
    page: int
    per_page: int
    pages: int


class TokenEventResponse(BaseModel):
    id: int
    token_id: Optional[int]
    token_name: str
    event: str
    occurred_at: datetime
    detail: Optional[Dict[str, Any]] = None

    model_config = {'from_attributes': True}


class PaginatedEvents(BaseModel):
    items: List[TokenEventResponse]
    total: int
    page: int
    per_page: int
    pages: int


class VoiceLogResponse(BaseModel):
    id: int
    token_id: Optional[int]
    token_name: str
    channel_id: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    bytes_relayed: int
    listeners: int

    model_config = {'from_attributes': True}


class PaginatedVoiceLogs(BaseModel):
    items: List[VoiceLogResponse]
    total: int
    page: int
    per_page: int
    pages: int


class VoiceChannelClientInfo(BaseModel):
    ws_id: str
    token_id: int
    token_name: str
    transmitting: bool
    muted: bool = False


class VoiceChannelResponse(BaseModel):
    id: int
    number: int
    name: str
    is_enabled: bool
    created_at: datetime
    client_count: int = 0
    clients: List[VoiceChannelClientInfo] = []

    model_config = {'from_attributes': True}


class VoiceChannelCreate(BaseModel):
    number: int
    name: str


class VoiceChannelUpdate(BaseModel):
    name: Optional[str] = None
    is_enabled: Optional[bool] = None
