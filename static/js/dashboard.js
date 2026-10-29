const dashboardWorkspace = document.getElementById("dashboardWorkspace");
const sidebarToggle = document.getElementById("dashboardSidebarToggle");
const sidebar = document.getElementById("dashboardSidebar");
const mobileWorkspace = window.matchMedia("(max-width: 991.98px)");

if (dashboardWorkspace && sidebarToggle && sidebar) {
    const updateSidebarButton = () => {
        const expanded = mobileWorkspace.matches
            ? dashboardWorkspace.classList.contains("is-sidebar-open")
            : !dashboardWorkspace.classList.contains("is-sidebar-collapsed");
        sidebarToggle.setAttribute("aria-expanded", String(expanded));
        sidebarToggle.setAttribute(
            "aria-label",
            expanded ? "Collapse workspace navigation" : "Expand workspace navigation"
        );
    };

    sidebarToggle.addEventListener("click", () => {
        if (mobileWorkspace.matches) {
            dashboardWorkspace.classList.toggle("is-sidebar-open");
        } else {
            dashboardWorkspace.classList.toggle("is-sidebar-collapsed");
        }
        updateSidebarButton();
    });

    dashboardWorkspace.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && mobileWorkspace.matches) {
            dashboardWorkspace.classList.remove("is-sidebar-open");
            sidebarToggle.focus();
            updateSidebarButton();
        }
    });

    mobileWorkspace.addEventListener("change", () => {
        dashboardWorkspace.classList.remove("is-sidebar-open", "is-sidebar-collapsed");
        updateSidebarButton();
    });

    updateSidebarButton();
}

const chartDataElement = document.getElementById("dashboard-chart-data");

if (chartDataElement) {
    const showChartState = (chartId, message) => {
        const chartContainer = document.querySelector(`[data-chart="${chartId}"]`);
        if (!chartContainer) {
            return;
        }
        const canvas = chartContainer.querySelector("canvas");
        const state = chartContainer.querySelector(".dashboard-chart-state");
        if (canvas) {
            canvas.hidden = true;
        }
        if (state) {
            state.textContent = message;
            state.hidden = false;
        }
    };

    let dashboardData;
    try {
        dashboardData = JSON.parse(chartDataElement.textContent);
    } catch (error) {
        console.error("Could not read dashboard chart data.", error);
        document.querySelectorAll(".dashboard-chart").forEach((chart) => {
            const canvas = chart.querySelector("canvas");
            const state = chart.querySelector(".dashboard-chart-state");
            if (canvas) {
                canvas.hidden = true;
            }
            if (state) {
                state.textContent = "Chart data could not be loaded.";
                state.hidden = false;
            }
        });
    }

    if (dashboardData) {
        const chartDefinitions = [
            {
                id: "predictionChart",
                key: "prediction_distribution",
                emptyMessage: "No transaction predictions are available yet.",
                type: "doughnut",
                dataset: (series) => ({
                    data: series.values,
                    backgroundColor: ["#15803D", "#B91C1C"],
                    borderColor: "#FFFFFF",
                    borderWidth: 3,
                }),
            },
            {
                id: "riskChart",
                key: "risk_distribution",
                emptyMessage: "No risk-level data is available yet.",
                type: "bar",
                dataset: (series) => ({
                    label: "Transactions",
                    data: series.values,
                    backgroundColor: ["#15803D", "#B45309", "#B91C1C"],
                    borderRadius: 5,
                }),
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
            },
            {
                id: "typeChart",
                key: "transaction_types",
                emptyMessage: "No transaction type data is available yet.",
                type: "bar",
                dataset: (series) => ({
                    label: "Transactions",
                    data: series.values,
                    backgroundColor: "#C47A50",
                    borderRadius: 5,
                }),
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
            },
            {
                id: "trendChart",
                key: "risk_trend",
                emptyMessage: "No transaction trend data is available for the last 14 days.",
                type: "line",
                dataset: (series) => ({
                    label: "Average fraud probability (%)",
                    data: series.values,
                    borderColor: "#98512F",
                    backgroundColor: "rgba(196, 122, 80, 0.16)",
                    pointBackgroundColor: "#17243A",
                    pointRadius: 3,
                    fill: true,
                    tension: 0.25,
                }),
                scales: { y: { beginAtZero: true, max: 100 } },
            },
            {
                id: "reviewChart",
                key: "flagged_review_status",
                emptyMessage: "No model-flagged transactions are available for review.",
                type: "bar",
                dataset: (series) => ({
                    label: "Model-flagged transactions",
                    data: series.values,
                    backgroundColor: "#27364B",
                    borderRadius: 5,
                }),
                indexAxis: "y",
                scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
            },
        ];

        if (typeof Chart === "undefined") {
            chartDefinitions.forEach(({ id }) =>
                showChartState(id, "Charts are unavailable because the charting library did not load.")
            );
        } else {
            const textColor = getComputedStyle(document.documentElement)
                .getPropertyValue("--color-content-secondary")
                .trim();

            chartDefinitions.forEach((definition) => {
                const series = dashboardData[definition.key];
                const hasValues = series && series.values.some((value) => Number(value) > 0);
                const hasLabels = series && series.labels.length > 0;
                if (!hasValues || (definition.key === "risk_trend" && !hasLabels)) {
                    showChartState(
                        definition.id,
                        definition.emptyMessage
                    );
                    return;
                }

                const canvas = document.getElementById(definition.id);
                if (!canvas) {
                    return;
                }
                try {
                    new Chart(canvas, {
                        type: definition.type,
                        data: {
                            labels: series.labels,
                            datasets: [definition.dataset(series)],
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            indexAxis: definition.indexAxis || "x",
                            plugins: {
                                legend: {
                                    display: definition.type === "doughnut",
                                    position: "bottom",
                                    labels: { color: textColor, usePointStyle: true, padding: 18 },
                                },
                            },
                            scales: definition.scales
                                ? {
                                    ...definition.scales,
                                    [definition.indexAxis === "y" ? "x" : "y"]: {
                                        ...definition.scales[definition.indexAxis === "y" ? "x" : "y"],
                                        ticks: {
                                            ...definition.scales[definition.indexAxis === "y" ? "x" : "y"].ticks,
                                            color: textColor,
                                        },
                                        grid: { color: "rgba(39, 54, 75, 0.08)" },
                                    },
                                    [definition.indexAxis === "y" ? "y" : "x"]: {
                                        ticks: {
                                            color: textColor,
                                            ...(definition.indexAxis === "y" ? {} : { autoSkip: true, maxRotation: 0 }),
                                        },
                                        grid: { display: false },
                                    },
                                }
                                : undefined,
                        },
                    });
                } catch (error) {
                    console.error(`Could not render dashboard chart: ${definition.id}.`, error);
                    showChartState(definition.id, "This chart could not be rendered.");
                }
            });
        }
    }
}
