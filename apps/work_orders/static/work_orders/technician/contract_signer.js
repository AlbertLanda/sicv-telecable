/*
 * El contrato del abonado, abierto sobre la orden de instalación para
 * firmarlo en el domicilio.
 *
 * Es el documento entero y no un resumen: el abonado firma lo que puede leer,
 * así que el visor trae el PDF tal cual sale de SICV, con zoom y
 * desplazamiento, y la firma se recoge encima de él y no en otra pantalla.
 *
 * Firmar son tres pasos, y son tres a propósito:
 *
 *   dibujar  →  colocar  →  aceptar
 *
 * El trazo se dibuja en un recuadro aparte, porque firmar con el dedo sobre
 * un contrato reducido a pantalla de móvil no sale legible. Después aparece
 * sobre la hoja, ya a su tamaño, y se puede mover y estirar hasta dejarlo
 * donde toca. Nace sobre la línea de EL ABONADO -el hueco que el propio PDF
 * declara al dibujarse-, así que aceptar sin tocar nada deja la firma bien
 * puesta; moverla es para ajustar, no para buscar el sitio.
 *
 * Nada de esto decide el papel: lo que se guarda es el trazo y dónde quedó
 * respecto de ese hueco, y el contrato se vuelve a dibujar en el servidor con
 * esos datos. El navegador no fabrica un PDF firmado.
 *
 * Va en un módulo aparte del portal porque es lo único que necesita pdf.js:
 * el resto de la aplicación sigue sin depender de ninguna librería, y el
 * navegador solo descarga el visor cuando hay un contrato que abrir.
 */

import * as pdfjs from "./vendor/pdfjs/pdf.min.js";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    "./vendor/pdfjs/pdf.worker.min.js",
    import.meta.url,
).toString();


const ZOOM_MINIMO = 0.5;
const ZOOM_MAXIMO = 4;
const PASO_DE_ZOOM = 0.25;

// Cabecera con la que el PDF dice dónde quedó su hueco de firma.
const CABECERA_DEL_ANCLA = "X-Contrata-Ancla";

// Márgenes del tamaño de la firma, en proporción al hueco que el contrato
// reserva. Nadie necesita una firma diminuta ni una que cruce la hoja.
const ANCHO_MINIMO = 0.25;
const ANCHO_MAXIMO = 2.5;

// Margen que se deja alrededor del trazo al recortarlo. Sin él, una firma
// recortada al píxel queda pegada a su propio borde.
const MARGEN_DEL_RECORTE = 12;


const estado = {
    opciones: null,
    documento: null,
    zoom: 1,
    // Escala base: la que hace que la hoja entre de ancho en la pantalla.
    // El zoom se cuenta sobre ella, así que «100 %» significa «la hoja
    // completa», que es lo que espera quien mira un contrato en un móvil.
    escalaBase: 1,
    // Cada repintado del documento lleva su número. Un zoom pulsado dos
    // veces seguidas deja el primero a medias: al terminar comprueba si
    // sigue siendo el vigente y, si no, tira lo que dibujó.
    repintado: 0,

    // El hueco de firma del documento abierto, en unidades del PDF.
    ancla: null,

    // El trazo recién dibujado, a la espera de colocarse.
    trazo: null,

    // Dónde está la firma dentro del hueco, en puntos del PDF. Es la fuente
    // de verdad: los píxeles de pantalla se derivan de aquí en cada
    // repintado, y no al revés, para que el zoom no la vaya moviendo.
    colocacion: null,

    // Qué hace la capa que va encima de la hoja:
    //   null       nada, el documento se lee sin más
    //   "toque"    hay una firma registrada y se puede coger
    //   "edicion"  se está moviendo esa firma ya registrada
    //   "nueva"    se está colocando un trazo recién dibujado
    modo: null,
    trazoUrl: null,

    dibujando: false,
    hayTrazo: false,
    ultimoPunto: null,
    ultimoMedio: null,
    limites: null,
    tinta: "#12161f",
    grosor: 0.006,
};


function elemento(id) {
    return document.getElementById(id);
}


/* ------------------------------------------------------------------ *
 * El documento
 * ------------------------------------------------------------------ */

async function descargarContrato(sinFirma = false) {
    const url = sinFirma
        ? `${estado.opciones.documentUrl}?sin_firma=1`
        : estado.opciones.documentUrl;

    const respuesta = await fetch(url, {
        headers: { Authorization: `Token ${estado.opciones.token}` },
    });

    if (!respuesta.ok) {
        throw new Error("No se pudo abrir el contrato del abonado.");
    }

    const cabecera = respuesta.headers.get(CABECERA_DEL_ANCLA);

    try {
        estado.ancla = cabecera ? JSON.parse(cabecera) : null;
    } catch (error) {
        estado.ancla = null;
    }

    return respuesta.arrayBuffer();
}


async function abrirDocumento(sinFirma = false) {
    const cargando = elemento("signer-loading");
    cargando.hidden = false;
    cargando.textContent = "Abriendo el contrato…";

    try {
        const datos = await descargarContrato(sinFirma);
        estado.documento = await pdfjs.getDocument({ data: datos }).promise;

        elemento("signer-pages").textContent =
            estado.documento.numPages === 1
                ? "1 página"
                : `${estado.documento.numPages} páginas`;

        if (!sinFirma) ofrecerLaFirmaRegistrada();

        await dibujarPaginas();
        cargando.hidden = true;
    } catch (error) {
        cargando.hidden = false;
        cargando.textContent = error.message || "No se pudo abrir el contrato.";
    }
}


function anchoDisponible() {
    // 24 px de aire a cada lado, como el resto de las tarjetas del portal.
    return Math.max(240, elemento("signer-doc").clientWidth - 24);
}


function escalaActual() {
    return estado.escalaBase * estado.zoom;
}


function guardarLaCapaDeLaFirma() {
    /* Devuelve la capa al visor antes de vaciar las páginas.
     *
     * La capa se mete dentro de la hoja para poder apoyarse sobre ella, y
     * las hojas se tiran enteras en cada repintado. Sin rescatarla antes, el
     * primer zoom se la lleva por delante y a partir de ahí no hay firma que
     * colocar ni, peor, elemento que apagar al cerrar el visor.
     */

    const capa = elemento("signer-place");

    if (capa && capa.parentElement !== elemento("signer")) {
        elemento("signer").append(capa);
    }
}


function puntoDeLectura() {
    /* Por dónde va el técnico leyendo, en proporción al documento.

    Se guarda como proporción y no en píxeles porque la altura cambia con el
    zoom: los mismos 800 px son media hoja o dos según la escala.
    */

    const visor = elemento("signer-doc");

    return visor.scrollHeight > 0 ? visor.scrollTop / visor.scrollHeight : 0;
}


function volverAlPuntoDeLectura(proporcion) {
    const visor = elemento("signer-doc");

    visor.scrollTop = proporcion * visor.scrollHeight;
}


async function dibujarPaginas() {
    const contenedor = elemento("signer-canvases");
    const mio = (estado.repintado += 1);

    // Repintar tira las hojas y las vuelve a crear, y eso deja el visor
    // arriba del todo. Quien está firmando la cuarta página no tiene por qué
    // volver a bajar cada vez que guarda, mueve o borra la firma.
    const lectura = puntoDeLectura();

    guardarLaCapaDeLaFirma();
    contenedor.replaceChildren();

    const primera = await estado.documento.getPage(1);
    estado.escalaBase = anchoDisponible() / primera.getViewport({ scale: 1 }).width;

    const escala = escalaActual();

    // La pantalla de un móvil tiene más píxeles que puntos CSS. Sin esto el
    // texto del contrato se lee borroso, que en un documento que se firma no
    // es un detalle estético.
    const densidad = Math.min(window.devicePixelRatio || 1, 2);

    for (let numero = 1; numero <= estado.documento.numPages; numero += 1) {
        if (mio !== estado.repintado) return;

        const pagina = await estado.documento.getPage(numero);
        const vista = pagina.getViewport({ scale: escala });

        // Cada hoja va en su propia caja posicionada: es lo que permite
        // apoyar la firma sobre la página y no sobre el visor.
        const hoja = document.createElement("div");
        hoja.className = "signer-page-wrap";
        hoja.dataset.pagina = String(numero);
        hoja.style.width = `${Math.floor(vista.width)}px`;
        hoja.style.height = `${Math.floor(vista.height)}px`;

        const lienzo = document.createElement("canvas");
        lienzo.className = "signer-page";
        lienzo.width = Math.floor(vista.width * densidad);
        lienzo.height = Math.floor(vista.height * densidad);
        lienzo.style.width = `${Math.floor(vista.width)}px`;
        lienzo.style.height = `${Math.floor(vista.height)}px`;

        hoja.append(lienzo);
        contenedor.append(hoja);

        await pagina.render({
            canvasContext: lienzo.getContext("2d"),
            viewport: pagina.getViewport({ scale: escala * densidad }),
        }).promise;
    }

    if (mio === estado.repintado) {
        volverAlPuntoDeLectura(lectura);
        pintarColocacion();
    }
}


function aplicarZoom(nuevo) {
    const limitado = Math.min(ZOOM_MAXIMO, Math.max(ZOOM_MINIMO, nuevo));

    if (limitado === estado.zoom) return;

    estado.zoom = limitado;
    elemento("signer-zoom-level").textContent = `${Math.round(limitado * 100)}%`;
    dibujarPaginas();
}


/* ------------------------------------------------------------------ *
 * El lienzo de la firma
 * ------------------------------------------------------------------ */

function prepararLienzo() {
    const lienzo = elemento("signature-canvas");
    const caja = lienzo.parentElement.getBoundingClientRect();
    const densidad = Math.min(window.devicePixelRatio || 1, 3);

    lienzo.width = Math.floor(caja.width * densidad);
    lienzo.height = Math.floor(caja.height * densidad);

    aplicarPlumaAlLienzo();

    estado.hayTrazo = false;
    estado.ultimoPunto = null;
    estado.ultimoMedio = null;
    estado.limites = { izquierda: Infinity, derecha: 0, arriba: Infinity, abajo: 0 };
}


function aplicarPlumaAlLienzo() {
    /* Color y grosor del trazo.
     *
     * Se aplican al contexto y no a lo ya dibujado: cambiar de pluma a
     * mitad de una firma afecta a lo que venga, como con un bolígrafo.
     */
    const lienzo = elemento("signature-canvas");
    const contexto = lienzo.getContext("2d");

    contexto.lineCap = "round";
    contexto.lineJoin = "round";
    contexto.strokeStyle = estado.tinta;
    // El grosor va en proporción al lienzo: en un móvil pequeño y en una
    // tablet la firma tiene que verse con el mismo peso.
    contexto.lineWidth = Math.max(1.5, lienzo.width * estado.grosor);
}


function limpiarLienzo() {
    const lienzo = elemento("signature-canvas");
    lienzo.getContext("2d").clearRect(0, 0, lienzo.width, lienzo.height);

    aplicarPlumaAlLienzo();

    estado.hayTrazo = false;
    estado.ultimoPunto = null;
    estado.ultimoMedio = null;
    estado.limites = { izquierda: Infinity, derecha: 0, arriba: Infinity, abajo: 0 };
}


function puntoDelEvento(evento) {
    const lienzo = elemento("signature-canvas");
    const caja = lienzo.getBoundingClientRect();

    return {
        x: ((evento.clientX - caja.left) / caja.width) * lienzo.width,
        y: ((evento.clientY - caja.top) / caja.height) * lienzo.height,
    };
}


function anotarLimite(punto) {
    const limites = estado.limites;
    limites.izquierda = Math.min(limites.izquierda, punto.x);
    limites.derecha = Math.max(limites.derecha, punto.x);
    limites.arriba = Math.min(limites.arriba, punto.y);
    limites.abajo = Math.max(limites.abajo, punto.y);
}


function empezarTrazo(evento) {
    evento.preventDefault();
    estado.dibujando = true;
    estado.ultimoPunto = puntoDelEvento(evento);
    // El trazo arranca donde cae el dedo: ese punto es a la vez el primer
    // extremo de la primera curva.
    estado.ultimoMedio = estado.ultimoPunto;
    anotarLimite(estado.ultimoPunto);
    elemento("signature-canvas").setPointerCapture(evento.pointerId);
}


function seguirTrazo(evento) {
    if (!estado.dibujando) return;
    evento.preventDefault();

    const lienzo = elemento("signature-canvas");
    const contexto = lienzo.getContext("2d");
    const punto = puntoDelEvento(evento);
    const anterior = estado.ultimoPunto;

    // Cada tramo va del punto medio anterior al nuevo, curvándose sobre el
    // punto real que los separa. Encadenar los medios es lo que deja una
    // línea continua: dibujar de punto a punto medio y arrancar el
    // siguiente tramo en el punto entero dejaba media curva sin pintar, y
    // la firma salía a rayas.
    const medio = {
        x: (anterior.x + punto.x) / 2,
        y: (anterior.y + punto.y) / 2,
    };

    contexto.beginPath();
    contexto.moveTo(estado.ultimoMedio.x, estado.ultimoMedio.y);
    contexto.quadraticCurveTo(anterior.x, anterior.y, medio.x, medio.y);
    contexto.stroke();

    anotarLimite(punto);
    estado.ultimoMedio = medio;
    estado.ultimoPunto = punto;
    estado.hayTrazo = true;
}


function terminarTrazo() {
    if (estado.dibujando && estado.ultimoPunto && estado.ultimoMedio) {
        // El último tramo, del medio hasta donde se levantó el dedo: sin
        // esto la firma se queda a medio milímetro de su final.
        const contexto = elemento("signature-canvas").getContext("2d");
        contexto.beginPath();
        contexto.moveTo(estado.ultimoMedio.x, estado.ultimoMedio.y);
        contexto.lineTo(estado.ultimoPunto.x, estado.ultimoPunto.y);
        contexto.stroke();
    }

    estado.dibujando = false;
    estado.ultimoPunto = null;
    estado.ultimoMedio = null;
}


function recortarFirma() {
    /* El trazo recortado a lo que realmente se dibujó.
     *
     * Quien firma ocupa el lienzo como quiere, y el contrato reserva un alto
     * fijo encima de la línea. Sin recortar, una firma pequeña en una
     * esquina llegaría al papel como un sello diminuto perdido en el aire.
     */
    const lienzo = elemento("signature-canvas");
    const limites = estado.limites;

    const izquierda = Math.max(0, Math.floor(limites.izquierda - MARGEN_DEL_RECORTE));
    const arriba = Math.max(0, Math.floor(limites.arriba - MARGEN_DEL_RECORTE));
    const ancho = Math.min(
        lienzo.width - izquierda,
        Math.ceil(limites.derecha - limites.izquierda + MARGEN_DEL_RECORTE * 2),
    );
    const alto = Math.min(
        lienzo.height - arriba,
        Math.ceil(limites.abajo - limites.arriba + MARGEN_DEL_RECORTE * 2),
    );

    const recorte = document.createElement("canvas");
    recorte.width = Math.max(1, ancho);
    recorte.height = Math.max(1, alto);

    recorte
        .getContext("2d")
        .drawImage(lienzo, izquierda, arriba, ancho, alto, 0, 0, ancho, alto);

    return recorte;
}


/* ------------------------------------------------------------------ *
 * Colocar la firma sobre la hoja
 * ------------------------------------------------------------------ */

function colocacionInicial(proporcion) {
    /* Centrada en el hueco y apoyada en la línea.
     *
     * Es la misma regla que aplica el papel cuando nadie ha movido nada, así
     * que aceptar sin tocar deja la firma donde el contrato la espera.
     */
    const ancla = estado.ancla;

    const ancho = Math.min(ancla.ancho, ancla.alto / (proporcion || 1));

    return {
        x: (ancla.ancho - ancho) / 2,
        y: 0,
        ancho,
        alto: ancho * proporcion,
    };
}


function pintarColocacion() {
    /* Lleva la colocación -que vive en puntos del PDF- a la pantalla. */

    const capa = elemento("signer-place");

    if (!capa) return;

    if (!estado.colocacion || !estado.ancla) {
        capa.hidden = true;
        return;
    }

    const hoja = document.querySelector(
        `.signer-page-wrap[data-pagina="${estado.ancla.pagina}"]`,
    );

    if (!hoja) {
        capa.hidden = true;
        return;
    }

    if (capa.parentElement !== hoja) hoja.append(capa);

    const escala = escalaActual();
    const { x, y, ancho, alto } = estado.colocacion;

    // El PDF cuenta desde abajo y la pantalla desde arriba.
    const izquierda = (estado.ancla.x + x) * escala;
    const arriba =
        (estado.ancla.pagina_alto - (estado.ancla.y + y) - alto) * escala;

    capa.style.left = `${izquierda}px`;
    capa.style.top = `${arriba}px`;
    capa.style.width = `${ancho * escala}px`;
    capa.style.height = `${alto * escala}px`;
    capa.hidden = false;
}


function moverColocacion(dxPantalla, dyPantalla) {
    const escala = escalaActual();
    const ancla = estado.ancla;
    const colocacion = estado.colocacion;

    const x = colocacion.x + dxPantalla / escala;
    // Arrastrar hacia abajo en pantalla es restar en el PDF.
    const y = colocacion.y - dyPantalla / escala;

    // La firma puede salirse del hueco -hay quien firma largo-, pero no de
    // la hoja: una firma fuera del papel no se imprime.
    const minimoX = -ancla.x;
    const maximoX = ancla.pagina_ancho - ancla.x - colocacion.ancho;
    const minimoY = -ancla.y;
    const maximoY = ancla.pagina_alto - ancla.y - colocacion.alto;

    colocacion.x = Math.min(maximoX, Math.max(minimoX, x));
    colocacion.y = Math.min(maximoY, Math.max(minimoY, y));

    pintarColocacion();
}


function redimensionarColocacion(anchoPantalla) {
    const escala = escalaActual();
    const ancla = estado.ancla;
    const colocacion = estado.colocacion;

    const proporcion = colocacion.alto / colocacion.ancho;

    const ancho = Math.min(
        ancla.ancho * ANCHO_MAXIMO,
        Math.max(ancla.ancho * ANCHO_MINIMO, anchoPantalla / escala),
    );

    colocacion.ancho = ancho;
    colocacion.alto = ancho * proporcion;

    pintarColocacion();
}


function arrastreDeLaFirma() {
    const capa = elemento("signer-place");
    const asa = elemento("signer-place-handle");

    let ultimo = null;
    let estirando = false;

    capa.addEventListener("pointerdown", (evento) => {
        if (!estado.colocacion) return;

        // Un toque sobre la firma que ya está en el papel no la arrastra: la
        // despega primero. Así nadie mueve por accidente una firma dada por
        // buena mientras lee el contrato.
        if (estado.modo === "toque") {
            evento.preventDefault();
            evento.stopPropagation();
            editarFirmaRegistrada();
            return;
        }

        evento.preventDefault();
        evento.stopPropagation();

        estirando = evento.target === asa;
        ultimo = { x: evento.clientX, y: evento.clientY };
        capa.setPointerCapture(evento.pointerId);
        capa.classList.add("is-active");
    });

    capa.addEventListener("pointermove", (evento) => {
        if (!ultimo) return;
        evento.preventDefault();

        const dx = evento.clientX - ultimo.x;
        const dy = evento.clientY - ultimo.y;
        ultimo = { x: evento.clientX, y: evento.clientY };

        if (estirando) {
            redimensionarColocacion(capa.offsetWidth + dx);
        } else {
            moverColocacion(dx, dy);
        }
    });

    const soltar = () => {
        ultimo = null;
        estirando = false;
        capa.classList.remove("is-active");
    };

    capa.addEventListener("pointerup", soltar);
    capa.addEventListener("pointercancel", soltar);
}


function modoColocacion(modo) {
    /* Qué se ve abajo y qué permite la capa, según lo que se esté haciendo. */

    const colocando = modo === "nueva" || modo === "edicion";
    const editando = modo === "edicion";

    estado.modo = modo;

    elemento("signer-draw").hidden = colocando;
    elemento("signer-place-bar").hidden = !colocando;
    elemento("signer-place-delete").hidden = !editando;
    elemento("signer-place-cancel").hidden = !editando;
    elemento("signer-signed-hint").hidden = modo !== "toque";

    const capa = elemento("signer-place");

    if (capa) {
        capa.classList.toggle("is-editable", colocando);
        capa.classList.toggle("is-touchable", modo === "toque");
    }

    const imagen = elemento("signer-place-image");
    if (imagen) imagen.hidden = !colocando;

    if (!modo) {
        estado.trazo = null;
        estado.colocacion = null;
        if (capa) capa.hidden = true;
    }
}


function ofrecerLaFirmaRegistrada() {
    /* La firma que ya está en el papel, lista para volver a cogerse.
     *
     * Lo que se pinta encima es una zona transparente: la firma que se ve es
     * la del propio PDF, no una copia. Tocarla es lo que la despega del
     * documento para moverla, y mientras nadie la toque el contrato se lee
     * sin nada superpuesto.
     */

    const trazo = estado.ancla && estado.ancla.trazo;

    if (!trazo || !estado.opciones.canSign) {
        modoColocacion(null);
        return;
    }

    estado.colocacion = { ...trazo };
    modoColocacion("toque");
}


async function editarFirmaRegistrada() {
    /* Despega del documento la firma ya guardada para recolocarla.
     *
     * El trazo se pide al servidor en vez de repintarse: lo que se mueve
     * tiene que ser el mismo dibujo que hizo el abonado. Y el contrato se
     * vuelve a pedir sin él, porque con la firma dibujada debajo se verían
     * dos y solo una sería la que se va a guardar.
     */

    try {
        const respuesta = await fetch(estado.opciones.signatureUrl, {
            headers: { Authorization: `Token ${estado.opciones.token}` },
        });

        if (!respuesta.ok) throw new Error("No se pudo abrir la firma guardada.");

        if (estado.trazoUrl) URL.revokeObjectURL(estado.trazoUrl);
        estado.trazoUrl = URL.createObjectURL(await respuesta.blob());
        elemento("signer-place-image").src = estado.trazoUrl;

        const colocacion = { ...estado.colocacion };

        modoColocacion("edicion");
        await abrirDocumento(true);

        estado.colocacion = colocacion;
        pintarColocacion();
    } catch (error) {
        estado.opciones.onMessage(error.message, "error");
        modoColocacion("toque");
    }
}


function empezarAColocar() {
    /* Del lienzo a la hoja: el trazo aparece sobre la línea, ya a tamaño. */

    if (!estado.hayTrazo) {
        estado.opciones.onMessage("Dibuje la firma del abonado antes de continuar.", "error");
        return;
    }

    if (!estado.ancla || !estado.ancla.pagina) {
        estado.opciones.onMessage(
            "No se pudo ubicar el espacio de firma en el contrato.",
            "error",
        );
        return;
    }

    const recorte = recortarFirma();

    estado.trazo = recorte;
    estado.colocacion = colocacionInicial(recorte.height / recorte.width);

    elemento("signer-place-image").src = recorte.toDataURL("image/png");

    cerrarHojaDeFirma();
    modoColocacion("nueva");
    pintarColocacion();
    irALaFirma();
}


function irALaFirma() {
    elemento("signer-place")?.scrollIntoView({
        behavior: "smooth",
        block: "center",
    });
}


/* ------------------------------------------------------------------ *
 * Aceptar, rechazar y guardar
 * ------------------------------------------------------------------ */

function abrirHojaDeFirma() {
    elemento("signer-sheet").hidden = false;
    // El lienzo se mide cuando ya está en pantalla: medido antes, sale de
    // tamaño cero y el trazo aparece desplazado.
    requestAnimationFrame(prepararLienzo);
}


function cerrarHojaDeFirma() {
    elemento("signer-sheet").hidden = true;
}


function firmaComoPng() {
    return new Promise((resolver) => {
        estado.trazo.toBlob(resolver, "image/png");
    });
}


function colocacionParaElServidor() {
    return {
        offset_x: estado.colocacion.x.toFixed(2),
        offset_y: estado.colocacion.y.toFixed(2),
        width: estado.colocacion.ancho.toFixed(2),
    };
}


async function guardarFirma(boton) {
    if (!estado.colocacion) return;

    const moviendo = estado.modo === "edicion";

    if (!moviendo && !estado.trazo) return;

    boton.disabled = true;
    boton.textContent = "Guardando…";

    try {
        const medidas = colocacionParaElServidor();
        let peticion;

        if (moviendo) {
            // Mover una firma no es volver a firmarla: el trazo es el mismo
            // y el abonado no tiene que estar delante otra vez.
            peticion = fetch(estado.opciones.signatureUrl, {
                method: "PATCH",
                headers: {
                    Authorization: `Token ${estado.opciones.token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(medidas),
            });
        } else {
            const cuerpo = new FormData();
            cuerpo.append("image", await firmaComoPng(), "firma.png");
            Object.entries(medidas).forEach(([campo, valor]) =>
                cuerpo.append(campo, valor),
            );

            peticion = fetch(estado.opciones.signatureUrl, {
                method: "POST",
                headers: { Authorization: `Token ${estado.opciones.token}` },
                body: cuerpo,
            });
        }

        const respuesta = await peticion;
        const datos = await respuesta.json().catch(() => null);

        if (!respuesta.ok) {
            throw new Error(
                datos?.detail || "No se pudo guardar la firma del abonado.",
            );
        }

        modoColocacion(null);
        estado.opciones.onMessage(
            moviendo ? "Firma actualizada." : "Contrato firmado por el abonado.",
            "success",
        );
        estado.opciones.onSigned?.(datos);

        // Se vuelve a pedir el documento: lo que el abonado tiene que ver
        // ahora es su contrato con la firma dentro, no el que trajo el
        // técnico en blanco. La hoja se queda donde estaba, que es justo
        // donde acaba de firmar.
        await abrirDocumento();
    } catch (error) {
        estado.opciones.onMessage(error.message, "error");
    } finally {
        boton.disabled = false;
        boton.textContent = "Aceptar y guardar";
    }
}


async function eliminarFirma(boton) {
    /* Quita la firma del contrato. El documento vuelve a su línea en blanco. */

    boton.disabled = true;

    try {
        const respuesta = await fetch(estado.opciones.signatureUrl, {
            method: "DELETE",
            headers: { Authorization: `Token ${estado.opciones.token}` },
        });

        const datos = await respuesta.json().catch(() => null);

        if (!respuesta.ok) {
            throw new Error(datos?.detail || "No se pudo eliminar la firma.");
        }

        modoColocacion(null);
        estado.opciones.onMessage("Firma eliminada del contrato.", "success");
        estado.opciones.onSigned?.(datos);

        // Sin saltar a ninguna parte: borrar una firma deja el contrato a la
        // vista en la misma hoja, que es donde hay que comprobar que se fue.
        await abrirDocumento();
    } catch (error) {
        estado.opciones.onMessage(error.message, "error");
    } finally {
        boton.disabled = false;
    }
}


/* ------------------------------------------------------------------ *
 * El visor
 * ------------------------------------------------------------------ */

function cerrar() {
    /* Cerrar el contrato devuelve la pantalla como estaba.
     *
     * El bloqueo del desplazamiento se suelta **lo primero** y el resto va en
     * un `finally`: mientras el visor estuvo abierto, el cuerpo de la página
     * no se desplaza, y si algo fallara al recoger, el técnico se quedaría
     * con la ficha de la orden congelada sin saber por qué.
     */

    elemento("signer").hidden = true;
    document.body.classList.remove("signer-open");

    try {
        cerrarHojaDeFirma();
        modoColocacion(null);

        estado.documento?.destroy?.();

        if (estado.trazoUrl) URL.revokeObjectURL(estado.trazoUrl);

        guardarLaCapaDeLaFirma();
        elemento("signer-canvases").replaceChildren();
    } finally {
        estado.documento = null;
        estado.ancla = null;
        estado.trazoUrl = null;
    }
}


function pellizcoDeZoom() {
    /* Zoom con dos dedos sobre el documento.
     *
     * Con un dedo no se hace nada: ese gesto es el desplazamiento por la
     * hoja, que es como se lee un contrato largo en una pantalla pequeña.
     */
    const documento = elemento("signer-doc");
    let distanciaInicial = null;
    let zoomInicial = 1;

    const distancia = (toques) =>
        Math.hypot(
            toques[0].clientX - toques[1].clientX,
            toques[0].clientY - toques[1].clientY,
        );

    documento.addEventListener("touchstart", (evento) => {
        if (evento.touches.length !== 2) return;
        distanciaInicial = distancia(evento.touches);
        zoomInicial = estado.zoom;
    }, { passive: true });

    documento.addEventListener("touchmove", (evento) => {
        if (evento.touches.length !== 2 || !distanciaInicial) return;
        evento.preventDefault();

        const proporcion = distancia(evento.touches) / distanciaInicial;
        const objetivo = Math.round((zoomInicial * proporcion) / 0.05) * 0.05;

        if (Math.abs(objetivo - estado.zoom) >= PASO_DE_ZOOM / 2) {
            aplicarZoom(objetivo);
        }
    }, { passive: false });

    documento.addEventListener("touchend", (evento) => {
        if (evento.touches.length < 2) distanciaInicial = null;
    }, { passive: true });
}


function elegirPluma() {
    document.querySelectorAll("[data-ink]").forEach((boton) => {
        boton.addEventListener("click", () => {
            estado.tinta = boton.dataset.ink;
            document
                .querySelectorAll("[data-ink]")
                .forEach((otro) => otro.classList.toggle("is-active", otro === boton));
            aplicarPlumaAlLienzo();
        });
    });

    document.querySelectorAll("[data-stroke]").forEach((boton) => {
        boton.addEventListener("click", () => {
            estado.grosor = Number(boton.dataset.stroke);
            document
                .querySelectorAll("[data-stroke]")
                .forEach((otro) => otro.classList.toggle("is-active", otro === boton));
            aplicarPlumaAlLienzo();
        });
    });
}


function conectarControles() {
    elemento("signer-close").addEventListener("click", cerrar);
    elemento("signer-zoom-in").addEventListener("click", () =>
        aplicarZoom(estado.zoom + PASO_DE_ZOOM),
    );
    elemento("signer-zoom-out").addEventListener("click", () =>
        aplicarZoom(estado.zoom - PASO_DE_ZOOM),
    );

    elemento("signer-draw").addEventListener("click", abrirHojaDeFirma);
    elemento("signature-cancel").addEventListener("click", cerrarHojaDeFirma);
    elemento("signature-clear").addEventListener("click", limpiarLienzo);
    elemento("signature-accept").addEventListener("click", empezarAColocar);

    elemento("signer-place-redraw").addEventListener("click", async () => {
        // Volver a dibujar sobre una firma registrada deja el documento sin
        // ella mientras tanto: lo que se está haciendo es sustituirla.
        const veniaDeUnaFirmaGuardada = estado.modo === "edicion";

        modoColocacion(null);
        if (veniaDeUnaFirmaGuardada) await abrirDocumento(true);
        abrirHojaDeFirma();
    });
    elemento("signer-place-cancel").addEventListener("click", async () => {
        modoColocacion(null);
        await abrirDocumento();
    });
    elemento("signer-place-delete").addEventListener("click", (evento) =>
        eliminarFirma(evento.currentTarget),
    );
    elemento("signer-place-accept").addEventListener("click", (evento) =>
        guardarFirma(evento.currentTarget),
    );

    const lienzo = elemento("signature-canvas");
    lienzo.addEventListener("pointerdown", empezarTrazo);
    lienzo.addEventListener("pointermove", seguirTrazo);
    lienzo.addEventListener("pointerup", terminarTrazo);
    lienzo.addEventListener("pointercancel", terminarTrazo);
    lienzo.addEventListener("pointerleave", terminarTrazo);

    arrastreDeLaFirma();
    elegirPluma();
    pellizcoDeZoom();

    document.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape" && !elemento("signer").hidden) cerrar();
    });
}


async function abrir(opciones) {
    estado.opciones = {
        onMessage: () => {},
        ...opciones,
    };
    estado.zoom = 1;

    elemento("signer-name").textContent = opciones.title || "Contrato";
    elemento("signer-zoom-level").textContent = "100%";
    // Un contrato se abre por su principio. El punto de lectura se conserva
    // entre repintados, no entre aperturas.
    elemento("signer-doc").scrollTop = 0;
    elemento("signer").hidden = false;
    document.body.classList.add("signer-open");

    modoColocacion(null);

    // Firmar es lo que trae al técnico aquí, pero el contrato también se
    // consulta después de firmado: si ya no se puede firmar, el visor sigue
    // abriendo el documento y se calla el botón.
    elemento("signer-actions").hidden = !opciones.canSign;

    await abrirDocumento();
}


if (!window.SICV_CONTRACT_SIGNER) {
    conectarControles();

    window.SICV_CONTRACT_SIGNER = { abrir, cerrar };
    document.dispatchEvent(new CustomEvent("sicv:contract-signer-ready"));
}
