import os
import io
import hmac
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath
from app.extensions import db
from datetime import datetime

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

def create_online_backup():
    database_path = Path(db.engine.url.database).resolve()
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])

    backup_dir = STAGING_DIR / "online_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_db = backup_dir / f"backup_{timestamp}.db"
    backup_zip = backup_dir / f"online_backup_{timestamp}.zip"

    source = sqlite3.connect(str(database_path))
    destination = sqlite3.connect(str(backup_db))

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    try:
        with zipfile.ZipFile(
            backup_zip, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(
                backup_db,
                "database/fp_growth_demo.db"
            )

            if upload_folder.exists():
                for file_path in upload_folder.iterdir():
                    if file_path.is_file():
                        archive.write(
                            file_path,
                            f"uploads/{file_path.name}"
                        )

        # Verifikasi ZIP dan database hasil backup
        with zipfile.ZipFile(backup_zip, "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("Backup ZIP rusak.")

            db_bytes = archive.read(
                "database/fp_growth_demo.db"
            )

        check_db = sqlite3.connect(":memory:")
        try:
            check_db.deserialize(db_bytes)

            integrity = check_db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            if integrity != "ok":
                raise ValueError("Backup database tidak valid.")
        finally:
            check_db.close()

    except Exception:
        if backup_zip.exists():
            backup_zip.unlink()
        raise

    finally:
        if backup_db.exists():
            backup_db.unlink()

    return backup_zip

@recovery.route("/admin/recovery/backup", methods=["POST"])
def backup_online():
    check_token()

    if not Path("/data").is_dir():
        abort(403)

    database_url = db.engine.url

    if database_url.get_backend_name() != "sqlite":
        abort(400)

    active_database = Path(database_url.database).resolve()

    if active_database != Path("/data/fp_growth_demo.db").resolve():
        abort(400)

    try:
        backup_file = create_online_backup()

        return render_template_string("""
            <h2>Backup Online Berhasil</h2>
            <p>File: {{ filename }}</p>
            <p>Lokasi: {{ location }}</p>
            <strong>Database online belum diubah.</strong>
        """,
        filename=backup_file.name,
        location=str(backup_file))

    except Exception:
        current_app.logger.exception(
            "Gagal membuat backup online."
        )
        return "Backup gagal. Periksa log aplikasi.", 500

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
            <h2>Manajemen Pemulihan Database</h2>

            <h3>1. Backup Database Online</h3>
            <form method="POST" action="/admin/recovery/backup">
                <input type="password" name="token"
                    placeholder="Token pemulihan" required>
                <button type="submit">Buat Backup Online</button>
            </form>

            <hr>

            <h3>2. Validasi Paket Pemulihan</h3>
            <form method="POST" enctype="multipart/form-data">
                <input type="password" name="token"
                    placeholder="Token pemulihan" required>
                <p>Pilih recovery_package.zip:</p>
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
