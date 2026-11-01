"""Capability discovery, verification, and the broker tool allowlist.

Flow (plan sections 14 and 17):
  1. The gateway authenticates to the broker's MCP endpoint with the
     owner-provisioned token.
  2. It lists the server's tools and computes a canonical digest over the
     complete tool set (name + description + input schema, order-independent).
  3. The digest must match the owner-allowlisted digest stored in the
     configuration before any read is permitted.
  4. A mismatch fails closed: the gateway stops, records the difference, and
     reports it to the owner. It never silently accepts a changed tool set,
     including a changed schema for a permitted tool.

The allowlist file (``config/capability_allowlist.yaml``) is version
control territory: it maps roles (account, positions, open orders, ...) to
concrete tool names and classifies every listed tool as ``read`` or
``trade``. In this build the adapter can only ever call tools classified
``read``; trade-classified entries exist for visibility and for the
separately approved live build.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..contracts.broker import CapabilityMismatch

DEFAULT_ROLES: tuple[str, ...] = (
    "account",
    "positions",
    "open_orders",
    "fills",
    "quotes",
    "place_order",
    "cancel_order",
)

READ_ROLES: tuple[str, ...] = ("account", "positions", "open_orders", "fills", "quotes")


@dataclass(frozen=True)
class ToolSchema:
    """One tool as reported by ``tools/list``."""

    name: str
    description: str
    input_schema: dict

    @classmethod
    def from_api(cls, raw: dict) -> ToolSchema:
        return cls(
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            input_schema=dict(raw.get("inputSchema") or raw.get("input_schema") or {}),
        )


def canonical_digest(schemas: list[ToolSchema]) -> str:
    """SHA-256 over the canonical, order-independent tool set.

    Ordering by tool name makes the digest stable across server list order.
    Any change to a name, description, or input schema changes the digest.
    """
    canonical = [
        {
            "name": schema.name,
            "description": schema.description,
            "input_schema": schema.input_schema,
        }
        for schema in sorted(schemas, key=lambda item: item.name)
    ]
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CapabilityReport:
    """Outcome of one authenticated discovery + verification pass."""

    tools: tuple[ToolSchema, ...] = field(default=())
    digest: str | None = None
    verified: bool = False
    mismatch_detail: str | None = None
    discovered_at: str | None = None


def verify_capability(tools: list[ToolSchema], allowlisted_digest: str | None) -> CapabilityReport:
    """Compare the discovered digest against the owner-allowlisted digest.

    A missing allowlisted digest is a mismatch (fail-closed): the owner must
    run ``broker setup`` and record the verified digest before reads proceed.
    """
    if len({tool.name for tool in tools}) != len(tools):
        return CapabilityReport(verified=False, mismatch_detail="duplicate tool names")
    digest = canonical_digest(tools)
    if not allowlisted_digest:
        return CapabilityReport(
            tools=tuple(tools),
            digest=digest,
            verified=False,
            mismatch_detail="no allowlisted digest in configuration (run 'broker setup')",
        )
    if digest != allowlisted_digest.strip().lower():
        return CapabilityReport(
            tools=tuple(tools),
            digest=digest,
            verified=False,
            mismatch_detail=(
                f"capability digest mismatch: server={digest[:16]}… "
                f"allowlisted={allowlisted_digest.strip().lower()[:16]}… "
                f"({len(tools)} tools listed)"
            ),
        )
    return CapabilityReport(tools=tuple(tools), digest=digest, verified=True)


@dataclass(frozen=True)
class RoleSpec:
    """One role binding: role name -> concrete tool name + category."""

    role: str
    name: str | None
    category: str  # "read" | "trade"


class ToolAllowlist:
    """The owner-controlled mapping from gateway roles to tool names."""

    def __init__(self, roles: dict[str, RoleSpec], version: int = 1) -> None:
        self._roles = roles
        self._version = version

    @classmethod
    def from_file(cls, path: str | Path) -> ToolAllowlist | None:
        """Load the allowlist, or None when the file does not exist.

        Construction must never crash on a missing file: the shadow cycle
        fails closed with ``allowlist_missing`` instead, and
        ``broker setup`` writes the file the owner generated.
        """
        if not Path(path).exists():
            return None
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CapabilityMismatch(f"allowlist file is not a mapping: {path}")
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: dict, *, source: str = "<dict>") -> ToolAllowlist:
        tools = raw.get("tools") or {}
        if not isinstance(tools, dict):
            raise CapabilityMismatch(f"allowlist 'tools' must be a mapping ({source})")
        roles: dict[str, RoleSpec] = {}
        for role in DEFAULT_ROLES:
            entry = tools.get(role) or {}
            if not isinstance(entry, dict):
                raise CapabilityMismatch(f"allowlist role '{role}' must be a mapping")
            name = entry.get("name")
            category = str(entry.get("category", "read")).lower()
            if category not in ("read", "trade"):
                raise CapabilityMismatch(
                    f"allowlist role '{role}' has invalid category '{category}'"
                )
            if name is not None:
                name = str(name).strip() or None
            roles[role] = RoleSpec(role=role, name=name, category=category)
        return cls(roles=roles, version=int(raw.get("version", 1)))

    @property
    def version(self) -> int:
        return self._version

    def spec(self, role: str) -> RoleSpec | None:
        return self._roles.get(role)

    def tool_name(self, role: str) -> str | None:
        spec = self._roles.get(role)
        return spec.name if spec is not None else None

    def unmapped_roles(self) -> list[str]:
        return [role for role in DEFAULT_ROLES if self._roles[role].name is None]

    def role_for(self, tool_name: str) -> RoleSpec | None:
        for spec in self._roles.values():
            if spec.name is not None and spec.name == tool_name:
                return spec
        return None

    def read_tool_names(self) -> set[str]:
        """Names this build may ever call: mapped, read-classified tools."""
        return {
            spec.name
            for spec in self._roles.values()
            if spec.role in READ_ROLES and spec.name is not None and spec.category == "read"
        }

    def permits(self, tool_name: str, *, required_category: str) -> bool:
        spec = self.role_for(tool_name)
        return spec is not None and spec.category == required_category and spec.name is not None

    def to_dict(self) -> dict:
        return {
            "version": self._version,
            "tools": {
                spec.role: {"name": spec.name, "category": spec.category}
                for spec in self._roles.values()
            },
        }
