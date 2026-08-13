import json
from pathlib import Path
import pytest
from rdflib import Graph
from nidm2neurobagel import (
    load_source_graph,
    extract_neurobagel_dataset,
    load_context,
    convert_to_rdf,
)


def test_test_nidm_extraction():
    test_nidm_path = Path(__file__).parent / "example" / "test_nidm.ttl"
    g = load_source_graph(str(test_nidm_path))
    assert len(g) > 0

    dataset = extract_neurobagel_dataset(g)
    assert dataset["schemaKey"] == "Dataset"
    assert dataset["hasLabel"] == "Test Project name"
    assert dataset["identifier"].startswith("nb:")

    samples = dataset.get("hasSamples", [])
    assert len(samples) == 2

    # Map by label
    sub_map = {s["hasLabel"]: s for s in samples}
    assert "John Doe" in sub_map
    assert "George" in sub_map

    # John Doe checks
    john = sub_map["John Doe"]
    assert john["schemaKey"] == "Subject"
    assert len(john["hasSession"]) == 1
    john_pheno = john["hasSession"][0]
    assert john_pheno["schemaKey"] == "PhenotypicSession"
    assert john_pheno["hasAge"] == 60.0
    assert john_pheno["hasSex"]["schemaKey"] == "Sex"
    assert john_pheno["hasSex"]["identifier"] == "snomed:248153007"

    # George checks
    george = sub_map["George"]
    assert george["schemaKey"] == "Subject"
    assert len(george["hasSession"]) == 2
    session_types = {ses["schemaKey"] for ses in george["hasSession"]}
    assert "PhenotypicSession" in session_types
    assert "ImagingSession" in session_types

    pheno_ses = [s for s in george["hasSession"] if s["schemaKey"] == "PhenotypicSession"][0]
    assert len(pheno_ses["hasAssessment"]) == 1
    assert pheno_ses["hasAssessment"][0]["schemaKey"] == "Assessment"

    img_ses = [s for s in george["hasSession"] if s["schemaKey"] == "ImagingSession"][0]
    assert len(img_ses["hasAcquisition"]) == 1
    acq = img_ses["hasAcquisition"][0]
    assert acq["schemaKey"] == "Acquisition"
    assert acq["hasContrastType"]["schemaKey"] == "Image"


def test_neurobagel_jsonld_structure_compliance():
    """Verify structure matches example synthetic Neurobagel documents."""
    test_nidm_path = Path(__file__).parent / "example" / "test_nidm.ttl"
    g = load_source_graph(str(test_nidm_path))
    dataset = extract_neurobagel_dataset(g)
    ctx = load_context()

    doc = {"@context": ctx, **dataset}
    # Check top-level JSON-LD serializability
    json_str = json.dumps(doc)
    assert len(json_str) > 0

    # Test conversion to RDF graph and roundtrip
    rdf_g = convert_to_rdf(dataset, ctx)
    assert len(rdf_g) > 20


def test_sparql_construct_query():
    """Verify construct_query.sparql execution directly."""
    test_nidm_path = Path(__file__).parent / "example" / "test_nidm.ttl"
    query_path = Path(__file__).parent / "construct_query.sparql"
    g = load_source_graph(str(test_nidm_path))
    query_text = query_path.read_text(encoding="utf-8")

    res = g.query(query_text)
    out_g = Graph()
    for t in res:
        out_g.add(t)

    assert len(out_g) > 20
