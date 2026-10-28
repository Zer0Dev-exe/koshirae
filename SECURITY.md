# Política de seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usa el reporte privado de GitHub:
<https://github.com/Zer0Dev-exe/koshirae/security/advisories/new>

Incluye una descripción, pasos para reproducirlo y el impacto. Se responderá lo antes posible.

## Alcance

Koshirae guarda tokens de acceso (GitHub, GitLab, Bitbucket, MongoDB Atlas) y claves de IA en tu directorio de configuración local. Son de especial interés: fugas de credenciales en logs o salida, ejecución de comandos no deseada y operaciones destructivas sin confirmación.

## Versiones soportadas

Solo la última versión publicada.
