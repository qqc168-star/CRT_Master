from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class RegistryError(ValueError):
    """The source registry violates the active read-only contract."""


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    namespace: str
    input_family: str
    role: str
    provider: str
    transport: str
    endpoint: str | None
    parser_id: str
    criticality: str
    max_age_seconds: int
    raw: dict[str, Any]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class SourceRegistry:
    def __init__(self, payload: dict[str, Any], *, path: Path | None = None):
        self.payload = payload
        self.path = path
        self._validate()
        self.hash = sha256_hex(canonical_json_bytes(payload))
        self._by_id = {
            item["source_id"]: SourceSpec(
                source_id=item["source_id"],
                namespace=item["namespace"],
                input_family=item["input_family"],
                role=item["role"],
                provider=item["provider"],
                transport=item["transport"],
                endpoint=item.get("endpoint"),
                parser_id=item["parser_id"],
                criticality=item["criticality"],
                max_age_seconds=int(item["max_age_seconds"]),
                raw=item,
            )
            for item in payload["sources"]
        }

    @classmethod
    def load(cls, path: str | Path) -> "SourceRegistry":
        file_path = Path(path)
        return cls(json.loads(file_path.read_text(encoding="utf-8")), path=file_path)

    def get(self, source_id: str) -> SourceSpec:
        try:
            return self._by_id[source_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown source_id: {source_id}") from exc

    def by_input_family(self, input_family: str) -> SourceSpec:
        matches = [s for s in self._by_id.values() if s.input_family == input_family]
        if len(matches) != 1:
            raise RegistryError(
                f"Expected exactly one source for {input_family}; found {len(matches)}"
            )
        return matches[0]

    def with_l6_candidate_sources(self) -> "SourceRegistry":
        """Overlay L6 without mutating the base registry pinned by L4 OI policy."""
        from copy import deepcopy
        from .l6_source_binding import SOURCE_IDS
        overlay = json.loads((Path(__file__).resolve().parents[2] /
                              "CONFIG/L6_SOURCE_BINDING_OVERLAY_V0.1.json").read_text(encoding="utf-8"))
        payload = deepcopy(self.payload)
        # Other approved overlays may already be present; compare the exact base projection.
        base_ids = {x["source_id"] for x in json.loads((Path(__file__).resolve().parents[2] /
                    "CONFIG/SOURCE_REGISTRY_V1.2.json").read_text(encoding="utf-8"))["sources"]}
        base = deepcopy(payload)
        base["sources"] = [x for x in base["sources"] if x["source_id"] in base_ids]
        if sha256_hex(canonical_json_bytes(base)) != overlay["base_registry_sha256"]:
            raise RegistryError("L6 overlay base registry hash mismatch")
        present = {x["input_family"]: x for x in payload["sources"]}
        if {x["input_family"] for x in overlay["sources"]} != set(SOURCE_IDS):
            raise RegistryError("L6 overlay must contain exactly the two locked families")
        for item in overlay["sources"]:
            existing = present.get(item["input_family"])
            if existing is not None and existing != item:
                raise RegistryError("L6 overlay source conflict")
            if existing is None:
                payload["sources"].append(item)
        return SourceRegistry(payload)

    def _validate(self) -> None:
        required_root = {
            "registry_id",
            "version",
            "status",
            "formal_parent",
            "production_profile",
            "external_action_authority",
            "sources",
        }
        missing = required_root - self.payload.keys()
        if missing:
            raise RegistryError(f"Registry missing root fields: {sorted(missing)}")
        if self.payload["external_action_authority"] != "NONE":
            raise RegistryError("External action authority must remain NONE")
        if not isinstance(self.payload["sources"], list) or not self.payload["sources"]:
            raise RegistryError("sources must be a non-empty list")

        required_source = {
            "source_id",
            "namespace",
            "input_family",
            "role",
            "provider",
            "transport",
            "parser_id",
            "criticality",
            "max_age_seconds",
        }
        ids: set[str] = set()
        families: set[str] = set()
        for item in self.payload["sources"]:
            if not isinstance(item, dict):
                raise RegistryError("Every source must be an object")
            absent = required_source - item.keys()
            if absent:
                raise RegistryError(
                    f"Source missing fields {sorted(absent)}: {item.get('source_id')}"
                )
            source_id = item["source_id"]
            family = item["input_family"]
            if source_id in ids:
                raise RegistryError(f"Duplicate source_id: {source_id}")
            if family in families:
                raise RegistryError(f"Duplicate input_family: {family}")
            ids.add(source_id)
            families.add(family)
            if not str(item["namespace"]).startswith("AS-L"):
                raise RegistryError(f"Invalid AS namespace: {item['namespace']}")
            if int(item["max_age_seconds"]) <= 0:
                raise RegistryError(f"max_age_seconds must be positive: {source_id}")
            if item.get("authentication") not in {"NONE", "LOCAL_READ_ONLY"}:
                raise RegistryError(f"Unexpected authentication mode: {source_id}")

        probe = next(
            (x for x in self.payload["sources"] if x["input_family"] == "LIQUIDATION_CONNECTIVITY_PROBE"),
            None,
        )
        if probe is None:
            raise RegistryError("Liquidation connectivity probe is required")
        self._validate_liquidation_route(probe)

        aggregate = next(
            (x for x in self.payload["sources"] if x["input_family"] == "LIQUIDATION_AGGREGATES"),
            None,
        )
        if aggregate is None:
            raise RegistryError("Persistent liquidation aggregate source is required")
        if aggregate.get("criticality") != "CRITICAL_FAIL_CLOSED":
            raise RegistryError("Liquidation aggregate must remain critical fail-closed")

        from .l6_source_binding import SOURCE_IDS
        for item in self.payload["sources"]:
            family = item["input_family"]
            if family in SOURCE_IDS:
                if (item["source_id"] != SOURCE_IDS[family]
                        or item["namespace"] != "AS-L6"
                        or item["transport"] != "LOCAL_VERIFIED_PROVIDER_ARCHIVES"
                        or item["authentication"] != "LOCAL_READ_ONLY"
                        or item["criticality"] != "CRITICAL_FAIL_CLOSED"):
                    raise RegistryError("L6 locked source binding changed")
                for key, expected in {"formal_model": "NOT_APPROVED", "production": "NOT_APPROVED",
                                      "action_output": "NONE", "external_action_authority": "NONE",
                                      "capital_decision_authority": "USER_ONLY"}.items():
                    if item.get(key) != expected:
                        raise RegistryError(f"L6 authority changed: {key}")

    @staticmethod
    def _validate_liquidation_route(item: dict[str, Any]) -> None:
        endpoint = item.get("endpoint")
        if not isinstance(endpoint, str):
            raise RegistryError("Liquidation probe endpoint is missing")
        parsed = urlparse(endpoint)
        if parsed.scheme != "wss" or parsed.netloc != "fstream.binance.com":
            raise RegistryError("Liquidation probe must use Binance USD-M WSS")
        if not parsed.path.startswith("/market/"):
            raise RegistryError("forceOrder must use Binance /market route")
        if "/public/" in parsed.path:
            raise RegistryError("forceOrder must never use Binance /public route")
        if not parsed.path.endswith("/ws/btcusdt@forceOrder"):
            raise RegistryError("Liquidation stream path must be btcusdt@forceOrder")
        if item.get("endpoint_category") != "MARKET":
            raise RegistryError("Liquidation endpoint_category must be MARKET")
        if item.get("metric_authority") != "NONE":
            raise RegistryError("Connectivity probe cannot have metric authority")
