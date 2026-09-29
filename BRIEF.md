# Senior Data Scientist (SEO): technical test

Transformation Unit, Resilience and Recovery Directorate (RED), Ministry of Housing, Communities and Local Government (MHCLG)

## Summary

Your task is to create an information extraction (IE) pipeline to pull out structured information relating to a set of entities, and the relationships between them. Please spend no more than 4 hours to create a pipeline that reads a set of incident emails, writes to a small database that can be queried to understand the current situation of an entity and how it has changed over time.

We will also run your pipeline on a **private dataset** that you will not see. For this reason:

1. At least one part of your pipeline must be extensible.
2. Your README must say which parts of your pipeline you expect to work on the private dataset, and why.

You send us your code, a README, a design note of about 1,000 words, and the output of your pipeline. The design note must describe the options that you considered for each stage and sketch out how you would evaluate a system like this.

## 1. Context

The RED Transformation Unit is building a system that turns incident reports into structured data that people can query. The reports are emails from local resilience forums (LRFs), councils, emergency services, utilities and central government.

The same entities may appear in many emails, with different names. Facts about them change: a road closes and then opens again, and an early report can be wrong. The system must connect these facts to the correct entity and keep a record of what was reported, when, and by which email.

## 2. Your task

### 2.1 What the pipeline must do

Your pipeline must:

1. Read the `.eml` files in a folder.
2. Find mentions of the four entity types in section 2.2.
3. **Resolve** each mention to one entity. If the entity is in a reference list, use the reference ID. If it is not in a reference list, create a new entity.
4. **Link** the resolved entities with the four relation types in section 2.3.
5. Record each reported property value as a dated **observation**, with the email that reported it.
6. Write your output to the folder given by `--out`.

The pipeline does entity resolution first, and then linking. Linking does not replace entity resolution.

### 2.2 Entities

There are four entity types only.

| Entity type | Reference list |
|---|---|
| Local resilience forum (`lrf`) | `lrfs.csv` |
| Incident (`incident`) | `incidents.csv` |
| Organisation (`organisation`) | `organisations.csv` |
| Site (`site`) | `sites.csv` |

A site is a named place that an incident can affect or that an organisation can operate. For example: a town, a road, a bridge, a school, a rest centre or a water treatment works.

### 2.3 Relations

| Relation | From | To | Meaning |
|---|---|---|---|
| `AFFECTS` | incident | site | The incident has an effect on the site, for example flooding, closure or loss of supply. |
| `COORDINATED_BY` | incident | lrf | The LRF coordinates the multi-agency response to the incident. |
| `RESPONDS_TO` | organisation | incident | The organisation takes part in the response to the incident. |
| `OPERATES` | organisation | site | The organisation runs or manages the site. |

These are just some examples of relationship between entities that could be defined, feel free to create your own and ignore these entirely. We are also interested in how you might model the system.

## 3. The data

| Folder or file | Content |
|---|---|
| `data/emails/` | About 270 `.eml` files. One fictional scenario over 6 days in January 2026. |
| `data/reference/` | Four reference lists (CSV). |
| `data/README.md` | The columns in each reference list. |

All the data is synthetic. The scenario, the incidents and the people are fictional. The data uses real place names and real organisation names for realism only. Nothing in the data describes real events or the performance of a real organisation.

## 4. The private dataset

We will run your pipeline on a private dataset. You will not see it. This dataset:

1. Uses the same email format (`.eml`) and the same reference list columns.
2. Comes from a different scenario: a different region, different incidents, different organisations, sites and senders, and different rows in the reference lists.
3. Has a similar number of emails.

Ensure that we can run your pipeline on the private dataset (e.g. a different folder of emails) with the same command that we use for the provided data.

## 5. Rules

### 5.1 Models and APIs

1. Your pipeline **must not** call a hosted LLM or an external API when it runs.
2. You can use local models, including small local LLMs, if they run on a CPU in reasonable time.
3. Your setup step can download packages and model weights. Your run step must work without network access.

### 5.2 Run time

We will run each submission on a small machine. The default limit is **10 minutes** for a full run on the provided data. If your pipeline needs more time, say so in your README and give the time that you measured. We will not run code that takes hours.

### 5.3 AI coding assistants

You can use AI coding assistants to write your code but in your README, tell us briefly how you used AI assistants.
The rules in 5.1 apply to your pipeline, not to your coding assistant.

### 5.4 Time

Do not spend more than 4 hours. In your README, tell us how you used your time and what you did not finish.

If part of this brief is not clear, make a reasonable assumption. Write the assumption in your README.

## 6. What to send us and deadline

Send one zip file that contains at least these items to `cameron.currie@communities.gov.uk` or add `cameron-currie` to your GitHub repo.
The deadline is 4th October by 23:59.

| Item | Content |
|---|---|
| Code | Your pipeline. It must run with: `python -m pipeline --emails <folder> --reference <folder> --out <folder>` |
| `README.md` | Replace the template in this repository. Complete all sections, including the private dataset table (section 4) and how to extend your pipeline. |
| `DESIGN_NOTE.md` | About 1,000 words. It must include how you would evaluate a system like this. See section 6.1. |


### 6.1 Design note

Write about 1,000 words. Your design note should cover:

1. **Approach and alternatives.** For each stage of your pipeline, the approach that you used and the options and alternatives that you considered or that could be used. Include what you would do if you had a frontier (state-of-the-art) LLM endpoint.
2. **Evaluation.** How you would evaluate a system like this, for each stage and from start to end. We give you no labels. Tell us how you would get them or how you would work without them, and how you would monitor quality on new data.
3. **Trade-offs and next steps.** The main limitations of your pipeline and what you would do next with more time.
