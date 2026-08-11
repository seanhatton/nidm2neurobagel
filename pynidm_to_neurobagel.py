#!/usr/bin/env python3
"""
PyNIDM to Neurobagel RDF Converter

Converts PyNIDM RDF (Turtle format) into Neurobagel-compatible RDF
using a SPARQL CONSTRUCT query executed with rdflib.

Supported output formats:
    - json-ld (default)  Serialize as JSON-LD (optionally framed with a context)
    - turtle             Serialize as Turtle

Usage examples:
    python pynidm_to_neurobagel.py input.ttl
    python pynidm_to_neurobagel.py input.ttl -o out.jsonld
    python pynidm_to_neurobagel.py input.ttl -o out.jsonld --context neurobagel_context.jsonld
"""

import argparse
import logging
import sys
from pathlib import Path

from rdflib import Dataset, Namespace
from rdflib.namespace import RDF, RDFS, XSD, PROV, DCTERMS

log = logging.getLogger("pynidm2neurobagel")

# --------------------------------------------------------------------------- #
# Namespace bindings used both for parsing the input graph and for the output
# graph, so prefixes serialize correctly in the result.
# --------------------------------------------------------------------------- #
NAMESPACES = {
    "nidm": Namespace("http://purl.org/nidash/nidm#"),
    "prov": Namespace("http://www.w3.org/ns/prov#"),
    "niiri": Namespace("http://purl.org/nidash/niiri#"),
    "bids": Namespace("http://purl.org/nidash/bids#"),
    "dct": Namespace("http://purl.org/dc/terms/"),
    "dctypes": Namespace("http://purl.org/dc/dcmitype/"),
    "nfo": Namespace("http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#"),
    "sio": Namespace("http://semanticscience.org/resource/"),
    "onli": Namespace("http://purl.org/ontology/onli#"),
    "reproschema": Namespace("http://purl.org/reproschema#"),
    "ilx": Namespace("http://uri.interlex.org/base/ilx_"),
    "fsl": Namespace("http://purl.org/nidash/fsl#"),
    "freesurfer": Namespace("http://purl.org/nidash/freesurfer#"),
    "fs": Namespace("http://purl.org/nidash/freesurfer#"),
    "ants": Namespace("http://purl.org/nidash/ants#"),
    "xsd": Namespace("http://www.w3.org/2001/XMLSchema#"),
    "crypto": Namespace("http://id.loc.gov/vocabulary/preservation/cryptographicHashFunction#"),
    "dcat": Namespace("http://www.w3.org/ns/dcat#"),
    "dicom": Namespace("http://purl.org/nidash/dicom#"),
    "ndar": Namespace("http://purl.org/ndar#"),
    "ncicb": Namespace("http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#"),
    "obo": Namespace("http://purl.obolibrary.org/obo/"),
    "pato": Namespace("http://purl.obolibrary.org/obo/pato#"),
    "schema": Namespace("http://schema.org/"),
    "vc": Namespace("http://www.w3.org/2018/credentials#"),
    "xml": Namespace("http://www.w3.org/XML/1998/namespace"),
    "scr": Namespace("http://purl.org/scr#"),
    "nlx": Namespace("http://uri.neuinfo.org/nif/nlx/"),
    "birnlex": Namespace("http://purl.org/nidash/birnlex#"),
    "uberon": Namespace("http://purl.obolibrary.org/obo/UBERON_"),
    "nb": Namespace("http://neurobagel.org/vocab#"),
    "snomed": Namespace("http://snomed.info/id/"),
    "np": Namespace("http://neurobagel.org/vocab/phenotype#"),
    "rdf": Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    "rdfs": Namespace("http://www.w3.org/2000/01/rdf-schema#"),
}

# --------------------------------------------------------------------------- #
# The SPARQL CONSTRUCT query. Loaded from an external .sparql file so it can be
# re-used / edited independently, but see load_construct_query() fallback.
# --------------------------------------------------------------------------- #
DEFAULT_QUERY_PATH = Path(__file__).resolve().parent / "construct_query.sparql"


def load_construct_query(query_path=None):
    """Load the CONSTRUCT query text from a file or an embedded string."""
    if query_path is not None:
        return Path(query_path).read_text(encoding="utf-8")

    if DEFAULT_QUERY_PATH.exists():
        return DEFAULT_QUERY_PATH.read_text(encoding="utf-8")

    # Embedded fallback (kept minimal; keep construct_query.sparql in sync).
    raise FileNotFoundError(
        f"Could not locate construct query file at {DEFAULT_QUERY_PATH}. "
        "Provide one with --query."
    )


def build_graph():
    """Create a Dataset with all output namespaces pre-bound."""
    graph = Dataset()
    for prefix, ns in NAMESPACES.items():
        graph.bind(prefix, ns)
    return graph


def load_pynidm(input_path):
    """Parse a PyNIDM Turtle/JSON-LD file into an rdflib graph."""
    graph = Dataset()
    for prefix, ns in NAMESPACES.items():
        graph.bind(prefix, ns)

    fmt = "turtle"
    if input_path.lower().endswith((".jsonld", ".json")):
        fmt = "json-ld"
    graph.parse(input_path, format=fmt)
    return graph


def execute_construct(source_graph, query_text):
    """Run a SPARQL CONSTRUCT against source_graph and return the result graph."""
    query = source_graph.query(query_text)
    result_graph = build_graph()
    for triple in query:
        result_graph.add(triple)
    return result_graph


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Input PyNIDM RDF file (.ttl or .jsonld)")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument("--format", choices=["turtle", "json-ld", "n3", "rdfxml"],
                        default="json-ld",
                        help="Output RDF serialization format (default: json-ld)")
    parser.add_argument("--query", help="Path to a custom CONSTRUCT query .sparql file")
    parser.add_argument("--context", help="JSON-LD context file to embed in JSON-LD output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")

    # --- resolve query ------------------------------------------------------ #
    try:
        query_text = load_construct_query(args.query)
    except FileNotFoundError as exc:
        log.error(exc)
        return 2

    # --- parse source ------------------------------------------------------- #
    log.info("Parsing input: %s", args.input)
    source = load_pynidm(args.input)
    log.info("Loaded %d triples from source", len(source))

    # --- execute CONSTRUCT -------------------------------------------------- #
    log.info("Executing SPARQL CONSTRUCT query")
    output = execute_construct(source, query_text)
    log.info("Produced %d triples", len(output))

    if not len(output):
        log.warning("Output graph is empty - check that the input matches the "
                    "expected PyNIDM structure.")

    # --- serialize ---------------------------------------------------------- #
    fmt = args.format
    if fmt == "rdfxml":
        fmt = "xml"

    serialized = output.serialize(format=fmt)

    # Optionally embed a JSON-LD context by framing is more involved; for a
    # simple embed we wrap the serialized JSON-LD with the provided context.
    if fmt == "json-ld" and args.context:
        import json
        try:
            context = json.loads(Path(args.context).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Could not load context file %s: %s", args.context, exc)
            return 2
        # Replace/add the @context at the top of the serialized JSON-LD.
        data = json.loads(serialized)
        if isinstance(data, list):
            for item in data:
                if "@context" not in item:
                    item["@context"] = context
        elif isinstance(data, dict):
            data.setdefault("@context", context)
        serialized = json.dumps(data, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
        log.info("Wrote output to %s", args.output)
    else:
        sys.stdout.write(serialized)
        if not serialized.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())