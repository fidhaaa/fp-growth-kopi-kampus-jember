import os
import io
import hmac
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath
from app.extensions import db

from flask import (
    Blueprint, request, current_app, abort,
    render_template_string
)

recovery = Blueprint("recovery", __name__)

STAGING_DIR = Path("/data/recovery_staging")
MAX_PACKAGE_SIZE = 15 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024

EXPECTED_DB = "database/fp_growth_demo.db"
REQUIRED_TABLES = {
    "user",
    "analysis_history",
    "simulation_history",
    "user_activity_log",
}

def check_token():
    expected = os.getenv("RECOVERY_TOKEN")
    supplied = request.form.get("token", "")

    if not expected or not hmac.compare_digest(
        supplied, expected
    ):
        abort(403)

def validate_package(package_bytes):
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]

        if len(names) != len(set(names)):
            raise ValueError("ZIP memiliki nama file duplikat.")

        if EXPECTED_DB not in names:
            raise ValueError("Database tidak ditemukan.")

        total_size = sum(info.file_size for info in infos)

        if total_size > MAX_UNCOMPRESSED_SIZE:
            raise ValueError("Ukuran hasil ekstraksi ZIP terlalu besar.")

        for info in infos:
            if info.is_dir():
                continue

            path = PurePosixPath(info.filename)

            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 2
                or not (
                    info.filename == EXPECTED_DB
                    or info.filename.startswith("uploads/")
                )
            ):
                raise ValueError(
                    f"Struktur file tidak diizinkan: {info.filename}"
                )

            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ZIP tidak boleh berisi symbolic link.")

        upload_files = {}

        for name in names:
            if name.endswith("/"):
                continue

            path = PurePosixPath(name)

            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 2
            ):
                raise ValueError(
                    f"Struktur file tidak diizinkan: {name}"
                )

            if name.startswith("uploads/"):
                filename = path.name

                if filename in upload_files:
                    raise ValueError(
                        f"Nama file upload duplikat: {filename}"
                    )

                upload_files[filename] = archive.read(name)

        db_bytes = archive.read(EXPECTED_DB)

    # Periksa database secara read-only dari memori.
    connection = sqlite3.connect(":memory:")

    try:
        connection.deserialize(db_bytes)

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise ValueError("Integritas database gagal.")

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            )
        }

        missing = REQUIRED_TABLES - tables

        if missing:
            raise ValueError(
                "Tabel database tidak lengkap: "
                + ", ".join(sorted(missing))
            )

        admin = connection.execute(
            "SELECT COUNT(*) FROM user "
            "WHERE username=? AND role=?",
            ("fida", "admin")
        ).fetchone()[0]

        if admin != 1:
            raise ValueError(
                "Akun admin fida tidak ditemukan."
            )

        history_files = {
            row[0]
            for row in connection.execute(
                "SELECT filename FROM analysis_history"
            )
        }

        missing_files = history_files - set(upload_files)

        if missing_files:
            raise ValueError(
                "File riwayat tidak ditemukan dalam ZIP: "
                + ", ".join(sorted(missing_files))
            )

        counts = {}

        for table in REQUIRED_TABLES:
            counts[table] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]

        return {
            "integrity": integrity,
            "counts": counts,
            "upload_count": len(upload_files),
            "admin": "fida",
        }

    finally:
        connection.close()

@recovery.route(
    "/admin/recovery/stage",
    methods=["GET", "POST"]
)
def stage_recovery():
    if not Path("/data").is_dir():
        abort(403)

    database_url = db.engine.url

    if database_url.get_backend_name() != "sqlite":
        abort(400)

    active_database = Path(database_url.database).resolve()
    expected_database = Path("/data/fp_growth_demo.db").resolve()

    if active_database != expected_database:
        abort(400)

    if request.method == "GET":
        return render_template_string("""
            <h2>Validasi Paket Pemulihan</h2>
            <p>Unggah recovery_package.zip untuk diperiksa.</p>
            <form method="POST" enctype="multipart/form-data">
                <p>Token pemulihan:</p>
                <input type="password" name="token"
                       required autocomplete="off">
                <p>Paket pemulihan:</p>
                <input type="file" name="package"
                       accept=".zip" required>
                <button type="submit">Validasi Paket</button>
            </form>
        """)

    check_token()

    uploaded = request.files.get("package")

    if (
        not uploaded
        or not uploaded.filename
        or not uploaded.filename.lower().endswith(".zip")
    ):
        abort(400)

    package_bytes = uploaded.read(MAX_PACKAGE_SIZE + 1)

    if len(package_bytes) > MAX_PACKAGE_SIZE:
        abort(413)

    try:
        result = validate_package(package_bytes)

        STAGING_DIR.mkdir(parents=True, exist_ok=True)

        staged_file = STAGING_DIR / "recovery_package.zip"
        temporary_file = STAGING_DIR / "recovery_package.tmp"

        temporary_file.write_bytes(package_bytes)
        os.replace(temporary_file, staged_file)

    except (ValueError, zipfile.BadZipFile, sqlite3.Error) as error:
        return (
            f"<h3>Validasi gagal</h3><p>{error}</p>",
            400
        )

    return render_template_string("""
        <h2>Validasi Berhasil</h2>
        <p>Database: {{ integrity }}</p>
        <p>Akun admin: {{ admin }}</p>
        <p>Jumlah file upload: {{ upload_count }}</p>
        <h3>Jumlah data</h3>
        <ul>
        {% for name, count in counts.items() %}
            <li>{{ name }}: {{ count }}</li>
        {% endfor %}
        </ul>
        <p>Paket tersimpan di lokasi staging.</p>
        <strong>Database online belum diubah.</strong>
    """, **result)
