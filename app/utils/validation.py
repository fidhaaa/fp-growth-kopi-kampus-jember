import pandas as pd
import os
from werkzeug.utils import secure_filename

# Pengaturan
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

MENU_FILE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "produk_valid.xlsx"
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_valid_menu():
    menu_df = pd.read_excel(MENU_FILE)

    return set(
        menu_df.iloc[:, 0]
        .astype(str)
        .str.strip()
        .str.lower()
        .tolist()
    )

# def load_valid_menu():
#     menu_df = pd.read_excel(MENU_FILE)

#     # nama asli
#     original = (
#         menu_df.iloc[:, 0]
#         .astype(str)
#         .str.strip()
#     )

#     # key huruf kecil
#     lower = original.str.lower()

#     # untuk validasi
#     menu_valid = set(lower)

#     # untuk mengembalikan nama asli
#     menu_mapping = dict(zip(lower, original))

#     return menu_valid, menu_mapping

def validate_menu(products, menu_valid):
    menu_valid = set(menu_valid)

    return sorted({
        str(item).strip()
        for item in products
        if str(item).strip().lower() not in menu_valid
    })

# Fungsi validasi & pemrosesan file
def validate_and_process_file(file, save_path):
    warning= None
    error = None

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower()

    if ext == 'xlx':
        return None, None, None, "Ekstensi .xlx tidak dikenali. Apakah maksud Anda .xlsx atau .xls?"

    if ext not in ALLOWED_EXTENSIONS:
        return None, None, None, "Format file tidak didukung. Gunakan .csv, .xls, atau .xlsx."

    file.save(save_path)
    menu_valid= load_valid_menu()

    try:
        if ext == "csv":
            df = pd.read_csv(
                save_path,
                header=None,
                engine="python"
            )

            if df.empty:
                return None, None, None, "File CSV kosong."

            transaksi = []

            for idx, row in enumerate(df.values, start=1):
                items = []

                for cell in row:
                    if pd.isna(cell):
                        continue

                    items.extend([
                        item.strip()
                        for item in str(cell).split(",")
                        if item.strip()
                    ])

                if not items:
                    return None, None, None, f"Terdapat baris kosong pada baris {idx}."

                transaksi.append(items)

            semua_produk = [
                item
                for trx in transaksi
                for item in trx
            ]

            produk_tidak_valid = validate_menu(
                semua_produk,
                menu_valid
            )

            if produk_tidak_valid:
                return (
                    None,
                    None,
                    None,
                    "Produk berikut tidak terdapat pada daftar menu cafe: "
                    + ", ".join(produk_tidak_valid)
                )

            return transaksi, "csv", warning, None

        elif ext in ['xlsx', 'xls']:
            df = pd.read_excel(save_path)

            df.columns = df.columns.str.strip().str.lower()

            required = {'tanggal', 'struk', 'produk'}

            if not required.issubset(df.columns):
                return( None, None, None,
                    "File Excel harus memiliki header: "
                    "tanggal, struk, dan produk."
                )

            # if df[["tanggal", "struk", "produk"]].isnull().any().any():
            #     return None, None, (
            #         "File Excel mengandung nilai kosong di kolom wajib."
            #     )

            # Hitung missing value pada kolom wajib
            missing = df[["tanggal", "struk", "produk"]].isnull().sum()
            # missing_rows = df[["tanggal", "struk", "produk"]].isnull().any(axis=1).sum()
            missing_struk = int(missing["struk"])
            missing_produk = int(missing["produk"])
            missing_tanggal = int(missing["tanggal"])

            missing_rows = df[["tanggal", "struk", "produk"]].isnull().any(axis=1).sum()
            total_rows = len(df)
            persentase = (missing_rows / total_rows) * 100

            if missing_rows > 0:
                # Jika lebih dari 2% maka ditolak
                if persentase > 2:
                    return (
                        None,
                        None,
                        None,
                        f"Ditemukan {missing_rows} baris data kosong (missing value) ({persentase:.2f}%). "
                        "Jumlah tersebut melebihi batas toleransi 2% dari keseluruhan data. "
                        "Silakan perbaiki file terlebih dahulu."
                    )

            # Hapus missing value
            df = df.dropna(subset=["tanggal", "struk", "produk"])
            jumlah_data_setelah = len(df)

            warning = (
                f"Ditemukan data kosong sebagai berikut, "
                f"Tanggal : {missing_tanggal} data, "
                f"Struk : {missing_struk} data, "
                f"Produk : {missing_produk} data. "
                f"Sebanyak {missing_rows} baris ({persentase:.2f}%) "
                f"mengandung minimal satu data kosong dan telah dihapus secara otomatis "
                f"pada tahap preprocessing. "
                f"Jumlah data berubah dari {total_rows} baris menjadi {jumlah_data_setelah} baris."
            )

            produk_tidak_valid = validate_menu(
                df["produk"],
                menu_valid
            )

            if produk_tidak_valid:
                return (
                    None,
                    None,
                    None,
                    "Produk berikut tidak terdapat pada daftar menu cafe: "
                    + ", ".join(produk_tidak_valid)
                )

            # validasi nomor struk
            df["struk"] = pd.to_numeric(df["struk"], errors="coerce")
            df = df.dropna(subset=["struk"])
            df["struk"] = df["struk"].astype(int)

            # standardisasi produk
            df["produk"] = (
                df["produk"]
                .astype(str)
                .str.strip()
                .str.lower()
            )

            # hapus duplikat
            df = df.drop_duplicates(subset=["struk", "produk"])

            # hapus transaksi 1 produk
            jumlah_produk = df.groupby("struk")["produk"].nunique()
            struk_valid = jumlah_produk[jumlah_produk >= 2].index
            df = df[df["struk"].isin(struk_valid)]

            transaksi = (
                df.groupby("struk")["produk"]
                .apply(
                    lambda x: [
                        item.strip()
                        for item in x
                        if isinstance(item, str) and item.strip()
                    ]
                )
                .tolist()
            )

            print("Jumlah transaksi:", len(transaksi))
            print("Jumlah baris:", len(df))
            print("Jumlah struk:", df["struk"].nunique())

            return transaksi, 'excel', warning, None

    except Exception as e:
        return None, None, None, f"Terjadi kesalahan saat memproses file: {str(e)}"

