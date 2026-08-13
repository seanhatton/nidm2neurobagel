# nidm2neurobagel
Convert NIDM-encoded RDFs to Neurobagel RDFs

## Requirements

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

## Usage

Convert a PyNIDM Turtle file to Neurobagel JSON-LD output (default):

```bash
python nidm2neurobagel.py example/test_nidm.ttl -o output.jsonld
```

Export as Turtle:

```bash
python nidm2neurobagel.py example/test_nidm.ttl -o output.ttl --format turtle
```

If no output file is provided, the converted RDF is written to stdout.

## Running Tests

Execute the test suite with `pytest`:

```bash
pytest
```
