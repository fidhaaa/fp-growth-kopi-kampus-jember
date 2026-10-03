# FP-Growth Website — Deployment Preparation

This copy is prepared for a public portfolio deployment.

## Local run

1. Create/activate a Python virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Run:
   `python run.py`
4. Open the local URL shown by Flask.

If `DATABASE_URL` is not set, the app uses SQLite at `instance/fp_growth_demo.db`.

## Production

Set these environment variables:

- `SECRET_KEY`: a long random secret
- `DATABASE_URL`: a PostgreSQL connection URL for persistent production data

The Render start command is:

`gunicorn run:app`

## Files intentionally excluded from the public repository

- original/local databases
- uploaded transaction files
- local cache files
- generated user visualization images
- scratch files and archived code

Do not commit real transaction/customer data to a public repository.
