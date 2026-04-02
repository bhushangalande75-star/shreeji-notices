from flask import Flask, render_template, request, make_response, Response, stream_with_context, session, redirect, url_for, jsonify
import pandas as pd
import os, io, zipfile, json, uuid, tempfile, glob, subprocess, sys
from datetime import date, datetime
from notice_generator import generate_notice
from notice_generator_2nd import generate_notice_2nd
from pypdf import PdfWriter, PdfReader
from database import (save_batch, get_batches, get_batch_notices, update_payment,
                      get_eligible_for_2nd, get_paid_members, delete_batch,
                      get_society_by_username, get_all_societies, create_society,
                      delete_society, get_society_stats)
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "shreeji-iconic-chs-2026")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin@2026")

TEMP_DIR = os.path.join(tempfile.gettempdir(), "society_notices")
os.makedirs(TEMP_DIR, exist_ok=True)

def get_libreoffice_path():
    paths = {
        "win32":  [r"C:\Program Files\LibreOffice\program\soffice.exe",
                   r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"],
        "darwin": ["/Applications/LibreOffice.app/Contents/MacOS/soffice"],
    }.get(sys.platform, ["/usr/bin/libreoffice", "/usr/bin/soffice"])
    return next((p for p in paths if os.path.exists(p)), None)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("society_id") and not session.get("is_admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── Auth ───────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # Admin login
        if username == "admin" and password == ADMIN_PASSWORD:
            session["is_admin"]   = True
            session["society_id"] = None
            session["society_name"] = "Admin"
            return redirect(url_for("admin_dashboard"))

        # Society login
        society = get_society_by_username(username)
        if society and society["password"] == password:
            session["society_id"]   = society["id"]
            session["society_name"] = society["name"]
            session["is_admin"]     = False
            return redirect(url_for("index"))

        error = "❌ Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Admin ──────────────────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_dashboard():
    societies = get_all_societies()
    return render_template("admin.html", societies=societies)

@app.route("/admin/create_society", methods=["POST"])
@admin_required
def admin_create_society():
    create_society(
        request.form.get("name"),
        request.form.get("address"),
        request.form.get("username"),
        request.form.get("password"),
        request.form.get("regd_no")
    )
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete_society/<int:society_id>", methods=["POST"])
@admin_required
def admin_delete_society(society_id):
    delete_society(society_id)
    return jsonify({"success": True})

# ── Main App ───────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    stats = get_society_stats(session["society_id"])
    return render_template("index.html", society_name=session["society_name"], stats=stats)

@app.route("/tracker")
@login_required
def tracker():
    society_id = session.get("society_id")
    batches = get_batches(society_id) if society_id else []
    stats   = get_society_stats(society_id) if society_id else {}
    return render_template("tracker.html", batches=batches, society_name=session[\"society_name\"], stats=stats)

@app.route("/tracker/batch/<int:batch_id>")
@login_required
def batch_detail(batch_id):
    notices = get_batch_notices(batch_id)
    batches = get_batches(session["society_id"])
    batch   = next((b for b in batches if b["id"] == batch_id), None)
    paid    = [n for n in notices if n["payment_status"] == "Paid"]
    pending = [n for n in notices if n["payment_status"] == "Pending"]
    return render_template("batch_detail.html", batch=batch, notices=notices,
                           paid=paid, pending=pending, society_name=session["society_name"])

@app.route("/tracker/update_payment", methods=["POST"])
@login_required
def update_payment_route():
    data = request.json
    update_payment(data["notice_id"], data["status"], data.get("payment_date", ""),
                   data.get("payment_amount", 0), data.get("remark", ""))
    return jsonify({"success": True})

@app.route("/tracker/delete_batch/<int:batch_id>", methods=["POST"])
@login_required
def delete_batch_route(batch_id):
    delete_batch(batch_id)
    return jsonify({"success": True})

@app.route("/tracker/export/<int:batch_id>/<report_type>")
@login_required
def export_report(batch_id, report_type):
    batches = get_batches(session["society_id"])
    batch   = next((b for b in batches if b["id"] == batch_id), None)
    members = get_eligible_for_2nd(batch_id) if report_type == "eligible" else get_paid_members(batch_id)
    title   = "Eligible_for_2nd_Notice" if report_type == "eligible" else "Paid_Members"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="C00000")
    headers  = ["Flat No", "Ref No", "Member Name", "Amount (Rs.)", "Status", "Payment Date", "Amount Paid", "Remark"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center")
    for row, m in enumerate(members, 2):
        ws.cell(row=row, column=1, value=m["flat_no"])
        ws.cell(row=row, column=2, value=m["ref_no"])
        ws.cell(row=row, column=3, value=m["member_name"])
        ws.cell(row=row, column=4, value=m["amount"])
        ws.cell(row=row, column=5, value=m["payment_status"])
        ws.cell(row=row, column=6, value=m.get("payment_date", ""))
        ws.cell(row=row, column=7, value=m.get("payment_amount", ""))
        ws.cell(row=row, column=8, value=m.get("payment_remark", ""))
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    response = make_response(buf.read())
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response.headers["Content-Disposition"] = f"attachment; filename={title}_Batch{batch_id}.xlsx"
    return response

# ── Generate ───────────────────────────────────────────────────
@app.route("/generate", methods=["POST"])
@login_required
def generate():
    if "excel" not in request.files:
        return make_response(json.dumps({"error": "No file uploaded"}), 400)
    file = request.files["excel"]
    if file.filename == "":
        return make_response(json.dumps({"error": "No file selected"}), 400)
    try:
        df   = pd.read_excel(file, header=None)
        data = df.iloc[1:].reset_index(drop=True)
    except Exception as e:
        return make_response(json.dumps({"error": f"Could not read Excel: {str(e)}"}), 400)

    total              = len(data)
    notice_type        = request.form.get("notice_type", "1st")
    batch_name         = request.form.get("batch_name", f"Batch {date.today().strftime('%b %Y')}")
    maintenance_period = request.form.get("maintenance_period", "March 2026")
    due_date           = request.form.get("due_date", "31st March 2026")
    subject            = request.form.get("subject", "Sub: Notice for Recovery of Due Maintenance.")
    raw_date           = request.form.get("issued_date", date.today().strftime("%d-%m-%Y"))
    try:
        issued_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")
    except:
        issued_date = raw_date

    society_id = session["society_id"]
    sess_id    = str(uuid.uuid4())
    sess_dir   = os.path.join(TEMP_DIR, sess_id)
    os.makedirs(sess_dir, exist_ok=True)
    soffice    = get_libreoffice_path()

    def stream():
        docx_files  = []
        members_log = []
        count = 0

        yield f"data: {json.dumps({'type':'start','total':total})}\n\n"

        for i, row in data.iterrows():
            try:
                flat_no     = str(row[2]).strip()
                ref_no      = str(row[4]).strip()
                name        = str(row[5]).strip()
                amount      = int(row[7])
                prev_ref_no = str(row[8]).strip() if notice_type == "2nd" and len(row) > 8 else ""

                if notice_type == "2nd":
                    doc_bytes = generate_notice_2nd(flat_no, ref_no, name, amount, prev_ref_no, issued_date, due_date, maintenance_period, subject)
                else:
                    doc_bytes = generate_notice(flat_no, ref_no, name, amount, due_date, maintenance_period, subject)

                filename = f"Notice_{ref_no.replace('/', '-')}_{flat_no}.docx"
                docx_files.append((filename, doc_bytes))
                members_log.append({"flat_no": flat_no, "ref_no": ref_no, "name": name, "amount": amount, "prev_ref_no": prev_ref_no})
                with open(os.path.join(sess_dir, filename), "wb") as f:
                    f.write(doc_bytes)
                count += 1
                yield f"data: {json.dumps({'type':'progress','count':count,'total':total,'name':name})}\n\n"
            except Exception as e:
                print(f"Row error: {e}")

        if count == 0:
            yield f"data: {json.dumps({'type':'failed','msg':'No notices generated. Check Excel format.'})}\n\n"
            return

        save_batch(batch_name, notice_type, issued_date, members_log, society_id)

        yield f"data: {json.dumps({'type':'status','msg':'Creating ZIP file...'})}\n\n"
        zip_path = os.path.join(sess_dir, "notices.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fbytes in docx_files:
                zf.writestr(fname, fbytes)

        pdf_pages = 0
        if soffice:
            yield f"data: {json.dumps({'type':'status','msg':'Converting to PDF...'})}\n\n"
            pdf_dir   = os.path.join(sess_dir, "pdf")
            os.makedirs(pdf_dir, exist_ok=True)
            docx_list = sorted(glob.glob(os.path.join(sess_dir, "*.docx")))
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", pdf_dir] + docx_list, capture_output=True)
            yield f"data: {json.dumps({'type':'status','msg':'Merging PDF pages...'})}\n\n"
            writer = PdfWriter()
            for pf in sorted(glob.glob(os.path.join(pdf_dir, "*.pdf"))):
                for page in PdfReader(pf).pages:
                    writer.add_page(page)
            pdf_path = os.path.join(sess_dir, "notices.pdf")
            with open(pdf_path, "wb") as f:
                writer.write(f)
            pdf_pages = len(writer.pages)

        yield f"data: {json.dumps({'type':'done','sess_id':sess_id,'count':count,'pages':pdf_pages,'has_pdf':soffice is not None})}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream")

@app.route("/download/<sess_id>/<filetype>")
@login_required
def download(sess_id, filetype):
    sess_dir = os.path.join(TEMP_DIR, sess_id)
    paths = {
        "zip": (os.path.join(sess_dir, "notices.zip"), "application/zip",  "Maintenance_Notices.zip"),
        "pdf": (os.path.join(sess_dir, "notices.pdf"), "application/pdf",  "Maintenance_Notices_All.pdf"),
    }
    if filetype not in paths: return "Invalid", 400
    path, mime, name = paths[filetype]
    if not os.path.exists(path): return "File not found", 404
    response = make_response(open(path, "rb").read())
    response.headers["Content-Type"]        = mime
    response.headers["Content-Disposition"] = f"attachment; filename={name}"
    return response

if __name__ == "__main__":
    lo = get_libreoffice_path()
    print("="*55)
    print("✅ Society Notice App → http://localhost:5000")
    print(f"🔒 Admin: admin / {ADMIN_PASSWORD}")
    print(f"📄 LibreOffice: {lo or '❌ NOT FOUND'}")
    print("="*55)
    app.run(debug=True)
