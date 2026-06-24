from pydantic import BaseModel
from typing import Optional


class HeartbeatRequest(BaseModel):
    device_id:  str
    ts:         float
    uptime_s:   float
    connected:  bool


class HeartbeatResponse(BaseModel):
    status:     str   = "ok"
    server_ts:  float
