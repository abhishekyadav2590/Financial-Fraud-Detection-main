const statementDataElement = document.getElementById("statement-chart-data");
if (statementDataElement && window.Chart) {
    const data = JSON.parse(statementDataElement.textContent);
    const chart = (id, type, source, label, colors) => new Chart(document.getElementById(id), {
        type,
        data: { labels: source.labels, datasets: [{ label, data: source.values, backgroundColor: colors, borderColor: "#0d6efd", borderWidth: 2, tension: 0.25 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === "doughnut" } }, scales: type === "doughnut" ? {} : { y: { beginAtZero: true } } }
    });
    chart("statementRiskChart", "doughnut", data.risk, "Transactions", ["#198754", "#ffc107", "#dc3545"]);
    chart("statementSpendChart", "line", data.spending, "Spending", "rgba(13,110,253,.25)");
    chart("statementHourChart", "bar", data.hours, "Transactions", "rgba(23,63,109,.75)");
    chart("statementMerchantChart", "bar", data.merchants, "Transactions", "rgba(13,110,253,.7)");
}
