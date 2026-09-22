# Librerías de terceros del portal del técnico

## pdf.js 4.10.38 (Mozilla, Apache-2.0)

`vendor/pdfjs/pdf.min.js` y `vendor/pdfjs/pdf.worker.min.js`, tomados del
build ESM de la versión 4.10.38.

**Está copiado en el repositorio y no se pide a un CDN.** El portal se usa en
el domicilio del abonado, con la conexión que haya; un contrato que no abre
porque un CDN tarda es un contrato que no se firma. Además, lo que se dibuja
en pantalla antes de recoger una firma tiene que venir del mismo sitio que el
resto del sistema.

Los archivos se renombraron de `.mjs` a `.js` a propósito: se cargan como
módulo por `type="module"`, y `.js` lo sirve como JavaScript cualquier
servidor sin configurarle un tipo MIME nuevo.

Es la única librería de terceros del portal, y solo la usa
`contract_signer.js`. El resto de la interfaz sigue sin dependencias.

Para actualizarla, se sustituyen los dos archivos por los de la nueva
versión —siempre los dos juntos: pdf.js exige que el visor y su worker sean
de la misma— y se comprueba que el contrato se abre y se firma.
