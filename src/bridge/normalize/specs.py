"""Spec-table normalisation (module 5)."""

from __future__ import annotations

import re

from .text import clean_text, normalize_key

_KEY_MAP: dict[str, tuple[str, ...]] = {
    "processor": ("processor", "processador", "cpu", "chip", "modelo_do_processador"),
    "processor_brand": ("processor_brand", "marca_do_processador", "cpu_brand"),
    "processor_speed": ("processor_speed", "clock", "frequencia", "velocidade"),
    "processor_cores": ("cores", "nucleos", "num_cores", "quantidade_de_nucleos"),
    "graphics": ("gpu", "graphics", "placa_de_video", "video", "graphics_card",
                 "processador_grafico", "placa_grafica"),
    "graphics_memory": ("graphics_memory", "memoria_de_video", "vram"),
    "memory": ("memory", "memoria", "ram", "memoria_ram", "system_memory"),
    "memory_type": ("memory_type", "tipo_de_memoria"),
    "storage": ("storage", "armazenamento", "ssd", "hdd", "hard_drive",
                "capacidade_do_ssd", "capacidade_de_armazenamento"),
    "display_size": ("screen_size", "display_size", "tamanho_da_tela", "tela"),
    "display_resolution": ("resolution", "resolucao"),
    "display_refresh": ("refresh_rate", "taxa_de_atualizacao"),
    "operating_system": ("operating_system", "sistema_operacional", "os"),
    "weight": ("weight", "peso"),
    "battery": ("battery", "bateria"),
    "model": ("model", "modelo", "part_number", "mpn"),
    "brand": ("brand", "marca", "fabricante", "manufacturer"),
    "warranty": ("warranty", "garantia"),
    "color": ("color", "cor"),
    "condition": ("condition", "condicao", "is_new"),
}

_LOOKUP: dict[str, str] = {
    token: canonical for canonical, tokens in _KEY_MAP.items() for token in tokens
}

_UNIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gb|tb|mb|ghz|mhz|wh|kg|g|in|\"|pol)\b", re.IGNORECASE)


def normalize_spec_key(raw_key: str) -> str | None:
    """Map a raw spec label onto the canonical vocabulary, or None if unmapped."""
    key = normalize_key(raw_key)
    if not key:
        return None
    if key in _LOOKUP:
        return _LOOKUP[key]
    for token in sorted(_LOOKUP, key=len, reverse=True):
        if token in key:
            return _LOOKUP[token]
    return None


def normalize_spec_value(raw_value: str) -> str | None:
    """Light value normalisation: collapse whitespace, standardise units."""
    text = clean_text(raw_value)
    if not text:
        return None
    text = _UNIT_RE.sub(lambda m: f"{m.group(1)}{m.group(2).upper()}", text)
    return text[:512]


def flatten_specs(specs: dict[str, str]) -> str:
    """Flatten a spec dict into one searchable blob for attribution fallback."""
    return " ".join(f"{k} {v}" for k, v in specs.items() if v)


def spec_mentions_brand_or_line(
    specs: dict[str, str], brand_display: str, processor_line: str | None
) -> tuple[bool, str | None]:
    """Rubric check P3: is the brand or processor line named in the spec table?"""
    priority_keys = ("processor", "processor_brand", "graphics", "brand", "model")
    priority_blob = " ".join(
        v for k, v in specs.items() if normalize_spec_key(k) in priority_keys
    )
    full_blob = flatten_specs(specs)

    needles = [brand_display]
    if processor_line:
        needles.append(processor_line)

    for blob, source in ((priority_blob, "spec_field"), (full_blob, "spec_table")):
        low = blob.lower()
        for needle in needles:
            if needle and needle.lower() in low:
                return True, f"{source}:'{needle}'"
    return False, None
