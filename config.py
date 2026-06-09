import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

_DEFAULTS: dict = {
    "zip_code": "",
    "slack_webhook": "",
}


def load() -> dict:
    try:
        with open(_CONFIG_PATH, "r") as f:
            data = json.load(f)
            return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def save(settings: dict) -> None:
    with open(_CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)
