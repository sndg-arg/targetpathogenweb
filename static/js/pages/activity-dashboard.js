(function () {
    "use strict";

    var dataEl = document.getElementById("activity-dashboard-data");
    if (!dataEl) return;

    var data = JSON.parse(dataEl.textContent);
    // Pinned to en-US rather than the browser's own locale -- this page's
    // copy is all English, so a Spanish-locale browser would otherwise mix
    // "ayer"/"hoy" (locale-driven) into English sentences (hardcoded here).
    var UI_LOCALE = "en-US";
    var numberFormat = new Intl.NumberFormat(UI_LOCALE);
    var relativeTimeFormat = (typeof Intl.RelativeTimeFormat === "function")
        ? new Intl.RelativeTimeFormat(UI_LOCALE, { numeric: "auto" })
        : null;

    var charts = [];
    var prefersReducedMotion = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Count up from 0 instead of popping straight to the final value -- a
    // small, cheap bit of motion that reads as "live dashboard" rather than
    // a static report. Skipped entirely under prefers-reduced-motion.
    function animateNumber(el, target, suffix) {
        if (!el) return;
        suffix = suffix || "";
        if (prefersReducedMotion || typeof requestAnimationFrame !== "function") {
            el.textContent = numberFormat.format(target) + suffix;
            return;
        }
        var duration = 650;
        var startTime = null;
        function step(ts) {
            if (startTime === null) startTime = ts;
            var progress = Math.min((ts - startTime) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = numberFormat.format(Math.round(target * eased)) + suffix;
            if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

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
            warning: cssVar("--tp-color-warning-border"),
            text: cssVar("--tp-color-text-secondary"),
            textMuted: cssVar("--tp-color-text-muted"),
            grid: cssVar("--tp-color-border-soft"),
            surface: cssVar("--tp-color-surface"),
            border: cssVar("--tp-color-border")
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
        Array.prototype.forEach.call(document.querySelectorAll("[data-kpi]"), function (el) {
            var key = el.getAttribute("data-kpi");
            animateNumber(el, kpis[key] || 0, el.getAttribute("data-kpi-suffix") || "");
        });
        var errorsCard = document.querySelector('[data-kpi-card="errors"]');
        if (errorsCard && kpis.errors > 0) errorsCard.classList.add("has-errors");

        Array.prototype.forEach.call(document.querySelectorAll("[data-kpi-delta]"), function (el) {
            var pct = kpis[el.getAttribute("data-kpi-delta")];
            if (pct === null || pct === undefined) {
                el.textContent = "";
                return;
            }
            var invert = el.hasAttribute("data-invert-tone");
            var good = invert ? pct <= 0 : pct >= 0;
            el.classList.toggle("is-up", good);
            el.classList.toggle("is-down", !good);
            var sign = pct > 0 ? "+" : "";
            el.textContent = sign + pct + "% " + el.getAttribute("data-delta-period");
        });

        var authenticatedIps = document.querySelector('[data-kpi-meta="unique_ips_authenticated"]');
        if (authenticatedIps && kpis.unique_ips_authenticated !== undefined) {
            authenticatedIps.textContent = countLabel(kpis.unique_ips_authenticated, "IP", "IPs") + " from logged-in sessions";
        }

        var blockedMeta = document.querySelector('[data-kpi-meta="blocked_requests"]');
        if (blockedMeta && kpis.blocked_requests !== undefined) {
            blockedMeta.textContent = requestsLabel(kpis.blocked_requests) + " never made it past the login wall";
        }
    }

    function relativeSince(isoDate) {
        var d = new Date(isoDate);
        var diffDays = Math.round((d - new Date()) / 86400000);
        var relative = relativeTimeFormat ? relativeTimeFormat.format(diffDays, "day") : d.toLocaleDateString(UI_LOCALE);
        return "Last seen " + relative + " · " + d.toLocaleString(UI_LOCALE);
    }

    // Compact form for the narrower "last seen" column in the 5-col wide
    // rows -- the full "Last seen 3 days ago · 8/30/2026, 11:30:23 PM" string
    // wraps to two ragged lines there. Same info, just on hover instead of
    // always-on.
    function relativeSinceCompact(isoDate) {
        var d = new Date(isoDate);
        var diffDays = Math.round((d - new Date()) / 86400000);
        var relative = relativeTimeFormat ? relativeTimeFormat.format(diffDays, "day") : d.toLocaleDateString(UI_LOCALE);
        return '<span title="' + escapeHtml(d.toLocaleString(UI_LOCALE)) + '">' + escapeHtml(relative) + "</span>";
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
            var lastLogin = account.last_login ? relativeSince(account.last_login) : "Never logged in";
            var badge = account.is_superuser
                ? '<span class="tp-chip tp-chip--sm">admin</span>'
                : account.is_staff
                ? '<span class="tp-chip tp-chip--sm tp-chip--meta">staff</span>'
                : '<span class="tp-chip tp-chip--sm tp-chip--homolog">user</span>';
            return (
                '<div class="activity-account-row">' +
                '<span class="activity-account-name">' + account.username + "</span>" +
                badge +
                '<span class="activity-account-lastlogin">' + lastLogin + "</span>" +
                "</div>"
            );
        }).join("");
    }

    var HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

    // user_agent and path are plain-text columns holding attacker-controlled
    // header/URL content (no DB-level format constraint like the `ip` column
    // has) -- escape before innerHTML or a crafted User-Agent becomes stored
    // XSS against whichever staff member next opens this dashboard.
    function escapeHtml(value) {
        return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) {
            return HTML_ESCAPES[c];
        });
    }

    // Well-known, self-declared automated clients -- named so the reader
    // doesn't have to parse a raw UA string to tell "Anthropic's own web
    // crawler" from "a search engine" from "a bare HTTP library". Deliberately
    // conservative: an unmatched UA (even an odd-looking one) gets no badge
    // rather than a guessed one, so a badge here is always a real signal.
    var KNOWN_BOT_SIGNATURES = [
        { label: "AI crawler", re: /claudebot|gptbot|ccbot|bytespider|perplexitybot|amazonbot|google-extended/i },
        { label: "Search crawler", re: /googlebot|bingbot|duckduckbot|yandexbot|baiduspider|slurp/i },
        { label: "HTTP client", re: /python-requests|python-urllib|python\/\d|aiohttp|go-http-client|libwww-perl|okhttp|node-fetch|axios\//i },
        { label: "Generic bot", re: /\bbot\b|crawler|spider|scraper|headlesschrome/i }
    ];

    function classifyBot(userAgent) {
        if (!userAgent) return null;
        for (var i = 0; i < KNOWN_BOT_SIGNATURES.length; i++) {
            if (KNOWN_BOT_SIGNATURES[i].re.test(userAgent)) return KNOWN_BOT_SIGNATURES[i].label;
        }
        return null;
    }

    function userAgentCell(userAgent, botLabel) {
        var safe = escapeHtml(userAgent);
        var agentHtml = safe
            ? '<span class="activity-user-agent" title="' + safe + '">' + safe + "</span>"
            : '<span class="activity-user-agent activity-user-agent--empty">—</span>';
        var badgeHtml = botLabel
            ? '<span class="tp-chip tp-chip--sm activity-bot-chip">' + escapeHtml(botLabel) + "</span>"
            : "";
        return '<span class="activity-user-agent-cell">' + agentHtml + badgeHtml + "</span>";
    }

    // Flag emoji (regional indicator pairs) render as an actual flag on
    // macOS/iOS/Android, but plain Windows (no dedicated flag font) falls
    // back to showing the two raw letters -- inconsistent width, reads as
    // broken text leaking into the UI rather than an icon. A small
    // fixed-width badge renders identically everywhere and never
    // misaligns row to row.
    function countryBadge(countryCode) {
        var code = /^[a-z]{2}$/i.test(countryCode || "") ? countryCode.toUpperCase() : "—";
        return '<span class="activity-country-badge">' + code + "</span>";
    }

    function locationPlace(row) {
        var text = row.country ? (row.city ? row.city + ", " : "") + row.country : "Unknown location";
        return countryBadge(row.country_code) + '<span class="activity-location-place-text">' + escapeHtml(text) + "</span>";
    }

    function countLabel(count, singular, plural) {
        return numberFormat.format(count) + " " + (count === 1 ? singular : plural);
    }

    function requestsLabel(count) {
        return countLabel(count, "request", "requests");
    }

    function pathsLabel(count) {
        return countLabel(count, "path", "paths");
    }

    // Groups IP-level rows (data.locations / data.login_attempts, both
    // shaped { ip, count, country, country_code, region, ... }) into one
    // entry per region+country (e.g. "Buenos Aires, Argentina") -- the
    // always-visible summary is "which places, roughly", not a per-IP list,
    // which is what the collapsed detail panel is for. Falls back to just
    // the country when ip-api didn't resolve a region (or the region name
    // duplicates the country, which it does for some city-states).
    function groupByLocation(rows) {
        var order = [];
        var byKey = {};
        rows.forEach(function (row) {
            var country = row.country || "Unknown";
            var label = row.region && row.region !== country ? row.region + ", " + country : country;
            if (!byKey[label]) {
                byKey[label] = {
                    label: label,
                    country_code: row.country_code,
                    ip_count: 0,
                    requests: 0,
                    muted: country === "Unknown"
                };
                order.push(label);
            }
            byKey[label].ip_count += 1;
            byKey[label].requests += row.count;
        });
        return order
            .map(function (key) { return byKey[key]; })
            .sort(function (a, b) { return b.requests - a.requests; });
    }

    // Shared renderer for every chip-row summary on this page (bot type,
    // country) -- also hides the collapsed detail panel's toggle entirely
    // when there's nothing to show, replacing it with just the empty-state
    // sentence (offering to "expand" an empty table is pointless).
    function renderChipSummary(selector, chips, emptyText) {
        var el = document.querySelector(selector);
        if (!el) return;
        var details = el.nextElementSibling;
        if (details && details.tagName === "DETAILS") details.hidden = !chips.length;
        if (!chips.length) {
            el.innerHTML = '<p class="activity-accounts-empty">' + emptyText + "</p>";
            return;
        }
        el.innerHTML = chips.map(function (chip) {
            var variant = chip.muted ? " activity-summary-chip--muted" : "";
            var badge = chip.country_code ? countryBadge(chip.country_code) + " " : "";
            return (
                '<span class="activity-summary-chip' + variant + '">' +
                '<strong>' + badge + escapeHtml(chip.label) + "</strong>" +
                '<span>' + countLabel(chip.ip_count, "IP", "IPs") + " · " + requestsLabel(chip.requests) + "</span>" +
                "</span>"
            );
        }).join("");
    }

    function renderAuthenticatedLocations() {
        var rows = data.locations || [];
        renderChipSummary("[data-locations-summary]", groupByLocation(rows), "No logged-in sessions yet.");
        var container = document.querySelector("[data-locations-list]");
        if (!container) return;
        if (!rows.length) {
            container.innerHTML = '<p class="activity-accounts-empty">No logged-in sessions yet.</p>';
            return;
        }
        container.innerHTML = rows.map(function (row) {
            var who = row.users && row.users.length ? row.users.join(", ") : "—";
            return (
                '<div class="activity-location-row">' +
                '<span class="activity-location-place">' + locationPlace(row) + "</span>" +
                '<span class="activity-location-ip">' + row.ip + "</span>" +
                '<span class="activity-location-users">' + who + "</span>" +
                '<span class="activity-location-count">' + requestsLabel(row.count) + "</span>" +
                "</div>"
            );
        }).join("");
    }

    function renderLoginAttempts() {
        var rows = data.login_attempts || [];
        renderChipSummary(
            "[data-login-attempts-summary]",
            groupByLocation(rows),
            "No failed login attempts in this window."
        );
        var container = document.querySelector("[data-login-attempts-list]");
        if (!container) return;
        if (!rows.length) {
            container.innerHTML = '<p class="activity-accounts-empty">No failed login attempts in this window.</p>';
            return;
        }
        container.innerHTML = rows.map(function (row) {
            return (
                '<div class="activity-location-row activity-location-row--wide">' +
                '<span class="activity-location-place">' + locationPlace(row) + "</span>" +
                '<span class="activity-location-ip">' + row.ip + "</span>" +
                userAgentCell(row.user_agent, null) +
                '<span class="activity-location-users">' + relativeSinceCompact(row.last_seen) + "</span>" +
                '<span class="activity-location-count">' + requestsLabel(row.count) + "</span>" +
                "</div>"
            );
        }).join("");
    }

    // Rollup across EVERY blocked request in the window (data.bot_traffic_summary
    // is computed server-side over the full queryset), not just the top-10-by-IP
    // rows renderBlockedAttempts() below shows -- a handful of IPs from the same
    // crawler can otherwise fill most of that table on their own and hide how
    // many distinct actors, and how much total traffic, each type represents.
    function renderBotSummary() {
        var rows = data.bot_traffic_summary || [];
        var chips = rows.map(function (row) {
            return {
                label: row.label,
                ip_count: row.ip_count,
                requests: row.requests,
                muted: row.label === "Unclassified"
            };
        });
        renderChipSummary("[data-bot-summary]", chips, "No scanning traffic in this window — nice.");
    }

    function renderBlockedAttempts() {
        var container = document.querySelector("[data-blocked-list]");
        if (!container) return;
        var rows = data.blocked_attempts || [];
        if (!rows.length) {
            container.innerHTML = '<p class="activity-accounts-empty">No scanning traffic in this window — nice.</p>';
            return;
        }
        container.innerHTML = rows.map(function (row) {
            return (
                '<div class="activity-location-row activity-location-row--wide activity-location-row--blocked">' +
                '<span class="activity-location-place">' + locationPlace(row) + "</span>" +
                '<span class="activity-location-ip">' + row.ip + "</span>" +
                userAgentCell(row.user_agent, classifyBot(row.user_agent)) +
                '<span class="activity-location-users">' + pathsLabel(row.distinct_paths) + "</span>" +
                '<span class="activity-location-count">' + requestsLabel(row.count) + "</span>" +
                "</div>"
            );
        }).join("");
    }

    function renderTopErrorPaths() {
        var container = document.querySelector("[data-error-paths-list]");
        if (!container) return;
        var rows = data.top_error_paths || [];
        if (!rows.length) {
            container.innerHTML = '<p class="activity-accounts-empty">No errors in this window — nice.</p>';
            return;
        }
        container.innerHTML = rows.map(function (row) {
            var chips = row.codes.map(function (c) {
                var variant = c.code >= 500 ? "activity-error-chip--5xx" : "activity-error-chip--4xx";
                return (
                    '<span class="activity-error-chip ' + variant + '">' +
                    c.code + " × " + numberFormat.format(c.count) +
                    "</span>"
                );
            }).join("");
            return (
                '<div class="activity-error-path-row">' +
                '<span class="activity-error-path-name">' + escapeHtml(row.path) + "</span>" +
                '<span class="activity-error-path-codes">' + chips + "</span>" +
                '<span class="activity-location-count">' + requestsLabel(row.count) + "</span>" +
                "</div>"
            );
        }).join("");
    }

    // If RequestLog's own history is shorter than the chart's window (e.g.
    // right after this logging was deployed), the early flat-then-ramp
    // reads as a real traffic spike. Name the actual cause instead.
    function renderTimeseriesNote() {
        var el = document.querySelector("[data-timeseries-note]");
        if (!el) return;
        var points = data.timeseries || [];
        if (!data.logging_started_at || !points.length) {
            el.textContent = "";
            return;
        }
        var startedAt = new Date(data.logging_started_at);
        var windowStart = new Date(points[0].date + "T00:00:00");
        if (startedAt <= windowStart) {
            el.textContent = "";
            return;
        }
        el.textContent = "Activity logging started " +
            startedAt.toLocaleDateString(UI_LOCALE, { month: "short", day: "numeric", year: "numeric" }) +
            " -- the ramp-up before that date is missing history, not a real traffic spike.";
    }

    function renderTimeseries(t) {
        var canvas = document.getElementById("activity-timeseries-chart");
        if (!canvas) return null;
        var points = data.timeseries || [];
        var labels = points.map(function (p) {
            return new Date(p.date + "T00:00:00").toLocaleDateString(UI_LOCALE, { month: "short", day: "numeric" });
        });
        // Stacked area, authenticated below anonymous/blocked -- shows the
        // real vs noise split at a glance, with the stack's total height
        // still reading as "requests that day" like the single-line version
        // used to.
        return new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Authenticated",
                        data: points.map(function (p) { return p.authenticated; }),
                        borderColor: t.brand,
                        backgroundColor: hexToRgba(t.brand, 0.35),
                        borderWidth: 2,
                        tension: 0.3,
                        fill: true,
                        stack: "requests",
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: t.brand,
                        pointHoverBorderColor: t.surface,
                        pointHoverBorderWidth: 2
                    },
                    {
                        label: "Anonymous / blocked",
                        data: points.map(function (p) { return p.anonymous; }),
                        borderColor: t.warning,
                        backgroundColor: hexToRgba(t.warning, 0.25),
                        borderWidth: 2,
                        tension: 0.3,
                        fill: true,
                        stack: "requests",
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: t.warning,
                        pointHoverBorderColor: t.surface,
                        pointHoverBorderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: baseTooltip(t)
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        ticks: { color: t.textMuted, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }
                    },
                    y: {
                        stacked: true,
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

    var STATUS_BUCKET_META = {
        "2xx": "Success",
        "3xx": "Redirects",
        "4xx": "Client errors",
        "5xx": "Server errors"
    };

    function statusPercent(count, total) {
        if (!total) return "0%";
        var pct = (count / total) * 100;
        // A handful of errors against thousands of requests rounds to "0%",
        // which reads as "no errors" -- the opposite of what a nonzero count
        // means. "<1%" keeps it both honest and legible at any proportion.
        if (count > 0 && pct < 1) return "<1%";
        return Math.round(pct) + "%";
    }

    function renderStatusTiles() {
        var container = document.querySelector("[data-status-tiles]");
        if (!container) return;
        var rows = data.status_breakdown || [];
        var total = rows.reduce(function (sum, r) { return sum + r.count; }, 0);
        if (!total) {
            container.innerHTML = '<p class="activity-chart-empty">No requests logged yet.</p>';
            return;
        }
        container.innerHTML = rows.map(function (r) {
            return (
                '<div class="activity-status-tile activity-status-tile--' + r.bucket + '">' +
                '<p class="activity-status-tile-label">' + r.bucket +
                ' <span class="activity-status-tile-sublabel">' + (STATUS_BUCKET_META[r.bucket] || "") + "</span></p>" +
                '<p class="activity-status-tile-value" data-status-value="' + r.bucket + '">0</p>' +
                '<p class="activity-status-tile-meta">' + statusPercent(r.count, total) + " of total</p>" +
                "</div>"
            );
        }).join("");

        rows.forEach(function (r) {
            animateNumber(container.querySelector('[data-status-value="' + r.bucket + '"]'), r.count);
        });
    }

    function renderCharts() {
        // Only the two chart panels below need the Chart.js vendor script
        // -- if it 404s or is blocked, KPIs/accounts/locations/status tiles
        // (already rendered above by the time this runs) must still work.
        if (typeof Chart === "undefined") return;
        charts.forEach(function (c) { c.destroy(); });
        charts = [];
        var t = theme();
        [renderTimeseries(t), renderTopPages(t)].forEach(function (c) {
            if (c) charts.push(c);
        });
    }

    renderKpis();
    renderAccounts();
    renderAuthenticatedLocations();
    renderLoginAttempts();
    renderBotSummary();
    renderBlockedAttempts();
    renderStatusTiles();
    renderTopErrorPaths();
    renderTimeseriesNote();
    renderCharts();

    var themeObserver = new MutationObserver(function () { renderCharts(); });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
})();
