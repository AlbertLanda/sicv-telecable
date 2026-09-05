(() => {
    "use strict";

    const config = window.SICV_TECHNICIAN_CONFIG;
    const tokenKey = "sicv.technician.token";
    const state = {
        token: sessionStorage.getItem(tokenKey) || "",
        technician: null,
        currentScreen: "home",
        detailId: null,
        detailBackScreen: "mine",
        detailEditable: false,
        currentOrder: null,
        toastTimer: null,
    };

    const $ = (selector) => document.querySelector(selector);
    const $$ = (selector) => Array.from(document.querySelectorAll(selector));

    function text(value, fallback = "—") {
        if (value === null || value === undefined || value === "") return fallback;
        return String(value);
    }

    function formatDate(value) {
        if (!value) return "—";
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return text(value);
        return new Intl.DateTimeFormat("es-PE", {
            dateStyle: "short",
            timeStyle: "short",
        }).format(parsed);
    }

    function money(value) {
        const number = Number(value || 0);
        return Number.isFinite(number) ? `S/ ${number.toFixed(2)}` : "S/ 0.00";
    }

    function showToast(message, kind = "") {
        const toast = $("#toast");
        toast.textContent = message;
        toast.className = `toast show ${kind}`.trim();
        clearTimeout(state.toastTimer);
        state.toastTimer = setTimeout(() => {
            toast.className = "toast";
        }, 3200);
    }

    function errorMessage(payload, fallback = "No se pudo completar la operación.") {
        if (!payload) return fallback;
        if (typeof payload === "string") return payload;
        if (payload.detail) return String(payload.detail);
        const first = Object.values(payload)[0];
        if (Array.isArray(first) && first.length) return String(first[0]);
        if (typeof first === "string") return first;
        return fallback;
    }

    async function api(url, options = {}) {
        const headers = new Headers(options.headers || {});
        if (state.token) headers.set("Authorization", `Token ${state.token}`);
        if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
            headers.set("Content-Type", "application/json");
        }

        let response;
        try {
            response = await fetch(url, { ...options, headers });
        } catch (error) {
            throw new Error("No se pudo conectar con el servidor. Revisa tu conexión.");
        }

        let payload = null;
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("application/json")) payload = await response.json();

        if (response.status === 401 && url !== config.loginUrl) {
            logout(false);
            showToast("Tu sesión ya no es válida. Ingresa nuevamente.", "error");
            throw new Error("Sesión no válida.");
        }

        if (!response.ok) {
            const error = new Error(errorMessage(payload));
            error.status = response.status;
            error.payload = payload;
            throw error;
        }
        return payload;
    }

    function setBusy(button, busy, busyLabel = "Procesando…") {
        if (!button) return;
        if (busy) {
            button.dataset.originalLabel = button.textContent;
            button.textContent = busyLabel;
            button.disabled = true;
        } else {
            button.textContent = button.dataset.originalLabel || button.textContent;
            button.disabled = false;
        }
    }

    function ensureCompletionPanel() {
        if ($("#completion-panel")) return;
        const evidenceForm = $("#evidence-form");
        const evidencePanel = evidenceForm ? evidenceForm.closest(".panel") : null;
        if (!evidencePanel) return;

        const panel = document.createElement("section");
        panel.id = "completion-panel";
        panel.className = "panel";
        panel.innerHTML = `
            <div class="panel-heading">
                <div>
                    <p class="eyebrow">Cierre técnico</p>
                    <h2>Finalizar Orden Técnica</h2>
                </div>
                <span id="completion-status" class="mini-badge">Pendiente</span>
            </div>
            <p id="completion-help" class="helper">Inicia la atención antes de finalizar la orden.</p>

            <dl class="data-list two-column">
                <div><dt>Ficha técnica</dt><dd id="completion-sheet">—</dd></div>
                <div><dt>Materiales instalados</dt><dd id="completion-installed">0</dd></div>
                <div><dt>Materiales retirados</dt><dd id="completion-removed">0</dd></div>
                <div><dt>Metrajes</dt><dd id="completion-meters">0</dd></div>
                <div><dt>Evidencias</dt><dd id="completion-evidences">0</dd></div>
                <div><dt>Resultado</dt><dd id="completion-selected-result">Sin registrar</dd></div>
            </dl>

            <form id="complete-order-form" class="form-grid" hidden>
                <label class="field field-full">
                    <span>Resultado de la atención</span>
                    <select id="completion-result" required>
                        <option value="">Seleccione resultado...</option>
                    </select>
                </label>
                <label class="field field-full">
                    <span>Observación final de la atención</span>
                    <textarea id="completion-remarks" rows="3" maxlength="1000" placeholder="Opcional: observación antes de cerrar la atención"></textarea>
                </label>
                <div class="field-full">
                    <button id="complete-order-submit" class="btn btn-primary btn-block" type="submit">Finalizar atención</button>
                </div>
            </form>

            <form id="liquidate-order-form" class="form-grid" hidden>
                <div class="note-box field-full">
                    <strong>Atención finalizada</strong>
                    <p>Revisa el resultado y describe el trabajo ejecutado. Al confirmar, la OT quedará Liquidada y ya no podrá editarse desde campo.</p>
                </div>
                <label class="field field-full">
                    <span>Trabajo ejecutado / solución</span>
                    <textarea id="liquidation-resolution" rows="4" maxlength="4000" required placeholder="Describe qué se realizó en el domicilio"></textarea>
                </label>
                <label class="field field-full">
                    <span>Observaciones técnicas adicionales</span>
                    <textarea id="liquidation-notes" rows="3" maxlength="4000" placeholder="Opcional"></textarea>
                </label>
                <div class="field-full">
                    <button id="liquidate-order-submit" class="btn btn-primary btn-block" type="submit">Finalizar orden técnica</button>
                </div>
            </form>

            <div id="completion-done" class="empty-state compact" hidden>
                Orden técnica liquidada. El registro de campo quedó consolidado para su revisión posterior.
            </div>
        `;
        evidencePanel.insertAdjacentElement("afterend", panel);
    }

    function showLogin() {
        $("#login-view").hidden = false;
        $("#app-view").hidden = true;
        $("#login-password").value = "";
        setTimeout(() => $("#login-username").focus(), 30);
    }

    function showApp() {
        $("#login-view").hidden = true;
        $("#app-view").hidden = false;
        renderIdentity();
        navigate("home");
    }

    function renderIdentity() {
        if (!state.technician) return;
        $("#technician-name").textContent = state.technician.full_name || state.technician.username || "Técnico";
        $("#technician-branch").textContent = state.technician.branch_name || "Sin sede asignada";
    }

    function logout(showMessage = true) {
        state.token = "";
        state.technician = null;
        state.detailId = null;
        state.detailEditable = false;
        state.currentOrder = null;
        sessionStorage.removeItem(tokenKey);
        showLogin();
        if (showMessage) showToast("Sesión cerrada.", "success");
    }

    async function bootstrap() {
        ensureCompletionPanel();
        bindEvents();
        updateNetworkStatus();
        if (!state.token) {
            showLogin();
            return;
        }
        try {
            state.technician = await api(config.meUrl);
            showApp();
        } catch (error) {
            if (state.token) showToast(error.message, "error");
        }
    }

    async function handleLogin(event) {
        event.preventDefault();
        const button = $("#login-submit");
        const errorBox = $("#login-error");
        errorBox.hidden = true;
        setBusy(button, true, "Ingresando…");
        try {
            const result = await api(config.loginUrl, {
                method: "POST",
                body: JSON.stringify({
                    username: $("#login-username").value.trim(),
                    password: $("#login-password").value,
                }),
            });
            state.token = result.token;
            state.technician = result.technician;
            sessionStorage.setItem(tokenKey, state.token);
            showApp();
            showToast("Bienvenido al canal técnico.", "success");
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.hidden = false;
        } finally {
            setBusy(button, false);
        }
    }

    function navigate(screen) {
        if (screen === "detail" && !state.detailId) return;
        state.currentScreen = screen;
        $$(".screen").forEach((section) => {
            section.hidden = section.dataset.screen !== screen;
        });
        $$("#bottom-nav [data-nav]").forEach((button) => {
            button.classList.toggle("active", button.dataset.nav === screen);
        });
        if (screen === "home") loadHome();
        if (screen === "available") loadAvailable();
        if (screen === "mine") loadMine();
        if (screen === "detail") loadDetail(state.detailId);
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function element(tag, className = "", content = "") {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (content !== "") node.textContent = content;
        return node;
    }

    function statusBadge(order) {
        return element("span", "mini-badge", order.status_display || order.status || "Estado");
    }

    function orderCard(order, mode) {
        const card = element("article", "order-card");
        const top = element("div", "order-card-top");
        const titleWrap = element("div");
        titleWrap.append(
            element("span", "order-number", text(order.order_number)),
            element("h3", "", text(order.customer?.display_name, "Cliente")),
            element("p", "", `${text(order.service_type, "Servicio")} · ${text(order.plan, "Sin plan")}`),
        );
        top.append(titleWrap, statusBadge(order));

        const meta = element("div", "order-meta");
        const location = mode === "available"
            ? [order.district, order.zone || order.branch].filter(Boolean).join(" · ")
            : formatDate(order.scheduled_at);
        meta.append(
            element("span", "", mode === "available" ? `📍 ${text(location, "Ubicación por confirmar")}` : `🗓 ${text(location, "Sin programación")}`),
            element("span", "", `⚑ ${text(order.priority_display, "Prioridad")}`),
        );

        const actions = element("div", "order-card-actions");
        if (mode === "available") {
            const claim = element("button", "btn btn-primary btn-block", "Tomar orden");
            claim.type = "button";
            claim.addEventListener("click", () => claimOrder(order.id, claim));
            actions.append(claim);
        } else {
            const detail = element("button", "btn btn-secondary btn-block", "Ver Orden Técnica");
            detail.type = "button";
            detail.addEventListener("click", () => openDetail(order.id, "mine"));
            actions.append(detail);
        }
        card.append(top, meta, actions);
        return card;
    }

    async function loadAvailable() {
        const loading = $("#available-loading");
        const list = $("#available-list");
        const empty = $("#available-empty");
        loading.hidden = false;
        empty.hidden = true;
        list.replaceChildren();
        const suffix = $("#available-scope-all").checked ? "?scope=all" : "";
        try {
            const orders = await api(`${config.workOrdersUrl}available/${suffix}`);
            orders.forEach((order) => list.append(orderCard(order, "available")));
            empty.hidden = orders.length !== 0;
        } catch (error) {
            showToast(error.message, "error");
            empty.textContent = "No se pudieron cargar las órdenes disponibles.";
            empty.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    async function loadMine() {
        const loading = $("#mine-loading");
        const list = $("#mine-list");
        const empty = $("#mine-empty");
        loading.hidden = false;
        empty.hidden = true;
        list.replaceChildren();
        try {
            const orders = await api(config.workOrdersUrl);
            orders.forEach((order) => list.append(orderCard(order, "mine")));
            empty.hidden = orders.length !== 0;
        } catch (error) {
            showToast(error.message, "error");
            empty.textContent = "No se pudieron cargar tus órdenes.";
            empty.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    async function loadHome() {
        const availableCount = $("#home-available-count");
        const mineCount = $("#home-mine-count");
        const next = $("#home-next-order");
        availableCount.textContent = "—";
        mineCount.textContent = "—";
        next.textContent = "Cargando tus órdenes…";
        try {
            const [available, mine] = await Promise.all([
                api(`${config.workOrdersUrl}available/`),
                api(config.workOrdersUrl),
            ]);
            availableCount.textContent = String(available.length);
            mineCount.textContent = String(mine.length);
            next.replaceChildren();
            if (!mine.length) {
                next.className = "empty-state";
                next.textContent = "No tienes órdenes asignadas. Revisa la bandeja de disponibles.";
                return;
            }
            next.className = "";
            next.append(orderCard(mine[0], "mine"));
        } catch (error) {
            next.className = "empty-state";
            next.textContent = "No se pudo actualizar el resumen.";
        }
    }

    async function claimOrder(id, button) {
        setBusy(button, true, "Tomando…");
        try {
            await api(`${config.workOrdersUrl}${id}/claim/`, {
                method: "POST",
                body: JSON.stringify({}),
            });
            showToast("Orden asignada correctamente.", "success");
            openDetail(id, "available");
        } catch (error) {
            showToast(error.message, "error");
            setBusy(button, false);
            if (error.status === 409) loadAvailable();
        }
    }

    function openDetail(id, backScreen = "mine") {
        state.detailId = id;
        state.detailBackScreen = backScreen;
        navigate("detail");
    }

    function setDetailText(selector, value, fallback = "—") {
        $(selector).textContent = text(value, fallback);
    }

    function buildAddressSearchUrl(address) {
        const query = [address?.address, address?.district].filter(Boolean).join(", ");
        return query ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}` : "";
    }

    function renderDetail(order) {
        state.currentOrder = order;
        setDetailText("#detail-number", order.order_number, "OT");
        setDetailText("#detail-customer", order.customer?.display_name, "Cliente");
        setDetailText("#detail-service", `${text(order.service_type, "Servicio")} · ${text(order.plan, "Sin plan")}`);
        setDetailText("#detail-status", order.status_display || order.status, "Estado");

        const address = order.address || {};
        setDetailText("#detail-address", address.address);
        setDetailText("#detail-reference", address.reference, "Sin referencia");
        setDetailText("#detail-district", [address.district, order.zone].filter(Boolean).join(" · "), "Sin distrito/zona");

        const mapLink = $("#detail-map-link");
        const gpsUrl = address.gps_link || "";
        const fallbackUrl = buildAddressSearchUrl(address);
        mapLink.href = gpsUrl || fallbackUrl || "#";
        mapLink.hidden = !gpsUrl && !fallbackUrl;
        $("#detail-gps-note").textContent = gpsUrl
            ? "Ubicación GPS validada. La dirección textual se mantiene como referencia."
            : "GPS no disponible o inválido. El mapa buscará usando la dirección registrada.";

        renderPlan(order.plan_details);

        setDetailText("#detail-type", order.order_type);
        setDetailText("#detail-priority", order.priority_display || order.priority);
        setDetailText("#detail-branch", order.branch);
        setDetailText("#detail-reason", order.reason, "Sin motivo registrado");
        setDetailText("#detail-scheduled", formatDate(order.scheduled_at));
        setDetailText("#detail-started", formatDate(order.started_at));
        setDetailText("#detail-description", order.detail, "Sin detalle adicional.");
        renderDetailActions(order);
        configureTechnicalMode(order);
    }

    function renderPlan(plan) {
        // El bloque puede no venir: una orden cuya suscripcion se sirviera sin
        // plan dejaria `plan_details` en null. Se pinta con guiones en vez de
        // reventar, porque el resto de la ficha -direccion, motivo, horario-
        // sigue siendo util para ir a trabajar.
        const data = plan || {};

        setDetailText("#detail-plan-name", data.name, "Sin plan");
        setDetailText("#detail-plan-service", data.service_type);
        setDetailText(
            "#detail-plan-speed",
            data.speed_mbps ? `${data.speed_mbps} Mbps` : "",
            "No aplica",
        );
        setDetailText("#detail-plan-technology", data.technology, "No registrada");
        setDetailText(
            "#detail-plan-tv",
            // El cero es un dato, no un vacio: "0 puntos" significa que
            // ninguna salida de TV entra sin cargo, y el tecnico tiene que
            // saberlo antes de cablear. Por eso se compara contra null y no
            // se usa un condicional que trate el 0 como ausencia.
            data.included_tv_points === null || data.included_tv_points === undefined
                ? ""
                : `${data.included_tv_points}`,
        );
        setDetailText("#detail-plan-category", data.commercial_category_display);
        setDetailText("#detail-plan-annexes", data.annex_count);
        setDetailText("#detail-plan-tv-total", data.total_tv_points);

        // El contrato prevalece sobre el catálogo, incluso si su importe es
        // cero o no existe tarifa geográfica. No inventar precios cuando la
        // respuesta de una API antigua todavía no incluye estos campos.
        for (const [selector, amount] of [
            ["#detail-plan-monthly-base", data.base_monthly_fee],
            ["#detail-plan-monthly-annexes", data.annex_monthly_charge],
            ["#detail-plan-monthly", data.total_monthly_price],
            ["#detail-plan-installation", data.base_installation_fee],
        ]) {
            setDetailText(selector, amount == null ? "" : money(amount), "No registrada");
        }

        const note = $("#detail-plan-note");

        if (!plan) {
            note.textContent = "La suscripción de esta orden no tiene plan registrado.";
        } else {
            note.textContent = "Importes contratados de la suscripción, antes de pronto pago. " +
                "La mensualidad total incluye los anexos activos. " +
                "Las cortesías no utilizadas en la instalación inicial no quedan reservadas.";
        }
    }

    function renderDetailActions(order) {
        const actions = $("#detail-actions");
        actions.replaceChildren();
        if (order.can_start_attention) {
            const startButton = element("button", "btn btn-primary btn-block", "Iniciar atención");
            startButton.type = "button";
            startButton.addEventListener("click", () => startAttention(order.id, startButton));
            actions.append(startButton);
        }
        const refresh = element("button", "btn btn-secondary btn-block", "Actualizar Orden Técnica");
        refresh.type = "button";
        refresh.addEventListener("click", () => loadDetail(order.id));
        actions.append(refresh);
    }

    function configureTechnicalMode(order) {
        const editable = order.status === "IN_PROGRESS";
        state.detailEditable = editable;
        $("#field-sheet-mode").textContent = editable ? "Editable" : "Solo lectura";
        $("#field-sheet-help").textContent = editable
            ? "Registra la información real encontrada durante la atención."
            : "La toma de la OT no habilita datos técnicos. Primero debes iniciar la atención.";
        $("#field-materials-help").textContent = editable
            ? "Declara por separado lo que queda instalado y lo que se retira del domicilio."
            : "Inicia la atención para declarar los materiales realmente instalados o retirados.";
        $("#materials-help").textContent = editable
            ? "Registra únicamente el metraje real usado. El SICV calcula los excesos."
            : "Inicia la atención para registrar los metrajes de instalación.";

        ["#field-nap", "#field-terminal", "#field-equipment", "#field-seal", "#field-notes", "#field-save"].forEach((selector) => {
            $(selector).disabled = !editable;
        });
        [
            "#installed-material-id", "#installed-material-quantity", "#installed-material-remarks", "#installed-material-submit",
            "#removed-material-id", "#removed-material-quantity", "#removed-material-remarks", "#removed-material-submit",
        ].forEach((selector) => {
            $(selector).disabled = !editable;
        });
        ["#material-type", "#material-meters", "#material-submit"].forEach((selector) => {
            $(selector).disabled = !editable;
        });
        ["#evidence-file", "#evidence-description", "#evidence-submit"].forEach((selector) => {
            $(selector).disabled = !editable;
        });
    }

    async function loadDetail(id) {
        const loading = $("#detail-loading");
        const content = $("#detail-content");
        loading.hidden = false;
        loading.textContent = "Cargando Orden Técnica…";
        content.hidden = true;
        try {
            const order = await api(`${config.workOrdersUrl}${id}/`);
            renderDetail(order);
            await Promise.all([
                loadFieldSheet(id),
                loadFieldMaterials(id),
                loadMaterials(id),
                loadEvidences(id),
                loadCompletion(id, order),
            ]);
            content.hidden = false;
            loading.hidden = true;
        } catch (error) {
            loading.textContent = error.message;
            showToast(error.message, "error");
        }
    }

    async function startAttention(id, button) {
        setBusy(button, true, "Iniciando…");
        try {
            await api(`${config.workOrdersUrl}${id}/start/`, {
                method: "POST",
                body: JSON.stringify({}),
            });
            showToast("Atención iniciada. Ya puedes completar la ficha técnica.", "success");
            await loadDetail(id);
        } catch (error) {
            showToast(error.message, "error");
            setBusy(button, false);
        }
    }

    async function loadFieldSheet(id) {
        try {
            const sheet = await api(`${config.workOrdersUrl}${id}/field-sheet/`);
            $("#field-nap").value = sheet.nap || "";
            $("#field-terminal").value = sheet.terminal || "";
            $("#field-equipment").value = sheet.equipment_code || "";
            $("#field-seal").value = sheet.seal_number || "";
            $("#field-notes").value = sheet.notes || "";
        } catch (error) {
            showToast(`Ficha técnica: ${error.message}`, "error");
        }
    }

    async function saveFieldSheet(event) {
        event.preventDefault();
        if (!state.detailId) return;
        const button = $("#field-save");
        setBusy(button, true, "Guardando…");
        try {
            await api(`${config.workOrdersUrl}${state.detailId}/field-sheet/`, {
                method: "PATCH",
                body: JSON.stringify({
                    nap: $("#field-nap").value.trim(),
                    terminal: $("#field-terminal").value.trim(),
                    equipment_code: $("#field-equipment").value.trim(),
                    seal_number: $("#field-seal").value.trim(),
                    notes: $("#field-notes").value.trim(),
                }),
            });
            showToast("Ficha técnica guardada.", "success");
            await loadCompletion(state.detailId, state.currentOrder);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    function populateFieldMaterialCatalog(catalog) {
        ["#installed-material-id", "#removed-material-id"].forEach((selector) => {
            const select = $(selector);
            const selected = select.value;
            select.replaceChildren();
            const placeholder = element("option", "", "Seleccione material...");
            placeholder.value = "";
            select.append(placeholder);
            (catalog || []).forEach((material) => {
                const option = element("option", "", `${material.name} · ${material.unit_label}`);
                option.value = material.id;
                select.append(option);
            });
            if (selected && Array.from(select.options).some((option) => option.value === selected)) {
                select.value = selected;
            }
        });
    }

    function renderFieldMaterialList(items, listSelector, emptySelector, countSelector) {
        const list = $(listSelector);
        const empty = $(emptySelector);
        list.replaceChildren();
        $(countSelector).textContent = String(items.length);
        empty.hidden = items.length !== 0;

        items.forEach((item) => {
            const row = element("article", "material-item");
            const material = item.material || {};
            const unit = material.unit_label || material.unit_of_measure || "";
            row.append(
                element("strong", "", material.name || "Material"),
                element("p", "", `${text(item.quantity, "0")} ${unit}${item.remarks ? ` · ${item.remarks}` : ""}`),
            );
            if (state.detailEditable) {
                const remove = element("button", "btn btn-danger btn-block", "Quitar registro");
                remove.type = "button";
                remove.addEventListener("click", () => deleteFieldMaterial(item.id, remove));
                row.append(remove);
            }
            list.append(row);
        });
    }

    function renderFieldMaterials(payload) {
        populateFieldMaterialCatalog(payload?.catalog || []);
        renderFieldMaterialList(
            payload?.installed || [],
            "#installed-materials-list",
            "#installed-materials-empty",
            "#installed-materials-count",
        );
        renderFieldMaterialList(
            payload?.removed || [],
            "#removed-materials-list",
            "#removed-materials-empty",
            "#removed-materials-count",
        );
    }

    async function loadFieldMaterials(id) {
        try {
            renderFieldMaterials(await api(`${config.workOrdersUrl}${id}/field-materials/`));
        } catch (error) {
            $("#installed-materials-list").replaceChildren();
            $("#removed-materials-list").replaceChildren();
            $("#installed-materials-empty").textContent = "No se pudieron consultar los materiales instalados.";
            $("#removed-materials-empty").textContent = "No se pudieron consultar los materiales retirados.";
            $("#installed-materials-empty").hidden = false;
            $("#removed-materials-empty").hidden = false;
        }
    }

    async function saveFieldMaterial(event, movementType) {
        event.preventDefault();
        if (!state.detailId) return;

        const installed = movementType === "INSTALLED";
        const prefix = installed ? "installed" : "removed";
        const materialId = $(`#${prefix}-material-id`).value;
        const quantity = $(`#${prefix}-material-quantity`).value;
        const remarks = $(`#${prefix}-material-remarks`).value.trim();
        const button = $(`#${prefix}-material-submit`);

        if (!materialId) {
            showToast("Selecciona un material.", "error");
            return;
        }
        if (quantity === "" || Number(quantity) <= 0) {
            showToast("Ingresa una cantidad mayor a cero.", "error");
            return;
        }

        setBusy(button, true, "Guardando…");
        try {
            const payload = await api(`${config.workOrdersUrl}${state.detailId}/field-materials/`, {
                method: "POST",
                body: JSON.stringify({
                    material_id: Number(materialId),
                    movement_type: movementType,
                    quantity,
                    remarks,
                }),
            });
            $(`#${prefix}-material-quantity`).value = "";
            $(`#${prefix}-material-remarks`).value = "";
            renderFieldMaterials(payload);
            showToast(
                installed ? "Material instalado registrado." : "Material retirado registrado.",
                "success",
            );
            await loadCompletion(state.detailId, state.currentOrder);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function deleteFieldMaterial(movementId, button) {
        if (!state.detailId || !state.detailEditable) return;
        setBusy(button, true, "Quitando…");
        try {
            const payload = await api(`${config.workOrdersUrl}${state.detailId}/field-materials/`, {
                method: "DELETE",
                body: JSON.stringify({movement_id: movementId}),
            });
            renderFieldMaterials(payload);
            showToast("Registro de material eliminado.", "success");
            await loadCompletion(state.detailId, state.currentOrder);
        } catch (error) {
            showToast(error.message, "error");
            setBusy(button, false);
        }
    }

    function renderMaterials(payload) {
        const list = $("#materials-list");
        const empty = $("#materials-empty");
        const items = payload?.items || [];
        list.replaceChildren();
        $("#materials-total").textContent = `Exceso ${money(payload?.total_excess_charge)}`;
        empty.hidden = items.length !== 0;
        items.forEach((item) => {
            const row = element("article", "material-item");
            row.append(
                element("strong", "", item.material_label || item.material),
                element("p", "", `${text(item.meters_used, "0")} m usados · ${text(item.free_meters_snapshot, "0")} m incluidos · ${text(item.excess_meters, "0")} m excedentes · ${money(item.excess_charge)}`),
            );
            list.append(row);
        });
    }

    async function loadMaterials(id) {
        try {
            renderMaterials(await api(`${config.workOrdersUrl}${id}/materials/`));
        } catch (error) {
            $("#materials-list").replaceChildren();
            $("#materials-empty").textContent = "No se pudieron consultar los metrajes.";
            $("#materials-empty").hidden = false;
        }
    }

    async function saveMaterial(event) {
        event.preventDefault();
        if (!state.detailId) return;
        const meters = $("#material-meters").value;
        if (meters === "" || Number(meters) < 0) {
            showToast("Ingresa un metraje válido.", "error");
            return;
        }
        const button = $("#material-submit");
        setBusy(button, true, "Guardando…");
        try {
            await api(`${config.workOrdersUrl}${state.detailId}/materials/`, {
                method: "POST",
                body: JSON.stringify({
                    material: $("#material-type").value,
                    meters_used: meters,
                }),
            });
            $("#material-meters").value = "";
            showToast("Metraje registrado. El exceso fue calculado por el SICV.", "success");
            await loadMaterials(state.detailId);
            await loadCompletion(state.detailId, state.currentOrder);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function loadEvidences(id) {
        const list = $("#evidence-list");
        const empty = $("#evidence-empty");
        list.replaceChildren();
        try {
            const evidences = await api(`${config.workOrdersUrl}${id}/evidences/`);
            $("#evidence-count").textContent = String(evidences.length);
            empty.hidden = evidences.length !== 0;
            evidences.forEach((evidence) => {
                const item = element("article", "evidence-item");
                const link = element("a", "", evidence.description || `Evidencia #${evidence.id}`);
                link.href = evidence.file;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                const meta = element("p", "", `${formatDate(evidence.created_at)} · ${text(evidence.uploaded_by?.display_name, "Técnico")}`);
                item.append(link, meta);
                list.append(item);
            });
        } catch (error) {
            $("#evidence-count").textContent = "!";
            empty.textContent = "No se pudieron consultar las evidencias.";
            empty.hidden = false;
        }
    }

    async function uploadEvidence(event) {
        event.preventDefault();
        if (!state.detailId) return;
        const fileInput = $("#evidence-file");
        if (!fileInput.files.length) {
            showToast("Selecciona una foto o PDF.", "error");
            return;
        }
        const button = $("#evidence-submit");
        const data = new FormData();
        data.append("file", fileInput.files[0]);
        data.append("description", $("#evidence-description").value.trim());
        setBusy(button, true, "Subiendo…");
        try {
            await api(`${config.workOrdersUrl}${state.detailId}/evidences/`, {
                method: "POST",
                body: data,
            });
            fileInput.value = "";
            $("#evidence-description").value = "";
            showToast("Evidencia registrada.", "success");
            await loadEvidences(state.detailId);
            await loadCompletion(state.detailId, state.currentOrder);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    function renderCompletion(payload, order) {
        const summary = payload?.summary || {};
        $("#completion-status").textContent = payload?.status_display || order?.status_display || "Estado";
        $("#completion-sheet").textContent = summary.field_sheet_registered ? "Registrada" : "Sin datos";
        $("#completion-installed").textContent = String(summary.installed_materials || 0);
        $("#completion-removed").textContent = String(summary.removed_materials || 0);
        $("#completion-meters").textContent = String(summary.meter_records || 0);
        $("#completion-evidences").textContent = String(summary.evidences || 0);
        $("#completion-selected-result").textContent = payload?.selected_result?.name || "Sin registrar";

        const resultSelect = $("#completion-result");
        const selected = resultSelect.value;
        resultSelect.replaceChildren();
        const placeholder = element("option", "", "Seleccione resultado...");
        placeholder.value = "";
        resultSelect.append(placeholder);
        (payload?.results || []).forEach((result) => {
            const option = element("option", "", result.name);
            option.value = result.id;
            resultSelect.append(option);
        });
        if (selected && Array.from(resultSelect.options).some((option) => option.value === selected)) {
            resultSelect.value = selected;
        }

        const statusCode = payload?.status || order?.status;
        const completeForm = $("#complete-order-form");
        const liquidationForm = $("#liquidate-order-form");
        const done = $("#completion-done");
        completeForm.hidden = true;
        liquidationForm.hidden = true;
        done.hidden = true;

        if (statusCode === "IN_PROGRESS") {
            $("#completion-help").textContent = "Revisa lo registrado, selecciona el resultado real de la visita y finaliza la atención.";
            completeForm.hidden = false;
        } else if (statusCode === "ATTENDED") {
            $("#completion-help").textContent = "La atención ya terminó. Falta consolidar la liquidación técnica de esta OT.";
            liquidationForm.hidden = false;
        } else if (statusCode === "LIQUIDATED") {
            $("#completion-help").textContent = "La Orden Técnica ya fue finalizada y liquidada.";
            done.hidden = false;
        } else {
            $("#completion-help").textContent = "Inicia la atención antes de finalizar la orden.";
        }
    }

    async function loadCompletion(id, order = state.currentOrder) {
        if (!$("#completion-panel")) return;
        try {
            const payload = await api(`${config.workOrdersUrl}${id}/complete/`);
            renderCompletion(payload, order);
        } catch (error) {
            $("#completion-help").textContent = "No se pudo consultar el estado de cierre de la OT.";
        }
    }

    async function finalizeAttention(event) {
        event.preventDefault();
        if (!state.detailId) return;
        const resultId = $("#completion-result").value;
        if (!resultId) {
            showToast("Selecciona el resultado de la atención.", "error");
            return;
        }

        const button = $("#complete-order-submit");
        setBusy(button, true, "Finalizando…");
        try {
            await api(`${config.workOrdersUrl}${state.detailId}/complete/`, {
                method: "POST",
                body: JSON.stringify({
                    result_id: Number(resultId),
                    remarks: $("#completion-remarks").value.trim(),
                }),
            });
            showToast("Atención finalizada. Revisa y envía la liquidación técnica.", "success");
            await loadDetail(state.detailId);
        } catch (error) {
            showToast(error.message, "error");
            setBusy(button, false);
        }
    }

    async function finalizeLiquidation(event) {
        event.preventDefault();
        if (!state.detailId) return;
        const resolution = $("#liquidation-resolution").value.trim();
        if (!resolution) {
            showToast("Describe el trabajo ejecutado antes de finalizar la OT.", "error");
            return;
        }

        const button = $("#liquidate-order-submit");
        setBusy(button, true, "Finalizando…");
        try {
            await api(`${config.workOrdersUrl}${state.detailId}/liquidate/`, {
                method: "POST",
                body: JSON.stringify({
                    resolution_detail: resolution,
                    technical_notes: $("#liquidation-notes").value.trim(),
                    remarks: "Liquidación técnica finalizada desde el portal de campo.",
                }),
            });
            showToast("Orden Técnica liquidada correctamente.", "success");
            await loadDetail(state.detailId);
        } catch (error) {
            showToast(error.message, "error");
            setBusy(button, false);
        }
    }

    function updateNetworkStatus() {
        $("#network-banner").hidden = navigator.onLine;
    }

    function bindEvents() {
        $("#login-form").addEventListener("submit", handleLogin);
        $("#logout-button").addEventListener("click", () => logout(true));
        $("#refresh-available").addEventListener("click", loadAvailable);
        $("#refresh-mine").addEventListener("click", loadMine);
        $("#available-scope-all").addEventListener("change", loadAvailable);
        $("#detail-back").addEventListener("click", () => navigate(state.detailBackScreen));
        $("#field-sheet-form").addEventListener("submit", saveFieldSheet);
        $("#installed-material-form").addEventListener("submit", (event) => saveFieldMaterial(event, "INSTALLED"));
        $("#removed-material-form").addEventListener("submit", (event) => saveFieldMaterial(event, "REMOVED"));
        $("#materials-form").addEventListener("submit", saveMaterial);
        $("#evidence-form").addEventListener("submit", uploadEvidence);
        $("#complete-order-form").addEventListener("submit", finalizeAttention);
        $("#liquidate-order-form").addEventListener("submit", finalizeLiquidation);
        $$('[data-nav]').forEach((button) => {
            button.addEventListener("click", () => navigate(button.dataset.nav));
        });
        window.addEventListener("online", updateNetworkStatus);
        window.addEventListener("offline", updateNetworkStatus);
    }

    bootstrap();
})();
