# NDOH Registry Notebooks

This folder contains ready-to-run Jupyter notebooks for quick data exploration against the Django project.

## Prerequisites

1. Activate your virtual environment.
2. Install notebook tools:
   - `pip install jupyter ipykernel`
3. From the project root, start Jupyter:
   - `jupyter notebook`

## Available notebooks

- `workforce_registry_quickstart.ipynb`
  - Loads Django settings
  - Runs basic workforce count queries
  - Builds a small DataFrame for quick inspection

## CSV templates

See `notebooks/csv_templates/` for ready-made templates for all models, including:

- `location.csv` with all 22 PNG provinces and major districts
- `nursingprofessional.csv`, `midwife.csv`, `communityhealthworker.csv`, `healthstudent.csv`
- `application.csv`, `documenttype.csv`, `cadre.csv`, `traininginstitution.csv`

## Bulk import command

```bash
python manage.py import_workforce_files --path notebooks/csv_templates
```

## Bootstrap reference data

```bash
python manage.py bootstrap_reference_data
```

## Notes

- These notebooks run against your configured database from `.env`.
- Keep notebooks free of production secrets and personal data before sharing.
