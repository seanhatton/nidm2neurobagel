# nidm2neurobagel
Convert NIDM-encoded RDFs to Neurobagel RDFs

## Requirements

Install the Python dependency:

```bash
python -m pip install -r requirements.txt
```

## Usage

Convert a PyNIDM Turtle file to JSON-LD output (default):

```bash
python pynidm_to_neurobagel.py input.ttl -o output.jsonld
```

Export as Turtle:

```bash
python pynidm_to_neurobagel.py input.ttl -o output.jsonld --format json-ld --context neurobagel_context.jsonld
```

If no output file is provided, the converted RDF is written to stdout.
