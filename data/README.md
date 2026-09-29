# Data

All data in this folder is synthetic. The scenario, the incidents and the people are fictional. Real place names and real organisation names are used for realism only. Nothing here describes real events or the performance of a real organisation.

## `emails/`

About 270 emails in `.eml` format.

## `reference/`

Four CSV files (UTF-8, header row). In the `aliases` column, other names are separated by `|`.

| File | Columns |
|---|---|
| `lrfs.csv` | `lrf_id`, `name`, `aliases` |
| `incidents.csv` | `incident_id`, `name`, `aliases`, `incident_type`, `start_date`, `status` |
| `organisations.csv` | `org_id`, `name`, `aliases`, `org_type`, `notes` |
| `sites.csv` | `site_id`, `name`, `aliases`, `site_type`, `locality` |
