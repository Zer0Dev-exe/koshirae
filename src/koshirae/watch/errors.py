class WatchError(Exception):
    """Error controlado de la vigilancia (configuración, git, comandos…)."""


class ConfigError(WatchError):
    pass


class CommandError(WatchError):
    pass
