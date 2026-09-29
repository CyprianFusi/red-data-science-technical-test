"""Command-line entry point for the incident email IE pipeline.

Run:
    python -m pipeline --emails data/emails --reference data/reference --out output
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.emails import parse_eml_folder
from pipeline.extract import find_mentions
from pipeline.observations import extract_observations, load_observation_rules
from pipeline.reference import load_all_gazetteers
from pipeline.relations import extract_relations, load_relation_rules
from pipeline.resolve import EntityResolver
from pipeline.store import write_output

_RULES_DIR = Path(__file__).parent / "rules"


def run(emails_dir: Path, reference_dir: Path, out_dir: Path) -> dict:
    gazetteers = load_all_gazetteers(reference_dir)
    relation_rules = load_relation_rules(_RULES_DIR / "relations.yaml")
    observation_rules = load_observation_rules(_RULES_DIR / "observations.yaml")

    parsed_emails = parse_eml_folder(emails_dir)
    resolver = EntityResolver(gazetteers)
    all_relations = []
    all_observations = []

    for email in parsed_emails:
        # Keyed on path, not Message-ID: the header can be missing or (across
        # a forwarded copy) duplicated, but each .eml file's path is always
        # unique, and this key must match source_emails' primary key in
        # pipeline.store so relation/observation provenance always joins.
        source_email = str(email.path)
        mentions = find_mentions(email.text, gazetteers)
        resolved = [(mention, resolver.resolve(mention, source_email)) for mention in mentions]

        all_relations.extend(
            extract_relations(email.text, resolved, relation_rules, source_email, email.date)
        )
        all_observations.extend(
            extract_observations(email.text, resolved, observation_rules, source_email, email.date)
        )

    write_output(
        out_dir,
        emails=parsed_emails,
        entities=resolver.all_entities(),
        aliases=resolver.aliases(),
        first_seen=resolver.first_seen(),
        relations=all_relations,
        observations=all_observations,
    )

    return {
        "emails": len(parsed_emails),
        "entities": len(resolver.all_entities()),
        "relations": len(all_relations),
        "observations": len(all_observations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Incident email IE pipeline")
    parser.add_argument("--emails", required=True, type=Path, help="folder of .eml files")
    parser.add_argument("--reference", required=True, type=Path, help="folder of reference list CSV files")
    parser.add_argument("--out", required=True, type=Path, help="output folder")
    args = parser.parse_args()

    summary = run(args.emails, args.reference, args.out)
    print(
        f"Processed {summary['emails']} emails -> "
        f"{summary['entities']} entities, {summary['relations']} relations, "
        f"{summary['observations']} observations. Output: {args.out}"
    )


if __name__ == "__main__":
    main()
