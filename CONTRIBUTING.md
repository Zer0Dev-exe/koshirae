# Contribuir a Koshirae

¡Gracias por querer ayudar!

## Flujo de trabajo

`main` está protegida: no se hace push directo, todo entra por pull request.

1. Haz fork o crea una rama desde `main` (`feat/lo-que-sea`, `fix/lo-que-sea`).
2. Prepara el entorno:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev,ai]"
   ```
3. Haz tus cambios y añade o actualiza tests en `tests/<subcomando>/`.
4. Ejecuta `pytest` y comprueba que pasa todo.
5. Abre el pull request explicando qué cambia y por qué. Se exige historial lineal (rebase o squash) y resolver todas las conversaciones.

## Convenciones

- Python ≥ 3.11, con `from __future__ import annotations`.
- Sigue el estilo del código vecino: nombres, docstrings y comentarios en español.
- CLI con Typer y salida con Rich; las operaciones destructivas deben pedir confirmación (respetando `--yes`).
- Mensajes de commit claros y en imperativo, p. ej. `Añade koshirae watch logs`.

## Reportar errores y proponer ideas

Usa las plantillas de [Issues](https://github.com/Zer0Dev-exe/koshirae/issues/new/choose). Incluye versión (`koshirae --version`), sistema operativo y los pasos para reproducirlo. Elimina tokens y credenciales de cualquier salida que pegues.
