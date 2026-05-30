import json
from dataclasses import dataclass, asdict
from pathlib import Path

APP_VERSION = "0.2.0"
SETTINGS_PATH = Path("clustree_settings.json")

CLUSTER_GAP_PRESETS = {
    "Tight - 3 hours": 3,
    "Normal - 12 hours": 12,
    "Travel - 36 hours": 36,
    "Vacation blob - 72 hours": 72,
    "Custom": None,
}

DEFAULT_PRESET_NAME = "Normal - 12 hours"


@dataclass
class AppSettings:
    cluster_gap_preset: str = DEFAULT_PRESET_NAME
    cluster_gap_hours: int = 12
    thumbnail_size: int = 200

    def normalize(self):
        """Keeps settings sane after loading older or hand-edited JSON."""
        if self.cluster_gap_preset in CLUSTER_GAP_PRESETS:
            preset_value = CLUSTER_GAP_PRESETS[self.cluster_gap_preset]
            if preset_value is not None:
                self.cluster_gap_hours = preset_value
        else:
            self.cluster_gap_preset = "Custom"

        try:
            self.cluster_gap_hours = int(self.cluster_gap_hours)
        except (TypeError, ValueError):
            self.cluster_gap_hours = 12

        if self.cluster_gap_hours < 1:
            self.cluster_gap_hours = 1
        elif self.cluster_gap_hours > 168:
            self.cluster_gap_hours = 168

        try:
            self.thumbnail_size = int(self.thumbnail_size)
        except (TypeError, ValueError):
            self.thumbnail_size = 200

        if self.thumbnail_size < 64:
            self.thumbnail_size = 64
        elif self.thumbnail_size > 512:
            self.thumbnail_size = 512

        return self


def load_settings(path: Path = SETTINGS_PATH) -> AppSettings:
    if not path.exists():
        settings = AppSettings().normalize()
        save_settings(settings, path)
        return settings

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        settings = AppSettings(**{**asdict(AppSettings()), **raw}).normalize()
    except Exception:
        settings = AppSettings().normalize()

    save_settings(settings, path)
    return settings


def save_settings(settings: AppSettings, path: Path = SETTINGS_PATH):
    settings.normalize()
    path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
