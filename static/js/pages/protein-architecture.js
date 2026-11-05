/*
 * Protein architecture map (components/protein/architecture_map.html), shared
 * by the pathogen and human protein pages: clicking a domain marks its
 * residues in components/protein/sequence_blocks.html and scrolls to them.
 */
(function () {
    "use strict";

    // Clicking a domain on the architecture map marks its residues in the
    // sequence below and scrolls them into view; clicking it again clears it.
    function initArchitectureMap() {
        var sequence = document.querySelector("[data-sequence-blocks]");
        var domains = document.querySelectorAll(".ha-domain[data-start]");
        if (!sequence || !domains.length) return;
        var blocks = Array.prototype.slice.call(sequence.querySelectorAll(".hseq-block"));
        blocks.forEach(function (block) { block.dataset.text = block.textContent; });

        function clear() {
            blocks.forEach(function (block) {
                if (block.querySelector("mark")) block.textContent = block.dataset.text;
            });
            domains.forEach(function (d) { d.classList.remove("is-active"); });
        }

        function mark(start, end) {
            var first = null;
            blocks.forEach(function (block) {
                var blockStart = parseInt(block.dataset.start, 10);
                var text = block.dataset.text;
                var from = Math.max(start, blockStart) - blockStart;
                var to = Math.min(end, blockStart + text.length - 1) - blockStart + 1;
                if (to <= 0 || from >= text.length) return;
                block.textContent = "";
                block.appendChild(document.createTextNode(text.slice(0, from)));
                var highlighted = document.createElement("mark");
                highlighted.textContent = text.slice(from, to);
                block.appendChild(highlighted);
                block.appendChild(document.createTextNode(text.slice(to)));
                if (!first) first = block;
            });
            if (first) {
                var offset = first.getBoundingClientRect().top - sequence.getBoundingClientRect().top;
                sequence.scrollTo({ top: Math.max(0, sequence.scrollTop + offset - 24), behavior: "smooth" });
            }
        }

        domains.forEach(function (domain) {
            domain.addEventListener("click", function () {
                var wasActive = domain.classList.contains("is-active");
                clear();
                if (wasActive) return;
                domain.classList.add("is-active");
                mark(parseInt(domain.dataset.start, 10), parseInt(domain.dataset.end, 10));
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initArchitectureMap);
    } else {
        initArchitectureMap();
    }
})();
