document.addEventListener("DOMContentLoaded", () => {
    const source = document.getElementById("contribution-data");
    const canvas = document.getElementById("contributionChart");
    if (!source || !canvas || typeof Chart === "undefined") return;
    const factors = JSON.parse(source.textContent).sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
    new Chart(canvas, {type: "bar", data: {labels: factors.map(item => item.label), datasets: [{label: "Contribution to fraud log-odds", data: factors.map(item => item.contribution), backgroundColor: factors.map(item => item.contribution >= 0 ? "rgba(220,53,69,.75)" : "rgba(25,135,84,.75)"), borderColor: factors.map(item => item.contribution >= 0 ? "#dc3545" : "#198754"), borderWidth: 1}]}, options: {indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}, tooltip: {callbacks: {afterLabel: context => factors[context.dataIndex].impact}}}, scales: {x: {title: {display: true, text: "Log-odds contribution"}}}}});
});
