from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    user_id: str
    session_id: str
    turno_id: str = ""
    moeda_informada: str | None = None
    escritas_pendentes: list[dict[str, Any]] = field(default_factory=list)
