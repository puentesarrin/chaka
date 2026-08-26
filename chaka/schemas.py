import re
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from chaka import passwords

# Deliberately permissive: enough to catch a typo or an empty box, without
# pulling in an RFC-complete validator (and its dependency) for an admin form.
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$')
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def _check_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError('Not a valid email address')
    else:
        return value


def _check_username(value: str) -> str:
    value = value.strip()
    if not _USERNAME_RE.match(value):
        raise ValueError('May only contain letters, digits, dot, dash and underscore')
    else:
        return value


Email = Annotated[str, StringConstraints(max_length=255), AfterValidator(_check_email)]
Username = Annotated[str, StringConstraints(min_length=1, max_length=64), AfterValidator(_check_username)]


class UserCreate(BaseModel):
    username: Username
    email: Email
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=256)
    full_name: Optional[str] = Field(default=None, max_length=120)
    is_active: bool = True


class UserUpdate(BaseModel):
    email: Optional[Email] = None
    full_name: Optional[str] = Field(default=None, max_length=120)
    is_active: Optional[bool] = None


class UserPassword(BaseModel):
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=256)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {'from_attributes': True}


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
