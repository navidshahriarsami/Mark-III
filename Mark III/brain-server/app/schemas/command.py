from pydantic import BaseModel, Field
from typing import Optional
import uuid


class PendingCommandRequest(BaseModel):
    """Posted by the daemon when a privileged command awaits approval."""
    device_id:  str
    request_id: str
    raw:        str
    requester:  str = "brain-server"


class PendingCommandResponse(BaseModel):
    status:     str = "queued"
    request_id: str


class CommandStatusResponse(BaseModel):
    request_id: str
    status:     str   # "pending" | "approved" | "denied"


class CommandResultRequest(BaseModel):
    """Posted by the daemon after a command executes (or is denied)."""
    device_id:   str
    request_id:  str
    status:      str
    stdout:      str = ""
    stderr:      str = ""
    returncode:  Optional[int] = None


class CommandResultResponse(BaseModel):
    status:     str = "recorded"
    request_id: str


class PendingCommandsResponse(BaseModel):
    """Returned to the daemon by the command poll loop."""
    commands:   list[dict]
