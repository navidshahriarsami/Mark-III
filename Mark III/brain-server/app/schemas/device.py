from pydantic import BaseModel
from typing import Optional


class DeviceRegisterRequest(BaseModel):
    device_id: str
    hostname:  str
    platform:  str
    version:   str


class DeviceRegisterResponse(BaseModel):
    status:    str = "registered"
    device_id: str
    message:   str = "Device registered with MARK III brain server."
