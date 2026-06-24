from pydantic import BaseModel
from typing import Optional


class BreachReportRequest(BaseModel):
    """Posted by the daemon's rabbit-hole detector when threshold is crossed."""
    device_id:    str
    keyword:      str
    duration_min: float
    process_name: str
    active_domain: Optional[str] = None


class BreachReportResponse(BaseModel):
    status:           str = "recorded"
    notif_sent:       bool
    notif_provider:   str
    breach_id:        int
