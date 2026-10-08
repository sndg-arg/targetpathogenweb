/* Custom-styled <select> replacement -- present on every page (loaded directly
 * from masterpage.html, matching the existing plain-script convention used by
 * agent-drawer.js/nav-toggle.js). Wraps every plain <select> (opt-in via the
 * .tp-select markup, excluding [multiple]/[size]/explicitly-native selects) in a
 * button+listbox pair styled to match the rest of the design system, while
 * keeping the original <select> in the DOM (hidden) as the source of truth --
 * form submission and any code reading .value still just works.
 */
(function () {
    const SELECTOR = "select:not([multiple]):not([size]):not([data-tp-select-native]):not([data-tp-select-enhanced]):not([data-tp-select-raw])";

    function getEnhancedWrappers() {
        return Array.from(document.querySelectorAll(".tp-select[data-tp-select-enhanced='1']"));
    }

    function getEnabledOptionButtons(wrapper) {
        return Array.from(wrapper.querySelectorAll(".tp-select-option")).filter(function (button) {
            return button.getAttribute("aria-disabled") !== "true";
        });
    }

    function closeSelect(wrapper) {
        if (!wrapper || !wrapper.classList.contains("is-open")) return;
        const trigger = wrapper.querySelector(".tp-select-trigger");
        const menu = wrapper.querySelector(".tp-select-menu");
        wrapper.classList.remove("is-open");
        if (trigger) trigger.setAttribute("aria-expanded", "false");
        if (menu) menu.hidden = true;
    }

    function closeAllSelects(exceptWrapper) {
        getEnhancedWrappers().forEach(function (wrapper) {
            if (wrapper === exceptWrapper) return;
            closeSelect(wrapper);
        });
    }

    function focusOptionWithOffset(wrapper, offset) {
        const enabledButtons = getEnabledOptionButtons(wrapper);
        if (!enabledButtons.length) return;
        let activeIndex = enabledButtons.findIndex(function (button) {
            return button === document.activeElement;
        });
        if (activeIndex === -1) {
            activeIndex = enabledButtons.findIndex(function (button) {
                return button.classList.contains("is-selected");
            });
        }
        if (activeIndex === -1) {
            activeIndex = offset > 0 ? -1 : 0;
        }
        const nextIndex = (activeIndex + offset + enabledButtons.length) % enabledButtons.length;
        enabledButtons[nextIndex].focus();
    }

    function focusBoundaryOption(wrapper, isLast) {
        const enabledButtons = getEnabledOptionButtons(wrapper);
        if (!enabledButtons.length) return;
        const target = isLast ? enabledButtons[enabledButtons.length - 1] : enabledButtons[0];
        target.focus();
    }

    function openSelect(wrapper) {
        if (!wrapper || wrapper.classList.contains("is-disabled")) return;
        const trigger = wrapper.querySelector(".tp-select-trigger");
        const menu = wrapper.querySelector(".tp-select-menu");
        if (!trigger || !menu) return;
        closeAllSelects(wrapper);
        wrapper.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
        menu.hidden = false;
        window.requestAnimationFrame(function () {
            const selected = menu.querySelector(".tp-select-option.is-selected[aria-disabled='false']");
            if (selected) {
                selected.focus();
                return;
            }
            const firstEnabled = menu.querySelector(".tp-select-option[aria-disabled='false']");
            if (firstEnabled) firstEnabled.focus();
        });
    }

    function getOptionEntries(select) {
        const entries = [];
        Array.from(select.children).forEach(function (child) {
            if (child.tagName === "OPTGROUP") {
                entries.push({
                    type: "group",
                    label: child.label || ""
                });
                Array.from(child.children).forEach(function (option) {
                    const inheritedDisabled = option.parentElement && option.parentElement.tagName === "OPTGROUP" && option.parentElement.disabled;
                    entries.push({
                        type: "option",
                        value: option.value,
                        label: (option.textContent || "").trim(),
                        disabled: option.disabled || inheritedDisabled,
                        selected: option.selected
                    });
                });
                return;
            }
            if (child.tagName === "OPTION") {
                const inheritedDisabled = child.parentElement && child.parentElement.tagName === "OPTGROUP" && child.parentElement.disabled;
                entries.push({
                    type: "option",
                    value: child.value,
                    label: (child.textContent || "").trim(),
                    disabled: child.disabled || inheritedDisabled,
                    selected: child.selected
                });
            }
        });
        return entries;
    }

    function renderSelect(wrapper) {
        const select = wrapper.querySelector("select[data-tp-select-enhanced='1']");
        const trigger = wrapper.querySelector(".tp-select-trigger");
        const menu = wrapper.querySelector(".tp-select-menu");
        const label = trigger ? trigger.querySelector(".tp-select-label") : null;
        if (!select || !trigger || !menu || !label) return;

        const entries = getOptionEntries(select);
        const selectedOption = select.options && select.selectedIndex >= 0 ? select.options[select.selectedIndex] : null;
        const selectedValue = selectedOption ? String(selectedOption.value || "") : "";
        const hasRealSelection = selectedValue.trim().length > 0;
        const selectedLabel = selectedOption ? (selectedOption.textContent || "").trim() : "";
        label.textContent = selectedLabel || (entries.find(function (entry) {
            return entry.type === "option";
        }) || {}).label || "";

        wrapper.classList.toggle("is-disabled", Boolean(select.disabled));
        wrapper.classList.toggle("is-placeholder-value", !hasRealSelection);
        trigger.disabled = Boolean(select.disabled);

        menu.innerHTML = "";
        let optionIndex = 0;
        entries.forEach(function (entry) {
            if (entry.type === "group") {
                const groupLabel = document.createElement("p");
                groupLabel.className = "tp-select-group-label";
                groupLabel.textContent = entry.label;
                menu.appendChild(groupLabel);
                return;
            }
            const optionButton = document.createElement("button");
            optionButton.type = "button";
            optionButton.className = "tp-select-option";
            optionButton.textContent = entry.label;
            optionButton.setAttribute("role", "option");
            optionButton.setAttribute("aria-selected", entry.selected ? "true" : "false");
            optionButton.setAttribute("aria-disabled", entry.disabled ? "true" : "false");
            optionButton.setAttribute("data-value", entry.value);
            optionButton.setAttribute("data-option-index", String(optionIndex));
            if (entry.selected) {
                optionButton.classList.add("is-selected");
                if (String(entry.value || "").trim() === "") {
                    optionButton.classList.add("is-placeholder-selected");
                }
            }
            if (entry.disabled) optionButton.tabIndex = -1;
            menu.appendChild(optionButton);
            optionIndex += 1;
        });
    }

    function chooseOption(wrapper, value) {
        const select = wrapper.querySelector("select[data-tp-select-enhanced='1']");
        const trigger = wrapper.querySelector(".tp-select-trigger");
        if (!select) return;
        const currentValue = select.value;
        select.value = value;
        renderSelect(wrapper);
        closeSelect(wrapper);
        if (trigger) trigger.focus();
        if (currentValue !== value) {
            select.dispatchEvent(new Event("input", { bubbles: true }));
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }
    }

    function enhanceSelect(select) {
        if (!select || select.dataset.tpSelectEnhanced === "1") return;
        select.dataset.tpSelectEnhanced = "1";
        const wrapper = document.createElement("div");
        wrapper.className = "tp-select";
        wrapper.setAttribute("data-tp-select-enhanced", "1");
        Array.from(select.classList).forEach(function (className) {
            if (className === "form-control" || className === "form-select" || className === "tp-select-native") return;
            wrapper.classList.add(className);
        });

        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.className = "tp-select-trigger";
        trigger.setAttribute("aria-haspopup", "listbox");
        trigger.setAttribute("aria-expanded", "false");

        const label = document.createElement("span");
        label.className = "tp-select-label";
        trigger.appendChild(label);

        const chevron = document.createElement("span");
        chevron.className = "tp-chevron tp-chevron--down tp-select-chevron";
        chevron.setAttribute("aria-hidden", "true");
        trigger.appendChild(chevron);

        const menu = document.createElement("div");
        menu.className = "tp-select-menu";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;

        const parent = select.parentNode;
        if (!parent) return;
        parent.insertBefore(wrapper, select);
        wrapper.appendChild(select);
        wrapper.appendChild(trigger);
        wrapper.appendChild(menu);
        select.classList.add("tp-select-native");

        select.addEventListener("focus", function () {
            trigger.focus();
        });
        select.addEventListener("change", function () {
            renderSelect(wrapper);
        });
        select.addEventListener("input", function () {
            renderSelect(wrapper);
        });

        trigger.addEventListener("click", function () {
            if (wrapper.classList.contains("is-open")) {
                closeSelect(wrapper);
                return;
            }
            openSelect(wrapper);
        });

        trigger.addEventListener("keydown", function (event) {
            if (event.key === "ArrowDown") {
                event.preventDefault();
                openSelect(wrapper);
                focusBoundaryOption(wrapper, false);
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                openSelect(wrapper);
                focusBoundaryOption(wrapper, true);
                return;
            }
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (wrapper.classList.contains("is-open")) {
                    closeSelect(wrapper);
                } else {
                    openSelect(wrapper);
                }
            }
        });

        menu.addEventListener("click", function (event) {
            const optionButton = event.target.closest(".tp-select-option");
            if (!optionButton) return;
            if (optionButton.getAttribute("aria-disabled") === "true") return;
            chooseOption(wrapper, optionButton.getAttribute("data-value") || "");
        });

        menu.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                closeSelect(wrapper);
                trigger.focus();
                return;
            }
            if (event.key === "ArrowDown") {
                event.preventDefault();
                focusOptionWithOffset(wrapper, 1);
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                focusOptionWithOffset(wrapper, -1);
                return;
            }
            if (event.key === "Home") {
                event.preventDefault();
                focusBoundaryOption(wrapper, false);
                return;
            }
            if (event.key === "End") {
                event.preventDefault();
                focusBoundaryOption(wrapper, true);
                return;
            }
            if (event.key === "Enter" || event.key === " ") {
                const optionButton = event.target.closest(".tp-select-option");
                if (!optionButton || optionButton.getAttribute("aria-disabled") === "true") return;
                event.preventDefault();
                chooseOption(wrapper, optionButton.getAttribute("data-value") || "");
                return;
            }
            if (event.key === "Tab") {
                closeSelect(wrapper);
            }
        });

        renderSelect(wrapper);

        const observer = new MutationObserver(function () {
            renderSelect(wrapper);
        });
        observer.observe(select, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["disabled", "label", "selected", "value"]
        });
    }

    function initEnhancedSelects(root) {
        const scope = root && root.nodeType === 1 ? root : document;
        if (scope.matches && scope.matches(SELECTOR)) {
            enhanceSelect(scope);
        }
        scope.querySelectorAll(SELECTOR).forEach(function (select) {
            enhanceSelect(select);
        });
    }

    document.addEventListener("click", function (event) {
        if (event.target.closest(".tp-select")) return;
        closeAllSelects();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        closeAllSelects();
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initEnhancedSelects(document);
        });
    } else {
        initEnhancedSelects(document);
    }

    const rootObserver = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (node.nodeType !== 1) return;
                initEnhancedSelects(node);
            });
        });
    });

    rootObserver.observe(document.documentElement, {
        childList: true,
        subtree: true
    });

    window.tpEnhanceSelects = initEnhancedSelects;
})();
