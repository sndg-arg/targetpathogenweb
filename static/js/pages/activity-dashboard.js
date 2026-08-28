(function () {
    "use strict";

    var dataEl = document.getElementById("activity-dashboard-data");
    if (!dataEl || typeof Chart === "undefined") return;

    var data = JSON.parse(dataEl.textContent);
    var numberFormat = new Intl.NumberFormat();
    var relativeTimeFormat = (typeof Intl.RelativeTimeFormat === "function")
        ? new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })
        : null;

    var charts = [];

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function hexToRgba(hex, alpha) {
        var clean = hex.replace("#", "");
        if (clean.length === 3) {
            clean = clean.split("").map(function (c) { return c + c; }).join("");
        }
        var r = parseInt(clean.substring(0, 2), 16);
        var g = parseInt(clean.substring(2, 4), 16);
        var b = parseInt(clean.substring(4, 6), 16);
        return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
    }

    function theme() {
        return {
            brand: cssVar("--tp-color-brand-600"),
            text: cssVar("--tp-color-text-secondary"),
            textMuted: cssVar("--tp-color-text-muted"),
            grid: cssVar("--tp-color-border-soft"),
            surface: cssVar("--tp-color-surface"),
            border: cssVar("--tp-color-border"),
            status: {
                "2xx": cssVar("--tp-color-success-ink"),
                "3xx": cssVar("--tp-color-info-ink"),
                "4xx": cssVar("--tp-color-warning-ink"),
                "5xx": cssVar("--tp-color-danger-ink")
            }
        };
    }

    function baseTooltip(t) {
        return {
            backgroundColor: t.surface,
            titleColor: t.text,
            bodyColor: t.text,
            borderColor: t.border,
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8,
            displayColors: false
        };
    }

    function renderKpis() {
        var kpis = data.kpis || {};
        Object.keys(kpis).forEach(function (key) {
            var el = document.querySelector('[data-kpi="' + key + '"]');
            if (el) el.textContent = numberFormat.format(kpis[key] || 0);
        });
        var errorsCard = document.querySelector('[data-kpi-card="errors"]');
        if (errorsCard && kpis.errors > 0) errorsCard.classList.add("has-errors");
    }

    function renderAccounts() {
        var container = document.querySelector("[data-accounts-list]");
        if (!container) return;
        var accounts = data.accounts || [];
        if (!accounts.length) {
            container.innerHTML = '<p class="activity-accounts-empty">No active accounts.</p>';
            return;
        }
        container.innerHTML = accounts.map(function (account) {
            var lastLogin = "Never logged in";
            if (account.last_login) {
                var d = new Date(account.last_login);
                var diffDays = Math.round((d - new Date()) / 86400000);
                lastLogin = "Last seen " + (relativeTimeFormat ? relativeTimeFormat.format(diffDays, "day") : d.toLocaleDateString());
                lastLogin += " · " + d.toLocaleString();
            }
            var badge = account.is_superuser
                ? '<span class="tp-chip tp-chip--sm">admin</span>'
                : '<span class="tp-chip tp-chip--sm tp-chip--meta">staff</span>';
            return (
                '<div class="activity-account-row">' +
                '<span class="activity-account-name">' + account.username + "</span>" +
                badge +
                '<span class="activity-account-lastlogin">' + lastLogin + "</span>" +
                "</div>"
            );
        }).join("");
    }

    function renderTimeseries(t) {
        var canvas = document.getElementById("activity-timeseries-chart");
        if (!canvas) return null;
        var points = data.timeseries || [];
        var labels = points.map(function (p) {
            return new Date(p.date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
        });
        return new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Requests",
                    data: points.map(function (p) { return p.count; }),
                    borderColor: t.brand,
                    backgroundColor: hexToRgba(t.brand, 0.1),
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: t.brand,
                    pointHoverBorderColor: t.surface,
                    pointHoverBorderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, baseTooltip(t), { displayColors: false })
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: t.textMuted, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: t.grid, drawTicks: false },
                        border: { display: false },
                        ticks: { color: t.textMuted, precision: 0 }
                    }
                }
            }
        });
    }

    function renderTopPages(t) {
        var canvas = document.getElementById("activity-top-pages-chart");
        if (!canvas) return null;
        var rows = data.top_pages || [];
        if (!rows.length) {
            canvas.closest(".activity-chart-wrap").innerHTML = '<p class="activity-chart-empty">No page views yet.</p>';
            return null;
        }
        return new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: rows.map(function (r) { return r.path; }),
                datasets: [{
                    data: rows.map(function (r) { return r.count; }),
                    backgroundColor: t.brand,
                    borderRadius: 4,
                    barThickness: 16,
                    maxBarThickness: 20
                }]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: baseTooltip(t)
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: t.grid, drawTicks: false },
                        border: { display: false },
                        ticks: { color: t.textMuted, precision: 0 }
                    },
                    y: {
                        grid: { display: false },
                        border: { display: false },
                        ticks: { color: t.text }
                    }
                }
            }
        });
    }

    function renderStatusBreakdown(t) {
        var canvas = document.getElementById("activity-status-chart");
        if (!canvas) return null;
        var rows = data.status_breakdown || [];
        var total = rows.reduce(function (sum, r) { return sum + r.count; }, 0);
        if (!total) {
            canvas.closest(".activity-chart-wrap").innerHTML = '<p class="activity-chart-empty">No requests logged yet.</p>';
            return null;
        }
        var datasets = rows.map(function (r) {
            return {
                label: r.bucket + " (" + numberFormat.format(r.count) + ")",
                data: [r.count],
                backgroundColor: t.status[r.bucket],
                borderColor: t.surface,
                borderWidth: 2,
                borderRadius: 4,
                barThickness: 22
            };
        });
        return new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: { labels: ["Requests"], datasets: datasets },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: t.textMuted, boxWidth: 10, boxHeight: 10, padding: 14 }
                    },
                    tooltip: baseTooltip(t)
                },
                scales: {
                    x: { stacked: true, display: false },
                    y: { stacked: true, display: false }
                }
            }
        });
    }

    function renderCharts() {
        charts.forEach(function (c) { c.destroy(); });
        charts = [];
        var t = theme();
        [renderTimeseries(t), renderTopPages(t), renderStatusBreakdown(t)].forEach(function (c) {
            if (c) charts.push(c);
        });
    }

    renderKpis();
    renderAccounts();
    renderCharts();

    var themeObserver = new MutationObserver(function () { renderCharts(); });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
})();
