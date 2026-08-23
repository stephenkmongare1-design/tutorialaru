from flask import Blueprint, send_from_directory, current_app, abort, session

files_bp = Blueprint("files", __name__, url_prefix="/files")

_ALLOWED_SUBFOLDERS = {"assignments", "submissions", "recordings", "library", "avatars"}


@files_bp.route("/<subfolder>/<path:filename>")
def get_file(subfolder, filename):
    if not session.get("user_id"):
        abort(401)
    if subfolder not in _ALLOWED_SUBFOLDERS:
        abort(404)
    directory = f"{current_app.config['UPLOAD_FOLDER']}/{subfolder}"
    return send_from_directory(directory, filename)
