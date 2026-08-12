"""Config loading and project paths."""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = Path(os.environ.get("BRIDGE_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
EXPORT_DIR = Path(os.environ.get("BRIDGE_EXPORT_DIR", PROJECT_ROOT / "exports"))
DB_PATH = Path(os.environ.get("BRIDGE_DB_PATH", DATA_DIR / "bridge.db"))


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@functools.lru_cache(maxsize=None)
def brands_config() -> dict[str, Any]:
    return _load_yaml("brands.yaml")


@functools.lru_cache(maxsize=None)
def platforms_config() -> dict[str, Any]:
    return _load_yaml("platforms.yaml")


@functools.lru_cache(maxsize=None)
def oems_config() -> dict[str, Any]:
    return _load_yaml("oems.yaml")


@functools.lru_cache(maxsize=None)
def keywords_config() -> dict[str, Any]:
    return _load_yaml("keywords.yaml")


@functools.lru_cache(maxsize=None)
def scoring_config() -> dict[str, Any]:
    return _load_yaml("scoring.yaml")


@dataclass(frozen=True)
class ProcessorLine:
    brand: str
    name: str
    tier: str
    patterns: tuple[re.Pattern[str], ...]
    discrete_gpu: bool = False


@dataclass(frozen=True)
class BadgeSpec:
    brand: str
    name: str
    patterns: tuple[re.Pattern[str], ...]
    applies_to_lines: frozenset[str] = field(default_factory=frozenset)
    product_types: frozenset[str] = field(default_factory=frozenset)

    def is_eligible(self, processor_line: str | None, product_type: str | None) -> bool:
        """Whether this badge *should* appear on a product."""
        if self.applies_to_lines and (processor_line or "") not in self.applies_to_lines:
            return False
        if self.product_types and (product_type or "") not in self.product_types:
            return False
        return True


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


@functools.lru_cache(maxsize=None)
def processor_lines() -> tuple[ProcessorLine, ...]:
    """All processor lines across all brands, most-specific-first."""
    out: list[ProcessorLine] = []
    for brand_key, spec in brands_config()["brands"].items():
        for line in spec.get("processor_lines") or []:
            out.append(
                ProcessorLine(
                    brand=brand_key,
                    name=line["name"],
                    tier=line.get("tier", "unknown"),
                    patterns=_compile(line["patterns"]),
                    discrete_gpu=bool(line.get("discrete_gpu", False)),
                )
            )
    return tuple(out)


@functools.lru_cache(maxsize=None)
def brand_fallback_patterns() -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    """Generic brand mentions, used only when no processor line matched."""
    return tuple(
        (brand_key, _compile(spec.get("brand_patterns") or []))
        for brand_key, spec in brands_config()["brands"].items()
    )


@functools.lru_cache(maxsize=None)
def brand_context_patterns() -> dict[str, tuple[re.Pattern[str], ...]]:
    """Brands whose line matches require corroborating context to count."""
    return {
        brand_key: _compile(spec["context_patterns"])
        for brand_key, spec in brands_config()["brands"].items()
        if spec.get("context_patterns")
    }


@functools.lru_cache(maxsize=None)
def badge_specs() -> tuple[BadgeSpec, ...]:
    out: list[BadgeSpec] = []
    for brand_key, spec in brands_config()["brands"].items():
        for badge in spec.get("badges") or []:
            out.append(
                BadgeSpec(
                    brand=brand_key,
                    name=badge["name"],
                    patterns=_compile(badge["patterns"]),
                    applies_to_lines=frozenset(badge.get("applies_to_lines") or []),
                    product_types=frozenset(badge.get("product_types") or []),
                )
            )
    return tuple(out)


@functools.lru_cache(maxsize=None)
def oem_patterns() -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    return tuple(
        (oem_key, _compile(spec.get("patterns") or []))
        for oem_key, spec in oems_config()["oems"].items()
    )


@functools.lru_cache(maxsize=None)
def oem_sub_brand_patterns() -> tuple[tuple[str, str, re.Pattern[str]], ...]:
    """(oem_key, sub_brand_name, pattern) for family-level drill-down."""
    out: list[tuple[str, str, re.Pattern[str]]] = []
    for oem_key, spec in oems_config()["oems"].items():
        for sub in spec.get("sub_brands") or []:
            out.append((oem_key, sub, re.compile(rf"\b{re.escape(sub)}\b", re.IGNORECASE)))
    return tuple(out)


@functools.lru_cache(maxsize=None)
def board_partner_pattern() -> re.Pattern[str]:
    partners = oems_config().get("board_partners") or []
    if not partners:
        return re.compile(r"(?!x)x")
    return re.compile(r"\b(" + "|".join(re.escape(p) for p in partners) + r")\b", re.IGNORECASE)


@functools.lru_cache(maxsize=None)
def tracked_brands() -> tuple[str, ...]:
    return tuple(brands_config()["tracked_brands"])


@functools.lru_cache(maxsize=None)
def tracked_oems() -> tuple[str, ...]:
    return tuple(oems_config()["tracked_oems"])


@functools.lru_cache(maxsize=None)
def brand_display_names() -> dict[str, str]:
    names = {k: v.get("display_name", k.title()) for k, v in brands_config()["brands"].items()}
    names.setdefault("other", "Other / Unattributed")
    return names


def platform(platform_key: str) -> dict[str, Any]:
    try:
        return platforms_config()["platforms"][platform_key]
    except KeyError as exc:
        raise KeyError(f"Unknown platform '{platform_key}'") from exc


@functools.lru_cache(maxsize=None)
def platform_keys() -> tuple[str, ...]:
    return tuple(platforms_config()["platforms"].keys())


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
