from pydantic import BaseModel
from typing import Optional


class SnapshotRequest(BaseModel):
    device_id:      str
    ts:             float
    process_name:   str
    window_title:   str
    classification: str
    is_browser:     bool
    active_domain:  Optional[str] = None
    ocr_text:       Optional[str] = None


class SnapshotResponse(BaseModel):
    status:    str = "ingested"
    device_id: str
