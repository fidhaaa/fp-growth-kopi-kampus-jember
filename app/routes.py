import io
import json
import hashlib
import os
from collections import Counter
from datetime import datetime, timedelta

from time import time

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, abort, current_app
from .extensions import db
from app.models import SimulationHistory, AnalysisHistory, User, UserActivityLog
from werkzeug.exceptions import RequestEntityTooLarge

MENU_FILE = "produk_valid.xlsx"

main = Blueprint('main', __name__)

# Routes
@main.app_context_processor
def inject_latest_history():
    # Membuat variabel 'latest_history' tersedia di semua template.
    # Ambil history terbaru milik user yang sedang login.
    if 'user_id' in session:
        latest_history = AnalysisHistory.query.filter_by(user_id=session['user_id']) \
                                             .order_by(AnalysisHistory.id.desc()).first()
        return {'latest_history': latest_history}
    return {'latest_history': None}

@main.app_errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    flash("Ukuran file melebihi batas maksimum 2 MB.", "danger")
    return redirect(url_for("main.upload"))

@main.route('/')
def home():
    return redirect('/login')

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Cek panjang username
        if len(username) < 3:
            flash('Nama pengguna minimal 3 karakter', 'danger')
            log = UserActivityLog(username=username, action='register', status='gagal - username terlalu pendek')
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('main.register'))

        #  Cek panjang password
        if len(password) < 6:
            flash('Kata sandi minimal 6 karakter', 'danger')
            log = UserActivityLog(username=username, action='register', status='gagal - password terlalu pendek')
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('main.register'))
        
        # Cek apakah username sudah ada
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username sudah digunakan.', 'danger')
            log = UserActivityLog(username=username, action='register', status='gagal - username sudah ada')
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('main.register'))
        
        # Cek apakah ini user pertama
        is_first_user = User.query.filter(User.role.in_(['admin', 'user'])).count() == 0
        role = 'admin' if is_first_user else 'user'

        # Buat user baru
        new_user = User(username=username, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registrasi berhasil. Silakan login.', 'info')
        log = UserActivityLog(username=username, action='register', status=f'berhasil - sebagai {role}')
        db.session.add(log)
        db.session.commit()        
        return redirect(url_for('main.login'))

    return render_template('main/register.html')

@main.route('/demo')
def demo_login():
    # One-click portfolio demo using synthetic, read-only data.
    from app import _ensure_demo_data
    _ensure_demo_data(current_app)

    user = User.query.filter_by(username='demo').first()
    if not user:
        flash('Demo sedang tidak tersedia.', 'danger')
        return redirect(url_for('main.login'))

    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role

    log = UserActivityLog(username='demo', action='login', status='berhasil - mode demo')
    db.session.add(log)
    db.session.commit()

    return redirect(url_for('main.dashboard'))


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        user = User.query.filter_by(username=username).first()
           
        if user and user.check_password(request.form['password']):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role # misalnya 'admin' atau 'user'

            log = UserActivityLog(username=username, action='login', status='berhasil')
            db.session.add(log)
            db.session.commit()

            return redirect('/dashboard')

        flash('Nama Pengguna atau Kata Sandi salah. Silakan daftar jika belum memiliki akun', 'danger')
        log = UserActivityLog(username=username, action='login', status='gagal - username atau password salah')
        db.session.add(log)
        db.session.commit()

    return render_template('main/login.html')

def get_rules(history):
    try:
        rules = json.loads(history.result)

        for rule in rules:
            rule["antecedents"] = [
                clean_product_name(item)
                for item in rule["antecedents"]
            ]

            rule["consequents"] = [
                clean_product_name(item)
                for item in rule["consequents"]
            ]

        return rules

    except Exception:
        return []

def get_filtered_rules(history, min_conf, min_lift, min_length):
    filtered_rules = []

    rules = get_rules(history)

    for rule in rules:
        lhs_items = rule["antecedents"]
        rhs_items = rule["consequents"]
        conf = float(rule["confidence"])
        lift = float(rule["lift"])

        produk_total = len(lhs_items) + len(rhs_items)

        if (
            conf >= min_conf
            and lift >= min_lift
            and produk_total >= min_length
        ):
            filtered_rules.append({
                "lhs": lhs_items,
                "rhs": rhs_items,
                "conf": conf,
                "lift": lift
            })

    filtered_rules.sort(
        key=lambda x: (-x["lift"], -x["conf"])
    )
    return filtered_rules

def clean_product_name(nama):
    return (
        str(nama)
        .replace('"', '')
        .replace("'", "")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )

@main.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    last_visualized_id = session.pop('last_visualized_id', None)  # Ambil & hapus dari session

    # Ambil nilai filter dari query string
    try:
        min_conf = float(request.args.get('min_conf', 0.3))
        min_lift = float(request.args.get('min_lift', 1.0))
        min_length = int(request.args.get('min_length', 1))
    except:
        min_conf, min_lift, min_length = 0.3, 1.0, 1

    # Ambil semua riwayat analisis user
    histories = AnalysisHistory.query.order_by(AnalysisHistory.date_uploaded.desc()).all()

    # Lakukan filter aturan berdasarkan form
    for h in histories:
        h.filtered_table = get_filtered_rules(
            h,
            min_conf,
            min_lift,
            min_length
        )
    
    scroll_to = request.args.get("scroll_to")

    return render_template('main/dashboard.html',
                           histories=histories,
                           min_conf=min_conf,
                           min_lift=min_lift,
                           min_length=min_length,
                           username=session['username'],
                           last_visualized_id=last_visualized_id,
                           scroll_to=scroll_to)

@main.route('/lihat_data/<int:history_id>')
def lihat_data(history_id):
    import pandas as pd

    if 'user_id' not in session:
        return redirect('/login')
    
    history = AnalysisHistory.query.get_or_404(history_id)
    filename = history.filename
    
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        abort(404)

    try:
        ext = filename.rsplit('.', 1)[1].lower()
        if ext == 'csv':
            df = pd.read_csv(file_path, header=None)
            df.columns = [f'Kolom {i+1}' for i in range(df.shape[1])]
        elif ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path)
        else:
            flash("Format file tidak didukung.", "danger")
            return redirect(url_for('main.dashboard'))
    except Exception as e:
        flash(f'Gagal membaca file: {e}', 'danger')
        return redirect(url_for('main.dashboard'))

    data_preview = df.head(100)

    return render_template('main/lihat_data.html', filename=filename,  columns=data_preview.columns.tolist(), records=data_preview.values.tolist(), row_count=len(df), history=history, hide_navbar=True)

@main.route('/export/<int:history_id>')
def export_excel(history_id):
    import pandas as pd

    if 'user_id' not in session:
        return redirect('/login')

    # Mengambil riwayat tanpa memeriksa kepemilikan user berdasarkan history_id
    history = AnalysisHistory.query.get(history_id)
    if not history:
        flash('Riwayat tidak ditemukan.', 'warning')
        return redirect('/dashboard')

    # Mengambil riwayat dengan memeriksa kepemilikan user
    # history = AnalysisHistory.query.filter_by(id=history_id, user_id=session['user_id']).first()
    # if not history:
    #     flash('Riwayat tidak ditemukan.', 'warning')
    #     return redirect('/dashboard')

    # Ambil nilai filter dari query (jika ada)
    try:
        min_conf = float(request.args.get('min_conf', 0.3))
        min_lift = float(request.args.get('min_lift', 1.0))
        min_length = int(request.args.get('min_length', 1))
    except:
        min_conf, min_lift, min_length = 0.3, 1.0, 1

    filtered_rules = get_filtered_rules(
        history,
        min_conf,
        min_lift,
        min_length
    )

    data = []

    for rule in filtered_rules:
        data.append({
            "Jika Dibeli": ", ".join(rule["lhs"]),
            "Disarankan": ", ".join(rule["rhs"]),
            "Confidence": rule["conf"],
            "Lift": rule["lift"]
        })

    # Buat DataFrame dan simpan ke Excel
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Filtered Rules')
    output.seek(0)

    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     download_name=f'filtered_rules_{history_id}.xlsx',
                     as_attachment=True)

@main.route('/export_pdf/<int:history_id>')
def export_pdf(history_id):
    from fpdf import FPDF

    if 'user_id' not in session:
        return redirect('/login')

    history = AnalysisHistory.query.get(history_id)
    if not history:
        flash('Data tidak ditemukan', 'danger')
        return redirect('/dashboard')

    # Ambil filter dari url
    try:
        min_conf = float(request.args.get('min_conf', 0.3))
        min_lift = float(request.args.get('min_lift', 1.0))
        min_length = int(request.args.get('min_length', 1))
    except:
        min_conf, min_lift, min_length = 0.3, 1.0, 1

    filtered_rules = get_filtered_rules(
        history,
        min_conf,
        min_lift,
        min_length
    )

    # Buat PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 10, f"Aturan Asosiasi (Filtered)\nMin Conf: {min_conf}, Min Lift: {min_lift}, Min Produk: {min_length}\n", align='L')

    if not filtered_rules:
        pdf.multi_cell(0, 10, "Tidak ada aturan yang memenuhi filter.", 'warning')
    else:
        for i, rule in enumerate(filtered_rules, start=1):
            pdf.multi_cell(0, 8, f"{i}. Jika Dibeli : {', '.join(rule['lhs'])}")
            pdf.multi_cell(0, 8, f"   Disarankan : {', '.join(rule['rhs'])}")
            pdf.cell(
                0, 
                8, 
                f"   Confidence : {rule['conf']:.2f}    Lift : {rule['lift']:.2f}", ln=True)
            pdf.ln(2)

    # klo mau tampilan produk a -> produk b
    # if not filtered_lines:
    #     pdf.multi_cell(0, 10, "Tidak ada aturan yang memenuhi filter.", 'warning')
    # else:
    #     for rule in filtered_lines:
    #         pdf.multi_cell(
    #             0,
    #             8,
    #             f"{', '.join(rule['lhs'])} -> {', '.join(rule['rhs'])}"
    #         )
    #         pdf.cell(0, 8,
    #                 f"Confidence : {rule['conf']:.2f}    Lift : {rule['lift']:.2f}",
    #                 ln=True)
    #         pdf.ln(2)

    # Simpan ke memori (tanpa file)
    output = io.BytesIO()
    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    output.write(pdf_bytes)
    output.seek(0)

    return send_file(output,
                     mimetype='application/pdf',
                     download_name=f'filtered_rules_{history_id}.pdf',
                     as_attachment=True)

@main.route('/visualisasi_tampil/<int:history_id>')
def visualisasi_tampil(history_id):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import networkx as nx
    from matplotlib import rcParams
    from matplotlib.font_manager import FontProperties

    rcParams['font.family'] = 'Segoe UI Emoji'

    if 'user_id' not in session:
        return redirect('/login')

    # session['last_visualized_id'] = history_id  # Simpan ID di session

    # Pastikan user login
    user_id = session.get('user_id')

    history = AnalysisHistory.query.get(history_id)
    if not history:
        flash("Data analisis tidak ditemukan.", "warning")
        return redirect(url_for("main.dashboard"))
        # return "Data tidak ditemukan", 404
    try:
        min_conf = float(request.args.get('min_conf', 0.3))
        min_lift = float(request.args.get('min_lift', 1.0))
        min_length = int(request.args.get('min_length', 1))
    except:
        min_conf, min_lift, min_length = 0.3, 1.0, 1

    G = nx.MultiDiGraph()
    produk_counter = {}

    filtered_rules = get_filtered_rules(
        history,
        min_conf,
        min_lift,
        min_length
    )

    for rule in filtered_rules:
        lhs_items = rule["lhs"]
        rhs_items = rule["rhs"]
        conf = rule["conf"]
        lift = rule["lift"]

        # for item in lhs_items + rhs_items:
        #     produk_counter[item] = produk_counter.get(item, 0) + 1

        # for l in lhs_items:
        #     for r in rhs_items:
        #         if lift >= 2:
        #             color = "red"
        #         elif lift >= 1:
        #             color = "orange"
        #         else:
        #             color = "lightgray"

        #         if G.has_edge(r, l):
        #             rad = -0.15
        #         else:
        #             rad = 0.15

        #         G.add_edge(
        #             l,
        #             r,
        #             label=f"lift: {lift:.2f}\nconf: {conf:.2f}",
        #             color=color,
        #             lift=lift,
        #             conf=conf,
        #             rad=rad
        #         )

        lhs_node = ", ".join(lhs_items)
        rhs_node = ", ".join(rhs_items)

        # hitung frekuensi node
        produk_counter[lhs_node] = produk_counter.get(lhs_node, 0) + 1
        produk_counter[rhs_node] = produk_counter.get(rhs_node, 0) + 1

        if lift >= 2:
            color = "red"
        elif lift >= 1:
            color = "orange"
        else:
            color = "lightgray"

        if G.has_edge(rhs_node, lhs_node):
            rad = -0.15
        else:
            rad = 0.15

        G.add_edge(
            lhs_node,
            rhs_node,
            label=f"lift: {lift:.2f}\nconf: {conf:.2f}",
            color=color,
            lift=lift,
            conf=conf,
            rad=rad
        )

    max_freq = max(produk_counter.values(), default=0)
    produk_terbanyak = [produk for produk, freq in produk_counter.items() if freq == max_freq]

    if G.number_of_edges() == 0:
        flash("Tidak ada aturan yang memenuhi filter.", 'warning')
        return redirect('/dashboard')
    
    # Simpan list node secara eksplisit
    nodes_list = list(G.nodes())

    # Buat warna node dengan urutan yang pasti
    node_colors = []
    for node in nodes_list:
        freq = produk_counter.get(node, 0)
        if freq >= 10:
            node_colors.append("#56e046")
        elif freq >= 5:
            node_colors.append('skyblue')
        elif freq >= 1:
            node_colors.append('orange')
        else:
            node_colors.append('lightgray')

    # ------------------------------------------------------------
    # Simbol piala untuk produk yg sering muncul
    custom_labels = {}
    for node in G.nodes():
        if node in produk_terbanyak:
            custom_labels[node] = f"{node} 🏆"
        else:
            custom_labels[node] = node

    #  Buat kotak buat wadah tampilan aturan asosiasi yg mau divisualisasikan
    plt.figure(figsize=(11, 8))
    # pos = nx.spring_layout(G, k=3.0, seed=42, iterations=100)
    pos = nx.spring_layout(G, k=5, seed=42, iterations=200)
    ax = plt.gca()

    # Cari edge dengan lift tertinggi
    max_lift = max([d['lift'] for _, _, d in G.edges(data=True)], default=0)
    
    # Gambar EDGES dulu supaya panah tidak ketutupan node
    for idx, (u, v, key) in enumerate(G.edges(keys=True)):
        rad = 0.15 * (key + 1) if key % 2 == 0 else -0.15 * (key + 1)
        # rad = 0.15 if idx % 2 == 0 else -0.15
        # rad = G[u][v][key]["rad"]
        
        nx.draw_networkx_edges(
            G, pos,
            edgelist=[(u, v)],
            edge_color=G[u][v][key]['color'],
            connectionstyle=f'arc3,rad={rad}',
            arrowstyle='-|>', # Ujung panah
            arrowsize=35, # Besar kecilnya panah
            # width=2.5,
            width=2.7,
            ax=ax,
            min_source_margin=15,
            min_target_margin=15
        )

    # Gambar NODES setelah edges
    nx.draw_networkx_nodes(G, pos,
                        nodelist=nodes_list,
                        node_color=node_colors,
                        node_size=1500, # Kecilkan dikit biar panah kelihatan
                        edgecolors='black',
                        linewidths=0.8,
                        ax=ax)

    # Labels node
    emoji_font = FontProperties(family='Segoe UI Emoji')

    for node, (x, y) in pos.items():
        label_text = node

        # Teks nama produk (posisi normal)
        ax.text(
            x, y + 0.01 if node in produk_terbanyak else y,  # naikin dikit kalau pakai simbol di bawah
            label_text,
            fontsize=8,
            ha='center',
            va='center',
            fontproperties=emoji_font,
            color='black'
        )

        # Simbol piala di bawah teks
        if node in produk_terbanyak:
            ax.text(
                x, y - 0.02,  # di bawah tulisan
                "🏆",
                fontsize=10,
                ha='center',
                va='center',
                fontproperties=emoji_font,
                color='black'
            )

    # Labels edge (confidence/lift/support)
    label_positions = {}
    for i, (u, v, key) in enumerate(G.edges(keys=True)):
        x1, y1 = pos[u]
        x2, y2 = pos[v]

        # Posisi tengah edge
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2

        # Arah edge
        dx = x2 - x1
        dy = y2 - y1
        length = (dx**2 + dy**2)**0.5
        if length == 0:
            length = 1e-6  # hindari pembagian nol

        # Vektor normal (tegak lurus)
        norm_x = -dy / length
        norm_y = dx / length

        # label di tengah2 panah
        rad = 0.15 * (key + 1) if key % 2 == 0 else -0.15 * (key + 1)
        offset = -0.10 if rad > 0 else 0.10
        label_pos = (
            mid_x + offset * norm_x,
            mid_y + offset * norm_y
        )
        # Simpan posisi label
        label_positions[(u, v, key)] = label_pos

        # Simbol bintang untuk produk di aturan asoisasi dg lift tertinggi
        # letak bintang di samping nilai lift
        lift = G[u][v][key]["lift"]
        conf = G[u][v][key]["conf"]
        star = " ⭐" if lift == max_lift else ""
        label_text = (
            f"lift: {lift:.2f}{star}\n"
            f"conf: {conf:.2f}"
        )     

        # letak bintang di atas nilai lift
        # label_text = G[u][v][key]["label"]
        # if G[u][v][key]["lift"] == max_lift:
        #     label_text = "⭐\n" + label_text

        # letak bintang di sebelah nilai conf
        # label_text = G[u][v][key]['label']
        # if G[u][v][key]['lift'] == max_lift:
        #     label_text += " ⭐"

        ax.text(
            label_pos[0], 
            label_pos[1],
            label_text,
            fontsize=7,
            # color='black',
            # color='white',
            # fontweight="bold",
            ha='center',
            va='center',
            fontproperties=emoji_font,
            bbox=dict(
                facecolor='white', 
                edgecolor='gray', 
                # edgegolor='none' # Outline box tidak ada
                alpha=0.8, 
                # alpha=0.6, # Kotak box lebih transparan
                boxstyle='round,pad=0.2'
                # boxstyle='round,pad=0.15'
            )
        )

    # Cari semua edge yang punya lift tertinggi
    edges_with_max_lift = [e for e in G.edges(data=True) if e[2].get('lift', 0) == max_lift]

    # Di antara mereka, ambil yang confidence-nya paling tinggi
    best_edge = max(edges_with_max_lift, key=lambda x: x[2].get('conf', 0), default=None)

    # Tambahkan simbol 🔥 besar di tengah edge terbaik
    if best_edge:
        u, v, data = best_edge

        # cari key edge yang sesuai
        for key in G[u][v]:
            if (
                G[u][v][key]["conf"] == data["conf"]
                and
                G[u][v][key]["lift"] == data["lift"]
            ):
                label_x, label_y = label_positions[(u, v, key)]
                break

        ax.text(
            label_x,
            label_y + 0.065,
            "🔥",
            fontsize=14,
            ha='center',
            va='center',
            fontproperties=emoji_font
        )        
    # ------------------------------------------------------------

    # Simpan file statis di folder static/ dan buat nama file unik berdasarkan user dan histori
    filename = f"visualisasi_user{user_id}_hist{history_id}.png"
    filepath = os.path.join(current_app.static_folder, filename)
    print(filepath)
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(filepath, dpi=300, bbox_inches='tight')
    plt.close()

    # Menghitung statistik dasar hasil analisis
    jumlah_aturan = len(filtered_rules)
    produk_terlibat = set()
    for r in filtered_rules:
        produk_terlibat.update(r['lhs'])
        produk_terlibat.update(r['rhs'])
    jumlah_produk = len(produk_terlibat)
    tanggal_analisis = history.date_uploaded.strftime('%d %B %Y %H:%M')

    session['last_visualized_id'] = history_id

    return render_template('main/visualisasi.html',
                           min_conf=min_conf,
                           min_lift=min_lift,
                           min_length=min_length,
                           jumlah_aturan=jumlah_aturan,
                           jumlah_produk=jumlah_produk,
                           tanggal_analisis=tanggal_analisis,
                           history=history,
                           image_file=filename,
                           visual_filename=filename,
                           time=time)

@main.route('/hapus/<int:history_id>', methods=['POST'])
def hapus_file(history_id):
    if 'user_id' not in session:
        return redirect('/login')

    # Ambil riwayat berdasarkan ID
    history = AnalysisHistory.query.get(history_id)

    if not history:
        flash('Data tidak ditemukan.', 'danger')
        return redirect('/dashboard')

    # Ambil informasi user login
    user_id = session['user_id']
    user_role = session.get('role')

    if user_role == 'demo':
        flash('Mode demo bersifat read-only. Data contoh tidak dapat dihapus.', 'info')
        return redirect('/dashboard')
    
    # Admin boleh hapus semua, user hanya boleh hapus miliknya
    if user_role != 'admin' and history.user_id != user_id:
        flash('Anda tidak memiliki izin untuk menghapus data ini.', 'danger')
        return redirect('/dashboard')

    # Hapus file CSV dari folder upload
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], history.filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            flash(f'Gagal menghapus file: {e}', 'danger')
            return redirect('/dashboard')
        
    # Hapus file visualisasi yg terkait dari folder static
    visual_filename = f"static/visualisasi_user{history.user_id}_hist{history_id}.png"
    if os.path.exists(visual_filename):
        try:
            os.remove(visual_filename)
        except Exception as e:
            flash(f'Gagal menghapus visualisasi: {e}', 'danger')

    # Hapus dari database
    db.session.delete(history)
    db.session.commit()

    flash('Data berhasil dihapus.', 'success')
    return redirect('/dashboard')

@main.route('/reset_aplikasi', methods=['POST'])
def reset_aplikasi():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash("Akses ditolak.", "danger")
        return redirect(url_for('main.dashboard'))

    from app.models import User  # import model User
    import shutil

    try:
        # Hapus semua data dari database
        AnalysisHistory.query.delete()
        SimulationHistory.query.delete()
        User.query.delete()
        db.session.commit()

        # Hapus folder uploads
        upload_path = current_app.config['UPLOAD_FOLDER']
        if os.path.exists(upload_path):
            shutil.rmtree(upload_path)
        os.makedirs(upload_path, exist_ok=True)

        flash("Aplikasi berhasil di-reset.  Silakan buat akun baru untuk mulai menggunakan aplikasi kembali.", "success")

        session.pop("user_id", None)
        session.pop("username", None)
        session.pop("role", None)

        return redirect(url_for('main.register'))
    
    except Exception as e:
        db.session.rollback()
        flash(f"Gagal me-reset aplikasi: {str(e)}", "danger")

    return redirect(url_for('main.dashboard'))

@main.route('/upload', methods=['GET', 'POST'])
def upload():
    from app.utils.validation import allowed_file, validate_and_process_file
    from app.utils.fp_growth import analyze_fp_growth_from_list

    if 'user_id' not in session:
        return redirect('/login')

    if session.get('role') == 'demo':
        flash('Mode demo bersifat read-only. Gunakan menu ini melalui akun Anda sendiri untuk mengunggah data.', 'info')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash("Tidak ada file yang dipilih.", "danger")
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash("Format file tidak didukung. Hanya CSV, XLS, atau XLSX yang diperbolehkan.", "danger")
            return redirect(request.url)

        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

        transaksi, filetype, warning, error = validate_and_process_file(file, filepath)
        if error:
            flash(error, "danger")
            return redirect(request.url)  
        if warning:
            flash(warning, "info")      
        if not transaksi:
            flash("File valid tetapi tidak ada transaksi yang bisa dianalisis.", "danger")
            return redirect(request.url)
        # Pakai versi baru analyze_fp_growth_from_list
        result, err = analyze_fp_growth_from_list(transaksi)
        if err:
            flash(err, "danger")
            return redirect(request.url)
        if not result:
            flash("Tidak ada aturan yang memenuhi minimum confidence 0.30 atau minimum lift 1.", 'warning')
            return redirect(request.url)
    
        json_result = json.dumps(result)

        # Produk kurang laris
        counter = Counter()
        for trx in transaksi:
            counter.update(trx)

        least_sold = sorted(
            counter.items(),
            key=lambda x: x[1]
        )[:10]

        # Simpan JSON string ke database
        history = AnalysisHistory(
            user_id=session['user_id'],
            filename=filename,
            #result=json.dumps(result),  # simpan list of dict
            result=json_result,
            least_sold=json.dumps(least_sold)
        )

        try:
            db.session.add(history)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"Gagal menyimpan hasil analisis: {e}", "danger")
            return redirect(request.url)

        flash('File berhasil diunggah dan dianalisis.', 'success')
        return redirect(f'/dashboard#tabel-{history.id}')  

    return render_template('main/upload.html')

@main.route('/download-template/<filetype>')
def download_template(filetype):
    if filetype == "xlsx":
        filename = "template_transaksi.xlsx"
    elif filetype == "csv":
        filename = "template_transaksi.csv"
    else:
        abort(404)

    filepath = os.path.join(
        current_app.static_folder,
        "template",
        filename
    )

    print(filepath)
    print(os.path.exists(filepath))

    return send_file(filepath, as_attachment=True)

@main.route('/simulasi', methods=['GET', 'POST'])
def simulasi():
    import pandas as pd

    if 'user_id' not in session:
        return redirect('/login')

    rekomendasi = {}
    kombinasi_sudah_sesuai = []
    produk_dipilih = request.form.getlist('produk')
    semua_produk = set(produk_dipilih)
    produk_sesuai = set() 

    # Ambil semua history dari semua user untuk pilihan dropdown
    all_histories = AnalysisHistory.query.order_by(AnalysisHistory.date_uploaded.desc()).all()

    # Tentukan ID analisis yang dipilih user dari form
    if request.method == "POST":
        selected_analysis_id = request.form.get("history_id")
    else:
        selected_analysis_id = request.args.get("history_id")

    history = None
    pemilik_data = None

    # Jika user memilih analisis tertentu
    if selected_analysis_id:
        history = AnalysisHistory.query.filter_by(id=selected_analysis_id).first()
    else:
        # Default: ambil milik user itu sendiri jika ada
        history = AnalysisHistory.query.filter_by(user_id=session['user_id'])\
                                       .order_by(AnalysisHistory.date_uploaded.desc()).first()
        # Jika tetap kosong, pakai data admin
        if not history:
            admin_user = User.query.filter_by(username='admin').first()
            if admin_user:
                history = AnalysisHistory.query.filter_by(user_id=admin_user.id)\
                                               .order_by(AnalysisHistory.date_uploaded.desc()).first()

    if not history:
        flash("Belum ada hasil analisis. Silakan upload terlebih dahulu.", 'warning')
        return redirect('/upload')

    # Ambil nama pemilik data
    pemilik = db.session.get(User, history.user_id)
    pemilik_data = pemilik.username if pemilik else 'Tidak diketahui'
        
    # Ambil dan kumpulkan semua produk dari aturan hasil analisis
    rules = get_rules(history)

    for rule in rules:
        semua_produk.update(rule["antecedents"])
        semua_produk.update(rule["consequents"])

    # Hitung produk terlaris dari file yang dipilih
    produk_terlaris_pilihan = []
    counter_terlaris_pilihan = Counter()
    try:
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], history.filename)
        print("="*50)
        print("History ID :", history.id)
        print("Filename   :", history.filename)
        print("Filepath   :", filepath)
        print("Exists     :", os.path.exists(filepath))
        if os.path.exists(filepath):
            ext = history.filename.rsplit(".", 1)[1].lower()
            # File CSV (format basket)
            if ext == "csv":
                df = pd.read_csv(
                    filepath,
                    header=None,
                    engine="python"
                )
                for row in df.values:
                    for cell in row:
                        if pd.isna(cell):
                            continue
                        items = [
                            clean_product_name(item)
                            for item in str(cell).split(",")
                            if clean_product_name(item)
                        ]
                        counter_terlaris_pilihan.update(items)
            # File Excel (format transaksi)
            else:
                df = pd.read_excel(filepath)
                print("Shape :", df.shape)
                print("Kolom :", df.columns.tolist())

                print(df.tail(10))
                df.columns = df.columns.astype(str).str.strip()
                if "Produk" in df.columns:
                    df = df.dropna(subset=["Struk", "Produk"])
                    counter_terlaris_pilihan.update(
                            df["Produk"]
                            .astype(str)
                            .str.strip()
                            .apply(clean_product_name)                     
                    )
    except Exception as e:
        print(f"[ERROR] Gagal membaca file {history.filename}: {e}")
    produk_terlaris_pilihan = [item[0] for item in counter_terlaris_pilihan.most_common(3)] 
    produk_terlaris_nama = set(produk_terlaris_pilihan)

    if "Produk" in df.columns:
        mask = df["Produk"].astype(str).str.strip().str.lower() == "es"
        print(df.loc[mask])

        for k, v in counter_terlaris_pilihan.items():
            if k.startswith("Es"):
                print(repr(k), v)



    # Hitung produk kurang terlaris dari file yang dipilih
    produk_kurang_laris_pilihan = [
        produk
        for produk, jumlah in sorted(
            counter_terlaris_pilihan.items(),
            key=lambda x: x[1]
        )
        if produk not in produk_terlaris_nama      
    ][:3]

    # Proses form POST untuk rekomendasi produk
    if request.method == 'POST':
        produk_dipilih = request.form.getlist('produk')
        produk_dipilih_set = set(produk_dipilih)
        produk_sesuai = set()

        for rule in rules:
            lhs_set = set(rule["antecedents"])
            rhs_set = set(rule["consequents"])

            if lhs_set.issubset(produk_dipilih_set):

                if rhs_set.issubset(produk_dipilih_set):
                    kombinasi_sudah_sesuai.append({
                        "lhs": ", ".join(lhs_set),
                        "rhs": ", ".join(rhs_set)
                    })
                else:
                    key = ", ".join(lhs_set)

                    rekomendasi.setdefault(key, [])

                    rekomendasi[key].extend([
                        r for r in rhs_set
                        if r not in produk_dipilih_set
                        and r not in rekomendasi[key]
                    ])

        for combo in kombinasi_sudah_sesuai:
            produk_sesuai.update(combo['lhs'].split(', '))
            produk_sesuai.update(combo['rhs'].split(', '))

        semua_rekomendasi_flat = set()

        for produk in rekomendasi.values():
            semua_rekomendasi_flat.update(produk)

        new_simulasi = SimulationHistory(
            user_id=session['user_id'],
            selected_products=', '.join(produk_dipilih),
            recommended_products=', '.join(semua_rekomendasi_flat)
        )

        db.session.add(new_simulasi)
        db.session.commit()

    # Badge produk yg paling sering direkomendasikan versi tanpa highligt di checkbox produk
    # Hitung frekuensi produk rekomendasi
    # produk_rekom_counter = Counter()
    # for produk_list in rekomendasi.values():
    #     produk_rekom_counter.update(produk_list)

    # Ambil 3 produk paling sering direkomendasikan (opsional bisa disesuaikan)
    # produk_terpopuler = [produk for produk, _ in produk_rekom_counter.most_common(3)]

    # Badge produk yg paling sering direkomendasikan versi dg highligt di checkbox produk
    # Hitung produk paling sering muncul di bagian RHS dari aturan
    # counter_rhs = Counter()
    # for line in history.result.split('\n'):
    #     if '->' in line and 'conf:' in line:
    #         try:
    #             rhs = line.split('->')[1].split('(')[0]
    #             rhs_items = [item.strip() for item in rhs.split(',')]
    #             counter_rhs.update(rhs_items)
    #         except:
    #             continue

    # Ambil 3 produk yang paling sering direkomendasikan
    # produk_terpopuler = [item[0] for item in counter_rhs.most_common(3)]

    return render_template('main/simulasi.html',
                           semua_produk=sorted(semua_produk),
                           produk_dipilih=produk_dipilih,
                           rekomendasi=rekomendasi,
                           kombinasi_sudah_sesuai=kombinasi_sudah_sesuai,
                           produk_sesuai=produk_sesuai,
                           produk_terlaris_pilihan = produk_terlaris_pilihan,
                           produk_kurang_laris_pilihan=produk_kurang_laris_pilihan,
                           pemilik_data=pemilik_data,
                           all_histories=all_histories,
                           selected_analysis_id=selected_analysis_id or history.id,
                           history=history)

@main.route('/insight-global')
def insight_global():
    import pandas as pd

    # Ambil parameter filter waktu dari URL
    filter_waktu = request.args.get('filter_waktu', 'all')

    # Filter hasil berdasarkan waktu
    batas_tanggal = None
    if filter_waktu == '7':
        batas_tanggal = datetime.utcnow() - timedelta(days=7)
    elif filter_waktu == '30':
        batas_tanggal = datetime.utcnow() - timedelta(days=30)

    # Ambil semua hasil history untuk menghitung produk terpopuler
    all_analysis = AnalysisHistory.query.all()

    # Produk Terlaris
    counter_terlaris = Counter()
    counter_rhs = Counter()

    for h in all_analysis:
        if batas_tanggal and h.date_uploaded < batas_tanggal:
            continue

        # Hitung Produk Terlaris
        try:
            filepath = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                h.filename
            )

            if os.path.exists(filepath):
                ext = h.filename.rsplit(".", 1)[1].lower()
                if ext == "csv":
                    df = pd.read_csv(
                        filepath,
                        header=None,
                        engine="python"
                    )

                    for row in df.values:
                        for cell in row:
                            if pd.isna(cell):
                                continue
                            items = [
                                clean_product_name(item)
                                for item in str(cell).split(",")
                                if clean_product_name(item)
                            ]

                            counter_terlaris.update(items)
                else:
                    df = pd.read_excel(filepath)
                    df.columns = df.columns.astype(str).str.strip()

                    if "Produk" in df.columns:
                        counter_terlaris.update(
                            df["Produk"].dropna().apply(clean_product_name)
                        )

        except Exception:
            pass

        # Hitung Produk Terpopuler
        rules = get_rules(h)

        for rule in rules:
            counter_rhs.update(
                clean_product_name(item)
                for item in rule["consequents"]
            )

    produk_terlaris = [
        item[0]
        for item in counter_terlaris.most_common(5)
    ]

    produk_terpopuler = [
        item[0]
        for item in counter_rhs.most_common(5)
    ]

    return render_template('main/insight_global.html',
                           produk_terlaris=produk_terlaris,
                           produk_terpopuler=produk_terpopuler,
                           filter_waktu=filter_waktu)

@main.route('/logout')
def logout():
    session.clear()
    return redirect('/login')
