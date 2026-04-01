from flask import Flask, render_template, request, make_response, Response, stream_with_context, session, redirect, url_for, jsonify
import pandas as pd
import os, io, zipfile, json, uuid, tempfile, glob, subprocess, sys
from datetime import date
from notice_generator import generate_notice
from notice_generator_2nd import generate_notice_2nd
from pypdf import PdfWriter, PdfReader
from database import save_batch, get_batches, get_batch_notices, update_payment, get_eligible_for_2nd, get_paid_members, delete_batch, delete_batch, delete_batch, delete_batch_db
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "shreeji-iconic-chs-2026")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "shreeji2026")

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
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── Auth ───────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "❌ Incorrect password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Main page ─────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("index.html")

# ── Tracker page ──────────────────────────────────────────────
@app.route("/tracker")
@login_required
def tracker():
    batches = get_batches()
    return render_template("tracker.html", batches=batches)

@app.route("/tracker/batch/<int:batch_id>")
@login_required
def batch_detail(batch_id):
    notices  = get_batch_notices(batch_id)
    batches  = get_batches()
    batch    = next((b for b in batches if b['id'] == batch_id), None)
    paid     = [n for n in notices if n['payment_status'] == 'Paid']
    pending  = [n for n in notices if n['payment_status'] == 'Pending']
    return render_template("batch_detail.html", batch=batch, notices=notices, paid=paid, pending=pending)

@app.route("/tracker/update_payment", methods=["POST"])
@login_required
def update_payment_route():
    data = request.json
    update_payment(data['notice_id'], data['status'], data.get('payment_date',''), data.get('payment_amount',0), data.get('remark',''))
    return jsonify({"success": True})

# ── Export eligibility report ─────────────────────────────────
@app.route("/tracker/delete_batch/<int:batch_id>", methods=["POST"])
@login_required
def delete_batch(batch_id):
    delete_batch_db(batch_id)
    return jsonify({"success": True})

@app.route("/tracker/export/<int:batch_id>/<report_type>")
@login_required
def export_report(batch_id, report_type):
    batches = get_batches()
    batch   = next((b for b in batches if b['id'] == batch_id), None)

    if report_type == "eligible":
        members = get_eligible_for_2nd(batch_id)
        title   = "Eligible for 2nd Notice"
    else:
        members = get_paid_members(batch_id)
        title   = "Paid Members"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title

    # Header style
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="C00000")
    headers  = ["Flat No", "Ref No", "Member Name", "Amount (Rs.)", "Status", "Payment Date", "Payment Amount", "Remark"]

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center")

    for row, m in enumerate(members, 2):
        ws.cell(row=row, column=1, value=m['flat_no'])
        ws.cell(row=row, column=2, value=m['ref_no'])
        ws.cell(row=row, column=3, value=m['member_name'])
        ws.cell(row=row, column=4, value=m['amount'])
        ws.cell(row=row, column=5, value=m['payment_status'])
        ws.cell(row=row, column=6, value=m.get('payment_date',''))
        ws.cell(row=row, column=7, value=m.get('payment_amount',''))
        ws.cell(row=row, column=8, value=m.get('payment_remark',''))

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = make_response(buf.read())
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response.headers["Content-Disposition"] = f"attachment; filename={title.replace(' ','_')}_Batch{batch_id}.xlsx"
    return response

# ── Generate notices (1st or 2nd) ────────────────────────────
@app.route("/generate", methods=["POST"])
@login_required
def generate():
    if "excel" not in request.files:
        return make_response(json.dumps({"error": "No file uploaded"}), 400)
    file         = request.files["excel"]
    notice_type  = request.form.get("notice_type", "1st")
    issued_date  = request.form.get("issued_date", date.today().strftime("%d/%m/%Y"))
    batch_name   = request.form.get("batch_name", f"Batch {date.today().strftime('%b %Y')}")

    try:
        df   = pd.read_excel(file, header=None)
        data = df.iloc[1:].reset_index(drop=True)
    except Exception as e:
        return make_response(json.dumps({"error": f"Could not read Excel: {str(e)}"}), 400)

    total    = len(data)
    sess_id  = str(uuid.uuid4())
    sess_dir = os.path.join(TEMP_DIR, sess_id)
    os.makedirs(sess_dir, exist_ok=True)
    soffice  = get_libreoffice_path()

    def stream():
        docx_files  = []
        members_log = []
        count = 0

        yield f"data: {json.dumps({'type':'start','total':total})}\n\n"

        for i, row in data.iterrows():
            try:
                flat_no      = str(row[2]).strip()
                ref_no       = str(row[4]).strip()
                name         = str(row[5]).strip()
                amount       = int(row[7])
                prev_ref_no  = str(row[8]).strip() if notice_type == "2nd" and len(row) > 8 else ""

                if notice_type == "2nd":
                    doc_bytes = generate_notice_2nd(flat_no, ref_no, name, amount, prev_ref_no, issued_date)
                else:
                    doc_bytes = generate_notice(flat_no, ref_no, name, amount)

                filename = f"Notice_{ref_no.replace('/','-')}_{flat_no}.docx"
                docx_files.append((filename, doc_bytes))
                members_log.append({'flat_no': flat_no, 'ref_no': ref_no, 'name': name, 'amount': amount, 'prev_ref_no': prev_ref_no})

                with open(os.path.join(sess_dir, filename), "wb") as f:
                    f.write(doc_bytes)
                count += 1
                yield f"data: {json.dumps({'type':'progress','count':count,'total':total,'name':name})}\n\n"
            except Exception as e:
                print(f"Row error: {e}")

        if count == 0:
            yield f"data: {json.dumps({'type':'failed','msg':'No notices generated.'})}\n\n"
            return

        # Save to DB
        save_batch(batch_name, notice_type, issued_date, members_log)

        # ZIP
        yield f"data: {json.dumps({'type':'status','msg':'Creating ZIP file...'})}\n\n"
        zip_path = os.path.join(sess_dir, "notices.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fbytes in docx_files:
                zf.writestr(fname, fbytes)

        # PDF
        pdf_pages = 0
        if soffice:
            yield f"data: {json.dumps({'type':'status','msg':'Converting to PDF...'})}\n\n"
            pdf_dir   = os.path.join(sess_dir, "pdf")
            os.makedirs(pdf_dir, exist_ok=True)
            docx_list = sorted(glob.glob(os.path.join(sess_dir, "*.docx")))
            subprocess.run([soffice,"--headless","--convert-to","pdf","--outdir",pdf_dir]+docx_list, capture_output=True)
            yield f"data: {json.dumps({'type':'status','msg':'Merging PDF pages...'})}\n\n"
            writer = PdfWriter()
            for pf in sorted(glob.glob(os.path.join(pdf_dir,"*.pdf"))):
                for page in PdfReader(pf).pages:
                    writer.add_page(page)
            pdf_path = os.path.join(sess_dir, "notices.pdf")
            with open(pdf_path,"wb") as f:
                writer.write(f)
            pdf_pages = len(writer.pages)

        yield f"data: {json.dumps({'type':'done','sess_id':sess_id,'count':count,'pages':pdf_pages,'has_pdf':soffice is not None})}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream")

@app.route("/download/<sess_id>/<filetype>")
@login_required
def download(sess_id, filetype):
    sess_dir = os.path.join(TEMP_DIR, sess_id)
    paths = {
        "zip": (os.path.join(sess_dir,"notices.zip"), "application/zip", "Maintenance_Notices.zip"),
        "pdf": (os.path.join(sess_dir,"notices.pdf"), "application/pdf", "Maintenance_Notices_All.pdf"),
    }
    if filetype not in paths: return "Invalid", 400
    path, mime, name = paths[filetype]
    if not os.path.exists(path): return "File not found", 404
    response = make_response(open(path,"rb").read())
    response.headers["Content-Type"]        = mime
    response.headers["Content-Disposition"] = f"attachment; filename={name}"
    return response

if __name__ == "__main__":
    lo = get_libreoffice_path()
    print("="*55)
    print("✅ Society Notice App → http://localhost:5000")
    print(f"🔒 Password : {APP_PASSWORD}")
    print(f"📄 LibreOffice: {lo or '❌ NOT FOUND'}")
    print("="*55)
    app.run(debug=True)
