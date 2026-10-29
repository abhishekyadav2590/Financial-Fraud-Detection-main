document.addEventListener("DOMContentLoaded", () => {
    const source = document.getElementById("model-intelligence-data");
    if (!source || typeof Chart === "undefined") return;
    const data = JSON.parse(source.textContent);
    const chart = (id, config) => { const canvas = document.getElementById(id); if (canvas) new Chart(canvas, config); };
    if (data.dataset) chart("classDistributionChart", {type: "doughnut", data: {labels: ["Genuine", "Fraud"], datasets: [{data: [data.dataset.genuine_count, data.dataset.fraud_count], backgroundColor: ["#198754", "#dc3545"]}]}, options: {responsive: true, maintainAspectRatio: false}});
    if (data.histogram) {
        const labels = data.histogram.bin_edges.slice(0, -1).map((edge, i) => `${Math.round(edge * 100)}–${Math.round(data.histogram.bin_edges[i + 1] * 100)}%`);
        chart("probabilityChart", {type: "bar", data: {labels, datasets: [{label: "Genuine", data: data.histogram.genuine_counts, backgroundColor: "rgba(25,135,84,.65)"}, {label: "Fraud", data: data.histogram.fraud_counts, backgroundColor: "rgba(220,53,69,.65)"}]}, options: {responsive: true, maintainAspectRatio: false, scales: {x: {stacked: true}, y: {stacked: true}}}});
    }
    if (data.roc) chart("rocChart", {type: "line", data: {datasets: [{label: "Model ROC", data: data.roc.false_positive_rate.map((x, i) => ({x, y: data.roc.true_positive_rate[i]})), borderColor: "#0d6efd", pointRadius: 0}, {label: "Random", data: [{x:0,y:0},{x:1,y:1}], borderColor: "#adb5bd", borderDash: [5,5], pointRadius: 0}]}, options: {responsive: true, maintainAspectRatio: false, scales: {x: {type:"linear", min:0, max:1, title:{display:true,text:"False Positive Rate"}}, y:{min:0,max:1,title:{display:true,text:"True Positive Rate"}}}}});
    if (data.pr) chart("prChart", {type: "line", data: {datasets: [{label: "Precision-Recall", data: data.pr.recall.map((x, i) => ({x, y: data.pr.precision[i]})), borderColor: "#6f42c1", pointRadius: 0}]}, options: {responsive: true, maintainAspectRatio: false, scales: {x:{type:"linear",min:0,max:1,title:{display:true,text:"Recall"}},y:{min:0,max:1,title:{display:true,text:"Precision"}}}}});
    if (data.features) chart("featureInfluenceChart", {type: "bar", data: {labels: data.features.map(item => item.label), datasets: [{data: data.features.map(item => item.coefficient), backgroundColor: data.features.map(item => item.coefficient >= 0 ? "rgba(220,53,69,.7)" : "rgba(25,135,84,.7)")}]}, options: {indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{title:{display:true,text:"Fitted coefficient"}}}}});
});
