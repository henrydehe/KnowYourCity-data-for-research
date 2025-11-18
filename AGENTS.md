# Repository Guidelines

## Project Structure & Module Organization
The root directory is intentionally flat: `README.md` plus per-city archives. Files prefixed `kyc_ori_data_<City>_<Country>.zip` store the raw Know Your City settlement surveys, while `kyc_cln_data_<City>_<Country>.zip` contain the cleaned, analysis-ready extracts. `kyc_settlement_population_extract_v1.zip` holds the aggregated settlement population reference. Unzip to a working subfolder (for example, `unzip kyc_cln_data_Accra_Ghana.zip -d data/Accra`) and keep the archives untouched so they remain a canonical source of truth.

## Build, Test, and Development Commands
- `unzip kyc_cln_data_<City>_<Country>.zip -d data/<City>` — expands the cleaned dataset for the specified settlement cluster.
- `unzip kyc_ori_data_<City>_<Country>.zip -d data/<City>_raw` — pulls the original survey tables to a parallel folder for provenance checks.
- `sha256sum kyc_*zip` — produces integrity hashes that teammates can compare before sharing outputs.
Because there is no build system, treat each unzip + inspect cycle as the “run” step for this repository.

## Coding Style & Naming Conventions
When adding helper scripts or notebooks, keep them in a new `tools/` or `notebooks/` folder and name files with lowercase snake_case (e.g., `tools/clean_enumerator_notes.py`). Use UTF-8 CSVs, ISO 8601 dates, and settlement identifiers exactly as supplied in the raw extracts. Any derived columns should be prefixed with `calc_` to distinguish them from source variables before re-zipping.

## Testing Guidelines
Validation is data-focused: after transforming a city dataset, regenerate descriptive stats (row counts, settlement tallies, population sums) and compare against the cleaned archive before overwriting anything. Always spot-check two or three randomly selected settlements to ensure categorical levels remain unchanged. Keep intermediate QA notebooks and scripts out of version control unless they are reusable.

## Commit & Pull Request Guidelines
Follow the existing short imperative style (`Update README.md`, etc.). Each commit should mention the city or artifact it touches (e.g., “Refresh Accra cleaned data”). Pull requests must summarize the provenance of any new archive, document unzip/re-zip commands used, and include links to shared validation notes or dashboards. Never commit uncompressed survey folders; re-create zips locally and list them in the PR description with their new hashes.

## Data Handling & Security Notes
Survey files describe informal settlements and should be treated as sensitive. Share archives only through approved channels, do not email them, and scrub any personally identifiable information before publishing derived tables. When collaborating with external agents, provide instructions for obtaining the official archives rather than forwarding copies, and update `README.md` if access procedures change.
