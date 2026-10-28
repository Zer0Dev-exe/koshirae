import json

import pytest

from koshirae.watch import config as cfg
from koshirae.watch.errors import ConfigError
from koshirae.watch.models import Project, parse_config

SPANISH = """{
  // Intervalo general
  "intervaloPorDefectoSegundos": 30,
  "concurrencia": 3,
  "proyectos": [
    {
      "nombre": "api", "ruta": "/srv/api", "rama": "main", "intervaloSegundos": 10,
      "comandoBuild": "pnpm run build", /* bloque */
      "pm2": { "nombreProceso": "api", "accion": "reload", "iniciarSiEstaApagado": true },
      "url": "http://no-es-comentario"
    }
  ]
}"""


def test_strip_comments_keeps_strings():
    out = json.loads(cfg.strip_comments(SPANISH))
    assert out["proyectos"][0]["url"] == "http://no-es-comentario"


def test_parse_spanish_and_english_keys():
    c = parse_config(json.loads(cfg.strip_comments(SPANISH)))
    p = c.projects[0]
    assert (c.default_interval_seconds, c.concurrency) == (30, 3)
    assert p.pm2.action == "reload" and p.pm2.start_if_not_running is True
    en = parse_config({"projects": [{"name": "x", "path": "/x", "buildCommand": "make"}]})
    assert en.projects[0].build_command == "make" and en.projects[0].install_command == "pnpm install"


@pytest.mark.parametrize("raw", [
    {"concurrencia": 0},
    {"proyectos": [{"nombre": "", "ruta": "/x"}]},
    {"proyectos": [{"nombre": "x", "ruta": "/x", "intervaloSegundos": -1}]},
    {"proyectos": [{"nombre": "x", "ruta": "/x", "pm2": {"nombreProceso": "a", "accion": "kill"}}]},
    {"proyectos": "no"},
])
def test_invalid_configs_rejected(raw):
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_template_created_then_roundtrip():
    first = cfg.load_config()
    assert cfg.config_path().exists() and first.projects[0].enabled is False
    cfg.add_project(Project(name="Bot", path="/srv/bot", build_command="make"))
    assert cfg.add_project(Project(name="bot", path="/srv/bot2")) is True  # mismo nombre sin distinguir mayúsculas
    assert [p.path for p in cfg.load_config().projects if p.name.lower() == "bot"] == ["/srv/bot2"]
    assert cfg.remove_project("BOT") is True and cfg.remove_project("BOT") is False


def test_invalid_json_gives_clear_error():
    cfg.config_dir().mkdir(parents=True)
    (cfg.config_dir() / "config.jsonc").write_text("{ no json")
    with pytest.raises(ConfigError, match="no es un JSON válido"):
        cfg.load_config()
