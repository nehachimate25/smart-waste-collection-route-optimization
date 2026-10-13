"""
services/image_service.py

Handles bin image uploads safely:
    - validates file extension (only real image types)
    - validates file size
    - generates a safe, collision-proof filename (never trusts the
      client-submitted filename directly)
    - saves the actual file to uploads/bins/ (outside static/, per
      the project's own requirement to keep uploaded files separate
      from bundled static assets)
    - returns only the filename, which is what gets stored in the
      bins.image_filename column - never a huge base64 blob in SQLite.
"""

import os
import uuid
from werkzeug.utils import secure_filename
from config import Config


class ImageServiceError(Exception):
    pass


def _allowed_extension(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in Config.ALLOWED_IMAGE_EXTENSIONS


def save_bin_image(file_storage):
    """
    Save an uploaded image (a Werkzeug FileStorage object from
    request.files) and return the generated filename to store in the
    database. Returns None if no file was actually provided (image is
    optional - a bin can be created without one).
    """
    if file_storage is None or file_storage.filename == "":
        return None

    original_name = secure_filename(file_storage.filename)
    if not _allowed_extension(original_name):
        raise ImageServiceError(
            f"Invalid image type. Allowed: {', '.join(sorted(Config.ALLOWED_IMAGE_EXTENSIONS))}"
        )

    # Check size without trusting Content-Length: seek to end, measure, reset.
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > Config.MAX_IMAGE_SIZE_BYTES:
        raise ImageServiceError(
            f"Image is too large ({size // 1024}KB). Maximum is {Config.MAX_IMAGE_SIZE_BYTES // (1024*1024)}MB."
        )
    if size == 0:
        raise ImageServiceError("Uploaded image file is empty.")

    ext = original_name.rsplit(".", 1)[1].lower()
    # A random filename - never derived from user input beyond the extension -
    # so there is no path-traversal or filename-collision risk.
    safe_filename = f"{uuid.uuid4().hex}.{ext}"

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    file_storage.save(os.path.join(Config.UPLOAD_FOLDER, safe_filename))

    return safe_filename


def delete_bin_image(filename):
    """Best-effort delete; never raises if the file is already gone."""
    if not filename:
        return
    path = os.path.join(Config.UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)
