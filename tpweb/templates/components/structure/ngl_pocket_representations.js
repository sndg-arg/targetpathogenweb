{% for p in structure_data.pockets %}
    sele = "(STP AND .APOL AND {{p.name}}) OR (NOT water AND @{{p.atoms|join:","}})";
    representations["{{p.name}}_apol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-pocket-apolar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true
    });
    representations["{{p.name}}_apol"].sele = sele;
    pocketSurfaceKeys.push("{{p.name}}_apol");
    {% if forloop.counter <= 4 %}
        priorityPocketSurfaceKeys.push("{{p.name}}_apol");
    {% endif %}

    sele = "(STP AND .POL AND {{p.name}}) OR (NOT water AND @{{p.atoms|join:","}})";
    representations["{{p.name}}_pol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-pocket-polar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true
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
        sele: "NOT STP AND NOT water AND @{{p.atoms|join:","}}",
        color: tpColor("--tp-color-structure-pocket-polar")
    });
    visible["{{p.name}}_atm"] = false;
    representations["{{p.name}}_atm"].setVisibility(false);
    representations["{{p.name}}_atm"].sele = "NOT STP AND NOT water AND @{{p.atoms|join:","}}";

    representations["{{p.name}}_sph"] = component.addRepresentation("spacefill", {
        sele: "NOT STP AND NOT water AND @{{p.atoms|join:","}}",
        color: tpColor("--tp-color-structure-pocket-apolar"),
        radiusScale: 0.7
    });
    visible["{{p.name}}_sph"] = false;
    representations["{{p.name}}_sph"].setVisibility(false);
    representations["{{p.name}}_sph"].sele = "NOT STP AND NOT water AND @{{p.atoms|join:","}}";

    representations["{{p.name}}_lbl"] = component.addRepresentation("label", {
        labelType: "res",
        sele: activeChainSelector + " AND .CA AND ({{p.residues|join:" OR "}})",
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
    representations["{{p.name}}_lbl"].sele = activeChainSelector + " AND .CA AND ({{p.residues|join:" OR "}})";
    representations["{{p.name}}_zoom"] = {
        sele: "NOT STP AND NOT water AND @{{p.atoms|join:","}}"
    };
{% endfor %}

{% for p2 in structure_data.p2_pockets %}
    sele = "(STP AND .APOL AND {{p2.name}}) OR (NOT water AND @{{p2.atoms|join:","}})";
    representations["p2_{{p2.name}}_apol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-p2-apolar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true
    });
    representations["p2_{{p2.name}}_apol"].sele = sele;
    pocketSurfaceKeys.push("p2_{{p2.name}}_apol");
    {% if forloop.counter <= 3 %}
        priorityPocketSurfaceKeys.push("p2_{{p2.name}}_apol");
    {% endif %}

    sele = "(STP AND .POL AND {{p2.name}}) OR (NOT water AND @{{p2.atoms|join:","}})";
    representations["p2_{{p2.name}}_pol"] = component.addRepresentation("surface", {
        sele: sele,
        multipleBond: false,
        color: tpColor("--tp-color-structure-p2-polar"),
        opacity: STRUCTURE_VIEWER_CONFIG.surfaceOpacity,
        side: "double",
        opaqueBack: true
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
        sele: "NOT STP AND NOT water AND @{{p2.atoms|join:","}}",
        color: tpColor("--tp-color-structure-p2-polar")
    });
    visible["p2_{{p2.name}}_atm"] = false;
    representations["p2_{{p2.name}}_atm"].setVisibility(false);
    representations["p2_{{p2.name}}_atm"].sele = "NOT STP AND NOT water AND @{{p2.atoms|join:","}}";

    representations["p2_{{p2.name}}_sph"] = component.addRepresentation("spacefill", {
        sele: "NOT STP AND NOT water AND @{{p2.atoms|join:","}}",
        color: tpColor("--tp-color-structure-p2-apolar"),
        radiusScale: 0.7
    });
    visible["p2_{{p2.name}}_sph"] = false;
    representations["p2_{{p2.name}}_sph"].setVisibility(false);
    representations["p2_{{p2.name}}_sph"].sele = "NOT STP AND NOT water AND @{{p2.atoms|join:","}}";

    representations["p2_{{p2.name}}_lbl"] = component.addRepresentation("label", {
        labelType: "res",
        sele: activeChainSelector + " AND .CA AND ({{p2.residues|join:" OR "}})",
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
    representations["p2_{{p2.name}}_lbl"].sele = activeChainSelector + " AND .CA AND ({{p2.residues|join:" OR "}})";
    representations["p2_{{p2.name}}_zoom"] = {
        sele: "NOT STP AND NOT water AND @{{p2.atoms|join:","}}"
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
