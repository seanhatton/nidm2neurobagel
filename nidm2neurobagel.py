#!/usr/bin/env python3
"""
NIDM to Neurobagel JSON-LD / RDF Converter

Converts NIDM RDF (Turtle / JSON-LD) into Neurobagel-compatible JSON-LD or RDF
using SPARQL queries executed with rdflib, structuring output according to the
Neurobagel data model (bagel-cli).

Usage examples:
    python nidm2neurobagel.py example/test_nidm.ttl
    python nidm2neurobagel.py example/test_nidm.ttl -o output.jsonld
    python nidm2neurobagel.py example/test_nidm.ttl -o output.ttl --format turtle
"""

import argparse
import json
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import rdflib
from rdflib import Dataset, Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD, PROV, DCTERMS

log = logging.getLogger("nidm2neurobagel")

# --------------------------------------------------------------------------- #
# Namespaces
# --------------------------------------------------------------------------- #
NB = Namespace("http://neurobagel.org/vocab/")
NP = Namespace("https://github.com/nipoppy/pipeline-catalog/tree/main/processing/")
NIDM = Namespace("http://purl.org/nidash/nidm#")
SNOMED = Namespace("http://purl.bioontology.org/ontology/SNOMEDCT/")
NCIT = Namespace("http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#")

NAMESPACES = {
    "nb": NB,
    "np": NP,
    "nidm": NIDM,
    "snomed": SNOMED,
    "ncit": NCIT,
    "prov": PROV,
    "rdf": RDF,
    "rdfs": RDFS,
    "xsd": XSD,
    "dct": Namespace("http://purl.org/dc/terms/"),
    "dctypes": Namespace("http://purl.org/dc/dcmitype/"),
    "nfo": Namespace("http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#"),
    "sio": Namespace("http://semanticscience.org/ontology/sio.owl#"),
    "sio_res": Namespace("http://semanticscience.org/resource/"),
    "onli": Namespace("http://neurolog.unice.fr/ontoneurolog/v3.0/instrument.owl#"),
    "ndar": Namespace("https://ndar.nih.gov/api/datadictionary/v2/dataelement/"),
    "ncicb": Namespace("http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#"),
    "foaf": Namespace("http://xmlns.com/foaf/0.1/"),
    "fs": Namespace("http://purl.org/nidash/freesurfer#"),
    "fsl": Namespace("http://purl.org/nidash/fsl#"),
    "ants": Namespace("http://purl.org/nidash/ants#"),
}

DEFAULT_CONTEXT_PATH = Path(__file__).resolve().parent / "neurobagel_context.jsonld"

# Standard controlled term mapping for Sex / Gender
SEX_MAP = {
    "male": "snomed:248153007",
    "m": "snomed:248153007",
    "1": "snomed:248153007",
    "female": "snomed:248152002",
    "f": "snomed:248152002",
    "2": "snomed:248152002",
    "other": "snomed:32570681000036106",
}


def make_uuid_uri() -> str:
    """Generate a valid Neurobagel UUID identifier (nb:<uuid4>)."""
    return f"nb:{uuid.uuid4()}"


def load_context(context_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the Neurobagel JSON-LD context."""
    p = Path(context_path) if context_path else DEFAULT_CONTEXT_PATH
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("@context", data)
    # Fallback minimal context
    return {
        "nb": "http://neurobagel.org/vocab/",
        "snomed": "http://purl.bioontology.org/ontology/SNOMEDCT/",
        "nidm": "http://purl.org/nidash/nidm#",
        "ncit": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#",
        "np": "https://github.com/nipoppy/pipeline-catalog/tree/main/processing/",
        "schemaKey": "@type",
        "identifier": "@id",
        "Acquisition": "nb:Acquisition",
        "Assessment": "nb:Assessment",
        "CompletedPipeline": "nb:CompletedPipeline",
        "Dataset": "nb:Dataset",
        "Diagnosis": "nb:Diagnosis",
        "Image": "nb:Image",
        "ImagingSession": "nb:ImagingSession",
        "PhenotypicSession": "nb:PhenotypicSession",
        "Pipeline": "nb:Pipeline",
        "Session": "nb:Session",
        "Sex": "nb:Sex",
        "Subject": "nb:Subject",
        "hasAcquisition": {"@id": "nb:hasAcquisition"},
        "hasAge": {"@id": "nb:hasAge"},
        "hasAssessment": {"@id": "nb:hasAssessment"},
        "hasCompletedPipeline": {"@id": "nb:hasCompletedPipeline"},
        "hasContrastType": {"@id": "nb:hasContrastType"},
        "hasDiagnosis": {"@id": "nb:hasDiagnosis"},
        "hasFilePath": {"@id": "nb:hasFilePath"},
        "hasLabel": {"@id": "nb:hasLabel"},
        "hasPipelineName": {"@id": "nb:hasPipelineName"},
        "hasPipelineVersion": {"@id": "nb:hasPipelineVersion"},
        "hasSamples": {"@id": "nb:hasSamples"},
        "hasSession": {"@id": "nb:hasSession"},
        "hasSex": {"@id": "nb:hasSex"},
    }


def load_source_graph(input_path: str) -> Graph:
    """Parse a NIDM Turtle/JSON-LD file into an rdflib Graph."""
    graph = Graph()
    fmt = "turtle"
    if input_path.lower().endswith((".jsonld", ".json")):
        fmt = "json-ld"
    graph.parse(input_path, format=fmt)
    return graph


def extract_neurobagel_dataset(source: Graph) -> Dict[str, Any]:
    """
    Extract entities from NIDM graph using SPARQL SELECT queries and
    structure them into a Neurobagel Dataset JSON-LD dictionary.
    """
    # ----------------------------------------------------------------------- #
    # 1. Project / Dataset metadata
    # ----------------------------------------------------------------------- #
    q_project = """
    PREFIX nidm: <http://purl.org/nidash/nidm#>
    PREFIX dct: <http://purl.org/dc/terms/>
    PREFIX dctypes: <http://purl.org/dc/dcmitype/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?project ?title ?desc WHERE {
        ?project a nidm:Project .
        OPTIONAL { ?project dctypes:title ?title . }
        OPTIONAL { ?project rdfs:label ?title . }
        OPTIONAL { ?project dct:description ?desc . }
    }
    """
    dataset_label = "Neurobagel Dataset"
    dataset_desc = None
    for row in source.query(q_project):
        if row.title:
            dataset_label = str(row.title)
        if row.desc:
            dataset_desc = str(row.desc)
        break

    # ----------------------------------------------------------------------- #
    # 2. Subjects (Persons associated with Acquisitions/Project via sio:Subject role)
    # ----------------------------------------------------------------------- #
    q_subjects = """
    PREFIX nidm: <http://purl.org/nidash/nidm#>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX sio_owl: <http://semanticscience.org/ontology/sio.owl#>
    PREFIX sio_res: <http://semanticscience.org/resource/>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ndar: <https://ndar.nih.gov/api/datadictionary/v2/dataelement/>

    SELECT DISTINCT ?person ?srcId ?label ?givenName ?familyName WHERE {
        {
            ?acq a nidm:Acquisition ;
                 prov:qualifiedAssociation ?assoc .
            ?assoc prov:agent ?person ;
                   prov:hadRole ?role .
            FILTER(?role IN (sio_owl:Subject, sio_res:Subject))
        }
        UNION
        {
            ?project a nidm:Project ;
                     prov:qualifiedAssociation ?assoc .
            ?assoc prov:agent ?person ;
                   prov:hadRole ?role .
            FILTER(?role IN (sio_owl:Subject, sio_res:Subject))
        }
        OPTIONAL { ?person ndar:src_subject_id ?srcId . }
        OPTIONAL { ?person rdfs:label ?label . }
        OPTIONAL { ?person foaf:givenName ?givenName . }
        OPTIONAL { ?person foaf:familyName ?familyName . }
    }
    """
    subjects_map = {}  # person_uri -> Subject dict
    for row in source.query(q_subjects):
        person_uri = str(row.person)
        if row.srcId:
            sub_label = str(row.srcId)
        elif row.label:
            sub_label = str(row.label)
        elif row.givenName and row.familyName:
            sub_label = f"{row.givenName} {row.familyName}"
        elif row.givenName:
            sub_label = str(row.givenName)
        else:
            sub_label = re.sub(r"^.*[/#]", "", person_uri)

        subjects_map[person_uri] = {
            "identifier": make_uuid_uri(),
            "hasLabel": sub_label,
            "hasSession": [],
            "schemaKey": "Subject",
            "_uri": person_uri,
        }

    # ----------------------------------------------------------------------- #
    # 3. Sessions & Acquisitions hierarchy
    # ----------------------------------------------------------------------- #
    q_acquisitions = """
    PREFIX nidm: <http://purl.org/nidash/nidm#>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX sio_owl: <http://semanticscience.org/ontology/sio.owl#>
    PREFIX sio_res: <http://semanticscience.org/resource/>
    PREFIX dct: <http://purl.org/dc/terms/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?session ?sessionLabel ?sessionDesc ?acq ?person WHERE {
        ?session a nidm:Session .
        OPTIONAL { ?session rdfs:label ?sessionLabel . }
        OPTIONAL { ?session dct:description ?sessionDesc . }
        ?acq a nidm:Acquisition ;
             dct:isPartOf ?session .
        OPTIONAL {
            ?acq prov:qualifiedAssociation ?assoc .
            ?assoc prov:agent ?person ;
                   prov:hadRole ?role .
            FILTER(?role IN (sio_owl:Subject, sio_res:Subject))
        }
    }
    """
    subj_sessions: Dict[tuple, Dict[str, Any]] = {}

    for row in source.query(q_acquisitions):
        session_uri = str(row.session)
        person_uri = str(row.person) if row.person else None
        acq_uri = str(row.acq)

        target_persons = [person_uri] if person_uri else list(subjects_map.keys())
        for p_uri in target_persons:
            key = (p_uri, session_uri)
            if key not in subj_sessions:
                s_label = str(row.sessionLabel) if row.sessionLabel else re.sub(r"^.*[/#]", "", session_uri)
                subj_sessions[key] = {
                    "session_uri": session_uri,
                    "session_label": s_label,
                    "acquisitions": set(),
                    "hasAge": None,
                    "hasSex": None,
                    "hasDiagnosis": [],
                    "hasAssessment": [],
                    "imagingAcquisitions": [],
                    "completedPipelines": [],
                }
            subj_sessions[key]["acquisitions"].add(acq_uri)

    # ----------------------------------------------------------------------- #
    # 4. AcquisitionObjects (Images, Demographics, Assessments)
    # ----------------------------------------------------------------------- #
    q_objects = """
    PREFIX nidm: <http://purl.org/nidash/nidm#>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX nfo: <http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#>
    PREFIX ncicb: <http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#>
    PREFIX ndar: <https://ndar.nih.gov/api/datadictionary/v2/dataelement/>
    PREFIX onli: <http://neurolog.unice.fr/ontoneurolog/v3.0/instrument.owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?acqObj ?acq ?modality ?contrast ?filename ?age ?gender ?isAssessInst ?toolLabel WHERE {
        ?acqObj a nidm:AcquisitionObject ;
                prov:wasGeneratedBy ?acq .
        OPTIONAL { ?acqObj nidm:hadAcquisitionModality ?modality . }
        OPTIONAL { ?acqObj nidm:hadImageContrastType ?contrast . }
        OPTIONAL { ?acqObj nfo:filename ?filename . }
        OPTIONAL { ?acqObj ncicb:Age ?age . }
        OPTIONAL { ?acqObj ndar:gender ?gender . }
        OPTIONAL { ?acq rdfs:label ?toolLabel . }
        BIND(EXISTS { ?acqObj a onli:assessment-instrument } AS ?isAssessInst)
    }
    """
    for row in source.query(q_objects):
        acq_uri = str(row.acq)
        for (p_uri, s_uri), s_data in subj_sessions.items():
            if acq_uri in s_data["acquisitions"]:
                                # Check for Imaging
                if row.modality or row.contrast:
                    contrast_uri = str(row.contrast) if row.contrast else None
                    if not contrast_uri:
                        # Default to T1Weighted for MRI if unspecified
                        contrast_uri = "nidm:T1Weighted"
                    elif contrast_uri.startswith("http://purl.org/nidash/nidm#"):
                        contrast_uri = "nidm:" + contrast_uri.split("#")[-1]

                    s_data["imagingAcquisitions"].append({
                        "identifier": make_uuid_uri(),
                        "hasContrastType": {
                            "identifier": contrast_uri,
                            "schemaKey": "Image",
                        },
                        "schemaKey": "Acquisition",
                    })

                # Check for Age
                if row.age is not None:
                    try:
                        s_data["hasAge"] = float(str(row.age))
                    except ValueError:
                        pass

                # Check for Sex
                if row.gender is not None:
                    g_val = str(row.gender).strip().lower()
                    term_id = SEX_MAP.get(g_val, f"snomed:{g_val}")
                    s_data["hasSex"] = {
                        "identifier": term_id,
                        "schemaKey": "Sex",
                    }

                # Check for Assessment Instrument
                if row.isAssessInst and not (row.age is not None or row.gender is not None):
                    tool_id = "snomed:assessment"
                    if row.toolLabel:
                        tool_id = f"snomed:{row.toolLabel}"
                    s_data["hasAssessment"].append({
                        "identifier": tool_id,
                        "schemaKey": "Assessment",
                    })

    # ----------------------------------------------------------------------- #
    # 5. Derivatives / CompletedPipelines
    # ----------------------------------------------------------------------- #
    q_pipelines = """
    PREFIX nidm: <http://purl.org/nidash/nidm#>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX sio: <http://semanticscience.org/ontology/sio.owl#>
    PREFIX sio_res: <http://semanticscience.org/resource/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?derivActivity ?swName ?swVer ?swLabel WHERE {
        ?stats prov:wasGeneratedBy ?derivActivity .
        {
            ?derivActivity prov:qualifiedAssociation ?assoc .
            ?assoc prov:agent ?swAgent ;
                   prov:hadRole nidm:NIDM_0000164 .
        }
        UNION
        {
            ?derivActivity prov:wasAssociatedWith ?swAgent .
            ?swAgent a prov:SoftwareAgent .
        }
        OPTIONAL { ?swAgent sio:hasName ?swName . }
        OPTIONAL { ?swAgent sio_res:hasName ?swName . }
        OPTIONAL { ?swAgent sio:hasVersion ?swVer . }
        OPTIONAL { ?swAgent sio_res:hasVersion ?swVer . }
        OPTIONAL { ?swAgent rdfs:label ?swLabel . }
    }
    """
    pipelines_found = []
    for row in source.query(q_pipelines):
        p_name = str(row.swName or row.swLabel or "pipeline").lower()
        p_ver = str(row.swVer or "unknown")
        pipe_term = f"np:{p_name}"
        pipelines_found.append({
            "identifier": make_uuid_uri(),
            "hasPipelineName": {
                "identifier": pipe_term,
                "schemaKey": "Pipeline",
            },
            "hasPipelineVersion": p_ver,
            "schemaKey": "CompletedPipeline",
        })

    # ----------------------------------------------------------------------- #
    # 6. Assemble the nested Neurobagel Subject & Session hierarchy
    # ----------------------------------------------------------------------- #
    for (p_uri, s_uri), s_data in subj_sessions.items():
        if p_uri not in subjects_map:
            continue
        subject_dict = subjects_map[p_uri]

        # 6a. PhenotypicSession
        has_pheno = (
            s_data["hasAge"] is not None
            or s_data["hasSex"] is not None
            or len(s_data["hasDiagnosis"]) > 0
            or len(s_data["hasAssessment"]) > 0
        )
        if has_pheno:
            pheno_session = {
                "identifier": make_uuid_uri(),
                "hasLabel": s_data["session_label"],
                "schemaKey": "PhenotypicSession",
            }
            if s_data["hasAge"] is not None:
                pheno_session["hasAge"] = s_data["hasAge"]
            if s_data["hasSex"] is not None:
                pheno_session["hasSex"] = s_data["hasSex"]
            if s_data["hasDiagnosis"]:
                pheno_session["hasDiagnosis"] = s_data["hasDiagnosis"]
            if s_data["hasAssessment"]:
                pheno_session["hasAssessment"] = s_data["hasAssessment"]

            subject_dict["hasSession"].append(pheno_session)

        # 6b. ImagingSession
        s_pipelines = list(s_data["completedPipelines"]) + pipelines_found
        has_imaging = len(s_data["imagingAcquisitions"]) > 0 or len(s_pipelines) > 0

        if has_imaging:
            img_session = {
                "identifier": make_uuid_uri(),
                "hasLabel": s_data["session_label"],
                "schemaKey": "ImagingSession",
            }
            if s_data["imagingAcquisitions"]:
                img_session["hasAcquisition"] = s_data["imagingAcquisitions"]
            if s_pipelines:
                img_session["hasCompletedPipeline"] = s_pipelines

            subject_dict["hasSession"].append(img_session)

    # Clean up internal metadata fields
    samples_list = []
    for s in subjects_map.values():
        s.pop("_uri", None)
        samples_list.append(s)

    dataset = {
        "identifier": make_uuid_uri(),
        "hasLabel": dataset_label,
        "hasSamples": samples_list,
        "schemaKey": "Dataset",
    }
    return dataset


def convert_to_rdf(dataset_json: Dict[str, Any], context: Dict[str, Any]) -> Graph:
    """
    Convert a Neurobagel Dataset JSON-LD dictionary into an rdflib RDF Graph.
    """
    jsonld_doc = {"@context": context, **dataset_json}
    g = Graph()
    g.parse(data=json.dumps(jsonld_doc), format="json-ld")
    return g


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="Input NIDM RDF file (.ttl or .jsonld)")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--format",
        choices=["json-ld", "turtle", "n3", "rdfxml", "nt"],
        default="json-ld",
        help="Output serialization format (default: json-ld)",
    )
    parser.add_argument(
        "--context", help="Path to a custom Neurobagel JSON-LD context file"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info("Parsing input NIDM: %s", args.input)
    source_graph = load_source_graph(args.input)
    log.info("Loaded %d triples from source", len(source_graph))

    context = load_context(args.context)
    log.info("Extracting Neurobagel dataset model")
    dataset_dict = extract_neurobagel_dataset(source_graph)
    log.info(
        "Extracted dataset '%s' with %d subject(s)",
        dataset_dict.get("hasLabel"),
        len(dataset_dict.get("hasSamples", [])),
    )

    if args.format == "json-ld":
        output_data = {"@context": context, **dataset_dict}
        serialized = json.dumps(output_data, indent=2, ensure_ascii=False) + "\n"
    else:
        fmt = "xml" if args.format == "rdfxml" else args.format
        rdf_graph = convert_to_rdf(dataset_dict, context)
        serialized = rdf_graph.serialize(format=fmt)

    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
        log.info("Wrote output to %s", args.output)
    else:
        sys.stdout.write(serialized)

    return 0


if __name__ == "__main__":
    sys.exit(main())