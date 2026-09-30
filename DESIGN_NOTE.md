# Design note

## 1. Approach and alternatives

### Finding and resolving entities

For each entity type (LRF, incident, organisation, site), the pipeline builds a lookup table from the reference CSV: every name and every alias, lowercased. It scans each email for a match against that table first. If a mention doesn't match anything in the reference list — a site or organisation that simply isn't on the list — a small set of hand-written patterns catches the common shapes instead: road numbers, "... Council", "... Local Resilience Forum", "Storm <Name>", "... Rest Centre", and so on. If a mention still doesn't match exactly, a fuzzy-matching step (`rapidfuzz`, allowing a small amount of typo/wording difference) gives it one more chance against the reference list, and against any new entity already created earlier in the same run, before the pipeline finally creates a brand-new entity for it.

I considered using a small local language model or an NER (named-entity-recognition) model instead of these rules, but chose not to, for reasons that trace back to the brief's constraints: the reference lists already tell the pipeline most of what it needs to know, so a generic model would just be relearning that; downloading and running a model adds a point of failure exactly where the brief is strictest (no network at run time, ten minutes, CPU only, on data nobody has reviewed in advance); and rules are auditable — every decision traces back to the exact line of code that made it.

The trade-off is recall. A mention phrased in a way none of the rules anticipated is simply missed. The fallback patterns are written for UK civil-contingencies language, so a private dataset describing incidents differently would see more misses there — though the reference-list matching itself doesn't depend on this dataset at all, so that part should carry over cleanly.

### Linking entities together

Two resolved entities count as a candidate pair if their mentions are close enough together in the text (within 400 characters). A small YAML file of trigger phrases per relation type (`rules/relations.yaml`) then decides whether a relation actually holds, and which one. This file is deliberately the easiest part of the pipeline to extend — adding a new relation type is a couple of lines in a YAML file, not a code change.

I also considered a more linguistically-aware approach: parsing each sentence's grammar and reading the relation off the verb connecting the two mentions. That would likely do better on clean prose, but a lot of this dataset is semi-structured report text ("3. AGENCIES RESPONDING\nNCIC, Drinking Water Inspectorate, ...") that doesn't parse as ordinary sentences, and it brings back the same "needs a model" downside as above.

The trigger-phrase approach has a real weakness, and it showed up directly while building this: my first guess at the keyword list produced almost no matches for three of the four relation types. Reading the actual emails, I found the dataset uses phrases like "Lead:", "RESPONDING", and "run by" — not the words I'd guessed. Fixing that was, again, just a YAML edit. But it's a useful reminder that this keyword list is tuned to this dataset's writing style, and the private dataset will likely need the same kind of adjustment.

### Recording what changed and when

For each resolved entity, the pipeline looks for a small set of status keywords nearby ("closed", "reopened", "stood down", and so on) and, if it finds one, records a dated fact: this property had this value, as reported by this email. Nothing ever overwrites an earlier fact — every report stays in the record. That's what lets the pipeline answer both "what do we currently believe" and "how did this change over time," which is exactly what the brief asks for.

### If I had a frontier LLM available

Most of the hand-written matching above would become unnecessary. One well-structured prompt per email — reference lists as candidate entities, plus a schema for what to extract — could plausibly do detection, resolution, relation typing, and observation extraction all at once, and handle unusual phrasing better than these rules do. The cost is exactly what the brief rules out: a hosted model call at run time. A middle ground worth exploring with more time is a small local model used only as a second pass over whatever the rule-based system found nothing in.

## 2. Evaluation

The brief provides no labels, and asks how I'd get some, or work without them.

**Getting some labels.** The cheapest way is a small hand-annotated sample — 20 to 30 emails, picked to cover the different email styles in the corpus (plain text, HTML, dense report-style, casual reply-style), annotated independently by two people, with disagreements resolved into a single "correct answer" set. That gives a real precision/recall number for each stage — detection, resolution, relation extraction, observation extraction — measured separately, since a mistake at one stage isn't the same thing as a mistake at the next.

**Working without labels.** A few signals need no annotation and are cheap to compute on every run: how much of each reference list ever gets matched (a type clearly discussed but never matched suggests something's wrong); how often the pipeline has to invent a new entity (a sudden jump on a new dataset is an early warning); and whether one relation type fires far more than the others, worth a manual look even without ground truth. I'd also spot-check a handful of specific incidents by hand, tracing the raw emails against what the pipeline recorded — it doesn't scale, but it's the most direct test of what the brief actually cares about. On the private dataset, I'd run these checks automatically on every run and flag anything that looks different from the provided data, rather than assume no news is good news.

## 3. Trade-offs and next steps

Most of the pipeline's limitations follow directly from being rule-based: anything phrased in a way the rules didn't anticipate gets missed. The fallback patterns for new entities are the most fragile piece, since they're written for a specific style of UK incident-report language. There's also no handling of pronouns or indirect references ("it", "the road", "the council") pointing back to something mentioned earlier.

One issue was more serious, and worth describing honestly. An early version of the relation-linking logic treated any two entities within 400 characters as "close enough," without checking they were actually part of the same sentence or list item. On a dataset that lists several sites each with its own "(run by X)" note, a keyword belonging to one bullet could get attached to an entity from a different bullet nearby — one keyword alone produced over 1,500 relations this way, most wrong. A second pass caught this, plus a similar issue in how "what changed" facts were recorded, and fixed both by stopping a relation or fact from crossing a list-item boundary. That brought the real run down from 1,725 relations to 145, and cut contradictory same-email facts from 103 to 5. What's left: two facts about two *different* entities on the exact same line — an email subject reading "Cockermouth School closed and A591 reopened" — can still occasionally attach to the wrong one, since the fix works at line level, not clause level.

With more time, I'd prioritise: splitting text at the clause level, not just the line level, to close that last gap; a simple pass that resolves pronouns and vague references back to the most recently mentioned matching entity; replacing the keyword table's yes/no decision with a small trained classifier once a labelled sample exists; and a feedback loop where the pipeline's least-confident decisions get routed to a person for review, with corrections feeding straight back into the reference aliases and rule files that already drive the system.
