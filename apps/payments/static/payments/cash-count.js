(() => {
  const form = document.getElementById("cash-count");
  if (!form) return;
  const fields = Array.from(form.querySelectorAll("[data-denomination]"));
  const money = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN" });
  const cents = value => Math.round(Number(value) * 100);
  const update = () => {
    const valid = fields.every(field => /^\d+$/.test(field.value) && Number(field.value) <= 1000000);
    const counted = fields.reduce((sum, field) => sum + cents(field.dataset.denomination) * Number(field.value), 0);
    document.getElementById("cash-count-total").textContent = valid ? money.format(counted / 100) : "Revise las cantidades";
    document.getElementById("cash-count-difference").textContent = valid ? money.format((counted - cents(form.dataset.expected)) / 100) : "Pendiente";
  };
  form.addEventListener("input", update);
  update();
})();
