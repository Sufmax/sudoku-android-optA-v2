"""Chargement, validation et rechargement à chaud de `config/config.yaml`.

Toute la configuration est décrite par des modèles pydantic : une valeur invalide
est rejetée avec un message explicite au lieu de provoquer un comportement erroné.
"""
from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "config.yaml"

Pair = tuple[float, float]
IntPair = tuple[int, int]

#: Sections dont la modification n'est prise en compte qu'au redémarrage.
RESTART_REQUIRED: tuple[str, ...] = ("emulator", "display", "machine", "adb.path", "dashboard.url")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MachineCfg(_Base):
    id: str = "csb-01"
    version: str = "2.0.0"


class WorkflowCfg(_Base):
    auto_ready_on_resume: bool = False
    first_run_hint_s: int = 900
    resume_hint_s: int = 120


class EmulatorCfg(_Base):
    """Paramètres de l'émulateur Android (lus aussi par les scripts shell via `cfg`)."""

    backend: Literal["auto", "avd", "redroid", "remote"] = "auto"
    accel: Literal["auto", "on", "off"] = "auto"
    image_variant: Literal["playstore", "aurora"] = "playstore"
    image_fallback: bool = True
    avd_name: str = "sudoku"
    api_level: int = 29
    abi: Literal["x86_64", "x86"] = "x86_64"
    device_profile: str = "pixel_4"
    ram_mb: int = 4096
    vm_heap_mb: int = 512
    cores: int = 3
    data_partition: str = "6G"
    width: int = 1080
    height: int = 2340
    density: int = 420
    gpu: str = "swiftshader_indirect"
    dns_servers: str = "8.8.8.8,8.8.4.4"
    boot_timeout_s: int = 1500
    quickboot: bool = False
    console_port: int = 5554
    checkpoint_snapshot: str = "bot_checkpoint"
    snapshot_every_s: int = 0
    remote_serial: str = "127.0.0.1:5555"
    redroid_image: str = "redroid/redroid:13.0.0_gapps"
    game_package: str = "easy.sudoku.puzzle.solver.free"


class DisplayCfg(_Base):
    """Écran virtuel Xvfb + accès distant x11vnc/noVNC (phase de configuration manuelle)."""

    xvfb_display: str = ":1"
    xvfb_screen: str = "1920x1080x24"
    vnc_port: int = 5900
    novnc_port: int = 6080
    vnc_password: bool = True


class AdbCfg(_Base):
    path: str = "adb"
    serial: str = ""
    command_timeout_s: float = 10
    screencap_mode: Literal["raw", "png"] = "raw"
    reconnect_attempts: int = 6
    restart_emulator_after_failures: int = 3


class GridCfg(_Base):
    sizes: list[int] = Field(default_factory=lambda: [4, 6, 8, 9, 10, 12, 16])
    min_width_frac: float = 0.45
    squareness_tol: float = 0.12
    line_kernel_frac: float = 0.08
    adaptive_block_frac: float = 0.025
    adaptive_c: float = 6
    line_coverage_min: float = 0.55
    lattice_tol: float = 0.2
    thick_ratio_min: float = 1.25
    block_fallback: dict[str, IntPair] = Field(default_factory=lambda: {"4": (2, 2), "6": (2, 3), "9": (3, 3), "12": (3, 4), "16": (4, 4)})


class CellsCfg(_Base):
    inset_frac: float = 0.10
    ink_delta: float = 70
    min_glyph_h_frac: float = 0.33
    max_glyph_h_frac: float = 0.92
    template_size: int = 32
    digit_min_score: float = 0.70
    digit_min_margin: float = 0.04
    templates_per_symbol: int = 6


class ColorsCfg(_Base):
    error_hue: list[IntPair] = Field(default_factory=lambda: [(0, 12), (165, 180)])
    error_min_sat: int = 45
    error_min_val: int = 150
    user_hue: IntPair = (90, 135)
    user_min_sat: int = 70
    given_max_val: int = 140
    given_max_sat: int = 80


class KeypadCfg(_Base):
    ink: Literal["colored", "any"] = "colored"
    min_h_frac: float = 0.35
    max_h_frac: float = 1.25
    row_tol_frac: float = 0.35
    regularity_tol: float = 0.25


class OverlayCfg(_Base):
    dim_value_max: float = 175
    blob_area_frac: float = 0.06


class DetectionCfg(_Base):
    min_confidence_action: float = 0.75
    grid: GridCfg = Field(default_factory=GridCfg)
    cells: CellsCfg = Field(default_factory=CellsCfg)
    colors: ColorsCfg = Field(default_factory=ColorsCfg)
    keypad: KeypadCfg = Field(default_factory=KeypadCfg)
    overlay: OverlayCfg = Field(default_factory=OverlayCfg)


class OcrCfg(_Base):
    tesseract_path: str = "tesseract"
    languages: str = "fra+eng"
    psm: int = 11
    dual_polarity: bool = True
    min_word_conf: float = 40
    match_ratio: float = 0.78
    timeout_s: float = 12


class ScreenAction(_Base):
    type: Literal["tap_text", "back", "wait", "tap_blob_above_text", "relaunch", "none"]
    texts: list[str] = Field(default_factory=list)
    fallback: Literal["back", "wait", "none"] = "none"


class ScreenRule(_Base):
    id: str
    any: list[str]
    all: list[str] = Field(default_factory=list)  # phrases TOUTES requises en plus de `any`
    action: ScreenAction
    priority: int = 0


class TimingCfg(_Base):
    screen_poll_ms: int = 450
    after_menu_tap_ms: Pair = (900, 250)
    loading_timeout_s: float = 20
    game_over_wait_ms: int = 1000
    popup_wait_ms: Pair = (800, 200)
    unknown_screen_retries: int = 6
    max_action_retries: int = 4
    relaunch_wait_s: float = 6


class HumanCfg(_Base):
    tap_sigma_frac: float = 0.15
    tap_max_frac: float = 0.30
    handedness_bias: Pair = (0.02, 0.03)
    press_ms: IntPair = (40, 115)
    micro_swipe_prob: float = 0.25
    micro_swipe_frac: float = 0.03
    hesitation_prob: float = 0.04
    hesitation_ms: IntPair = (300, 1100)
    long_pause_prob: float = 0.008
    long_pause_ms: IntPair = (1500, 4000)
    move_order: Literal["human", "rows", "random", "box", "digit"] = "human"

    @field_validator("tap_max_frac")
    @classmethod
    def _bound(cls, v: float) -> float:
        if not 0.0 <= v < 0.5:
            raise ValueError("tap_max_frac doit être dans [0, 0.5[ pour rester dans la cible")
        return v


class WavesCfg(_Base):
    min_wave: int = 1
    fail_rate_shrink: float = 0.15
    shrink_factor: float = 0.5
    grow_factor: float = 1.25
    clean_waves_to_grow: int = 2
    max_corrections_per_cell: int = 3
    cut_on_digit_complete: bool = True
    correction: Literal["overwrite", "erase_then_write"] = "overwrite"


class SpeedTier(_Base):
    label: str
    wave_size: int
    cell_to_key_ms: Pair
    between_moves_ms: Pair
    jitter_frac: float = 0.2
    settle_ms: int = 400
    verify_reads: int = 1


class AdaptiveCfg(_Base):
    start: str = "medium"
    min: str = "very_slow"
    max: str = "very_fast"
    up_after_clean_waves: int = 3
    down_fail_rate: float = 0.2
    adb_latency_ok_ms: float = 90
    adb_latency_bad_ms: float = 250
    render_ok_ms: float = 700
    render_bad_ms: float = 1800
    cpu_load_max: float = 0.9
    cooldown_waves: int = 2
    ceiling_hold_s: float = 900


class SpeedCfg(_Base):
    mode: str = "adaptive"
    order: list[str]
    tiers: dict[str, SpeedTier]
    adaptive: AdaptiveCfg = Field(default_factory=AdaptiveCfg)

    @field_validator("order")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("speed.order ne peut pas être vide")
        return v


class SafetyCfg(_Base):
    consensus_reads: int = 2
    max_rereads: int = 6
    require_unique_solution: bool = True
    solver_timeout_s: float = 10
    max_game_errors: int = 2
    stuck_game_timeout_s: float = 600


class TelemetryCfg(_Base):
    log_level: str = "INFO"
    json_log_path: str = "var/logs/bot.jsonl"
    json_log_max_mb: int = 20
    stats_path: str = "var/state/stats.json"
    save_failure_screens: bool = True
    failure_screens_dir: str = "var/failures"
    failure_screens_max: int = 150


class DashboardCfg(_Base):
    enabled: bool = True
    url: str = ""
    heartbeat_s: float = 5
    backoff_initial_s: float = 1
    backoff_max_s: float = 60
    stream_fps: float = 0.5
    stream_width: int = 360
    stream_quality: int = 60


class AppConfig(_Base):
    machine: MachineCfg = Field(default_factory=MachineCfg)
    workflow: WorkflowCfg = Field(default_factory=WorkflowCfg)
    emulator: EmulatorCfg = Field(default_factory=EmulatorCfg)
    display: DisplayCfg = Field(default_factory=DisplayCfg)
    adb: AdbCfg = Field(default_factory=AdbCfg)
    detection: DetectionCfg = Field(default_factory=DetectionCfg)
    ocr: OcrCfg = Field(default_factory=OcrCfg)
    labels: dict[str, list[str]] = Field(default_factory=dict)
    screens: list[ScreenRule] = Field(default_factory=list)
    timing: TimingCfg = Field(default_factory=TimingCfg)
    human: HumanCfg = Field(default_factory=HumanCfg)
    waves: WavesCfg = Field(default_factory=WavesCfg)
    speed: SpeedCfg
    safety: SafetyCfg = Field(default_factory=SafetyCfg)
    telemetry: TelemetryCfg = Field(default_factory=TelemetryCfg)
    dashboard: DashboardCfg = Field(default_factory=DashboardCfg)

    def resolve_texts(self, texts: list[str]) -> list[str]:
        """Remplace les références `@label` par les libellés de la section `labels`."""
        out: list[str] = []
        for t in texts:
            if t.startswith("@"):
                key = t[1:]
                if key not in self.labels:
                    raise KeyError(f"libellé inconnu : {t}")
                out.extend(self.labels[key])
            else:
                out.append(t)
        return out


def _apply_env(raw: dict[str, Any]) -> dict[str, Any]:
    """Applique les surcharges issues des variables d'environnement (.env)."""
    data = copy.deepcopy(raw)
    env_map = {
        "MACHINE_ID": ("machine", "id"),
        "DASHBOARD_URL": ("dashboard", "url"),
        "ANDROID_BACKEND": ("emulator", "backend"),
        "IMAGE_VARIANT": ("emulator", "image_variant"),
        "REMOTE_ADB_SERIAL": ("emulator", "remote_serial"),
        "ADB_SERIAL": ("adb", "serial"),
    }
    for env, (sec, key) in env_map.items():
        val = os.environ.get(env)
        if val:
            data.setdefault(sec, {})[key] = val
    return data


def load_config(path: Path | str = DEFAULT_CONFIG_PATH, apply_env: bool = True) -> AppConfig:
    """Lit et valide le fichier YAML. Lève `ValueError` avec le détail si invalide."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p} : la racine YAML doit être un dictionnaire")
    return AppConfig.model_validate(_apply_env(raw) if apply_env else raw)


def _diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Liste des chemins pointés dont la valeur diffère entre deux arbres."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in set(a) | set(b):
            out.extend(_diff_paths(a.get(k), b.get(k), f"{prefix}{k}."))
        return out
    return [] if a == b else [prefix.rstrip(".")]


class ConfigManager:
    """Détient la configuration courante et gère le rechargement à chaud."""

    def __init__(self, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cfg = load_config(self.path)
        self._mtime = self.path.stat().st_mtime

    @property
    def cfg(self) -> AppConfig:
        with self._lock:
            return self._cfg

    def raw_yaml(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def _swap(self, new: AppConfig) -> list[str]:
        old_dump = self._cfg.model_dump(mode="json")
        changed = _diff_paths(old_dump, new.model_dump(mode="json"))
        restart = sorted({c for c in changed for r in RESTART_REQUIRED if c == r or c.startswith(r + ".")})
        self._cfg = new
        return restart

    def reload_if_changed(self) -> tuple[bool, list[str]]:
        """Recharge si le fichier a changé. Renvoie (rechargé, clés nécessitant redémarrage)."""
        with self._lock:
            mtime = self.path.stat().st_mtime
            if mtime == self._mtime:
                return False, []
            new = load_config(self.path)
            self._mtime = mtime
            return True, self._swap(new)

    def update_from_yaml(self, text: str) -> list[str]:
        """Valide puis écrit atomiquement un nouveau YAML (édition depuis le dashboard)."""
        raw = yaml.safe_load(text) or {}
        new = AppConfig.model_validate(_apply_env(raw))
        with self._lock:
            tmp = self.path.with_suffix(".yaml.tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)
            self._mtime = self.path.stat().st_mtime
            return self._swap(new)
