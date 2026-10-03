# Recursos de interfaz servidos por SICV

Se conservan las versiones que ya usaban las plantillas. El marco general deja de depender de CDN externos para estilos, iconos, JavaScript y tipografía.

- Bootstrap 5.3.0: https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css y https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js. Licencia MIT adjunta. Se quitaron referencias a sourcemaps de depuración que no se distribuyen.
- Bootstrap Icons 1.11.3: https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css y su `font/fonts/bootstrap-icons.woff2`. Licencia MIT adjunta. CSS conserva la fuente WOFF2; se retiró el fallback WOFF no distribuido.
- Inter variable, ejes opsz 14–32 y wght 400–700, subconjunto Latin: CSS obtenido de https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&display=swap el 2026-10-03. Fuente WOFF2 del último bloque Latin de esa respuesta: https://fonts.gstatic.com/s/inter/v20/UcCo3FwrK3iLTcviYwY.woff2. Licencia SIL OFL de https://github.com/google/fonts/blob/main/ofl/inter/OFL.txt adjunta. El archivo incluye caracteres españoles; otros alfabetos recurren a las fuentes de sistema.

WhiteNoise/collectstatic publica y versiona estos archivos en QA. No son bibliotecas nuevas ni un cambio de versión. La redistribución conserva sus licencias. Los mapas externos y otras vistas independientes pueden seguir consultando sus proveedores propios.
