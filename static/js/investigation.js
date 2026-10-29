const dimensionElement = document.getElementById("investigation-dimensions");
if (dimensionElement && window.Chart) {
    const dimensions = JSON.parse(dimensionElement.textContent);
    const available = Object.entries(dimensions).filter(([, value]) => value !== null);
    if (available.length >= 3) {
        new Chart(document.getElementById("investigationRadar"), {
            type: "radar",
            data: {
                labels: available.map(([name]) => name),
                datasets: [{ label: "Risk dimension", data: available.map(([, value]) => value), backgroundColor: "rgba(220,53,69,.18)", borderColor: "#dc3545", pointBackgroundColor: "#dc3545" }]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { r: { min: 0, max: 100, ticks: { stepSize: 20 } } } }
        });
    } else {
        document.getElementById("investigationRadar").replaceWith(Object.assign(document.createElement("p"), { className: "text-muted", textContent: "Not enough dimensions are available for a radar chart." }));
    }
}
