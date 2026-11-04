
from getpass import getpass

from app import create_app
from app.extensions import db
from app.models import (
    User,
    AnalysisHistory,
    SimulationHistory
)

app = create_app()

with app.app_context():

    # Pastikan script hanya berjalan pada database lokal
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    normalized_uri = db_uri.replace('\\', '/').lower()

    print("Database aktif:", db_uri)

    if '/data/' in normalized_uri or 'instance/fp_growth_demo.db' not in normalized_uri:
        raise RuntimeError(
            "Dibatalkan! Database aktif bukan database lokal yang diharapkan."
        )

    old_admin = User.query.filter_by(username='admin').first()
    new_admin = User.query.filter_by(username='fida').first()

    if not old_admin:
        raise RuntimeError("Akun admin lama tidak ditemukan.")

    if not new_admin:
        raise RuntimeError("Akun fida tidak ditemukan.")

    if old_admin.id == new_admin.id:
        raise RuntimeError("Kedua akun ternyata sama.")

    print("\nAkun lama:")
    print("Username:", old_admin.username)
    print("Role:", old_admin.role)
    print("ID:", old_admin.id)

    print("\nAkun yang akan dijadikan admin:")
    print("Username:", new_admin.username)
    print("Role saat ini:", new_admin.role)
    print("ID:", new_admin.id)

    password = getpass("\nMasukkan password baru untuk fida: ")
    password_confirm = getpass("Ulangi password baru: ")

    if len(password) < 4:
        raise ValueError("Gunakan password minimal 4 karakter.")

    if password != password_confirm:
        raise ValueError("Konfirmasi password tidak cocok.")

    # Hitung riwayat sebelum dipindahkan
    analysis_count = AnalysisHistory.query.filter_by(
        user_id=old_admin.id
    ).count()

    simulation_count = SimulationHistory.query.filter_by(
        user_id=old_admin.id
    ).count()

    print("\nRiwayat yang akan dialihkan:")
    print("Analisis:", analysis_count)
    print("Simulasi:", simulation_count)

    confirmation = input(
        "\nKetik PINDAHKAN untuk melanjutkan: "
    )

    if confirmation != "PINDAHKAN":
        print("Dibatalkan. Tidak ada perubahan.")
        raise SystemExit

    try:
        # Pindahkan kepemilikan riwayat
        AnalysisHistory.query.filter_by(
            user_id=old_admin.id
        ).update(
            {AnalysisHistory.user_id: new_admin.id},
            synchronize_session=False
        )

        SimulationHistory.query.filter_by(
            user_id=old_admin.id
        ).update(
            {SimulationHistory.user_id: new_admin.id},
            synchronize_session=False
        )

        # Jadikan fida sebagai admin
        new_admin.role = 'admin'
        new_admin.set_password(password)

        # Hapus akun admin lama
        db.session.delete(old_admin)

        db.session.commit()

        print("\nBerhasil!")
        print("Username admin baru: fida")
        print("Role: admin")
        print("Riwayat analisis dialihkan:", analysis_count)
        print("Riwayat simulasi dialihkan:", simulation_count)
        print("Akun admin lama telah dihapus.")

    except Exception:
        db.session.rollback()
        raise
