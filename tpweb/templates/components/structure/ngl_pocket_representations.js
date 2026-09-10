{% for p in structure_data.pockets %}
    var fpocketResidueSele = activeChainSelector + " AND NOT STP AND NOT water AND ({{p.residue_ids|join:" OR "}})";
    sele = fpocketResidueSele;
    representations["{{p.name}}_apol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-pocket-apolar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true,
        // See structure.html's __main_density surface repr: NGL's real
        // runtime default for a "surface" repr is surfaceType:"ms" with
        // useWorker:true (triangulated async in a Web Worker), and when
        // that worker silently fails to spin up, the surface never gets
        // built even though setVisibility(true) reports no error. Force
        // main-thread computation so pocket surface overlays actually render.
        useWorker: false
    });
    representations["{{p.name}}_apol"].sele = sele;
    pocketSurfaceKeys.push("{{p.name}}_apol");
    {% if forloop.counter <= 4 %}
        priorityPocketSurfaceKeys.push("{{p.name}}_apol");
    {% endif %}

    sele = fpocketResidueSele;
    representations["{{p.name}}_pol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-pocket-polar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true,
        // See structure.html's __main_density surface repr: NGL's real
        // runtime default for a "surface" repr is surfaceType:"ms" with
        // useWorker:true (triangulated async in a Web Worker), and when
        // that worker silently fails to spin up, the surface never gets
        // built even though setVisibility(true) reports no error. Force
        // main-thread computation so pocket surface overlays actually render.
        useWorker: false
    });
    representations["{{p.name}}_pol"].sele = sele;
    pocketSurfaceKeys.push("{{p.name}}_pol");
    {% if forloop.counter <= 4 %}
        priorityPocketSurfaceKeys.push("{{p.name}}_pol");
    {% endif %}

    visible["{{p.name}}_pol"] = false;
    visible["{{p.name}}_apol"] = false;
    representations["{{p.name}}_pol"].setVisibility(false);
    representations["{{p.name}}_apol"].setVisibility(false);

    representations["{{p.name}}_atm"] = component.addRepresentation("ball+stick", {
        sele: fpocketResidueSele,
        color: tpColor("--tp-color-structure-pocket-polar")
    });
    visible["{{p.name}}_atm"] = false;
    representations["{{p.name}}_atm"].setVisibility(false);
    representations["{{p.name}}_atm"].sele = fpocketResidueSele;

    {% if p.core_points %}
    var fpocketCoreShape{{ forloop.counter }} = new NGL.Shape("FPocket {{p.name}} core");
    var fpocketCoreColor{{ forloop.counter }} = tpColorTriplet("--tp-color-structure-pocket-apolar", "#20c3d6");
    {% for point in p.core_points %}
    fpocketCoreShape{{ forloop.parentloop.counter }}.addSphere([{{ point.x }}, {{ point.y }}, {{ point.z }}], fpocketCoreColor{{ forloop.parentloop.counter }}, {{ point.radius }});
    {% endfor %}
    registerShapeComponent("{{p.name}}_sph", fpocketCoreShape{{ forloop.counter }});
    {% else %}
    representations["{{p.name}}_sph"] = component.addRepresentation("spacefill", {
        sele: fpocketResidueSele,
        color: tpColor("--tp-color-structure-pocket-apolar"),
        radiusScale: 0.7
    });
    {% endif %}
    visible["{{p.name}}_sph"] = false;
    representations["{{p.name}}_sph"].setVisibility(false);
    {% if p.core_points %}
    representations["{{p.name}}_sph"].tpShapeComponent = true;
    {% else %}
    representations["{{p.name}}_sph"].sele = fpocketResidueSele;
    {% endif %}

    representations["{{p.name}}_lbl"] = component.addRepresentation("label", {
        labelType: "text",
        labelText: residueLabelTextByAtomIndex,
        sele: activeChainSelector + " AND .CA AND ({{p.residue_ids|join:" OR "}})",
        color: tpColor("--tp-color-structure-label") || "#0e2330",
        backgroundColor: tpColor("--tp-color-structure-label-bg") || "rgba(255,255,255,0.78)",
        showBackground: true,
        fontWeight: "bold",
        xOffset: 0,
        yOffset: 0,
        zOffset: 1.5,
        fixedSize: true,
        attachment: "middle-center"
    });
    visible["{{p.name}}_lbl"] = false;
    representations["{{p.name}}_lbl"].setVisibility(false);
    representations["{{p.name}}_lbl"].sele = activeChainSelector + " AND .CA AND ({{p.residue_ids|join:" OR "}})";
    representations["{{p.name}}_zoom"] = {
        sele: fpocketResidueSele
    };
{% endfor %}

{% for p2 in structure_data.p2_pockets %}
    var p2rankResidueSele = activeChainSelector + " AND NOT STP AND NOT water AND ({{p2.residue_ids|join:" OR "}})";
    sele = p2rankResidueSele;
    representations["p2_{{p2.name}}_apol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-p2-apolar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true,
        // See structure.html's __main_density surface repr: NGL's real
        // runtime default for a "surface" repr is surfaceType:"ms" with
        // useWorker:true (triangulated async in a Web Worker), and when
        // that worker silently fails to spin up, the surface never gets
        // built even though setVisibility(true) reports no error. Force
        // main-thread computation so pocket surface overlays actually render.
        useWorker: false
    });
    representations["p2_{{p2.name}}_apol"].sele = sele;
    pocketSurfaceKeys.push("p2_{{p2.name}}_apol");
    {% if forloop.counter <= 3 %}
        priorityPocketSurfaceKeys.push("p2_{{p2.name}}_apol");
    {% endif %}

    sele = p2rankResidueSele;
    representations["p2_{{p2.name}}_pol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-p2-polar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true,
        // See structure.html's __main_density surface repr: NGL's real
        // runtime default for a "surface" repr is surfaceType:"ms" with
        // useWorker:true (triangulated async in a Web Worker), and when
        // that worker silently fails to spin up, the surface never gets
        // built even though setVisibility(true) reports no error. Force
        // main-thread computation so pocket surface overlays actually render.
        useWorker: false
    });
    representations["p2_{{p2.name}}_pol"].sele = sele;
    pocketSurfaceKeys.push("p2_{{p2.name}}_pol");
    {% if forloop.counter <= 3 %}
        priorityPocketSurfaceKeys.push("p2_{{p2.name}}_pol");
    {% endif %}

    visible["p2_{{p2.name}}_pol"] = false;
    visible["p2_{{p2.name}}_apol"] = false;
    representations["p2_{{p2.name}}_pol"].setVisibility(false);
    representations["p2_{{p2.name}}_apol"].setVisibility(false);

    representations["p2_{{p2.name}}_atm"] = component.addRepresentation("ball+stick", {
        sele: p2rankResidueSele,
        color: tpColor("--tp-color-structure-p2-polar")
    });
    visible["p2_{{p2.name}}_atm"] = false;
    representations["p2_{{p2.name}}_atm"].setVisibility(false);
    representations["p2_{{p2.name}}_atm"].sele = p2rankResidueSele;

    {% if p2.core_points %}
    var p2rankCoreShape{{ forloop.counter }} = new NGL.Shape("P2Rank {{p2.name}} core");
    var p2rankCoreColor{{ forloop.counter }} = tpColorTriplet("--tp-color-structure-p2-apolar", "#f59e0b");
    {% for point in p2.core_points %}
    p2rankCoreShape{{ forloop.parentloop.counter }}.addSphere([{{ point.x }}, {{ point.y }}, {{ point.z }}], p2rankCoreColor{{ forloop.parentloop.counter }}, 1.1);
    {% endfor %}
    registerShapeComponent("p2_{{p2.name}}_sph", p2rankCoreShape{{ forloop.counter }});
    {% else %}
    representations["p2_{{p2.name}}_sph"] = component.addRepresentation("spacefill", {
        sele: p2rankResidueSele,
        color: tpColor("--tp-color-structure-p2-apolar"),
        radiusScale: 0.7
    });
    {% endif %}
    visible["p2_{{p2.name}}_sph"] = false;
    representations["p2_{{p2.name}}_sph"].setVisibility(false);
    {% if p2.core_points %}
    representations["p2_{{p2.name}}_sph"].tpShapeComponent = true;
    {% else %}
    representations["p2_{{p2.name}}_sph"].sele = p2rankResidueSele;
    {% endif %}

    representations["p2_{{p2.name}}_lbl"] = component.addRepresentation("label", {
        labelType: "text",
        labelText: residueLabelTextByAtomIndex,
        sele: activeChainSelector + " AND .CA AND ({{p2.residue_ids|join:" OR "}})",
        color: tpColor("--tp-color-structure-label") || "#0e2330",
        backgroundColor: tpColor("--tp-color-structure-label-bg") || "rgba(255,255,255,0.78)",
        showBackground: true,
        fontWeight: "bold",
        xOffset: 0,
        yOffset: 0,
        zOffset: 1.5,
        fixedSize: true,
        attachment: "middle-center"
    });
    visible["p2_{{p2.name}}_lbl"] = false;
    representations["p2_{{p2.name}}_lbl"].setVisibility(false);
    representations["p2_{{p2.name}}_lbl"].sele = activeChainSelector + " AND .CA AND ({{p2.residue_ids|join:" OR "}})";
    representations["p2_{{p2.name}}_zoom"] = {
        sele: p2rankResidueSele
    };
{% endfor %}

{% for rs in structure_data.residuesets %}
    sele = activeChainSelector + " AND ({{rs.residues|join:" OR "}})";
    representations["{{rs.name}}"] = component.addRepresentation("ball+stick", {
        sele: sele
    });
    visible["{{rs.name}}"] = false;
    representations["{{rs.name}}"].setVisibility(false);
    representations["{{rs.name}}"].sele = sele;
    representations["{{rs.name}}_zoom"] = {
        sele: sele
    };
{% endfor %}
