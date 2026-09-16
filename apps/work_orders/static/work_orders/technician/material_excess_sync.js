(() => {
    "use strict";

    const tokenKey = "sicv.technician.token";
    const nativeFetch = window.fetch.bind(window);

    function text(value, fallback = "0") {
        if (value === null || value === undefined || value === "") return fallback;
        return String(value);
    }

    function money(value) {
        const number = Number(value || 0);
        return Number.isFinite(number) ? `S/ ${number.toFixed(2)}` : "S/ 0.00";
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
        const headers = new Headers();
        const token = sessionStorage.getItem(tokenKey);
        if (token) headers.set("Authorization", `Token ${token}`);

        try {
            const response = await nativeFetch(materialsUrl, {headers});
            if (!response.ok) return;
            const payload = await response.json();
            renderAutomaticExcess(payload);
        } catch (_error) {
            // El flujo principal ya informa errores de red. Este refresco solo
            // mantiene sincronizado el resumen visual y no debe duplicar avisos.
        }
    }

    window.fetch = async function (input, init = {}) {
        const response = await nativeFetch(input, init);

        try {
            const url = typeof input === "string" ? input : input.url;
            const method = String(
                init.method || (typeof input !== "string" ? input.method : "GET")
            ).toUpperCase();

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
        } catch (_error) {
            // Nunca se altera la respuesta original del API por un refresco UI.
        }

        return response;
    };
})();
