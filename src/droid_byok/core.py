#!/usr/bin/env python3
"""droid-byok: interactive CLI for Factory Droid BYOK provider/model config.

Inspired by cc-switch CLI: default full-screen TUI, plus non-interactive subcommands.
Manages ~/.factory/settings.json customModels and session defaults.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError:  # pragma: no cover
    print("Missing dependency: rich. Install with: pip install rich", file=sys.stderr)
    sys.exit(1)


APP_NAME = "droid-byok"
VERSION = "0.3.1"
FACTORY_DIR = Path(os.environ.get("FACTORY_HOME", Path.home() / ".factory"))
SETTINGS_PATH = Path(os.environ.get("DROID_SETTINGS", FACTORY_DIR / "settings.json"))
STORE_PATH = Path(os.environ.get("DROID_BYOK_STORE", FACTORY_DIR / "droid-byok" / "providers.json"))
BACKUP_DIR = Path(os.environ.get("DROID_BYOK_BACKUP_DIR", FACTORY_DIR / "droid-byok" / "backups"))

PROVIDERS = (
    "generic-chat-completion-api",
    "anthropic",
    "openai",
)

console = Console()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def mask_secret(value: str | None, keep: int = 4) -> str:
    if not value:
        return "-"
    if value.startswith("${") and value.endswith("}"):
        return value
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "provider"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {
            "customModels": [],
            "sessionDefaultSettings": {},
        }
    data = load_json(SETTINGS_PATH, {})
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid settings file: {SETTINGS_PATH}")
    data.setdefault("customModels", [])
    data.setdefault("sessionDefaultSettings", {})
    if not isinstance(data["customModels"], list):
        raise SystemExit("settings.customModels must be a list")
    if not isinstance(data["sessionDefaultSettings"], dict):
        raise SystemExit("settings.sessionDefaultSettings must be an object")
    return data


def write_settings(data: dict[str, Any], *, backup: bool = True) -> Path | None:
    ensure_parent(SETTINGS_PATH)
    backup_path = None
    if backup and SETTINGS_PATH.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now_iso()
        backup_path = BACKUP_DIR / f"settings-{stamp}.json"
        n = 1
        while backup_path.exists():
            backup_path = BACKUP_DIR / f"settings-{stamp}-{n}.json"
            n += 1
        shutil.copy2(SETTINGS_PATH, backup_path)
        os.chmod(backup_path, 0o600)
    atomic_write_json(SETTINGS_PATH, data)
    return backup_path


def reindex_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, m in enumerate(models):
        item = dict(m)
        model_name = str(item.get("model") or f"model-{i}")
        base_id = f"custom:{model_name}"
        cid = str(item.get("id") or "")
        if not cid.startswith("custom:") or cid in used:
            n = 0
            while f"{base_id}-{n}" in used:
                n += 1
            cid = f"{base_id}-{n}"
        item["id"] = cid
        item["index"] = i
        used.add(cid)
        out.append(item)
    return out


def current_default_model(settings: dict[str, Any]) -> str | None:
    return settings.get("sessionDefaultSettings", {}).get("model")


def configured_model_ids(settings: dict[str, Any]) -> set[str]:
    return {str(m.get("id")) for m in settings.get("customModels") or [] if m.get("id")}


def invalid_model_refs(settings: dict[str, Any]) -> list[tuple[str, str]]:
    ids = configured_model_ids(settings)
    refs: list[tuple[str, str | None]] = [
        ("sessionDefaultSettings.model", settings.get("sessionDefaultSettings", {}).get("model")),
        ("missionOrchestratorModel", settings.get("missionOrchestratorModel")),
    ]
    mission = settings.get("missionModelSettings")
    if isinstance(mission, dict):
        refs.extend(
            [
                ("missionModelSettings.workerModel", mission.get("workerModel")),
                ("missionModelSettings.validationWorkerModel", mission.get("validationWorkerModel")),
            ]
        )
    return [(path, ref) for path, ref in refs if ref and ref not in ids]


def resolve_model_ref(settings: dict[str, Any], model_ref: str | None) -> str | None:
    if not model_ref:
        return None
    models = settings.get("customModels") or []
    ids = {m.get("id"): m for m in models}
    names = {m.get("model"): m for m in models}
    displays = {m.get("displayName"): m for m in models}
    target = ids.get(model_ref) or names.get(model_ref) or displays.get(model_ref)
    if not target:
        return None
    return str(target.get("id") or "")


def set_default_model(settings: dict[str, Any], model_id: str, *, sync_mission: bool = True) -> None:
    sds = settings.setdefault("sessionDefaultSettings", {})
    sds["model"] = model_id
    if not sync_mission:
        return

    should_sync_mission = (
        isinstance(settings.get("missionModelSettings"), dict)
        or "missionOrchestratorModel" in settings
        or settings.get("hasSeenMissionOnboarding") is True
    )
    if not should_sync_mission:
        return

    mission = settings.get("missionModelSettings")
    if not isinstance(mission, dict):
        mission = {}
        settings["missionModelSettings"] = mission
    mission["workerModel"] = model_id
    mission["validationWorkerModel"] = model_id
    settings["missionOrchestratorModel"] = model_id


def clear_default_model(settings: dict[str, Any]) -> None:
    sds = settings.setdefault("sessionDefaultSettings", {})
    sds.pop("model", None)
    mission = settings.get("missionModelSettings")
    if isinstance(mission, dict):
        mission.pop("workerModel", None)
        mission.pop("validationWorkerModel", None)
    settings.pop("missionOrchestratorModel", None)


def repair_default_model(settings: dict[str, Any], preferred: str | None = None) -> str | None:
    target = resolve_model_ref(settings, preferred)
    if not target:
        current = current_default_model(settings)
        if current in configured_model_ids(settings):
            target = str(current)
    if not target:
        models = settings.get("customModels") or []
        if models:
            target = str(models[0].get("id") or "")
    if target:
        set_default_model(settings, target)
        return target
    clear_default_model(settings)
    return None


DEFAULT_STORE: dict[str, Any] = {
    "version": 1,
    "providers": {},
    "activeProviderId": None,
}


@dataclass
class ProviderProfile:
    id: str
    name: str
    base_url: str
    api_key: str
    provider: str = "generic-chat-completion-api"
    models: list[dict[str, Any]] | None = None
    notes: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "baseUrl": self.base_url,
            "apiKey": self.api_key,
            "provider": self.provider,
            "models": self.models or [],
            "notes": self.notes,
            "updatedAt": self.updated_at or datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderProfile":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or data.get("id") or ""),
            base_url=str(data.get("baseUrl") or ""),
            api_key=str(data.get("apiKey") or ""),
            provider=str(data.get("provider") or "generic-chat-completion-api"),
            models=list(data.get("models") or []),
            notes=str(data.get("notes") or ""),
            updated_at=str(data.get("updatedAt") or ""),
        )


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or STORE_PATH
        self.data = load_json(self.path, DEFAULT_STORE)
        if "providers" not in self.data:
            self.data = copy.deepcopy(DEFAULT_STORE)

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    def list_providers(self) -> list[ProviderProfile]:
        items = []
        for pid, raw in self.data.get("providers", {}).items():
            if isinstance(raw, dict):
                raw = {**raw, "id": raw.get("id") or pid}
                items.append(ProviderProfile.from_dict(raw))
        items.sort(key=lambda p: p.name.lower())
        return items

    def get(self, provider_id: str) -> ProviderProfile | None:
        raw = self.data.get("providers", {}).get(provider_id)
        if not raw:
            return None
        raw = {**raw, "id": raw.get("id") or provider_id}
        return ProviderProfile.from_dict(raw)

    def upsert(self, profile: ProviderProfile) -> None:
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.data.setdefault("providers", {})[profile.id] = profile.to_dict()
        self.save()

    def delete(self, provider_id: str) -> bool:
        providers = self.data.get("providers", {})
        if provider_id not in providers:
            return False
        del providers[provider_id]
        if self.data.get("activeProviderId") == provider_id:
            self.data["activeProviderId"] = None
        self.save()
        return True

    def set_active(self, provider_id: str | None) -> None:
        self.data["activeProviderId"] = provider_id
        self.save()

    def active_id(self) -> str | None:
        return self.data.get("activeProviderId")


def models_from_profile(profile: ProviderProfile) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    if profile.models:
        for m in profile.models:
            model_id = str(m.get("model") or "").strip()
            if not model_id:
                continue
            entry = {
                "model": model_id,
                "displayName": str(m.get("displayName") or model_id),
                "baseUrl": str(m.get("baseUrl") or profile.base_url).rstrip("/"),
                "apiKey": str(m.get("apiKey") or profile.api_key),
                "provider": str(m.get("provider") or profile.provider),
                "maxOutputTokens": int(m.get("maxOutputTokens") or 16384),
                "noImageSupport": bool(m.get("noImageSupport", False)),
            }
            if m.get("id"):
                entry["id"] = str(m["id"])
            if m.get("maxContextLimit") is not None:
                entry["maxContextLimit"] = int(m["maxContextLimit"])
            if m.get("extraArgs"):
                entry["extraArgs"] = m["extraArgs"]
            if m.get("extraHeaders"):
                entry["extraHeaders"] = m["extraHeaders"]
            models.append(entry)
    return models


def model_signature(model: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(model.get("model") or ""),
        str(model.get("baseUrl") or "").rstrip("/"),
        str(model.get("provider") or ""),
        str(model.get("apiKey") or ""),
    )


def next_custom_model_id(model_name: str, used: set[str]) -> str:
    base_id = f"custom:{model_name}"
    n = 0
    while f"{base_id}-{n}" in used:
        n += 1
    return f"{base_id}-{n}"


def find_live_model_index(
    live_models: list[dict[str, Any]],
    wanted: dict[str, Any],
    consumed: set[int],
) -> int | None:
    wanted_id = str(wanted.get("id") or "")
    if wanted_id:
        for i, model in enumerate(live_models):
            if i not in consumed and str(model.get("id") or "") == wanted_id:
                return i

    wanted_sig = model_signature(wanted)
    for i, model in enumerate(live_models):
        if i not in consumed and model_signature(model) == wanted_sig:
            return i
    return None


def profile_models_from_live(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = (
        "id",
        "model",
        "displayName",
        "baseUrl",
        "apiKey",
        "provider",
        "maxOutputTokens",
        "maxContextLimit",
        "noImageSupport",
        "extraArgs",
        "extraHeaders",
    )
    return [{k: m[k] for k in keep if k in m and m[k] is not None} for m in models]


def upsert_provider_models(
    settings: dict[str, Any],
    profile: ProviderProfile,
) -> tuple[int, int, list[dict[str, Any]]]:
    wanted_models = models_from_profile(profile)
    if not wanted_models:
        raise SystemExit(f"Provider '{profile.id}' has no models. Add models first.")

    live_models = [dict(m) for m in settings.get("customModels") or [] if isinstance(m, dict)]
    consumed: set[int] = set()
    used_ids = {str(m.get("id")) for m in live_models if m.get("id")}
    provider_live_models: list[dict[str, Any]] = []
    added = 0
    updated = 0

    for wanted in wanted_models:
        idx = find_live_model_index(live_models, wanted, consumed)
        if idx is None:
            cid = str(wanted.get("id") or "")
            if not cid.startswith("custom:") or cid in used_ids:
                cid = next_custom_model_id(str(wanted.get("model") or "model"), used_ids)
            wanted["id"] = cid
            used_ids.add(cid)
            live_models.append(dict(wanted))
            provider_live_models.append(live_models[-1])
            added += 1
            continue

        consumed.add(idx)
        existing_id = str(live_models[idx].get("id") or wanted.get("id") or "")
        live_models[idx].update(wanted)
        if existing_id:
            live_models[idx]["id"] = existing_id
        provider_live_models.append(live_models[idx])
        updated += 1

    settings["customModels"] = reindex_models(live_models)
    refreshed_by_id = {m.get("id"): m for m in settings["customModels"]}
    refreshed = [refreshed_by_id.get(m.get("id"), m) for m in provider_live_models]
    profile.models = profile_models_from_live(refreshed)
    return added, updated, refreshed


def provider_removal_matchers(profile: ProviderProfile) -> tuple[set[str], set[tuple[str, str, str, str]]]:
    models = models_from_profile(profile)
    ids = {str(m.get("id")) for m in models if m.get("id")}
    signatures = {model_signature(m) for m in models if not m.get("id")}
    return ids, signatures


def remove_provider_models(profile: ProviderProfile, *, delete_store: bool = True) -> dict[str, Any]:
    settings = read_settings()
    live_models = [dict(m) for m in settings.get("customModels") or [] if isinstance(m, dict)]
    ids, signatures = provider_removal_matchers(profile)

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for model in live_models:
        mid = str(model.get("id") or "")
        if (mid and mid in ids) or model_signature(model) in signatures:
            removed.append(model)
        else:
            kept.append(model)

    settings["customModels"] = reindex_models(kept)
    removed_ids = {str(m.get("id") or "") for m in removed}
    if current_default_model(settings) in removed_ids or invalid_model_refs(settings):
        repair_default_model(settings)

    backup = write_settings(settings)
    store = Store()
    if delete_store:
        store.delete(profile.id)
    return {
        "removed": len(removed),
        "models": len(settings["customModels"]),
        "default": current_default_model(settings),
        "backup": str(backup) if backup else None,
    }


def apply_provider(
    profile: ProviderProfile,
    *,
    set_default: bool = True,
    default_model: str | None = None,
) -> dict[str, Any]:
    settings = read_settings()
    added, updated, provider_models = upsert_provider_models(settings, profile)
    if set_default:
        preferred = default_model or (str(provider_models[0].get("id") or "") if provider_models else None)
        repair_default_model(settings, preferred)
    elif current_default_model(settings) not in configured_model_ids(settings) or invalid_model_refs(settings):
        repair_default_model(settings)

    backup = write_settings(settings)
    store = Store()
    store.upsert(profile)
    if set_default:
        store.set_active(profile.id)
    return {
        "models": len(settings["customModels"]),
        "provider_models": len(provider_models),
        "added": added,
        "updated": updated,
        "default": current_default_model(settings),
        "backup": str(backup) if backup else None,
    }


def import_live_as_provider(provider_id: str | None = None, name: str | None = None) -> ProviderProfile:
    settings = read_settings()
    models = settings.get("customModels") or []
    if not models:
        raise SystemExit("No customModels found in settings.json")

    first = models[0]
    base_url = str(first.get("baseUrl") or "")
    api_key = str(first.get("apiKey") or "")
    provider = str(first.get("provider") or "generic-chat-completion-api")

    pid = provider_id or slugify(name or Path(base_url).name or "live-import")
    pname = name or pid

    store = Store()
    if store.get(pid):
        n = 2
        while store.get(f"{pid}-{n}"):
            n += 1
        pid = f"{pid}-{n}"

    model_list = []
    for m in models:
        model_list.append(
            {
                "id": m.get("id"),
                "model": m.get("model"),
                "displayName": m.get("displayName") or m.get("model"),
                "baseUrl": m.get("baseUrl") or base_url,
                "apiKey": m.get("apiKey") or api_key,
                "provider": m.get("provider") or provider,
                "maxOutputTokens": m.get("maxOutputTokens", 16384),
                "maxContextLimit": m.get("maxContextLimit"),
                "noImageSupport": m.get("noImageSupport", False),
                "extraArgs": m.get("extraArgs"),
                "extraHeaders": m.get("extraHeaders"),
            }
        )

    profile = ProviderProfile(
        id=pid,
        name=pname,
        base_url=base_url,
        api_key=api_key,
        provider=provider,
        models=model_list,
        notes="Imported from live ~/.factory/settings.json",
    )
    store.upsert(profile)
    store.set_active(pid)
    return profile


def set_session_default(model_ref: str) -> str:
    settings = read_settings()
    models = settings.get("customModels") or []
    if not models:
        raise SystemExit("No customModels configured")
    ids = {m.get("id"): m for m in models}
    names = {m.get("model"): m for m in models}
    displays = {m.get("displayName"): m for m in models}
    target = ids.get(model_ref) or names.get(model_ref) or displays.get(model_ref)
    if not target:
        raise SystemExit(f"Model not found: {model_ref}")
    set_default_model(settings, target["id"])
    write_settings(settings)
    return target["id"]


class FetchModelsError(RuntimeError):
    """Raised when an upstream model catalog cannot be fetched or parsed."""


def _resolved_api_key(api_key: str) -> str:
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", api_key.strip())
    if not match:
        return api_key.strip()
    env_name = match.group(1)
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise FetchModelsError(f"Environment variable {env_name} is not set")
    return value


def _models_endpoint_candidates(base_url: str) -> list[str]:
    base = base_url.strip().rstrip("/")
    if not base:
        raise FetchModelsError("Base URL is empty")
    parsed = urlparse.urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FetchModelsError(f"Invalid Base URL: {base_url}")
    path = parsed.path.rstrip("/")

    def endpoint(endpoint_path: str) -> str:
        return urlparse.urlunsplit(
            (parsed.scheme, parsed.netloc, endpoint_path, parsed.query, "")
        )

    if path.endswith("/models"):
        return [endpoint(path)]

    candidates = [endpoint(f"{path}/models")]
    if not path.endswith("/v1"):
        candidates.append(endpoint(f"{path}/v1/models"))
    return candidates


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _normalize_upstream_models(payload: Any) -> list[dict[str, Any]]:
    raw_models: Any = payload
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            if isinstance(payload.get(key), list):
                raw_models = payload[key]
                break
        else:
            raise FetchModelsError("Response does not contain a model list")
    if not isinstance(raw_models, list):
        raise FetchModelsError("Model response must be a list")

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_models:
        if isinstance(raw, str):
            model_id = raw.strip()
            display_name = model_id
            item: dict[str, Any] = {}
        elif isinstance(raw, dict):
            item = raw
            model_id = str(
                item.get("id")
                or item.get("model")
                or item.get("model_id")
                or item.get("name")
                or ""
            ).strip()
            display_name = str(
                item.get("displayName")
                or item.get("display_name")
                or item.get("name")
                or model_id
            ).strip()
        else:
            continue
        if not model_id or model_id in seen:
            continue

        model: dict[str, Any] = {
            "model": model_id,
            "displayName": display_name or model_id,
            "maxOutputTokens": 16384,
        }
        context_limit = _positive_int(
            item.get("context_length")
            or item.get("context_window")
            or item.get("max_context_length")
            or item.get("maxContextLimit")
        )
        top_provider = item.get("top_provider")
        if isinstance(top_provider, dict):
            output_limit = _positive_int(
                top_provider.get("max_completion_tokens")
                or top_provider.get("max_output_tokens")
            )
        else:
            output_limit = None
        output_limit = output_limit or _positive_int(
            item.get("max_output_tokens")
            or item.get("max_completion_tokens")
            or item.get("maxOutputTokens")
        )
        if context_limit is not None:
            model["maxContextLimit"] = context_limit
        if output_limit is not None:
            model["maxOutputTokens"] = output_limit
        models.append(model)
        seen.add(model_id)
    return models


def fetch_upstream_models(
    profile: ProviderProfile,
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Fetch and normalize the model catalog exposed by a provider."""
    api_key = _resolved_api_key(profile.api_key)
    headers = {
        "Accept": "application/json",
        "User-Agent": f"{APP_NAME}/{VERSION}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        if profile.provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"

    errors: list[str] = []
    for url in _models_endpoint_candidates(profile.base_url):
        try:
            req = urlrequest.Request(url, headers=headers, method="GET")
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                body = resp.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise FetchModelsError("Model response exceeds 4 MiB")
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise FetchModelsError("Upstream returned invalid JSON") from exc
                models = _normalize_upstream_models(payload)
                return {
                    "url": url,
                    "status": getattr(resp, "status", 200),
                    "models": models,
                }
        except FetchModelsError as exc:
            errors.append(f"{url}: {exc}")
        except urlerror.HTTPError as exc:
            if exc.code in {401, 403}:
                raise FetchModelsError(f"Authentication failed (HTTP {exc.code})") from exc
            errors.append(f"{url}: HTTP {exc.code}")
        except urlerror.URLError as exc:
            errors.append(f"{url}: {exc.reason}")
        except TimeoutError:
            errors.append(f"{url}: timed out")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise FetchModelsError("; ".join(errors) or "Unable to fetch upstream models")


def probe_endpoint(base_url: str, api_key: str, timeout: float = 8.0) -> dict[str, Any]:
    base = base_url.rstrip("/")
    candidates = [f"{base}/models", base]
    headers = {"User-Agent": f"{APP_NAME}/{VERSION}"}
    if api_key and not api_key.startswith("${"):
        headers["Authorization"] = f"Bearer {api_key}"

    last_err = None
    for url in candidates:
        try:
            req = urlrequest.Request(url, headers=headers, method="GET")
            t0 = time.perf_counter()
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                elapsed = (time.perf_counter() - t0) * 1000
                body = resp.read(200)
                return {
                    "ok": True,
                    "url": url,
                    "status": getattr(resp, "status", 200),
                    "ms": round(elapsed, 1),
                    "snippet": body[:80].decode("utf-8", errors="replace"),
                }
        except urlerror.HTTPError as e:
            if e.code in (401, 403, 404, 405):
                return {
                    "ok": True,
                    "url": url,
                    "status": e.code,
                    "ms": None,
                    "snippet": f"HTTP {e.code} (reachable)",
                }
            last_err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
    return {"ok": False, "error": last_err or "unknown error"}


def render_providers_table(store: Store, settings: dict[str, Any] | None = None) -> Table:
    settings = settings or read_settings()
    default = current_default_model(settings)
    active = store.active_id()
    table = Table(
        title="Providers",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("", width=2)
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("API URL")
    table.add_column("Models", justify="right")
    table.add_column("Provider")
    table.add_column("Key")

    providers = store.list_providers()
    if not providers:
        table.add_row("-", "(empty)", "use: provider add / import-live", "-", "-", "-", "-")
        return table

    for p in providers:
        mark = "✓" if p.id == active else ""
        table.add_row(
            mark,
            p.id,
            p.name,
            p.base_url or "-",
            str(len(p.models or [])),
            p.provider,
            mask_secret(p.api_key),
        )
    console.print(f"[dim]settings:[/dim] {SETTINGS_PATH}")
    console.print(f"[dim]default model:[/dim] {default or '-'}")
    console.print(f"[dim]active provider:[/dim] {active or '-'}")
    return table


def render_live_models_table(settings: dict[str, Any] | None = None) -> Table:
    settings = settings or read_settings()
    default = current_default_model(settings)
    table = Table(title="Live customModels (settings.json)", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("", width=2)
    table.add_column("#", justify="right")
    table.add_column("ID")
    table.add_column("Model")
    table.add_column("Display")
    table.add_column("Base URL")
    table.add_column("Provider")
    table.add_column("Key")

    models = settings.get("customModels") or []
    if not models:
        table.add_row("-", "-", "(none)", "-", "-", "-", "-", "-")
        return table
    for i, m in enumerate(models):
        mid = str(m.get("id") or "")
        mark = "✓" if mid == default else ""
        table.add_row(
            mark,
            str(i),
            mid,
            str(m.get("model") or ""),
            str(m.get("displayName") or ""),
            str(m.get("baseUrl") or ""),
            str(m.get("provider") or ""),
            mask_secret(str(m.get("apiKey") or "")),
        )
    return table


def print_help() -> None:
    console.print(
        Panel(
            f"""[bold]{APP_NAME}[/bold] manages Factory Droid BYOK configs.

[bold cyan]Interactive TUI[/bold cyan]
  {APP_NAME}                 # full-screen TUI (default)
  {APP_NAME} interactive
  {APP_NAME} tui

[bold cyan]Provider commands[/bold cyan] (Droid multi-model style)
  {APP_NAME} provider list
  {APP_NAME} provider current
  {APP_NAME} provider add --id doro --name doro --base-url https://us.doro.lol/v1 --api-key KEY --model grok-4.5
  {APP_NAME} provider delete <id>      # remove provider models from settings.json
  {APP_NAME} provider import-live [--id live] [--name live]
  {APP_NAME} provider default <id> [--model <model>] # set default only; keep other customModels
  {APP_NAME} provider switch <id> [--model <model>]  # compatibility alias for default
  {APP_NAME} use <id>                                # shortcut: set default
  {APP_NAME} provider speedtest [id]

[bold cyan]Live settings[/bold cyan]
  {APP_NAME} models list
  {APP_NAME} models default <id|name>
  {APP_NAME} models show

[bold cyan]TUI keys[/bold cyan]
  ↑/↓ j/k  move · Enter/u default · a add · e edit · d delete
  i import · m models · t speedtest · r refresh · ? help · q quit

[bold cyan]Paths[/bold cyan]
  settings: {SETTINGS_PATH}
  store:    {STORE_PATH}
  backups:  {BACKUP_DIR}
""",
            title="Help",
            border_style="cyan",
        )
    )


def run_interactive() -> int:
    try:
        here = Path(__file__).resolve().parent
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
        from .tui import run_tui

        return run_tui()
    except ImportError as e:
        console.print(f"[red]TUI dependency missing:[/red] {e}")
        console.print("Install with: [bold]pip install textual rich[/bold]")
        console.print("You can still use non-interactive commands, e.g. provider list")
        print_help()
        return 1


def cmd_provider_list(_: argparse.Namespace) -> int:
    store = Store()
    console.print(render_providers_table(store))
    return 0


def cmd_provider_current(_: argparse.Namespace) -> int:
    store = Store()
    settings = read_settings()
    active = store.active_id()
    default = current_default_model(settings)
    if not active:
        console.print("[yellow]No active provider[/yellow]")
    else:
        p = store.get(active)
        if p:
            console.print(f"[bold]{p.id}[/bold]  {p.name}")
            console.print(f"  url: {p.base_url}")
            console.print(f"  models: {len(p.models or [])}")
            console.print(f"  key: {mask_secret(p.api_key)}")
        else:
            console.print(f"[yellow]active id set but missing: {active}[/yellow]")
    console.print(f"default model: {default or '-'}")
    return 0


def cmd_provider_add(args: argparse.Namespace) -> int:
    store = Store()
    pid = args.id or slugify(args.name or "")
    if not pid:
        raise SystemExit("--id or --name required")
    if store.get(pid):
        raise SystemExit(f"Provider already exists: {pid}")
    if not args.base_url:
        raise SystemExit("--base-url required")
    if not args.api_key:
        raise SystemExit("--api-key required")
    models = []
    for m in args.model or []:
        if "=" in m:
            mid, disp = m.split("=", 1)
        else:
            mid, disp = m, m
        models.append({"model": mid, "displayName": disp, "maxOutputTokens": args.max_output_tokens})
    profile = ProviderProfile(
        id=pid,
        name=args.name or pid,
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        provider=args.provider,
        models=models,
        notes=args.notes or "",
    )
    result = apply_provider(profile, set_default=args.apply, default_model=args.default_model)
    console.print(
        f"[green]Added[/green] {pid} · providerModels={result['provider_models']} "
        f"· added={result['added']} · updated={result['updated']}"
    )
    if args.apply:
        console.print(f"[green]Default set[/green] {result['default']}")
    return 0


def cmd_provider_delete(args: argparse.Namespace) -> int:
    store = Store()
    profile = store.get(args.id)
    if not profile:
        raise SystemExit(f"Not found: {args.id}")
    result = remove_provider_models(profile, delete_store=True)
    console.print(
        f"[green]Deleted[/green] {args.id} · removed={result['removed']} · remainingModels={result['models']}"
    )
    if result["backup"]:
        console.print(f"[dim]backup: {result['backup']}[/dim]")
    return 0


def cmd_provider_switch(args: argparse.Namespace) -> int:
    store = Store()
    profile = store.get(args.id)
    if not profile:
        raise SystemExit(f"Not found: {args.id}")
    result = apply_provider(profile, default_model=args.model)
    console.print(
        f"[green]Default switched[/green] to {profile.id} · totalModels={result['models']} · default={result['default']}"
    )
    if result["backup"]:
        console.print(f"[dim]backup: {result['backup']}[/dim]")
    return 0


def cmd_provider_import_live(args: argparse.Namespace) -> int:
    profile = import_live_as_provider(provider_id=args.id, name=args.name)
    console.print(f"[green]Imported[/green] {profile.id} with {len(profile.models or [])} models")
    return 0


def cmd_provider_speedtest(args: argparse.Namespace) -> int:
    store = Store()
    if args.id:
        p = store.get(args.id)
        if not p:
            raise SystemExit(f"Not found: {args.id}")
        targets = [p]
    else:
        targets = store.list_providers()
    table = Table(title="Speedtest", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("OK")
    table.add_column("Status")
    table.add_column("ms", justify="right")
    table.add_column("Note")
    for p in targets:
        res = probe_endpoint(p.base_url, p.api_key)
        table.add_row(
            p.id,
            "yes" if res.get("ok") else "no",
            str(res.get("status") or "-"),
            str(res.get("ms") if res.get("ms") is not None else "-"),
            str(res.get("snippet") or res.get("error") or ""),
        )
    console.print(table)
    return 0


def cmd_provider_show(args: argparse.Namespace) -> int:
    store = Store()
    p = store.get(args.id)
    if not p:
        raise SystemExit(f"Not found: {args.id}")
    console.print(Panel.fit(f"[bold]{p.id}[/bold]  {p.name}", border_style="cyan"))
    console.print(f"url:      {p.base_url}")
    console.print(f"provider: {p.provider}")
    console.print(f"key:      {mask_secret(p.api_key)}")
    console.print(f"notes:    {p.notes or '-'}")
    console.print(f"updated:  {p.updated_at or '-'}")
    t = Table(box=box.SIMPLE, header_style="bold")
    t.add_column("Model")
    t.add_column("Display")
    t.add_column("maxOut")
    for m in p.models or []:
        t.add_row(str(m.get("model")), str(m.get("displayName")), str(m.get("maxOutputTokens", "")))
    console.print(t)
    return 0


def cmd_models_list(_: argparse.Namespace) -> int:
    console.print(render_live_models_table())
    return 0


def cmd_models_default(args: argparse.Namespace) -> int:
    mid = set_session_default(args.model)
    console.print(f"[green]Default model set:[/green] {mid}")
    return 0


def cmd_models_show(_: argparse.Namespace) -> int:
    console.print(f"settings: {SETTINGS_PATH}")
    console.print(f"exists:   {SETTINGS_PATH.exists()}")
    console.print(render_live_models_table())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Full-screen TUI + CLI for Factory Droid BYOK provider/model configuration.",
    )
    p.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {VERSION}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")

    s_int = sub.add_parser("interactive", help="Enter full-screen TUI")
    s_int.set_defaults(func=lambda _a: run_interactive())

    s_tui = sub.add_parser("tui", help="Enter full-screen TUI")
    s_tui.set_defaults(func=lambda _a: run_interactive())

    s_use = sub.add_parser("use", help="Set provider as default (shortcut)")
    s_use.add_argument("id", help="Provider ID")
    s_use.add_argument("--model", help="Default model name/id")
    s_use.set_defaults(func=cmd_provider_switch)

    s_prov = sub.add_parser("provider", help="Manage providers")
    psub = s_prov.add_subparsers(dest="provider_cmd", required=True)

    c = psub.add_parser("list", help="List providers")
    c.set_defaults(func=cmd_provider_list)

    c = psub.add_parser("current", help="Show current provider")
    c.set_defaults(func=cmd_provider_current)

    c = psub.add_parser("show", help="Show provider details")
    c.add_argument("id")
    c.set_defaults(func=cmd_provider_show)

    c = psub.add_parser("add", help="Add provider (non-interactive)")
    c.add_argument("--id")
    c.add_argument("--name")
    c.add_argument("--base-url", required=True)
    c.add_argument("--api-key", required=True)
    c.add_argument("--provider", default="generic-chat-completion-api", choices=list(PROVIDERS))
    c.add_argument("--model", action="append", help="Model id or model=DisplayName (repeatable)")
    c.add_argument("--max-output-tokens", type=int, default=16384)
    c.add_argument("--notes", default="")
    c.add_argument("--apply", action="store_true", help="Also set this provider as the default after adding")
    c.add_argument("--default-model", help="Default model when --apply")
    c.set_defaults(func=cmd_provider_add)

    c = psub.add_parser("delete", help="Delete provider")
    c.add_argument("id")
    c.set_defaults(func=cmd_provider_delete)

    c = psub.add_parser("default", help="Set provider as default")
    c.add_argument("id")
    c.add_argument("--model", help="Default model name/id")
    c.set_defaults(func=cmd_provider_switch)

    c = psub.add_parser("switch", help="Set provider as default (compatibility alias)")
    c.add_argument("id")
    c.add_argument("--model", help="Default model name/id")
    c.set_defaults(func=cmd_provider_switch)

    c = psub.add_parser("import-live", help="Import live settings.json as a provider profile")
    c.add_argument("--id")
    c.add_argument("--name")
    c.set_defaults(func=cmd_provider_import_live)

    c = psub.add_parser("speedtest", help="Probe provider endpoints")
    c.add_argument("id", nargs="?")
    c.set_defaults(func=cmd_provider_speedtest)

    s_models = sub.add_parser("models", help="Manage live customModels / default")
    msub = s_models.add_subparsers(dest="models_cmd", required=True)

    c = msub.add_parser("list", help="List live customModels")
    c.set_defaults(func=cmd_models_list)

    c = msub.add_parser("show", help="Show live settings summary")
    c.set_defaults(func=cmd_models_show)

    c = msub.add_parser("default", help="Set session default model")
    c.add_argument("model", help="Model id, model name, or displayName")
    c.set_defaults(func=cmd_models_default)

    s_help = sub.add_parser("help", help="Show cheatsheet")
    s_help.set_defaults(func=lambda _a: (print_help(), 0)[1])

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        return run_interactive()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return run_interactive()
    func: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 1
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
        return 130
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        if getattr(args, "verbose", False):
            console.print_exception()
        return 1


if __name__ == "__main__":
    sys.exit(main())
