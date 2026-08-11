# PyNIDM → Neurobagel Conversion — Project Review

> Review of the conversion tool (SPARQL CONSTRUCT + rdflib wrapper) against
> `conversion_work_summary.md`. Findings were verified empirically by running
> the converter with synthetic NIDM graphs (rdflib 7.6.0).

## Verdict

The **overall approach is sound** — using a SPARQL `CONSTRUCT` query executed
via `rdflib` is the right, idiomatic way to transform RDF→RDF, and the
namespace set, imaging-session detection, and provenance/pipeline handling are
reasonable scaffolds. **But the implementation has several correctness bugs
that mean the output does *not* match what the summary claims is "validated."**
The summary also overstates a few things.

---

## Critical / correctness bugs (with evidence)

**1. Rigid single-join WHERE drops whole datasets.** `?session`,
`?acquisition`, and `?acqObj` are *mandatory* (non-`OPTIONAL`) in the single
WHERE block. So if a Project has Sessions but no Acquisition, you get **zero
solutions → the Dataset and Session are dropped entirely.**

- *Evidence:* a `Project + Session` (no Acquisition) graph produced `0 triples`.
- *Contradiction:* §4/§6 claim `PhenotypicSession` support, but the query can
  never emit one, since acquisitions are required.

**2. `nb:Subject` silently becomes a Session.** `BIND(COALESCE(?subjectPerson,
?projPerson, ?session) AS ?subject)` falls back to the *session* IRI. Output
shows `<.../subject/sess1> a nb:Subject ; nb:hasSession niiri:sess1` — i.e. the
subject is the session, and `hasSession` points at itself. Also `nb:identifier`
and the subject's `rdfs:label` are **never emitted** — those variables
(`?subjectId`, `?personLabel`) are used in the CONSTRUCT but **never bound
anywhere in the WHERE**. So per §3.2 "Identifier from `ndar:src_subject_id`" is
not implemented.

**3. Every `AcquisitionObject` unconditionally becomes an `nb:Image`.** Phase 4
always emits `?acquisition a nb:Acquisition ; nb:hasImage ?image` for *all*
`?acqObj`, with no imaging-vs-assessment distinction. Demographic/assessment
objects (those carrying `ndar:gender`, `ncicb:Age`, or `PersonalDataElement`
predicates) will be wrongly turned into Images. The mapping table in §4 says
assessment objects → `Assessment/Diagnosis/Sex/Age`, but the query doesn't
separate them.

**4. The `--context` feature is doubly broken.** Feeding a real output +
`--context` produced malformed JSON-LD:

```json
{ "@id": "...", "@context": { "@context": { "rdf": ... } } }
```

- It nests the entire `{"@context": {...}}` object *as the value* of `@context`
  (should be `context["@context"]`).
- It never replaces rdflib's full-IRI serialization, so predicates remain
  `http://neurobagel.org/vocab#hasSession` instead of the compact `hasSession`
  the context defines. Framing effectively fails. §12 even lists "avoid nested
  `@context`" as a TODO, but the code actively *creates* the nested context.

---

## Medium issues

**5. Copy-paste duplicate branches (missing intended logic).** Several identical
`UNION`/`OPTIONAL` pairs are pointless and suggest intended-but-absent
alternatives:

- `{ ?session dct:isPartOf ?project } UNION { ?session dct:isPartOf ?project }`
  — both identical. §3.2 brags about "reverse direction" handling, but it was
  never implemented (the two branches are the same).
- Same duplication for `memberActivity`/`session`, `anyAcq`/`session`,
  `acquisition`/`session`, and redundant `OPTIONAL`s for `dctypes:title` (×2)
  and `dct:description` (×2).

**6. §5.5 "duplicate-prefix bug" is not actually exercised.** No
`dcterms:`/`dcmitype:`/`ncit:` prefix is declared in the SPARQL file — they were
simply *omitted*, not "consolidated." `DCTERMS` is imported but never used. The
summary overstates/misdescribes this.

**7. README is wrong.** The "Export as Turtle" example actually runs
`--format json-ld --context …` and omits `-o`. It's JSON-LD, not Turtle.

---

## Minor

- **Phase 6 param extraction** doesn't exclude `rdfs:label`, so label literals
  become `nb:PipelineParameter`s.
- **Unused namespace bindings** bloat `NAMESPACES` (`reproschema`, `ilx`,
  `crypto`, `dcat`, `dicom`, `obo`, `pato`, `schema`, `vc`, `xml`, `scr`, `nlx`,
  `birnlex`, `uberon`) — harmless but noisy.
- **`len()` on a `Dataset`** counts quads; works here (single default graph) but
  is fragile for multi-graph inputs.
- **Phase 5 assessment** is needlessly tied to the imaging chain via
  `FILTER(?assessment = ?acqObj)`.
- **Validation table's `0 triples`** for `derivatives_nidm.ttl` is attributed to
  "no Session/Acquisition chain" — consistent with bug #1, but worth noting it's
  *because* acquisitions are mandatory, not just "minimal provenance."

---

## What looks right / good

- The CONSTRUCT→rdflib architecture is appropriate.
- Comprehensive namespace bindings; clean prefix serialization via `bind()`.
- `ImagingSession` vs `PhenotypicSession` detection by modality filter is
  sensible.
- Pipeline/derivative provenance structure (activity → software agent →
  collection → measurements) is reasonable.
- The empty-output **warning** is genuinely useful — it's the only thing that
  would have surfaced bug #1 in production.

---

## Suggested fixes (priority order)

1. **Split into multiple CONSTRUCT templates** (or make `session`/`acquisition`/
   `acqObj` `OPTIONAL`) so datasets/sessions survive without acquisitions. This
   also lets `PhenotypicSession` actually be emitted.
2. **Separate imaging vs assessment objects** (e.g. require
   `nidm:hadAcquisitionModality` for the Image branch) so demographics stop
   becoming Images.
3. **Fix subject binding**: only emit `nb:Subject` when a real `prov:Person`
   with `sio:Subject` role exists; bind `nb:identifier` (`ndar:src_subject_id`)
   and `rdfs:label`.
4. **Fix `--context`**: use real JSON-LD framing (rdflib `frame()` or `pyld`)
   and index `context["@context"]`; ensure a single top-level `@context` and
   compact IRIs.
5. **Remove the duplicate `UNION`/`OPTIONAL` branches**; add the actual
   reverse-direction patterns if the data needs them.
6. **Align the summary and README** with reality; drop the unused
   import/namespaces.
