from pydantic import BaseModel


class SystemStats(BaseModel):
    version: str
    mem_total: int
    mem_used: int
    disk_total: int = 0
    disk_used: int = 0
    cpu_cores: int
    cpu_usage: float
    total_user: int
    online_users: int
    users_active: int
    users_on_hold: int
    users_disabled: int
    users_expired: int
    users_limited: int
    incoming_bandwidth: int
    outgoing_bandwidth: int
    incoming_bandwidth_speed: int
    outgoing_bandwidth_speed: int
    bandwidth_source: str = "nic"
    os_uptime: int = 0
    xray_uptime: int = 0
    node_uptime: int = 0
