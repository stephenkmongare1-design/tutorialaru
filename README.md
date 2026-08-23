# TutorAI — Direct Streamlit Upload

## Streamlit Cloud
Set **Main file path** to exactly:

`streamlit_app.py`

Do not select `main.py`, `app.py`, or a Python function.

## Local
`streamlit run streamlit_app.py`

## Required Streamlit Secrets
```toml
ANTHROPIC_API_KEY = "your-anthropic-key"
ANTHROPIC_MODEL = "claude-sonnet-5"
ADMIN_EMAIL = "admin@tutorai.local"
ADMIN_PASSWORD = "change-this-password"
SECRET_KEY = "change-this-secret"
```
