(function () {
    "use strict";

    function readToken(name, fallback) {
        var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return value || fallback;
    }

    function text(value, max) {
        value = value || "";
        if (value.length <= max) return value;
        return value.slice(0, max - 1) + "...";
    }

    function makeSvg(tag, attrs) {
        var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
        Object.keys(attrs || {}).forEach(function (key) {
            el.setAttribute(key, attrs[key]);
        });
        return el;
    }

    function addText(svg, value, x, y, className, maxLen) {
        var t = makeSvg("text", { x: x, y: y, class: className || "" });
        t.textContent = text(value, maxLen || 28);
        addTitle(t, value);
        svg.appendChild(t);
        return t;
    }

    function addTitle(el, value) {
        if (!value) return el;
        var title = makeSvg("title", {});
        title.textContent = value;
        el.appendChild(title);
        return el;
    }

    function metaboliteKey(item) {
        return (item.species_id || item.name || "").toLowerCase();
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatRole(role) {
        if (!role || role === "none") return "None";
        return role.replace(/_/g, " ");
    }

    function reactionTooltipHtml(reaction) {
        var badge = reaction.is_chokepoint
            ? '<span class="metabolic-network-tooltip-badge">' + escapeHtml(formatRole(reaction.chokepoint_role)) + '</span>'
            : "";
        var genes = (reaction.genes || []).map(function (g) { return g.accession; });
        return [
            '<div class="metabolic-network-tooltip-title">' + escapeHtml(reaction.name || reaction.id) + badge + '</div>',
            '<dl>',
            '<dt>EC</dt><dd>' + escapeHtml((reaction.ec_numbers || []).join(", ") || "-") + '</dd>',
            '<dt>KEGG</dt><dd>' + escapeHtml(reaction.kegg_reaction_id || "-") + '</dd>',
            '<dt>Genes</dt><dd>' + escapeHtml(genes.length ? genes.join(", ") : "No mapped protein") + '</dd>',
            '</dl>',
            genes.length ? '<div class="metabolic-network-tooltip-hint">Click a gene label to open its protein page.</div>' : ""
        ].join("");
    }

    function metaboliteTooltipHtml(item, role) {
        return [
            '<div class="metabolic-network-tooltip-title">' + escapeHtml(item.name || item.species_id) + '</div>',
            '<dl>',
            '<dt>Role</dt><dd>' + escapeHtml(role) + '</dd>',
            '<dt>Compartment</dt><dd>' + escapeHtml(item.compartment || "-") + '</dd>',
            '<dt>Type</dt><dd>' + (item.is_currency ? "Currency metabolite" : "Pathway metabolite") + '</dd>',
            '</dl>'
        ].join("");
    }

    function ensureTooltip(shell) {
        var tooltip = shell.querySelector(".metabolic-pathway-map-tooltip");
        if (!tooltip) {
            tooltip = document.createElement("div");
            tooltip.className = "metabolic-network-tooltip metabolic-pathway-map-tooltip";
            tooltip.style.display = "none";
            shell.appendChild(tooltip);
        }
        return tooltip;
    }

    function makeTooltipController(shell) {
        var tooltip = ensureTooltip(shell);
        var pinnedKey = null;

        function positionAt(evt) {
            var rect = shell.getBoundingClientRect();
            tooltip.style.left = (evt.clientX - rect.left + 16) + "px";
            tooltip.style.top = (evt.clientY - rect.top + 16) + "px";
        }

        function show(html, evt) {
            tooltip.innerHTML = html;
            tooltip.style.display = "block";
            positionAt(evt);
        }

        function hide() {
            if (pinnedKey) return;
            tooltip.style.display = "none";
        }

        document.addEventListener("click", function (evt) {
            if (!pinnedKey || shell.contains(evt.target)) return;
            pinnedKey = null;
            tooltip.style.display = "none";
        });

        return {
            bind: function (el, key, htmlFn) {
                el.addEventListener("mouseenter", function (evt) {
                    if (pinnedKey && pinnedKey !== key) return;
                    show(htmlFn(), evt);
                });
                el.addEventListener("mousemove", function (evt) {
                    if (pinnedKey && pinnedKey !== key) return;
                    positionAt(evt);
                });
                el.addEventListener("mouseleave", function () { hide(); });
                el.addEventListener("click", function (evt) {
                    if (pinnedKey === key) {
                        pinnedKey = null;
                        tooltip.style.display = "none";
                        return;
                    }
                    pinnedKey = key;
                    show(htmlFn(), evt);
                });
            }
        };
    }

    function buildDiagram(container, payload) {
        var reactions = (payload && payload.reactions) || [];
        var shell = container.closest(".metabolism-pathway-map-shell") || container.parentElement;
        if (!shell.__pathwayTooltip) {
            shell.__pathwayTooltip = makeTooltipController(shell);
        }
        var tooltipController = shell.__pathwayTooltip;
        if (!reactions.length) {
            container.classList.add("is-empty");
            container.textContent = "No reaction participants are available for this pathway.";
            return;
        }

        var palette = {
            bg: readToken("--tp-color-surface", "#ffffff"),
            band: readToken("--tp-color-surface-soft", "#f5f8fa"),
            grid: readToken("--tp-color-border-soft", "#d7e2e7"),
            text: readToken("--tp-color-text-primary", "#102a38"),
            muted: readToken("--tp-color-text-muted", "#66808d"),
            reaction: readToken("--tp-color-brand-700", "#007c91"),
            reactionSoft: readToken("--tp-color-brand-050", "#e7f7fa"),
            chokepoint: readToken("--tp-color-amber-500", "#c9861a"),
            metabolite: readToken("--tp-color-sage-500", "#6e9a83"),
            currency: readToken("--tp-color-text-soft", "#8fa0a8"),
            line: readToken("--tp-color-border-strong", "#b6c8d1")
        };

        var rowH = 126;
        var headerH = 52;
        var width = Math.max(980, container.clientWidth || 980);
        var height = headerH + reactions.length * rowH + 40;
        var substrateX = 170;
        var reactionX = Math.round(width / 2) - 95;
        var productX = width - 320;
        var reactionW = 190;
        var reactionH = 54;

        container.textContent = "";
        var baseViewBox = { x: 0, y: 0, width: width, height: height };
        var svg = makeSvg("svg", {
            viewBox: "0 0 " + width + " " + height,
            role: "img",
            "aria-label": "Metabolic pathway reaction map"
        });
        container.__pathwayMap = { svg: svg, baseViewBox: baseViewBox, currentViewBox: baseViewBox };

        svg.appendChild(makeSvg("rect", { x: 0, y: 0, width: width, height: height, fill: palette.bg }));
        var defs = makeSvg("defs", {});
        var marker = makeSvg("marker", {
            id: "pathway-arrow",
            markerWidth: 8,
            markerHeight: 8,
            refX: 7,
            refY: 3,
            orient: "auto",
            markerUnits: "strokeWidth"
        });
        marker.appendChild(makeSvg("path", { d: "M 0 0 L 7 3 L 0 6 z", fill: palette.line }));
        defs.appendChild(marker);
        svg.appendChild(defs);
        addText(svg, "Substrates", substrateX, 30, "pathway-map-axis", 20);
        addText(svg, "Reaction", reactionX + 42, 30, "pathway-map-axis", 20);
        addText(svg, "Products", productX, 30, "pathway-map-axis", 20);

        reactions.forEach(function (reaction, i) {
            var y = headerH + i * rowH;
            var midY = y + rowH / 2;
            var rowFill = i % 2 ? palette.bg : palette.band;
            var row = makeSvg("g", { class: reaction.is_chokepoint ? "pathway-map-row is-chokepoint" : "pathway-map-row" });
            row.style.animationDelay = Math.min(i * 22, 480) + "ms";
            addTitle(row, reaction.name || reaction.id);
            svg.appendChild(row);
            row.appendChild(makeSvg("rect", {
                x: 0, y: y, width: width, height: rowH,
                fill: rowFill
            }));
            row.appendChild(makeSvg("line", {
                x1: 0, x2: width, y1: y, y2: y,
                stroke: palette.grid, "stroke-width": 1
            }));

            var substrates = (reaction.substrates || []).slice(0, 4);
            var products = (reaction.products || []).slice(0, 4);
            var rxnStroke = reaction.is_chokepoint ? palette.chokepoint : palette.reaction;
            var rxnFill = reaction.is_chokepoint ? "rgba(201, 134, 26, 0.12)" : palette.reactionSoft;

            var rxn = addTitle(makeSvg("rect", {
                x: reactionX, y: midY - reactionH / 2, width: reactionW, height: reactionH,
                rx: 8, ry: 8,
                fill: rxnFill,
                stroke: rxnStroke,
                "stroke-width": reaction.is_chokepoint ? 2.4 : 1.6
            }), reaction.name || reaction.id);
            row.appendChild(rxn);
            addText(row, reaction.name || reaction.id, reactionX + 12, midY - 5, "pathway-map-reaction-label", 26);
            addGeneLinks(row, reaction.genes, reactionX + 12, midY + 13);
            tooltipController.bind(rxn, "reaction:" + reaction.id, function () { return reactionTooltipHtml(reaction); });

            substrates.forEach(function (item, j) {
                var my = midY - ((substrates.length - 1) * 18) / 2 + j * 18;
                var dot = drawMetabolite(row, item, substrateX, my, palette);
                tooltipController.bind(dot, "metabolite:" + reaction.id + ":s:" + metaboliteKey(item), function () { return metaboliteTooltipHtml(item, "Substrate"); });
                drawConnector(row, substrateX + 136, my, reactionX, midY, palette.line);
            });
            products.forEach(function (item, j) {
                var my = midY - ((products.length - 1) * 18) / 2 + j * 18;
                drawConnector(row, reactionX + reactionW, midY, productX - 18, my, palette.line);
                var dot = drawMetabolite(row, item, productX, my, palette);
                tooltipController.bind(dot, "metabolite:" + reaction.id + ":p:" + metaboliteKey(item), function () { return metaboliteTooltipHtml(item, "Product"); });
            });

            var shared = sharedMetabolites(reaction, reactions[i + 1]);
            if (shared.length) {
                drawCarryover(row, reactionX + reactionW + 34, y + rowH - 26, shared.join(", "), palette);
            }
        });

        container.appendChild(svg);
        bindControls(container);
    }

    function setViewBox(container, next) {
        var state = container.__pathwayMap;
        if (!state || !state.svg) return;
        state.currentViewBox = next;
        state.svg.setAttribute("viewBox", [next.x, next.y, next.width, next.height].join(" "));
    }

    function zoom(container, factor) {
        var state = container.__pathwayMap;
        if (!state) return;
        var vb = state.currentViewBox;
        var nextW = Math.max(240, Math.min(state.baseViewBox.width, vb.width * factor));
        var nextH = Math.max(180, Math.min(state.baseViewBox.height, vb.height * factor));
        setViewBox(container, {
            x: vb.x + (vb.width - nextW) / 2,
            y: vb.y + (vb.height - nextH) / 2,
            width: nextW,
            height: nextH
        });
    }

    function bindControls(container) {
        var shell = container.closest(".metabolism-pathway-map-shell");
        if (!shell || shell.__pathwayControlsBound) return;
        shell.__pathwayControlsBound = true;
        Array.prototype.forEach.call(shell.querySelectorAll("[data-pathway-map-action]"), function (button) {
            button.addEventListener("click", function () {
                var action = button.getAttribute("data-pathway-map-action");
                if (action === "fit") setViewBox(container, container.__pathwayMap.baseViewBox);
                if (action === "zoom-in") zoom(container, 0.78);
                if (action === "zoom-out") zoom(container, 1.22);
            });
        });
    }

    function drawMetabolite(svg, item, x, y, palette) {
        var isCurrency = Boolean(item.is_currency);
        var dot = addTitle(makeSvg("circle", {
            cx: x, cy: y - 4, r: isCurrency ? 5 : 7,
            fill: isCurrency ? palette.currency : palette.metabolite,
            opacity: isCurrency ? 0.55 : 1,
            class: "pathway-map-metabolite-dot"
        }), item.name || item.species_id);
        svg.appendChild(dot);
        addText(svg, item.name || item.species_id, x + 14, y, isCurrency ? "pathway-map-metabolite is-currency" : "pathway-map-metabolite", 34);
        return dot;
    }

    function addGeneLinks(row, genes, x, y) {
        var list = genes || [];
        var visible = list.slice(0, 2);
        var hiddenCount = Math.max(0, list.length - visible.length);
        if (!list.length) {
            addText(row, "No mapped protein", x, y, "pathway-map-gene-label is-muted-label", 22);
            return;
        }
        visible.forEach(function (gene, i) {
            var link = makeSvg("a", { href: gene.url, class: "pathway-map-gene-link" });
            var t = makeSvg("text", { x: x, y: y + i * 12, class: "pathway-map-gene-label" });
            t.textContent = text(gene.accession, 22);
            addTitle(link, "Open " + gene.accession);
            link.appendChild(t);
            row.appendChild(link);
        });
        if (hiddenCount > 0) {
            addText(row, "+" + hiddenCount + " more", x, y + visible.length * 12, "pathway-map-gene-label is-muted-label", 16);
        }
    }

    function drawConnector(svg, x1, y1, x2, y2, color) {
        var path = makeSvg("path", {
            d: "M " + x1 + " " + y1 + " C " + (x1 + 40) + " " + y1 + ", " + (x2 - 40) + " " + y2 + ", " + x2 + " " + y2,
            fill: "none",
            stroke: color,
            "stroke-width": 1.2,
            "stroke-linecap": "round",
            "marker-end": "url(#pathway-arrow)",
            opacity: 0.86
        });
        svg.appendChild(path);
    }

    function drawCarryover(svg, x, y, label, palette) {
        svg.appendChild(makeSvg("path", {
            d: "M " + x + " " + y + " v 28",
            fill: "none",
            stroke: palette.metabolite,
            "stroke-width": 1.4,
            "stroke-dasharray": "3 3",
            "marker-end": "url(#pathway-arrow)",
            opacity: 0.85
        }));
        addText(svg, label, x + 10, y + 17, "pathway-map-shared-label", 40);
    }

    function sharedMetabolites(a, b) {
        if (!a || !b) return [];
        var products = {};
        (a.products || []).forEach(function (item) {
            if (!item.is_currency) products[metaboliteKey(item)] = item.name;
        });
        return (b.substrates || [])
            .filter(function (item) { return !item.is_currency && products[metaboliteKey(item)]; })
            .map(function (item) { return item.name; })
            .slice(0, 2);
    }

    function init() {
        var container = document.getElementById("metabolic-pathway-diagram");
        var dataEl = document.getElementById("metabolic-pathway-diagram-data");
        if (!container || !dataEl) return;
        var payload;
        try {
            payload = JSON.parse(dataEl.textContent || "{}");
        } catch (err) {
            container.classList.add("is-empty");
            container.textContent = "Unable to render pathway diagram.";
            return;
        }
        try {
            buildDiagram(container, payload);
        } catch (err) {
            container.classList.add("is-empty");
            container.textContent = "Unable to render pathway diagram.";
            return;
        }

        var lastWidth = container.clientWidth;
        var resizeTimer = null;
        function scheduleRebuild() {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                var width = container.clientWidth;
                if (Math.abs(width - lastWidth) < 24) return;
                lastWidth = width;
                buildDiagram(container, payload);
            }, 180);
        }
        if ("ResizeObserver" in window) {
            new ResizeObserver(scheduleRebuild).observe(container);
        } else {
            window.addEventListener("resize", scheduleRebuild);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
