import os
from functools import wraps
from flask import session, redirect, url_for, flash, current_app, abort
from models import User


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return User.query.get(uid)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login"))
            if session.get("role") != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def allowed_file(filename, allowed_ext):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_ext


def save_upload(file_storage, subfolder):
    from werkzeug.utils import secure_filename
    import uuid
    filename = secure_filename(file_storage.filename)
    unique = f"{uuid.uuid4().hex[:10]}_{filename}"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, unique)
    file_storage.save(path)
    return unique  # store just the filename; folder is implied by context
