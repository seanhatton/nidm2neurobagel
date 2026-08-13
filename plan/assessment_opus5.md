# NIDM → Neurobagel Converter — Assessment & Remediation Plan

> **Reviewed:** `nidm2neurobagel.py`, `construct_query.sparql`,
> `neurobagel_context.jsonld`, `README.md`, `conversion_work_summary.md`
> **Method:** the converter was executed against synthetic NIDM fixtures modelled on
> PyNIDM's real `.ttl` shapes (rdflib 7.6.0, Python 3.13). Output was cross-checked
> against Neurobagel's authoritative data model
> ([`bagel-cli/bagel/models.py`](https://github.com/neurobagel/bagel-cli/blob/main/bagel/models.py),
> [`bagel/mappings.py`](https://github.com/neurobagel/bagel-cli/blob/main/bagel/mappings.py),
> [`bagel/utilities/model_utils.py`](https://github.com/neurobagel/bagel-cli/blob/main/bagel/utilities/model_utils.py)).
> Every claim below is backed by an observed run.

---

## Contents

1. [Headline](#1-headline)
2. [Part 1 — Target schema mismatch](#part-1--target-schema-mismatch-blocking)
3. [Part 2 — Query bugs](#part-2--query-bugs-empirically-verified)
4. [Part 3 — Documentation](#part-3--documentation)
5. [Part 4 — What is genuinely good](#part-4--what-is-genuinely-good)
6. [Part 5 — Priority remediation plan](#part-5--priority-remediation-plan)
7. [Part 6 — Strategic recommendation](#part-6--strategic-recommendation)
8. [Appendix A — Reproduction fixtures](#appendix-a--reproduction-fixtures)
9. [Appendix B — Delta vs `assessment_hy3.md`](#appendix-b--delta-vs-assessment_hy3md)

---

## 1. Headline

The **architecture is right.** A SPARQL `CONSTRUCT` executed via `rdflib` is the correct,
idiomatic way to transform RDF → RDF, and the NIDM-side pattern analysis in
`conversion_work_summary.md` §3.2 is genuinely accurate — those patterns do match real
PyNIDM output (`dct:isPartOf` reverse links, `prov:Person`, `dctypes:title`,
qualified associations with `sio:Subject` / `nidm:NIDM_0000164` roles).

There are two independent problem layers:

1. **The output does not conform to the real Neurobagel data model.** The target
   vocabulary is invented rather than derived from Neurobagel. This is the largest
   issue and it is not mentioned in the prior review.
2. **The query has correctness bugs that silently discard all phenotypic data** —
   which is the entire purpose of Neurobagel — plus a cartesian blow-up that makes
   runtime quadratic in dataset size.

**Bottom line:** the current output is not ingestible by Neurobagel. This is a
promising prototype, not a validated converter.

---

## Part 1 — Target schema mismatch (blocking)

### 1.1 Both Neurobagel namespaces are wrong

From `bagel/mappings.py`:

```python
NB = Namespace("nb", "http://neurobagel.org/vocab/")   # trailing SLASH, not '#'
NP = Namespace("np", "https://github.com/nipoppy/pipeline-catalog/tree/main/processing/")
```

`nidm2neurobagel.py` declares:

```python
"nb": Namespace("http://neurobagel.org/vocab#"),            # wrong: '#' not '/'
"np": Namespace("http://neurobagel.org/vocab/phenotype#"),  # wrong: not a Neurobagel namespace
```

Because `nb` is wrong, **every IRI the converter emits is a non-Neurobagel term.**
Nothing will match in their graph store, regardless of the rest of the mapping.

### 1.2 Class and property names do not exist in Neurobagel

From `bagel/models.py`, the real model is:

```
Dataset      : identifier, schemaKey, hasLabel, hasSamples[Subject],
               hasAuthors, hasKeywords, hasRepositoryURL, hasAccessType, ...
Subject      : identifier, schemaKey, hasLabel, hasSession[PhenotypicSession|ImagingSession]
Session      : identifier, schemaKey, hasLabel
  PhenotypicSession : hasAge(float), hasSex(Sex), isSubjectGroup, hasDiagnosis[], hasAssessment[]
  ImagingSession    : hasFilePath, hasAcquisition[], hasCompletedPipeline[]
Acquisition  : identifier, schemaKey, hasContrastType(Image)
CompletedPipeline : identifier, schemaKey, hasPipelineName(Pipeline), hasPipelineVersion(str)
ControlledTerm    : identifier, schemaKey      # Sex, Diagnosis, Assessment, Image, Pipeline
```

Mapping table:

| Emitted by this project | Actual Neurobagel | Status |
|---|---|---|
| `nb:hasSubject` | `hasSamples` | ❌ wrong name |
| `rdfs:label` | `hasLabel` | ❌ wrong predicate |
| `nb:identifier` | `identifier` → aliased to `@id`; must match `nb:<uuid4>` | ❌ wrong + never emitted |
| *(absent)* | `schemaKey` → aliased to `@type`; **required on every node** | ❌ missing entirely |
| `Subject nb:hasSex / hasAge / hasDiagnosis` | these live on **`PhenotypicSession`** | ❌ wrong attachment level |
| `?age a nb:Age ; nb:value ?v ; nb:unit "years"` | `hasAge` is a **plain float literal** | ❌ over-modelled |
| `?sex a nb:Sex ; nb:value ?v` | `hasSex` → `Sex` **controlled term** (`identifier` + `schemaKey`) | ❌ wrong shape |
| `Acquisition nb:hasImage → nb:Image {nb:path, nb:format}` | `Acquisition hasContrastType → Image`, where `Image` is a **controlled term** (e.g. `nidm:T1Weighted`), *not* a file entity | ❌ concept confusion |
| `nb:modality`, `nb:acquisitionModality` | no equivalent | ❌ invented |
| `CompletedPipeline nb:name / nb:version` | `hasPipelineName` (nipoppy catalog term) + `hasPipelineVersion` (string) | ❌ wrong names |
| `nb:DerivativeCollection`, `nb:Measurement`, `nb:PipelineParameter`, `nb:SoftwareAgent`, `nb:tool`, `nb:score`, `nb:assesses`, `nb:unit`, `nb:code`, `nb:structure`, `nb:laterality`, `nb:measureType`, `nb:generatedBy`, `nb:hasOutput`, `nb:hasParameter`, `nb:hasMeasurement` | **none of these exist in Neurobagel** | ❌ invented |

### 1.3 Two structural incompatibilities

**(a) Neurobagel is a nested JSON-LD tree; this emits flat RDF.**
From `model_utils.py`:

```python
def dataset_to_jsonld(context, dataset):
    return {**context, **dataset.model_dump(exclude_none=True, mode="json")}

def extract_and_validate_jsonld_dataset(file_path):
    jsonld  = file_utils.load_json(file_path)
    context = jsonld.pop("@context")
    jsonld_dataset = models.Dataset.model_validate(jsonld)   # ← strict
```

`Bagel` sets `model_config = ConfigDict(extra="forbid")`, so **any** unrecognised field
is a hard validation error. The current output fails on the first field.

**(b) Age/sex/diagnosis belong to a `PhenotypicSession`, not the `Subject`.**
In Neurobagel a subject normally has *both* a phenotypic session and one or more
imaging sessions. `construct_query.sparql` treats a session as strictly
`ImagingSession` **XOR** `PhenotypicSession` via
`BIND(IF(BOUND(?modType), nb:ImagingSession, nb:PhenotypicSession) AS ?sessionType)`.
That is architecturally incompatible with the target and needs rethinking, not patching.

> **Likely root cause:** the vocabulary appears to have been reverse-engineered from
> `annotation-tool`'s `example_synthetic_pheno-bids-derivatives.jsonld` rather than
> from `bagel-cli`'s data model. The former is an *input* annotation artefact; the
> latter is the *graph* schema.

---

## Part 2 — Query bugs (empirically verified)

### 🔴 B1. Sex, age and diagnosis are **never emitted** — silent, total loss

**Severity: critical.** This removes the only data Neurobagel actually queries on.

On the imaging fixture, `SELECT *` over the same `WHERE` block shows:

```
sexValue = M          ← bound
ageValue = 23.4       ← bound
sex      = (unbound)  ← IRI never minted
age      = (unbound)  ← IRI never minted
```

So `nb:hasSex`, `nb:hasAge`, `nb:Sex`, `nb:Age`, `nb:hasDiagnosis` and `nb:Diagnosis`
are **never present in any output**, for any input.

**Root cause:** a `BIND` inside an `OPTIONAL` that references an outer-scope variable.
rdflib evaluates the `OPTIONAL` group standalone *before* the left-join, so `?subject`
(itself produced by an outer `BIND`) is unbound while the inner `BIND` is evaluated.
`REPLACE(STR(unbound))` raises, and per SPARQL semantics an erroring `BIND` leaves the
variable unbound rather than failing the solution — hence total silence.

```sparql
OPTIONAL {
  ?acqObj ndar:gender ?sexValue .
  BIND("gender" AS ?sexLabel)
  BIND(IRI(CONCAT("http://neurobagel.org/sex/",
                  REPLACE(STR(?subject), ".*[/#]([^/#]+)$", "$1"))) AS ?sex)
       #             ^^^^^^^^ unbound inside this OPTIONAL → ?sex never binds
}
```

Isolated in a 3-triple reproducer. Notably `FILTER(BOUND(?subject))` *does* pass inside
the same `OPTIONAL` (filters are applied after the join), confirming this is
BIND-evaluation-order and not general variable scoping.

**Affects all four demographic blocks**: `ndar:gender`, `PersonalDataElement` gender/sex,
`ncicb:Age`, `PersonalDataElement` age, and diagnosis.

**Fix:** hoist the IRI-minting `BIND`s out of the `OPTIONAL`s, guarded by
`BOUND(?sexValue)` etc.:

```sparql
OPTIONAL { ?acqObj ndar:gender ?sexValue . }
# ... outside the OPTIONAL, where ?subject IS in scope:
BIND(IF(BOUND(?sexValue),
        IRI(CONCAT(STR(?subject), "/sex")),
        ?unbound) AS ?sex)
```

---

### 🔴 B2. Duplicate `UNION` branches cause an 8× cartesian blow-up → quadratic runtime

**Severity: critical (scalability).** The prior review called these "pointless"; they are
actively harmful. SPARQL `UNION` has **bag semantics** — no de-duplication — so each
identical pair *doubles* the solution multiset.

Three duplicated pairs exist:

```sparql
{ ?session dct:isPartOf ?project . }     UNION { ?session dct:isPartOf ?project . }
{ ?memberActivity dct:isPartOf ?session }UNION { ?memberActivity dct:isPartOf ?session }
{ ?anyAcq dct:isPartOf ?session . }      UNION { ?anyAcq dct:isPartOf ?session . }
{ ?acquisition dct:isPartOf ?session . } UNION { ?acquisition dct:isPartOf ?session . }
```

Measured solution-row counts (2 acquisition objects per subject, so 2 rows are needed
per subject):

| subjects | input triples | SPARQL solution rows | rows needed | waste |
|---|---|---|---|---|
| 1 | 27 | **16** | 2 | 8× |
| 2 | 51 | **32** | 4 | 8× |
| 4 | 99 | **64** | 8 | 8× |
| 8 | 195 | **128** | 16 | 8× |

Measured wall-clock (turtle output, warm interpreter):

| subjects | seconds |
|---|---|
| 4 | 3.8 |
| 8 | 9.4 |
| 12 | 19.7 |
| 20 | 50.8 |

That is ≈ O(n²). Extrapolating, a 500-subject dataset would take **hours**. There are
also redundant duplicate `OPTIONAL`s (`dctypes:title` ×2, `dct:description` ×2).

**Fix:** delete one branch from each pair. One line each; ~8× speedup. If the intent was
to also support a forward direction (`?project nidm:hasSession ?session`), write that as
the second branch — but §3.2 confirms NIDM only uses the reverse form, so the
`UNION`s are simply unnecessary.

---

### 🔴 B3. Derivative measurements collapse across subjects — data corruption

**Severity: critical.** Not mentioned in the prior review. The measurement IRI is minted
from the **DataElement alone**:

```sparql
BIND(IRI(CONCAT("http://neurobagel.org/measurement/",
                REPLACE(STR(?measPred), ".*[/#]([^/#]+)$", "$1"))) AS ?measurement)
```

Two subjects sharing a DataElement therefore produce **one node with two values**, and
the subject↔value association is irrecoverably lost:

```turtle
<http://iri.nidash.org/stats1> a nb:DerivativeCollection ;
    nb:hasMeasurement <http://neurobagel.org/measurement/DE_lhCortexVol> .
<http://iri.nidash.org/stats2> a nb:DerivativeCollection ;
    nb:hasMeasurement <http://neurobagel.org/measurement/DE_lhCortexVol> .   # same node!

<http://neurobagel.org/measurement/DE_lhCortexVol> a nb:Measurement ;
    rdfs:label "lhCortexVol" ;
    nb:unit "mm^3" ;
    nb:value "111111.0", "999999.0" .    # ← which subject is which?
```

**This invalidates the §8 validation table.** `brainvol_nidm.ttl` reporting only
"290 triples / 36 Measurements" from 7,117 input triples is not evidence of success — it
is the expected symptom of every subject's measurements collapsing onto ~36 shared nodes.

**Fix:** mint per-`(collection, dataElement)` IRIs, e.g.
`CONCAT(".../measurement/", localName(?derivativeCollection), "_", localName(?measPred))`.

---

### 🟠 B4. Malformed parameter IRIs

Observed output:

```turtle
<http://neurobagel.org/parameter/http://purl.org/nidash/nidmsomeParam>
    a nb:PipelineParameter ; rdfs:label "someParam" ; nb:value "5" .
<http://neurobagel.org/parameter/http://www.w3.org/2000/01/rdf-schemalabel>
    a nb:PipelineParameter ; rdfs:label "label" ; nb:value "FreeSurfer recon-all run" .
```

`REPLACE(STR(?paramPred), "[/#:]([^/#:]+)$", "$1")` replaces only the *matched tail*
with the capture group, so the prefix survives and the delimiter is merely deleted.

**Fix:** use the anchored form already used correctly elsewhere in the file:
`REPLACE(STR(?paramPred), "^.*[/#:]", "")`.

The second line also confirms the known **`rdfs:label`-as-parameter** bug — add
`rdfs:label` (and `dctypes:title`, `nfo:filename`) to the `?paramPred NOT IN (...)`
exclusion list.

---

### 🟠 B5. The pipeline subgraph is orphaned

`nb:CompletedPipeline` is emitted but **never linked to any session, subject or dataset**.
It is unreachable from the `nb:Dataset` root even within the project's own vocabulary:

```turtle
<http://neurobagel.org/dataset/proj1> a nb:Dataset ;
    nb:hasSubject <http://neurobagel.org/subject/person1> .   # → session → acquisition
<http://neurobagel.org/pipeline/fsact1> a nb:CompletedPipeline ;   # ← floating, no inbound edge
    nb:generatedBy <http://iri.nidash.org/fsagent> .
```

Neurobagel requires `ImagingSession hasCompletedPipeline → CompletedPipeline`.
**Fix:** add that edge, deriving the session from the derivative's provenance chain.

---

### 🟠 B6. Fabricated subjects, and role-blind fallback

With no `sio:Subject` association, the session is silently promoted to a subject:

```turtle
<http://neurobagel.org/subject/sess1> a nb:Subject ;
    nb:hasSession <http://iri.nidash.org/sess1> .
```

Caused by `BIND(COALESCE(?subjectPerson, ?projPerson, ?session) AS ?subjectSource)`.

*Correction to the prior review:* the subject IRI is `neurobagel.org/subject/sess1`,
**not** the session IRI itself, so `hasSession` is not literally self-referential — the
IRIs differ. The real problem is a fabricated entity, not a cycle.

*Additional issue the prior review missed:* the `?projPerson` fallback matches **any**
project agent with no role constraint —

```sparql
OPTIONAL {
  ?project prov:qualifiedAssociation ?projAssoc .
  ?projAssoc a prov:Association ; prov:agent ?projPerson .   # ← no prov:hadRole filter
}
```

— so a **PI, data curator or software agent can be emitted as a research subject.**

**Fix:** drop the `?session` fallback entirely; constrain `?projPerson` with
`prov:hadRole sio:Subject`; emit no `nb:Subject` when no real subject exists.

Also note `nb:identifier` and the subject's `rdfs:label` are in the `CONSTRUCT` template
but `?subjectId` and `?personLabel` are **never bound anywhere in the `WHERE`** — so
§4's "Identifier from `ndar:src_subject_id`" is unimplemented.

---

### 🟠 B7. `--context` is broken three ways

29 KB of output for a 25-triple graph, because the malformed context is copied into
**every one of the 7 top-level nodes** and no compaction ever occurs:

```json
[
  { "@id": "http://neurobagel.org/image/acqobj2",
    "@type": [ "http://neurobagel.org/vocab#Image" ],
    "http://www.w3.org/2000/01/rdf-schema#label": [ { "@value": "Image acqobj2" } ],
    "@context": { "@context": { "rdf": "...", "rdfs": "...", ... } } },
  ...
]
```

Three distinct defects:

1. **Nested `@context`** — the whole `{"@context": {...}}` document is used as the value
   of `@context`. Must index `context["@context"]`.
2. **Applied per-node** — `for item in data: item["@context"] = context` duplicates it
   ×N. A single top-level context is required.
3. **No compaction** — `Graph.serialize(format="json-ld")` does not consume a context, so
   predicates stay as full IRIs. Framing/compaction never happens; the flag currently
   accomplishes nothing but bloat.

rdflib will still round-trip the file (25 triples back) because it ignores the bogus
nested context — so this failure is silent. §12 lists "avoid nested `@context`" as a
TODO while the code actively creates one.

**Fix:** use `pyld.jsonld.compact(...)` / `frame(...)`, or emit the nested Neurobagel
JSON-LD directly (see Part 6).

---

### 🔴 B8. Mandatory acquisition chain silently drops whole datasets

`?session`, `?acquisition` and `?acqObj` are all **non-`OPTIONAL`** in a single `WHERE`
block. A `Project + Session` with no `Acquisition` yields:

```
INFO: Loaded 10 triples from source
INFO: Produced 0 triples
WARNING: Output graph is empty - check that the input matches the expected NIDM structure.
```

Consequences:

- Phenotype-only datasets — the **primary** Neurobagel use case — convert to nothing.
- `nb:PhenotypicSession` is **unreachable dead code**: it is only bound when `?modType`
  is unbound, but reaching that `BIND` already requires an `?acqObj` chain.
- §8's `derivatives_nidm.ttl → 0 triples` row is explained by this, not by
  "minimal provenance-only fixture".

**Fix:** split into several independent `CONSTRUCT` queries (dataset/subject, phenotypic
session, imaging session, derivatives) and merge the resulting graphs. This also
substantially mitigates B2, since each query joins far less.

---

### Minor

- **`len()` on `rdflib.Dataset`** counts quads. Correct for a single default graph, but
  fragile if a multi-graph input (e.g. TriG/quads JSON-LD) is ever passed.
- **Phase 5 assessments** are needlessly coupled to the imaging chain via
  `FILTER(?assessment = ?acqObj)`, so a session's assessments can only surface when they
  happen to sit on the same acquisition object being iterated.
- **~14 unused namespace bindings** (`reproschema`, `ilx`, `crypto`, `dcat`, `dicom`,
  `obo`, `pato`, `schema`, `vc`, `xml`, `scr`, `nlx`, `birnlex`, `uberon`) — harmless but
  noisy in both `NAMESPACES` and the SPARQL preamble.
- **`DCTERMS` is imported** in `nidm2neurobagel.py` and never used.
- **`load_construct_query()`** documents an "embedded fallback" that does not exist; it
  raises instead. Either embed the query or fix the docstring.
- **`--format rdfxml`** is remapped to `xml`; fine, but `n3` is offered and untested.

---

## Part 3 — Documentation

- 🔴 **The README is broken.** Every documented command invokes
  `pynidm_to_neurobagel.py`, which **no longer exists** — `git status` shows it was
  renamed to `nidm2neurobagel.py`. All three examples fail with
  "can't open file". `conversion_work_summary.md` §7, §9 and §11 carry the same stale name.
- 🟠 The README's **"Export as Turtle"** example actually passes
  `--format json-ld --context …`. It is JSON-LD, not Turtle.
- 🟠 **`conversion_work_summary.md` header — "Status: Implementation complete and
  validated" — is not supportable.** The §8 table measures only *that triples were
  produced*, never *that output conforms to Neurobagel*. Given Part 1 and B1/B3, it
  should read something like: *"Prototype — output not yet conformant to the Neurobagel
  data model; phenotypic mapping non-functional."*
- 🟠 **§5.5's duplicate-prefix claim is inaccurate.** No `dcterms:`, `dcmitype:` or
  `ncit:` prefix is declared anywhere in `construct_query.sparql` — they were simply
  never added, not "consolidated" to work around an rdflib bug. §10's note repeats this.
- 🟡 §8's sample output shows `nb:hasSubject` / `rdfs:label` etc.; once Part 1 is
  addressed these snippets all need regenerating.
- 🟡 §3.3's diagram places `hasDiagnosis`/`hasSex`/`hasAge` on `Subject`. Per
  `bagel/models.py` they belong on `PhenotypicSession`. The diagram is the origin of
  the modelling error and should be corrected first.

---

## Part 4 — What is genuinely good

Worth preserving through any rewrite:

- **The CONSTRUCT-via-rdflib architecture** is the right choice for RDF→RDF.
- **§3.2's empirical NIDM pattern table is accurate and valuable** — it captures
  non-obvious realities (`prov:Person` not `nidm:Person`; reverse `dct:isPartOf`;
  `dctypes:title`; `nidm:NIDM_0000164` as the software role) that would each cost hours
  to rediscover.
- **Imaging-vs-phenotypic session detection by modality filter** is the right heuristic,
  even though B8 makes it unreachable today.
- **Comprehensive namespace binding on the output graph** yields clean, readable Turtle.
- **The derivative provenance traversal** (collection → activity → qualified association
  → software agent, plus the `prov:wasAssociatedWith` fallback) is well-shaped and
  correctly handles the FS/FSL/ANTS `DataElement` indirection.
- **The empty-output warning** is the only diagnostic that surfaces B8 in production —
  genuinely useful, and it works.
- **Clean CLI ergonomics**: external `.sparql` file, `--query` override, stdout default,
  `-v`, modern `rdflib.Dataset` over deprecated `ConjunctiveGraph`.

---

## Part 5 — Priority remediation plan

Ordered by (impact ÷ effort). Items 2–4 and 7 are small, independent, and can land
immediately without waiting on the schema re-targeting.

| # | Action | Fixes | Effort | Blocking? |
|---|---|---|---|---|
| 1 | **Re-target the vocabulary to real Neurobagel.** Take `nb: http://neurobagel.org/vocab/`; rename to `hasSamples`/`hasLabel`/`hasContrastType`/`hasPipelineName`/`hasPipelineVersion`; emit `schemaKey` + `nb:<uuid4>` `identifier` on every node; drop invented terms. Verify field-by-field against `bagel/models.py`. | Part 1 | High | ✅ |
| 2 | **Hoist IRI-minting `BIND`s out of `OPTIONAL`s** so sex/age/diagnosis are actually emitted. | B1 | Low | ✅ |
| 3 | **Delete the three duplicate `UNION` pairs** and the duplicate `OPTIONAL`s. ~8× speedup, no behaviour change. | B2 | Trivial | ✅ |
| 4 | **Mint measurement IRIs per `(collection, dataElement)`.** | B3 | Low | ✅ |
| 5 | **Split into per-entity `CONSTRUCT` queries** (dataset+subject / phenotypic session / imaging session / derivatives) and merge graphs, so `session`/`acquisition`/`acqObj` stop being mandatory. Makes `PhenotypicSession` reachable and further cuts join cost. | B8, B2 | Medium | ✅ |
| 6 | **Move age/sex/diagnosis/assessment onto `PhenotypicSession`**; allow a subject to hold both a phenotypic and imaging session. | Part 1.3(b) | Medium | ✅ |
| 7 | **Gate the Image branch on `nidm:hadAcquisitionModality`** so demographics objects stop becoming Images; **require `prov:hadRole sio:Subject`** and remove the `?session` subject fallback; bind `nb:identifier` from `ndar:src_subject_id` and the person's `rdfs:label`. | B6 | Low | ✅ |
| 8 | **Fix the `REPLACE` regex** to `"^.*[/#:]"`; exclude `rdfs:label` from parameter extraction; **link `CompletedPipeline` to its `ImagingSession`.** | B4, B5 | Trivial | — |
| 9 | **Replace `--context`** with real compaction (`pyld`) — or drop the flag in favour of direct nested-JSON-LD emission (Part 6). | B7 | Medium | — |
| 10 | **Fix README + summary filenames** (`nidm2neurobagel.py`), correct the Turtle example, downgrade the "validated" status claim, fix §3.3's diagram and §5.5's prefix claim. | Part 3 | Low | — |
| 11 | **Add regression tests** asserting *triple content*, not triple counts. Include the fixtures in Appendix A — especially phenotype-only (must not be empty) and two-subject derivatives (values must not merge). | — | Medium | — |
| 12 | **Housekeeping:** drop unused namespaces and the `DCTERMS` import; fix `load_construct_query`'s docstring; add a `pyproject.toml` console-script entry point. | Minor | Low | — |

---

## Part 6 — Strategic recommendation

**Before writing more SPARQL, create a golden fixture.**

Hand-craft one target JSON-LD for `tests/experiment/test_nidm.ttl` and prove it validates:

```python
from bagel.utilities.model_utils import extract_and_validate_jsonld_dataset
context, dataset = extract_and_validate_jsonld_dataset(Path("expected_test_nidm.jsonld"))
```

Right now there is **no ground truth**, which is precisely how a non-conformant
vocabulary reached a "complete and validated" status label. A validating golden file
converts every question in Part 1 from a judgement call into a test.

**Then reconsider the output stage.** Neurobagel's pipeline is JSON-LD-first: a nested
pydantic tree with `@id`/`@type` aliasing and `extra="forbid"`. Producing flat RDF and
then framing it back into that exact tree is fighting the target format, and JSON-LD
framing is notoriously hard to pin down deterministically.

A pragmatic hybrid that keeps the good parts of the current design:

1. Keep SPARQL for **extraction** — but as `SELECT`, not `CONSTRUCT`, one query per
   entity type (subjects, phenotypic sessions, imaging sessions, acquisitions,
   pipelines). This preserves the valuable §3.2 pattern knowledge and stays declarative.
2. Assemble the **nested `models.Dataset`** in Python from those result sets.
3. Serialise with `dataset_to_jsonld(generate_context(...), dataset)` — reusing
   Neurobagel's own code, so conformance is guaranteed by construction rather than
   asserted.

This also disposes of B7 entirely (no framing needed), makes B3 impossible (identity is
explicit in Python, not encoded in a regex), and sidesteps B1 (no `BIND` scoping traps).

**Suggested sequencing:** items 2, 3, 4, 8 now (a day's work, immediate and verifiable
wins on the current codebase) → golden fixture → then decide between patching item 1 in
place or adopting the hybrid above.

---

## Appendix A — Reproduction fixtures

Each of these should become a regression test.

| Fixture | Contents | Observed | Expected | Bug |
|---|---|---|---|---|
| `imaging.ttl` | Project + Session + imaging acq + demographics acq + `sio:Subject` assoc (32 triples) | 25 triples, **16 solution rows**, no `hasSex`/`hasAge`, demographics object typed `nb:Image` | sex + age emitted; 2 solution rows; demographics not an Image | B1, B2 |
| `pheno_only.ttl` | Project + Session, no Acquisition (10 triples) | **0 triples** + empty warning | Dataset + Subject + `PhenotypicSession` | B8 |
| `no_person.ttl` | Project + Session + Acquisition, **no** `sio:Subject` assoc | `<…/subject/sess1> a nb:Subject` fabricated | no `nb:Subject` emitted | B6 |
| `deriv.ttl` | FreeSurfer `FSStatsCollection` + activity + software agent + 2 DataElements | pipeline orphaned; `rdfs:label` became a parameter; parameter IRIs contain embedded URLs | pipeline linked to session; clean IRIs | B4, B5 |
| `two_subj.ttl` | 2 subjects, both with `fs:DE_lhCortexVol` | single `nb:Measurement` node with `nb:value "111111.0", "999999.0"` | two distinct measurement nodes | B3 |
| `scale_N.ttl` | N subjects × 2 acquisitions | 16 solution rows per subject; 20 subjects = 50.8 s | 2 rows per subject; sub-second | B2 |
| `out.jsonld` | any output + `--context` | 29 KB for 25 triples; context nested and duplicated ×7; predicates uncompacted | one top-level `@context`; compact terms | B7 |

---

## Appendix B — Delta vs `assessment_hy3.md`

The prior review is broadly sound on the RDF mechanics. Differences:

**Confirmed as written**

- Mandatory acquisition chain drops datasets; `PhenotypicSession` unreachable (its #1 = B8).
- `--context` nesting and missing compaction (its #4 = B7).
- `?subjectId` / `?personLabel` used in `CONSTRUCT` but never bound (part of B6).
- `rdfs:label` becoming a `nb:PipelineParameter` (its Minor = part of B4).
- §5.5's duplicate-prefix claim is not exercised; `DCTERMS` unused.
- README's "Export as Turtle" example is JSON-LD.
- `len()` on `Dataset` counts quads; Phase 5 needlessly coupled via `FILTER(?assessment = ?acqObj)`; unused namespaces.

**Understated or mis-diagnosed**

| Prior review | Correction |
|---|---|
| #3: "demographics wrongly become Images" | True, but it missed the worse half — **sex/age/diagnosis are never emitted at all** (B1). Root cause is `BIND`-in-`OPTIONAL` scoping, not the Image branch. |
| #5: duplicate `UNION`s are "pointless" | They cause an **8× cartesian blow-up and quadratic runtime** (B2) — a scalability bug, not a style nit. |
| #2: "`hasSession` points at itself" | The subject IRI is `neurobagel.org/subject/sess1`; the session is `iri.nidash.org/sess1`. Different IRIs, so no self-loop. The bug is a *fabricated* subject (B6). |
| Validation table note on `derivatives_nidm.ttl → 0` | Correct, but §8's other rows are also unreliable: `brainvol → 290 triples / 36 Measurements` reflects **measurement collapse** (B3), not success. |

**Not identified at all**

1. **The entire Part 1 schema mismatch** — wrong `nb` namespace (`#` vs `/`), wrong `np`
   namespace, `hasSamples`/`hasLabel` naming, missing `schemaKey`/`identifier`,
   age/sex/diagnosis on the wrong entity, `nb:Image` concept confusion, ~16 invented
   terms, flat-RDF vs nested-tree, `extra="forbid"` validation. **This is the blocking
   issue.**
2. **B3 — measurement IRI collision across subjects** (silent data corruption).
3. **B4 — malformed parameter IRIs** from the wrong `REPLACE` anchor.
4. **B5 — the pipeline subgraph is orphaned** from the dataset root.
5. **Performance** — no timing or row-count analysis; the quadratic behaviour is
   unremarked.
6. **README invokes a filename that no longer exists** (a rename, not merely a wrong
   example) — every documented command fails.
7. **Role-blind `?projPerson` fallback** can promote a PI to a research subject.
8. **`load_construct_query`'s docstring** promises an embedded fallback that isn't there.
