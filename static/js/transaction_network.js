(() => {
    "use strict";
    const container = document.getElementById("transaction-network");
    if (!container) return;
    const data = JSON.parse(document.getElementById("network-data").textContent);
    const config = JSON.parse(document.getElementById("network-config").textContent);
    const relationships = new Map(data.relationships.map(item => [item.id, item]));
    const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;"})[char]);
    const money = value => new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR"}).format(value);
    const investigateUrl = row => config.investigate_template.replace("999999", String(row));
    const colors = {LOW: "#16875d", MEDIUM: "#c97809", HIGH: "#d23b4d"};
    let cy;

    try {
        cy = cytoscape({
            container,
            elements: [...data.nodes, ...data.edges],
            layout: {name: "concentric", concentric: node => node.id() === "account" ? 10 : 1, levelWidth: () => 1, minNodeSpacing: 55, animate: false},
            minZoom: 0.25, maxZoom: 2.5,
            style: [
                {selector: "node", style: {"label": "data(label)", "width": "data(size)", "height": "data(size)", "background-color": ele => colors[ele.data("risk_level")], "border-width": 4, "border-color": "#fff", "font-size": 11, "font-weight": 650, "text-wrap": "wrap", "text-max-width": 100, "text-valign": "bottom", "text-margin-y": 8, "color": "#17233a", "overlay-opacity": 0}},
                {selector: "node[type = 'ACCOUNT']", style: {"background-color": "#12345b", "color": "#081528", "font-size": 13, "font-weight": 750}},
                {selector: "edge", style: {"width": "data(width)", "line-color": ele => colors[ele.data("risk_level")], "curve-style": "bezier", "opacity": .68, "label": "data(label)", "font-size": 9, "text-background-color": "#fff", "text-background-opacity": .9, "text-background-padding": 2}},
                {selector: ":selected", style: {"border-color": "#246bfd", "border-width": 6, "line-color": "#246bfd", "opacity": 1, "z-index": 99}},
                {selector: ".filtered", style: {"display": "none"}}
            ]
        });
    } catch (error) {
        document.getElementById("network-render-error").classList.remove("d-none");
        return;
    }

    const detail = document.getElementById("network-detail");
    function showRelationship(id) {
        const item = relationships.get(id);
        if (!item) return;
        const badges = item.risk_indicators.length ? item.risk_indicators.map(label => `<span class="badge text-bg-light border">${escapeHtml(label)}</span>`).join(" ") : '<span class="text-muted small">No relationship-level indicators detected.</span>';
        const timeline = item.transactions.map(tx => `<div class="network-timeline-item"><span class="timeline-marker"></span><div><strong>${escapeHtml(String(tx.date).replace("T", " "))}</strong><div>${money(tx.amount)} <span class="risk-badge risk-${escapeHtml(tx.risk_level.toLowerCase())}">${escapeHtml(tx.risk_level)} ${tx.risk_score}/100</span></div><small class="text-muted">${escapeHtml(tx.reason)}</small>${tx.investigable ? `<div><a class="btn btn-sm btn-investigate mt-2" href="${investigateUrl(tx.row_number)}"><i class="bi bi-shield-exclamation me-1"></i>AI Investigate</a></div>` : ""}</div></div>`).join("");
        const highest = [...item.transactions].filter(tx => tx.investigable).sort((a, b) => b.risk_score - a.risk_score)[0];
        detail.innerHTML = `<div class="d-flex justify-content-between gap-2 align-items-start"><div><div class="data-label">Merchant / Payee</div><h3 class="h5 mt-1">${escapeHtml(item.merchant_or_payee)}</h3></div><span class="risk-badge risk-${item.risk_level.toLowerCase()}">${item.relationship_risk_score}/100</span></div>
        <div class="network-detail-grid"><div><span>Transactions</span><strong>${item.transaction_count}</strong></div><div><span>Total Amount</span><strong>${money(item.total_amount)}</strong></div><div><span>Average Amount</span><strong>${money(item.average_amount)}</strong></div><div><span>Average Risk</span><strong>${item.average_risk}/100</strong></div><div><span>Highest Risk</span><strong>${item.maximum_risk}/100</strong></div><div><span>High-Risk Transactions</span><strong>${item.high_risk_count}</strong></div><div><span>First Seen</span><strong>${escapeHtml(item.first_observed.replace("T", " "))}</strong></div><div><span>Last Seen</span><strong>${escapeHtml(item.last_observed.replace("T", " "))}</strong></div></div>
        <div class="small text-muted mb-3">${item.spending_concentration_pct}% of statement spending · ${item.risk_concentration_pct}% of HIGH-risk activity</div>
        <h4 class="h6">Risk Indicators</h4><div class="d-flex flex-wrap gap-2 mb-3">${badges}</div>
        ${highest ? `<a class="btn btn-investigate w-100 mb-3" href="${investigateUrl(highest.row_number)}"><i class="bi bi-shield-exclamation me-1"></i>Investigate Highest-Risk Transaction</a>` : ""}
        <h4 class="h6">Related Transactions</h4><div class="network-timeline">${timeline}</div>`;
    }

    function focusRelationship(id) {
        showRelationship(id);
        const node = cy.getElementById(id);
        if (node.nonempty() && node.visible()) {
            cy.elements().unselect(); node.select(); cy.animate({center: {eles: node}, zoom: Math.max(cy.zoom(), 1)}, {duration: 250});
        } else {
            detail.scrollIntoView({behavior: "smooth", block: "nearest"});
        }
    }
    cy.on("tap", "node[type != 'ACCOUNT'], edge", event => focusRelationship(event.target.data("relationship_id")));
    document.querySelectorAll(".relationship-focus").forEach(button => button.addEventListener("click", () => focusRelationship(button.dataset.relationshipId)));

    function applyFilters() {
        const risk = document.getElementById("risk-filter").value;
        const count = Number(document.getElementById("count-filter").value);
        const suspicious = document.getElementById("show-filter").value === "SUSPICIOUS";
        cy.batch(() => {
            data.relationships.forEach(item => {
                const visible = item.displayed && (risk === "ALL" || item.risk_level === risk) && item.transaction_count >= count && (!suspicious || item.relationship_risk_score >= 30);
                cy.getElementById(item.id).toggleClass("filtered", !visible);
                cy.getElementById(`edge-${item.id}`).toggleClass("filtered", !visible);
            });
        });
        cy.fit(cy.elements(":visible"), 45);
    }
    ["risk-filter", "count-filter", "show-filter"].forEach(id => document.getElementById(id).addEventListener("change", applyFilters));
    document.getElementById("fit-network").addEventListener("click", () => cy.fit(cy.elements(":visible"), 45));
    document.getElementById("reset-network").addEventListener("click", () => {
        document.getElementById("risk-filter").value = "ALL"; document.getElementById("count-filter").value = "1"; document.getElementById("show-filter").value = "ALL";
        applyFilters(); cy.layout({name: "concentric", concentric: node => node.id() === "account" ? 10 : 1, levelWidth: () => 1, minNodeSpacing: 55, animate: false}).run(); cy.fit(undefined, 45);
    });
    document.getElementById("focus-risk").addEventListener("click", () => focusRelationship(data.relationships[0].id));
})();
