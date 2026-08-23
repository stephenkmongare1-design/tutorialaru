# TutorAI — Streamlit edition

This version uses **Streamlit as the web UI**. Gunicorn and the Flask routes are
no longer the web entry point. The existing SQLAlchemy models and Anthropic AI
service are reused.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open the URL Streamlit prints.

## Streamlit Community Cloud

1. Put this `tutorai` folder in a GitHub repository.
2. In Streamlit Community Cloud, create an app.
3. Set the main file to `streamlit_app.py`.
4. Add these secrets/environment values in the Streamlit app settings:

```toml
ANTHROPIC_API_KEY = "your-key"
ANTHROPIC_MODEL = "claude-sonnet-5"
ADMIN_EMAIL = "admin@tutorai.local"
ADMIN_PASSWORD = "change-this-password"
SECRET_KEY = "change-this-secret"
```

The existing `config.py` reads environment variables, so for deployments that
provide secrets as environment variables this works directly. If your Streamlit
provider exposes secrets only through `st.secrets`, add the following at the top
of `streamlit_app.py` before importing `app`:

```python
import os
import streamlit as st

for key, value in st.secrets.items():
    if isinstance(value, (str, int, float)):
        os.environ.setdefault(key, str(value))
```

For a simple deployment, it is safer to place that snippet before:

```python
from app import app as flask_app
```

## Important persistence note

The default database is SQLite (`tutorai.db`) and uploads are stored in
`static/uploads`. Streamlit Community Cloud can reset local files when an app
restarts/redeploys. This is therefore suitable for a demo/MVP, not as the
production database/storage for real students.

For production, use PostgreSQL via `DATABASE_URL` and object storage such as
S3/Cloudinary for uploaded files.

## What is included

- Admin dashboard and user management
- Teacher dashboard
- Student dashboard
- Login/logout
- AI tutor
- AI question generation
- Teacher assignment creation from PDF/image
- Student interactive assignment answering
- Automatic online marking
- Results
- Live class scheduling/join links

The original Flask templates/blueprints are retained in the project so the
database model and AI code remain reusable.
