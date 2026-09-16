(() => {
    "use strict";

    const tokenKey = "sicv.technician.token";
    const nativeFetch = window.fetch.bind(window);
    const evidenceFileAccept = "image/jpeg,image/png,image/webp,application/pdf";
    const evidenceCameraAccept = "image/jpeg,image/png,image/webp";
    const terminalValues = Array.from({length: 16}, (_, index) => {
        const number = index + 1;
        return {
            value: String(number),
            label: String(number).padStart(2, "0"),
        };
    });
    let activeOrderId = null;
    let napSearchTimer = null;

    function text(value, fallback = "0") {
        if (value === null || value === undefined || value === "") return fallback;
        return String(value);
    }

    function money(value) {
        const number = Number(value || 0);
        return Number.isFinite(number) ? `S/ ${number.toFixed(2)}` : "S/ 0.00";
    }

    function normalize(value) {
        return String(value || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toUpperCase();
    }

    function authHeaders() {
        const headers = new Headers();
        const token = sessionStorage.getItem(tokenKey);
        if (token) headers.set("Authorization", `Token ${token}`);
        return headers;
    }

    function setInstallationExcessVisibility(order) {
        const panel = document.querySelector("#materials-panel");
        if (!panel) return;

        // El dominio de excesos vigente es exclusivamente de instalación.
        // Una avería puede consumir cable y queda registrada en materiales,
        // pero no debe mostrar una tarifa de "metraje de instalación".
        panel.hidden = !normalize(order?.order_type).includes("INSTALACION");
    }

    function renderAutomaticExcess(payload) {
        const list = document.querySelector("#materials-list");
        const empty = document.querySelector("#materials-empty");
        const total = document.querySelector("#materials-total");
        if (!list || !empty || !total) return;

        const items = payload?.items || [];
        list.replaceChildren();
        total.textContent = `Exceso ${money(payload?.total_excess_charge)}`;
        empty.hidden = items.length !== 0;

        items.forEach((item) => {
            const row = document.createElement("article");
            row.className = "material-item";

            const title = document.createElement("strong");
            title.textContent = item.material_label || item.material || "Cable";

            const detail = document.createElement("p");
            detail.textContent = (
                `${text(item.meters_used)} m instalados · ` +
                `${text(item.free_meters_snapshot)} m incluidos · ` +
                `${text(item.excess_meters)} m excedentes · ` +
                money(item.excess_charge)
            );

            row.append(title, detail);
            list.append(row);
        });
    }

    async function refreshAutomaticExcess(materialsUrl) {
        try {
            const response = await nativeFetch(materialsUrl, {headers: authHeaders()});
            if (!response.ok) return;
            const payload = await response.json();
            renderAutomaticExcess(payload);
        } catch (_error) {
            // El flujo principal ya informa errores de red. Este refresco solo
            // mantiene sincronizado el resumen visual y no debe duplicar avisos.
        }
    }

    function initTerminalSelect() {
        const current = document.querySelector("#field-terminal");
        if (!current || current.tagName === "SELECT") return;

        const select = document.createElement("select");
        select.id = current.id;
        select.name = current.name || "terminal";
        select.disabled = current.disabled;
        select.setAttribute("aria-label", "Borne");

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Seleccione borne...";
        select.append(placeholder);

        terminalValues.forEach(({value, label}) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            select.append(option);
        });

        const currentValue = String(current.value || "").trim();
        const number = Number.parseInt(currentValue, 10);
        if (Number.isInteger(number) && number >= 1 && number <= 16) {
            select.value = String(number);
        }

        current.replaceWith(select);
    }

    function createNapSearchBox(input) {
        if (!input || document.querySelector("#field-nap-search-results")) return null;

        input.autocomplete = "off";
        input.placeholder = "Escribe código o nombre de la NAP";

        // El resultado debe flotar sobre el formulario, no aumentar la altura
        // de la grilla y empujar Borne/MAC/Precinto mientras se está buscando.
        const wrapper = document.createElement("div");
        wrapper.id = "field-nap-search-wrapper";
        wrapper.style.position = "relative";
        wrapper.style.width = "100%";
        input.insertAdjacentElement("beforebegin", wrapper);
        wrapper.append(input);

        const help = document.createElement("small");
        help.id = "field-nap-search-help";
        help.textContent = "Escribe al menos 2 caracteres y selecciona una NAP del catálogo de la sede.";
        help.style.display = "block";
        help.style.marginTop = "6px";
        help.style.color = "#667085";

        const results = document.createElement("div");
        results.id = "field-nap-search-results";
        results.hidden = true;
        results.style.position = "absolute";
        results.style.top = "calc(100% + 6px)";
        results.style.left = "0";
        results.style.right = "0";
        results.style.border = "1px solid #d0d5dd";
        results.style.borderRadius = "10px";
        results.style.background = "#fff";
        results.style.maxHeight = "180px";
        results.style.overflowY = "auto";
        results.style.boxShadow = "0 10px 24px rgba(16, 24, 40, 0.14)";
        results.style.zIndex = "50";

        wrapper.append(results);
        wrapper.insertAdjacentElement("afterend", help);
        return results;
    }

    function renderNapResults(payload) {
        const input = document.querySelector("#field-nap");
        const resultsBox = document.querySelector("#field-nap-search-results");
        if (!input || !resultsBox) return;

        resultsBox.replaceChildren();
        const results = payload?.results || [];

        if (!payload?.catalog_enabled) {
            const empty = document.createElement("div");
            empty.textContent = "El catálogo NAP de esta sede aún no fue cargado.";
            empty.style.padding = "12px";
            empty.style.color = "#667085";
            resultsBox.append(empty);
            resultsBox.hidden = false;
            return;
        }

        if (!results.length) {
            const empty = document.createElement("div");
            empty.textContent = "No se encontraron NAP con ese código o nombre.";
            empty.style.padding = "12px";
            empty.style.color = "#667085";
            resultsBox.append(empty);
            resultsBox.hidden = false;
            return;
        }

        results.forEach((nap) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = nap.name;
            button.dataset.napId = nap.id;
            button.style.display = "block";
            button.style.width = "100%";
            button.style.padding = "10px 12px";
            button.style.border = "0";
            button.style.borderBottom = "1px solid #eaecf0";
            button.style.background = "#fff";
            button.style.textAlign = "left";
            button.style.cursor = "pointer";
            button.addEventListener("click", () => {
                input.value = nap.name;
                input.dataset.napId = String(nap.id);
                resultsBox.hidden = true;
                input.focus();
            });
            resultsBox.append(button);
        });
        resultsBox.hidden = false;
    }

    async function searchNaps(query) {
        if (!activeOrderId) return;
        try {
            const url = `/api/technicians/work-orders/${activeOrderId}/naps/?q=${encodeURIComponent(query)}`;
            const response = await nativeFetch(url, {headers: authHeaders()});
            if (!response.ok) return;
            renderNapResults(await response.json());
        } catch (_error) {
            const resultsBox = document.querySelector("#field-nap-search-results");
            if (resultsBox) resultsBox.hidden = true;
        }
    }

    function initNapSearch() {
        const input = document.querySelector("#field-nap");
        const resultsBox = createNapSearchBox(input);
        if (!input || !resultsBox) return;

        input.addEventListener("input", () => {
            input.dataset.napId = "";
            clearTimeout(napSearchTimer);
            const query = input.value.trim();
            if (query.length < 2 || !activeOrderId) {
                resultsBox.hidden = true;
                return;
            }
            napSearchTimer = setTimeout(() => searchNaps(query), 250);
        });

        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") resultsBox.hidden = true;
        });

        document.addEventListener("click", (event) => {
            if (event.target !== input && !resultsBox.contains(event.target)) {
                resultsBox.hidden = true;
            }
        });
    }

    function initFieldSheetUx() {
        const notes = document.querySelector("#field-notes");
        const notesField = notes?.closest(".field");
        if (notesField) {
            // Las notas históricas siguen en el DOM para que portal.js las
            // preserve al guardar, pero el flujo nuevo concentra la observación
            // opcional en el cierre general de la Orden Técnica.
            notesField.hidden = true;
        }

        const saveButton = document.querySelector("#field-save");
        if (saveButton) saveButton.textContent = "Guardar datos técnicos";

        const help = document.querySelector("#field-sheet-help");
        if (help) {
            help.dataset.editableText = "Registra y guarda NAP, borne, MAC/equipo y precinto encontrados en campo.";
        }

        const finalRemarks = document.querySelector("#completion-remarks");
        const finalRemarksLabel = finalRemarks?.closest(".field")?.querySelector("span");
        if (finalRemarksLabel) finalRemarksLabel.textContent = "Observación general de la orden (opcional)";
        if (finalRemarks) {
            finalRemarks.placeholder = "Registra aquí cualquier observación general relevante antes de finalizar la atención";
        }
    }

    function syncEvidenceSelection() {
        const input = document.querySelector("#evidence-file");
        const selected = document.querySelector("#evidence-selected-file");
        if (!input || !selected) return;
        const file = input.files?.[0];
        selected.textContent = file ? `Archivo listo: ${file.name}` : "Ningún archivo seleccionado.";
    }

    function initEvidenceCapture() {
        const input = document.querySelector("#evidence-file");
        const originalBox = input?.closest(".upload-box");
        if (!input || !originalBox || document.querySelector("#evidence-camera-trigger")) return;

        const box = document.createElement("div");
        box.className = "upload-box";

        const title = document.createElement("span");
        title.textContent = "Adjuntar evidencia";

        const help = document.createElement("small");
        help.textContent = "Toma una foto con el celular o selecciona JPG, PNG, WEBP o PDF · máximo 10 MB";

        const actions = document.createElement("div");
        actions.style.display = "grid";
        actions.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
        actions.style.gap = "10px";
        actions.style.marginTop = "12px";

        const cameraButton = document.createElement("button");
        cameraButton.id = "evidence-camera-trigger";
        cameraButton.type = "button";
        cameraButton.className = "btn btn-primary btn-block";
        cameraButton.textContent = "Tomar foto";

        const libraryButton = document.createElement("button");
        libraryButton.id = "evidence-file-trigger";
        libraryButton.type = "button";
        libraryButton.className = "btn btn-secondary btn-block";
        libraryButton.textContent = "Galería o PDF";

        const selected = document.createElement("small");
        selected.id = "evidence-selected-file";
        selected.className = "helper";
        selected.style.display = "block";
        selected.style.marginTop = "10px";
        selected.textContent = "Ningún archivo seleccionado.";

        input.hidden = true;
        input.accept = evidenceFileAccept;
        actions.append(cameraButton, libraryButton);
        box.append(title, help, input, actions, selected);
        originalBox.replaceWith(box);

        const syncDisabled = () => {
            cameraButton.disabled = input.disabled;
            libraryButton.disabled = input.disabled;
        };

        cameraButton.addEventListener("click", () => {
            if (input.disabled) return;
            input.value = "";
            input.accept = evidenceCameraAccept;
            input.setAttribute("capture", "environment");
            input.click();
        });

        libraryButton.addEventListener("click", () => {
            if (input.disabled) return;
            input.value = "";
            input.accept = evidenceFileAccept;
            input.removeAttribute("capture");
            input.click();
        });

        input.addEventListener("change", syncEvidenceSelection);
        new MutationObserver(syncDisabled).observe(input, {
            attributes: true,
            attributeFilter: ["disabled"],
        });
        syncDisabled();
    }

    window.fetch = async function (input, init = {}) {
        const response = await nativeFetch(input, init);

        try {
            const url = typeof input === "string" ? input : input.url;
            const method = String(
                init.method || (typeof input !== "string" ? input.method : "GET")
            ).toUpperCase();

            // El detalle de la OT decide si el panel de excesos corresponde y
            // también identifica qué OT debe usarse al buscar NAP por sede.
            const detailMatch = url.match(/\/work-orders\/(\d+)\/(?:\?.*)?$/);
            if (response.ok && method === "GET" && detailMatch) {
                activeOrderId = detailMatch[1];
                void response.clone().json().then(setInstallationExcessVisibility);
            }

            // Al agregar, corregir o quitar un material, el backend ya dejó el
            // metraje sincronizado. Refrescamos el resumen sin pedir al técnico
            // que vuelva a declarar el mismo cable.
            if (
                response.ok &&
                (method === "POST" || method === "DELETE") &&
                /\/field-materials\/(?:\?.*)?$/.test(url)
            ) {
                const materialsUrl = url.replace(
                    /\/field-materials\/(?:\?.*)?$/,
                    "/materials/",
                );
                void refreshAutomaticExcess(materialsUrl);
            }

            // portal.js limpia el input después de una carga exitosa. Dejamos
            // que complete ese ciclo y luego sincronizamos el texto visible.
            if (
                response.ok &&
                method === "POST" &&
                /\/evidences\/(?:\?.*)?$/.test(url)
            ) {
                setTimeout(syncEvidenceSelection, 0);
            }
        } catch (_error) {
            // Nunca se altera la respuesta original del API por un refresco UI.
        }

        return response;
    };

    initTerminalSelect();
    initNapSearch();
    initFieldSheetUx();
    initEvidenceCapture();
})();