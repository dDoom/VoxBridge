from __future__ import annotations

from dataclasses import dataclass


DEFAULT_MODEL = "gpt-realtime-translate"
API_SAMPLE_RATE = 24_000

TRANSLATION_LANGUAGES = [
    ("Arabic", "ar"),
    ("Chinese", "zh"),
    ("English", "en"),
    ("French", "fr"),
    ("German", "de"),
    ("Hindi", "hi"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Portuguese", "pt"),
    ("Russian", "ru"),
    ("Spanish", "es"),
    ("Turkish", "tr"),
]


@dataclass(frozen=True)
class RouteConfig:
    name: str
    enabled: bool
    input_device: int
    output_device: int
    source_language: str
    target_language: str


@dataclass(frozen=True)
class BridgeConfig:
    api_key: str
    model: str
    route_a: RouteConfig
    route_b: RouteConfig
