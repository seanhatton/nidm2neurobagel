# PyNIDM → Neurobagel Conversion: Implementation Plan & Documentation

> **Date:** 2026-08-10
> **Status:** Implementation complete and validated

This document captures the complete analysis, design, mapping strategy, and implementation of a tool that converts **PyNIDM RDF** (Turtle format) into **Neurobagel-compatible RDF/JSON-LD** using SPARQL CONSTRUCT queries.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Schema Analysis](#3-schema-analysis)
4. [Entity Mapping Strategy](#4-entity-mapping-strategy)
5. [Key Technical Challenges](#5-key-technical-challenges)
6. [SPARQL CONSTRUCT Query Design](#6-sparql-construct-query-design)
7. [Python Wrapper](#7-python-wrapper)
8. [Validation Results](#8-validation-results)
9. [Usage](#9-usage)
10. [Namespaces](#10-namespaces)
11. [Files Created](#11-files-created)
12. [Status & Next Steps](#12-status--next-steps)

---

## 1. Project Overview

The goal is to convert PyNIDM RDF graphs (neuroimaging experiment provenance encoded using the NIDASH `nidm:` vocabulary and W3C PROV-O) into the **Neurobagel** schema used by the `annotation-tool`, so that NIDM-formatted datasets can be ingested into the Neurobagel graph database and query/annotation tooling.

> **Core technology:** A **SPARQL CONSTRUCT** query (see [RDF-SPARQL-Query](https://www.w3.org/TR/rdf-sparql-query/)) transforms RDF → RDF. `rdflib` executes the query and serializes the result.

---

## 2. Repository Structure

### PyNIDM (Source schema)
- **Location:** `c:\Users\sehatton\Documents\GitHub\PyNIDM`
- **Core schema:** `src/nidm/experiment/schema/nidm_schema.yaml` (600+ lines, LinkML format)
- **Source examples:**
  - `tests/experiment/test_nidm.ttl` — basic Project→Session→Acquisition→AcquisitionObject hierarchy
  - `tests/experiment/data/read_nidm/brainvol_nidm.ttl` (7,117 lines) — real FreeSurfer/FSL/ANTS derivative stats
  - `tests/experiment/data/read_nidm/derivatives_nidm.ttl` — minimal derivative provenance fixture

### annotation-tool / Neurobagel (Target schema)
- **Location:** `c:\Users\sehatton\Documents\GitHub\annotation-tool`
- **Reference file:** `example_synthetic_pheno-bids-derivatives.jsonld`
- **Target classes:** Dataset, Subject, Session (Phenotypic/Imaging), Acquisition, Image, Assessment, Diagnosis, Sex, Age, Pipeline (CompletedPipeline)

---

## 3. Schema Analysis

### 3.1 PyNIDM Schema (`nidm_schema.yaml`)
Complete LinkML schema with:
- **20+ classes** with inheritance: Project, Session, Acquisition, AcquisitionObject, DataElement, PersonalDataElement, Derivative, DerivativeObject, Person, SoftwareAgent, Association, Collection, ExportActivity
- **Enums:** AcquisitionModality (MRI, PET, fMRI, …), ImageContrastType (T1Weighted, T2Weighted, DiffusionWeighted, …), ImageUsageType (Anatomical, Functional, DiffusionWeighted, …)
- **DataElement dual role** — both a metadata subject (with `rdfs:label`, `dct:description`) AND a predicate on AcquisitionObjects storing actual values

### 3.2 Actual RDF patterns observed (critical corrections)

The following patterns differ from initial assumptions and were verified against the real `.ttl` files:

| Item | Actual pattern |
|------|----------------|
| **Person** | typed `prov:Person` (NOT `nidm:Person`) |
| **Project → Session** | `?session dct:isPartOf ?project` (reverse direction, NOT `nidm:hasSession`) |
| **Session → Acquisition** | `?acquisition dct:isPartOf ?session` |
| **Project label** | `dctypes:title` or `dcmitype:title` |
| **Acquisition modality** | `nidm:hadAcquisitionModality nidm:MagneticResonanceImaging` |
| **Image contrast** | `nidm:hadImageContrastType nidm:T1Weighted` |
| **Subject link** | Acquisition's `prov:qualifiedAssociation` → `prov:Association` → `prov:agent` with `prov:hadRole sio:Subject` |
| **Software agent** | `prov:qualifiedAssociation` with role `nidm:NIDM_0000164` |
| **Derivative activity** | typed `prov:Activity` |
| **Demographics** | `ncicb:Age`, `ndar:gender` |

### 3.3 Neurobagel Schema (from JSON-LD `@context`)
Flattened structure optimized for graph-database queries:

```
Dataset ──hasSubject──▶ Subject ──hasSession──▶ Session (Phenotypic|Imaging)
                                              └──hasAcquisition──▶ Acquisition ──hasImage──▶ Image
                                              └──hasAssessment──▶ Assessment
Subject ──hasDiagnosis──▶ Diagnosis
Subject ──hasSex──▶ Sex
Subject ──hasAge──▶ Age
Pipeline ──hasName/hasVersion/hasParameters──▶ ...
```

---

## 4. Entity Mapping Strategy

| PyNIDM | Neurobagel | Notes |
|--------|------------|-------|
| `Project` | `Dataset` | Label from `dctypes:title` |
| `Person` (via `prov:qualifiedAssociation` with `sio:Subject` role) | `Subject` | Identifier from `ndar:src_subject_id` |
| `Session` | `ImagingSession` / `PhenotypicSession` | Determined by presence of imaging modality |
| `Acquisition` + `AcquisitionObject` (imaging) | `Acquisition` + `Image` | Modality, contrast type, file path |
| `AcquisitionObject` (assessment) | `Assessment / Diagnosis / Sex / Age` | Via `ncicb:Age`, `ndar:gender`, dynamic `PersonalDataElement` predicates |
| Derivative (FS/FSL/ANTS stats) | `CompletedPipeline` | `prov:wasGeneratedBy` → activity → software agent |

---

## 5. Key Technical Challenges

1. **Dynamic predicates:** DataElement URIs become predicates on AcquisitionObjects (e.g. `niiri:age_1nif2oc "12.36"`).
2. **Provenance depth:** PyNIDM uses PROV-O (Activity/Entity/Agent) with qualified associations.
3. **Multiple derivative types:** FreeSurfer, FSL, and ANTS each have their own namespaces and DataElement definitions.
4. **Controlled vocabulary mapping:** `nidm:isAbout`, `rdfs:label` from DataElements → SNOMED/NCIT terms.
5. **Duplicate-prefix rdflib bug:** declaring two PREFIXes pointing to the same URI (e.g. `dct:` and `dcterms:` → `http://purl.org/dc/terms/`) breaks `graph.query()`. Must consolidate to a single prefix per URI.

---

## 6. SPARQL CONSTRUCT Query Design

The query in `construct_query.sparql` transforms in six phases:

- **Phase 1 — Dataset:** `?project a nidm:Project` → `?dataset a nb:Dataset`
- **Phase 2 — Subjects:** Persons associated via `sio:Subject` role → `nb:Subject`
- **Phase 3 — Sessions:** `dct:isPartOf` chain → `nb:ImagingSession`/`nb:PhenotypicSession`
- **Phase 4 — Acquisitions & Images:** imaging AcquisitionObjects → `nb:Acquisition` + `nb:Image`
- **Phase 5 — Assessments:** `onli:instrument-based-assessment` objects → `nb:Assessment`
- **Phase 6 — Pipelines:** FS/FSL/ANTS stats → `nb:CompletedPipeline`, `nb:SoftwareAgent`, `nb:DerivativeCollection`, `nb:Measurement`

### Key query structure snippets

```sparql
# Dataset from Project
?project a nidm:Project .
OPTIONAL { ?project dctypes:title ?projectLabel . }
BIND(IRI(CONCAT("http://neurobagel.org/dataset/",
      REPLACE(STR(?project), ".*[/#]([^/#]+)$", "$1"))) AS ?dataset)

# Sessions linked via dct:isPartOf (reverse)
?session a nidm:Session .
{ ?session dct:isPartOf ?project . }
UNION { ?session dct:isPartOf ?project . }

# Imaging session detection
OPTIONAL {
  ?memberActivity a nidm:Acquisition ;
                  dct:isPartOf ?session .
  ?imgObj a nidm:AcquisitionObject ;
          prov:wasGeneratedBy ?memberActivity ;
          nidm:hadAcquisitionModality ?modType .
  FILTER(?modType IN (nidm:MagneticResonanceImaging, ...))
}
BIND(IF(BOUND(?modType), nb:ImagingSession, nb:PhenotypicSession) AS ?sessionType)
```

---

## 7. Python Wrapper

`pynidm_to_neurobagel.py` loads a PyNIDM Turtle/JSON-LD graph, executes the CONSTRUCT query, and serializes to Turtle or JSON-LD (optionally embedding a context).

```bash
# Usage
python pynidm_to_neurobagel.py input.ttl -o out.ttl
python pynidm_to_neurobagel.py input.ttl --format json-ld --context neurobagel_context.jsonld -o out.jsonld
```

**Features:**
- Binds all namespaces on the output graph for clean serialization
- CLI flags: `-o/--output`, `--format`, `--query`, `--context`, `-v/--verbose`
- Uses modern `rdflib.Dataset` (replaces deprecated `ConjunctiveGraph`)
- Validates the query and warns on empty output

---

## 8. Validation Results

| Input file | Triples in | Triples out | Notes |
|------------|-----------|-------------|-------|
| `tests/experiment/test_nidm.ttl` | 68 | **29** | Dataset, Subject, ImagingSession, Acquisitions, Images |
| `tests/experiment/data/read_nidm/brainvol_nidm.ttl` | 7,117 | **290** | + CompletedPipeline, DerivativeCollection, 36 Measurements, SoftwareAgent |
| `tests/experiment/data/read_nidm/derivatives_nidm.ttl` | 190 | 0 | Minimal provenance-only fixture (no Session/Acquisition chain) |

### Sample output (from `test_nidm.ttl`)
```turtle
<http://neurobagel.org/dataset/c0667568-...> a nb:Dataset ;
    rdfs:label "Test Project name" ;
    nb:hasSubject <http://neurobagel.org/subject/c066d198-...> ;
    dct:description "Test Project Description" .

<http://iri.nidash.org/c067401a-...> a nb:ImagingSession ;
    rdfs:label "Session c067401a-..." ;
    nb:hasAcquisition <...c0676dc4...>, <...c06844ba...>, <...c0690c92...> .

<http://iri.nidash.org/c0676dc4-...> a nb:Acquisition ;
    nb:hasImage <http://neurobagel.org/image/c0679cae-...> ;
    nb:modality nidm:MagneticResonanceImaging .
```

---

## 9. Usage

### Prerequisites
- Python 3.9+
- `rdflib` (v7.5.0 tested)
- Conda env `base` at `C:/Users/sehatton/miniconda3/python.exe`

### Quick start
```bash
cd c:\Users\sehatton\Documents\GitHub\PyNIDM
C:/Users/sehatton/miniconda3/python.exe pynidm_to_neurobagel.py tests/experiment/test_nidm.ttl -o out.ttl
C:/Users/sehatton/miniconda3/python.exe pynidm_to_neurobagel.py tests/experiment/test_nidm.ttl --format json-ld --context neurobagel_context.jsonld -o out.jsonld
```

---

## 10. Namespaces

### PyNIDM input prefixes
`nidm`, `prov`, `niiri`, `bids`, `dct`, `dctypes`, `nfo`, `sio`, `onli`, `reproschema`, `ilx`, `fsl`, `freesurfer`/`fs`, `ants`, `xsd`, `crypto`, `dcat`, `dicom`, `ndar`, `ncicb`, `obo`, `pato`, `schema`, `vc`, `xml`, `scr`, `nlx`, `birnlex`, `uberon`

> **Note:** multiple synonyms point to the same URI (e.g. `dct`/`dcterms`, `dctypes`/`dcmitype`, `ncicb`/`ncit`). The query consolidates to one prefix per URI to avoid the rdflib duplicate-prefix bug.

### Neurobagel output prefixes
`nb` (`http://neurobagel.org/vocab#`), `np` (`http://neurobagel.org/vocab/phenotype#`), `snomed`, `ncit`

---

## 11. Files Created

| File | Purpose |
|------|---------|
| `pynidm_to_neurobagel.py` | Main converter CLI (rdflib) |
| `construct_query.sparql` | Multi-phase SPARQL CONSTRUCT query |
| `neurobagel_context.jsonld` | JSON-LD `@context` for output framing |

---

## 12. Status & Next Steps

### Done
- ✅ Schema analysis of PyNIDM (`nidm_schema.yaml`) & Neurobagel (JSON-LD)
- ✅ Entity mapping strategy
- ✅ SPARQL CONSTRUCT query (all 6 phases)
- ✅ Python wrapper CLI
- ✅ JSON-LD context
- ✅ Validation on `test_nidm.ttl` and `brainvol_nidm.ttl`

### Possible next steps
- [ ] Expand Session/Acquisition handling for additional modalities (PET, DTI, CT)
- [ ] Improve controlled-vocabulary (SNOMED/NCIT) mapping from `nidm:isAbout`
- [ ] Add a `pyproject`/console-script entry point
- [ ] Frame JSON-LD output to the exact Neurobagel spec (avoid nested `@context`)
- [ ] Tests / CI integration

---

*Generated from conversation analysis on 2026-08-10.*