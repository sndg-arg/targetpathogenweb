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
        svg.appendChild(t);
        return t;
    }

    function metaboliteKey(item) {
        return (item.species_id || item.name || "").toLowerCase();
    }

    function buildDiagram(container, payload) {
        var reactions = (payload && payload.reactions) || [];
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

        var rowH = 116;
        var headerH = 52;
        var width = Math.max(980, container.clientWidth || 980);
        var height = headerH + reactions.length * rowH + 40;
        var substrateX = 170;
        var reactionX = Math.round(width / 2) - 76;
        var productX = width - 320;
        var reactionW = 152;
        var reactionH = 48;

        container.textContent = "";
        var svg = makeSvg("svg", {
            viewBox: "0 0 " + width + " " + height,
            role: "img",
            "aria-label": "Metabolic pathway reaction map"
        });

        svg.appendChild(makeSvg("rect", { x: 0, y: 0, width: width, height: height, fill: palette.bg }));
        addText(svg, "Substrates", substrateX, 30, "pathway-map-axis", 20);
        addText(svg, "Reaction", reactionX + 42, 30, "pathway-map-axis", 20);
        addText(svg, "Products", productX, 30, "pathway-map-axis", 20);

        reactions.forEach(function (reaction, i) {
            var y = headerH + i * rowH;
            var midY = y + rowH / 2;
            var rowFill = i % 2 ? palette.bg : palette.band;
            svg.appendChild(makeSvg("rect", {
                x: 0, y: y, width: width, height: rowH,
                fill: rowFill
            }));
            svg.appendChild(makeSvg("line", {
                x1: 0, x2: width, y1: y, y2: y,
                stroke: palette.grid, "stroke-width": 1
            }));

            var substrates = (reaction.substrates || []).slice(0, 4);
            var products = (reaction.products || []).slice(0, 4);
            var rxnStroke = reaction.is_chokepoint ? palette.chokepoint : palette.reaction;
            var rxnFill = reaction.is_chokepoint ? "rgba(201, 134, 26, 0.12)" : palette.reactionSoft;

            var rxn = makeSvg("rect", {
                x: reactionX, y: midY - reactionH / 2, width: reactionW, height: reactionH,
                rx: 8, ry: 8,
                fill: rxnFill,
                stroke: rxnStroke,
                "stroke-width": reaction.is_chokepoint ? 2.4 : 1.6
            });
            svg.appendChild(rxn);
            addText(svg, reaction.name || reaction.id, reactionX + 12, midY - 4, "pathway-map-reaction-label", 22);
            addText(svg, (reaction.genes || []).map(function (g) { return g.accession; }).join(", "), reactionX + 12, midY + 14, "pathway-map-gene-label", 24);

            substrates.forEach(function (item, j) {
                var my = midY - ((substrates.length - 1) * 18) / 2 + j * 18;
                drawMetabolite(svg, item, substrateX, my, palette);
                drawConnector(svg, substrateX + 112, my, reactionX, midY, palette.line);
            });
            products.forEach(function (item, j) {
                var my = midY - ((products.length - 1) * 18) / 2 + j * 18;
                drawConnector(svg, reactionX + reactionW, midY, productX - 18, my, palette.line);
                drawMetabolite(svg, item, productX, my, palette);
            });

            var shared = sharedMetabolites(reaction, reactions[i + 1]);
            if (shared.length) {
                addText(svg, text(shared.join(", "), 34), reactionX + reactionW + 26, y + rowH - 14, "pathway-map-shared-label", 36);
            }
        });

        container.appendChild(svg);
    }

    function drawMetabolite(svg, item, x, y, palette) {
        var isCurrency = Boolean(item.is_currency);
        svg.appendChild(makeSvg("circle", {
            cx: x, cy: y - 4, r: isCurrency ? 5 : 7,
            fill: isCurrency ? palette.currency : palette.metabolite,
            opacity: isCurrency ? 0.55 : 1
        }));
        addText(svg, item.name || item.species_id, x + 14, y, isCurrency ? "pathway-map-metabolite is-currency" : "pathway-map-metabolite", 28);
    }

    function drawConnector(svg, x1, y1, x2, y2, color) {
        var path = makeSvg("path", {
            d: "M " + x1 + " " + y1 + " C " + (x1 + 40) + " " + y1 + ", " + (x2 - 40) + " " + y2 + ", " + x2 + " " + y2,
            fill: "none",
            stroke: color,
            "stroke-width": 1.2,
            "stroke-linecap": "round",
            opacity: 0.86
        });
        svg.appendChild(path);
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
        try {
            buildDiagram(container, JSON.parse(dataEl.textContent || "{}"));
        } catch (err) {
            container.classList.add("is-empty");
            container.textContent = "Unable to render pathway diagram.";
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
