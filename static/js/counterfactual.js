document.addEventListener("DOMContentLoaded", () => {
    const source = document.getElementById("counterfactual-data");
    const canvas = document.getElementById("counterfactualChart");
    if (!source || !canvas || typeof Chart === "undefined") return;
    const scenarios = JSON.parse(source.textContent);
    new Chart(canvas, {type: "bar", data: {labels: scenarios.map(item => item.changed_fields.map(change => `${change.label}: ${change.after}`).join(" + ")), datasets: [{data: scenarios.map(item => item.new_probability * 100), backgroundColor: scenarios.map(item => item.percentage_point_change < 0 ? "rgba(25,135,84,.75)" : "rgba(220,53,69,.75)")}]}, options: {indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}, tooltip: {callbacks: {label: context => `${context.raw.toFixed(2)}% predicted fraud probability`}}}, scales: {x: {beginAtZero: true, max: 100, title: {display: true, text: "Predicted fraud probability (%)"}}}}});
});
