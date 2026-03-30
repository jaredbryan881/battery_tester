from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class VisaConfig:
    resource: str
    timeout_ms: int = 5000

@dataclass
class RelayConfig:
    port: str
    baudrate: int = 9600
    timeout_s: float = 1.0

@dataclass
class RoutingState:
    relay1: bool
    relay2: bool

@dataclass
class BatteryDefaults:
    chemistry: str
    v_charge_max: float
    v_discharge_min: float
    i_charge_a: float
    i_discharge_a: float
    sample_period_s: float
    ir_pulse_current_a: float
    ir_pulse_duration_s: float
    rest_after_charge_s: float
    rest_after_discharge_s: float

@dataclass
class AppConfig:
    visa_backend: str
    data_dir: str
    sdm3055: VisaConfig
    spd3303x: VisaConfig
    dl3021: VisaConfig
    relay: RelayConfig
    routing: dict[str, RoutingState]
    battery_defaults: BatteryDefaults

def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())

    return AppConfig(
        visa_backend=raw["visa_backend"],
        data_dir=raw["data_dir"],
        sdm3055=VisaConfig(**raw["sdm3055"]),
        spd3303x=VisaConfig(**raw["spd3303x"]),
        dl3021=VisaConfig(**raw["dl3021"]),
        relay=RelayConfig(**raw["relay"]),
        routing={k: RoutingState(**v) for k, v in raw["routing"].items()},
        battery_defaults=BatteryDefaults(**raw["battery_defaults"]),
    )