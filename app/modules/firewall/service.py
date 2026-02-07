from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.modules.firewall.repository import FirewallRepository


class FirewallValidationError(ValueError):
    pass


class FirewallIpAlreadyExistsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FirewallIpEntryData:
    ip_address: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FirewallListData:
    mode: Literal["allow_all", "allowlist_active"]
    entries: list[FirewallIpEntryData]


class FirewallService:
    def __init__(self, repository: FirewallRepository) -> None:
        self._repository = repository

    async def list_ips(self) -> FirewallListData:
        rows = await self._repository.list_entries()
        entries = [FirewallIpEntryData(ip_address=row.ip_address, created_at=row.created_at) for row in rows]
        mode: Literal["allow_all", "allowlist_active"] = "allow_all" if not entries else "allowlist_active"
        return FirewallListData(mode=mode, entries=entries)

    async def add_ip(self, ip_address: str) -> FirewallIpEntryData:
        normalized = normalize_ip_address(ip_address)
        if await self._repository.exists(normalized):
            raise FirewallIpAlreadyExistsError("IP address already exists")
        row = await self._repository.add(normalized)
        return FirewallIpEntryData(ip_address=row.ip_address, created_at=row.created_at)

    async def remove_ip(self, ip_address: str) -> bool:
        normalized = normalize_ip_address(ip_address)
        return await self._repository.delete(normalized)

    async def is_ip_allowed(self, ip_address: str | None) -> bool:
        allowlist = await self._repository.list_ip_addresses()
        if not allowlist:
            return True
        if ip_address is None:
            return False
        try:
            normalized = normalize_ip_address(ip_address)
        except FirewallValidationError:
            return False
        return normalized in allowlist


def normalize_ip_address(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise FirewallValidationError("IP address is required")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise FirewallValidationError("Invalid IP address") from exc
