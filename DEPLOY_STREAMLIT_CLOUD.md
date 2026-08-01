# RetailRecon AI — Streamlit Cloud Deployment

## Recommended repository structure

Upload the **contents of this folder** to the root of a GitHub repository.

Important files:

- `streamlit_app.py` — recommended Streamlit Cloud entry point
- `Home.py` — application home page
- `requirements.txt`
- `.streamlit/config.toml`
- `pages/` — all application pages

## GitHub upload

1. Create a new private GitHub repository.
2. Upload all files and folders from this package.
3. Confirm `pages/17_Merchant_ID_Master.py` exists in GitHub.
4. Do not upload `retailrecon.db`.
5. Do not upload `.streamlit/secrets.toml`.

## Streamlit deployment

When creating the app, use:

- Branch: `main`
- Main file path: `streamlit_app.py`

You may also use `Home.py`, but `streamlit_app.py` performs an extra package-integrity check before startup.

## First startup

The application creates a fresh SQLite database automatically.

Demo users remain configured in `auth.py` for testing only.

## Important production warning

SQLite on a hosted Streamlit instance is suitable for demonstration and UAT, but it is not a durable multi-user production database. App restarts or redeployments may remove local runtime data.

Before live finance use, move persistent data to a managed database and replace demo passwords with secure authentication.
