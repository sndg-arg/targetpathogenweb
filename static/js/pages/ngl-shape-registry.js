(function (global) {
    "use strict";

    /**
     * Registers an NGL Shape (FPocket/P2Rank alpha-sphere core geometry) as a
     * component whose visibility/autoView can be driven the same way as a
     * regular sele-based representation. This was the one piece of
     * initStructureComponent still byte-identical between protein.html and
     * structure.html after the rest (density mode, 3Dmol fallback, spin, zoom
     * toolbar) was already trimmed out of protein.html's lightweight preview --
     * everything else differs on purpose (full camera controls vs. preview),
     * so only this genuinely-duplicated piece was worth extracting.
     */
    function createShapeRegistry(stage, component, representations) {
        return function registerShapeComponent(key, shape) {
            var pendingVisible = false;
            var shapeComponent = null;
            representations[key] = {
                tpShapeComponent: true,
                setVisibility: function (on) {
                    pendingVisible = !!on;
                    if (shapeComponent && typeof shapeComponent.setVisibility === "function") {
                        shapeComponent.setVisibility(pendingVisible);
                    }
                },
                autoView: function (duration) {
                    if (shapeComponent && typeof shapeComponent.autoView === "function") {
                        shapeComponent.autoView(duration || 0);
                    } else if (component && typeof component.autoView === "function") {
                        component.autoView();
                    }
                }
            };
            var loaded = null;
            try {
                loaded = stage.addComponentFromObject(shape);
            } catch (err) {
                if (global.console && console.warn) console.warn("Unable to register pocket shape", key, err);
                return;
            }
            var onReady = function (readyComponent) {
                shapeComponent = readyComponent;
                if (shapeComponent && typeof shapeComponent.addRepresentation === "function") {
                    shapeComponent.addRepresentation("buffer", { opacity: 1.0 });
                }
                if (shapeComponent && typeof shapeComponent.setVisibility === "function") {
                    shapeComponent.setVisibility(pendingVisible);
                }
            };
            if (loaded && typeof loaded.then === "function") {
                loaded.then(onReady).catch(function (err) {
                    if (global.console && console.warn) console.warn("Unable to render pocket shape", key, err);
                });
            } else {
                onReady(loaded);
            }
        };
    }

    global.tpNglShapes = { createShapeRegistry: createShapeRegistry };
})(window);
