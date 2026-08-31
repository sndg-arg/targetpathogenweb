(function () {
    "use strict";

    var paramOptions = JSON.parse(document.getElementById("af-param-options").textContent || "[]");
    var existingGroups = JSON.parse(document.getElementById("af-existing-groups").textContent || "[]");
    var paramOptionsById = {};
    paramOptions.forEach(function (param) {
        paramOptionsById[String(param.id)] = param;
    });

    var categoriesInOrder = [];
    var paramsByCategory = {};
    paramOptions.forEach(function (param) {
        if (!paramsByCategory[param.category]) {
            paramsByCategory[param.category] = [];
            categoriesInOrder.push(param.category);
        }
        paramsByCategory[param.category].push(param);
    });

    var groupsContainer = document.getElementById("af-groups");
    var emptyHint = document.getElementById("af-empty-hint");
    var groupTemplate = document.getElementById("af-group-template");
    var conditionTemplate = document.getElementById("af-condition-template");
    var categoricalValueTemplate = document.getElementById("af-value-categorical-template");
    var numericValueTemplate = document.getElementById("af-value-numeric-template");

    function updateEmptyHint() {
        var hasGroups = groupsContainer.children.length > 0;
        emptyHint.hidden = hasGroups;
    }

    function populateParamSelect(selectEl, selectedId) {
        categoriesInOrder.forEach(function (category) {
            var optgroup = document.createElement("optgroup");
            optgroup.label = category;
            paramsByCategory[category].forEach(function (param) {
                var option = document.createElement("option");
                option.value = String(param.id);
                option.textContent = param.label;
                if (selectedId != null && String(selectedId) === String(param.id)) {
                    option.selected = true;
                }
                optgroup.appendChild(option);
            });
            selectEl.appendChild(optgroup);
        });
    }

    function buildValueArea(valueAreaEl, paramId, conditionState) {
        valueAreaEl.innerHTML = "";
        var param = paramOptionsById[String(paramId)];
        if (!param) {
            return;
        }
        if (param.type === "categorical") {
            var node = categoricalValueTemplate.content.cloneNode(true);
            var select = node.querySelector("[data-option-select]");
            (param.options || []).forEach(function (opt) {
                var option = document.createElement("option");
                option.value = String(opt.id);
                option.textContent = opt.label;
                if (conditionState && String(conditionState.option_id) === String(opt.id)) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
            valueAreaEl.appendChild(node);
        } else {
            var numericNode = numericValueTemplate.content.cloneNode(true);
            var opSelect = numericNode.querySelector("[data-operation]");
            var valueInput = numericNode.querySelector("[data-value]");
            var valueMaxInput = numericNode.querySelector("[data-value-max]");
            if (conditionState && conditionState.operation) {
                opSelect.value = conditionState.operation;
            }
            if (conditionState && conditionState.value != null) {
                valueInput.value = conditionState.value;
            }
            if (conditionState && conditionState.value_max != null) {
                valueMaxInput.value = conditionState.value_max;
            }
            valueMaxInput.hidden = opSelect.value !== "between";
            opSelect.addEventListener("change", function () {
                valueMaxInput.hidden = opSelect.value !== "between";
            });
            valueAreaEl.appendChild(numericNode);
        }
    }

    function addCondition(conditionsContainer, conditionState) {
        var node = conditionTemplate.content.cloneNode(true);
        var conditionEl = node.querySelector("[data-condition]");
        var paramSelect = conditionEl.querySelector("[data-param-select]");
        var valueArea = conditionEl.querySelector("[data-value-area]");

        populateParamSelect(paramSelect, conditionState ? conditionState.score_param_id : null);
        if (conditionState && conditionState.score_param_id != null) {
            buildValueArea(valueArea, conditionState.score_param_id, conditionState);
        }
        paramSelect.addEventListener("change", function () {
            buildValueArea(valueArea, paramSelect.value, null);
        });

        conditionsContainer.appendChild(conditionEl);
    }

    function createGroupElement(groupState) {
        var node = groupTemplate.content.cloneNode(true);
        var groupEl = node.querySelector("[data-group]");
        var conditionsContainer = groupEl.querySelector("[data-conditions]");
        var mode = groupState && groupState.mode === "any" ? "any" : "all";
        setGroupMode(groupEl, mode);

        var conditions = (groupState && groupState.conditions) || [{}];
        if (!conditions.length) {
            conditions = [{}];
        }
        conditions.forEach(function (conditionState) {
            addCondition(conditionsContainer, conditionState.score_param_id != null ? conditionState : null);
        });

        return groupEl;
    }

    function setGroupMode(groupEl, mode) {
        groupEl.dataset.mode = mode;
        groupEl.querySelectorAll("[data-mode-btn]").forEach(function (btn) {
            btn.classList.toggle("af-mode-btn--active", btn.dataset.modeBtn === mode);
        });
    }

    groupsContainer.addEventListener("click", function (event) {
        var addConditionBtn = event.target.closest("[data-add-condition]");
        if (addConditionBtn) {
            var group = addConditionBtn.closest("[data-group]");
            addCondition(group.querySelector("[data-conditions]"), null);
            return;
        }
        var removeConditionBtn = event.target.closest("[data-remove-condition]");
        if (removeConditionBtn) {
            var condition = removeConditionBtn.closest("[data-condition]");
            var conditionsList = condition.parentElement;
            condition.remove();
            if (!conditionsList.children.length) {
                addCondition(conditionsList, null);
            }
            return;
        }
        var removeGroupBtn = event.target.closest("[data-remove-group]");
        if (removeGroupBtn) {
            removeGroupBtn.closest("[data-group]").remove();
            updateEmptyHint();
            return;
        }
        var modeBtn = event.target.closest("[data-mode-btn]");
        if (modeBtn) {
            setGroupMode(modeBtn.closest("[data-group]"), modeBtn.dataset.modeBtn);
        }
    });

    document.getElementById("af-add-group").addEventListener("click", function () {
        groupsContainer.appendChild(createGroupElement(null));
        updateEmptyHint();
    });

    if (existingGroups.length) {
        existingGroups.forEach(function (groupState) {
            groupsContainer.appendChild(createGroupElement(groupState));
        });
    } else {
        groupsContainer.appendChild(createGroupElement(null));
    }
    updateEmptyHint();

    document.getElementById("af-form").addEventListener("submit", function () {
        var groups = [];
        groupsContainer.querySelectorAll("[data-group]").forEach(function (groupEl) {
            var conditions = [];
            groupEl.querySelectorAll("[data-condition]").forEach(function (conditionEl) {
                var paramSelect = conditionEl.querySelector("[data-param-select]");
                var paramId = paramSelect.value;
                if (!paramId) {
                    return;
                }
                var param = paramOptionsById[paramId];
                if (!param) {
                    return;
                }
                if (param.type === "categorical") {
                    var optionSelect = conditionEl.querySelector("[data-option-select]");
                    if (!optionSelect || !optionSelect.value) {
                        return;
                    }
                    conditions.push({
                        kind: "categorical",
                        score_param_id: paramId,
                        option_id: optionSelect.value,
                    });
                } else {
                    var opSelect = conditionEl.querySelector("[data-operation]");
                    var valueInput = conditionEl.querySelector("[data-value]");
                    var valueMaxInput = conditionEl.querySelector("[data-value-max]");
                    var value = valueInput ? valueInput.value : "";
                    var valueMax = valueMaxInput ? valueMaxInput.value : "";
                    if (!value && !valueMax) {
                        return;
                    }
                    conditions.push({
                        kind: "numeric",
                        score_param_id: paramId,
                        operation: opSelect ? opSelect.value : ">=",
                        value: value,
                        value_max: valueMax,
                    });
                }
            });
            if (conditions.length) {
                groups.push({ mode: groupEl.dataset.mode === "any" ? "any" : "all", conditions: conditions });
            }
        });
        document.getElementById("af-groups-json").value = JSON.stringify(groups);
    });
})();
