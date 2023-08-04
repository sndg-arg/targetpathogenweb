import 'bootstrap/dist/css/bootstrap.css';
import "msa/css/msa.css";


//import Phylocanvas from 'phylocanvas';
import $ from 'jquery';
import Fasta from 'biojs-io-fasta';


import msa from "msa";
//import phylocanvas from "@phylocanvas/phylocanvas.gl"
//import PhylocanvasGL, { TreeTypes } from "@phylocanvas/phylocanvas.gl";
//import metadata from 'phylocanvas-plugin-metadata';

//Phylocanvas.plugin(metadata);

import blasterjs from 'biojs-vis-blasterjs';

window.$ = $;
window.msa = msa;
window.blasterjs = blasterjs;
//window.Phylocanvas = Phylocanvas;
//window.PhylocanvasGL = PhylocanvasGL;
//window.TreeTypes = TreeTypes;
window.Fasta = Fasta;
import SeqView from "sequence-viewer";

window.SeqView = SeqView;

import FeatureViewer from 'feature-viewer';

window.FeatureViewer = FeatureViewer;

import {Stage as NGL} from 'ngl'
window.NGL = NGL;

import initRDKitModule from "@rdkit/rdkit";

window.initRDKit = (() => {
    let rdkitLoadingPromise;

    return () => {
        /**
         * Utility function ensuring there's only one call made to load RDKit
         * It returns a promise with the resolved RDKit API as value on success,
         * and a rejected promise with the error on failure.
         *
         * The RDKit API is also attached to the global object on successful load.
         */
        if (!rdkitLoadingPromise) {
            rdkitLoadingPromise = new Promise((resolve, reject) => {
                initRDKitModule()
                    .then((RDKit) => {
                        resolve(RDKit);
                    })
                    .catch((e) => {
                        reject();
                    });
            });
        }

        return rdkitLoadingPromise;
    };
})();

/*

window.customElements.define("protvista-track", ProtvistaTrack);
export default (name, constructor) => {
  if (!window.customElements.get(name)) {
    window.customElements.define(name, constructor);
  }
};

* */




