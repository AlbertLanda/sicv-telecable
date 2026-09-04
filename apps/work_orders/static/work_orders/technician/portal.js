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
        sessionStorage.removeItem(tokenKey);
        showLogin();
        if (showMessage) showToast("Sesión cerrada.", "success");
    }

    async function bootstrap() {
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
        $("#field-sheet-mode").textContent = editable ? "Editable" : "Solo lectura";
        $("#field-sheet-help").textContent = editable
            ? "Registra la información real encontrada durante la atención."
            : "La toma de la OT no habilita datos técnicos. Primero debes iniciar la atención.";
        $("#materials-help").textContent = editable
            ? "Registra únicamente el metraje real usado. El SICV calcula los excesos."
            : "Inicia la atención para registrar los metrajes de instalación.";

        ["#field-nap", "#field-terminal", "#field-equipment", "#field-seal", "#field-notes", "#field-save"].forEach((selector) => {
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
            await Promise.all([loadFieldSheet(id), loadMaterials(id), loadEvidences(id)]);
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
        } catch (error) {
            showToast(error.message, "error");
        } finally {
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
        } catch (error) {
            showToast(error.message, "error");
        } finally {
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
        $("#materials-form").addEventListener("submit", saveMaterial);
        $("#evidence-form").addEventListener("submit", uploadEvidence);
        $$('[data-nav]').forEach((button) => {
            button.addEventListener("click", () => navigate(button.dataset.nav));
        });
        window.addEventListener("online", updateNetworkStatus);
        window.addEventListener("offline", updateNetworkStatus);
    }

    bootstrap();
})();
