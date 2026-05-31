from config.settings import SETTINGS, Settings


class MapboxConfigurationError(RuntimeError):
    pass


def get_mapbox_token(settings: Settings = SETTINGS) -> str:
    return settings.mapbox_token


def require_mapbox_token(settings: Settings = SETTINGS) -> str:
    token = get_mapbox_token(settings)
    if not token:
        raise MapboxConfigurationError("MAPBOX_TOKEN is required for map rendering.")
    return token
