from flask import Flask, render_template, request, make_response, Response, stream_with_context, session, redirect, url_for, jsonify
import pandas as pd
import os, io, zipfile, json, uuid, tempfile, glob, subprocess, sys
from datetime import date, datetime
from notice_generator import generate_notice
from notice_generator_ai import build_ai_notice_docx, build_mom_docx
from notice_generator_2nd import generate_notice_2nd
from notice_generator_3rd import generate_notice_3rd
from notice_generator_ai import build_ai_notice_docx, build_mom_docx
import requests as http_requests
import base64
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
    return render_template("admin.html", societies=societies, society_name=session.get("society_name", "Admin"))

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
    return render_template("tracker.html", batches=batches, society_name=session["society_name"], stats=stats)

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
                prev_ref_no_1st = str(row[8]).strip() if notice_type == "3rd" and len(row) > 8 else ""
                prev_ref_no_2nd = str(row[9]).strip() if notice_type == "3rd" and len(row) > 9 else ""

                if notice_type == "3rd":
                    doc_bytes = generate_notice_3rd(flat_no, ref_no, name, amount, prev_ref_no_1st, prev_ref_no_2nd, issued_date, due_date, maintenance_period, subject)
                elif notice_type == "2nd":
                    doc_bytes = generate_notice_2nd(flat_no, ref_no, name, amount, prev_ref_no, issued_date, due_date, maintenance_period, subject)
                else:
                    doc_bytes = generate_notice(flat_no, ref_no, name, amount, due_date, maintenance_period, subject, issued_date)

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

@app.route("/ai-notices")
@login_required
def ai_notices():
    return render_template("ai_notices.html",
                           society_name=session["society_name"])

GROQ_API_KEY = os.environ.get("NOTICE_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

def call_groq(system_prompt, user_content):
    """Call Groq API (OpenAI-compatible). user_content can be str or list (for vision)."""
    if not GROQ_API_KEY:
        raise ValueError(
            "Groq API key is not set. "
            "Add NOTICE_API_KEY in your Render environment variables."
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    if isinstance(user_content, str):
        model = GROQ_MODEL
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]
    else:
        # Vision input — use Groq vision model
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
        content_parts = []
        for item in user_content:
            if item.get("type") == "text":
                content_parts.append({"type": "text", "text": item["text"]})
            elif item.get("type") == "image":
                src = item["source"]
                data_url = f"data:{src['media_type']};base64,{src['data']}"
                content_parts.append({
                    "type":      "image_url",
                    "image_url": {"url": data_url},
                })
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": content_parts},
        ]

    payload = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  2048,
        "temperature": 0.4,
    }

    resp = http_requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


@app.route("/ai-notices/generate-notice", methods=["POST"])
@login_required
def ai_generate_notice():
    """Generate a notice in the user's chosen language (English / Marathi / Hindi)."""
    try:
        notice_type   = request.form.get("notice_type", "General Notice")
        flat_no       = request.form.get("flat_no", "").strip()
        member_name   = request.form.get("member_name", "").strip()
        ref_no        = request.form.get("ref_no", "").strip()
        issued_date   = request.form.get("issued_date", date.today().strftime("%d-%m-%Y"))
        description   = request.form.get("description", "").strip()
        language      = request.form.get("language", "English").strip()
        society_name  = session.get("society_name", "Shreeji Iconic CHS Ltd.")

        try:
            issued_date = datetime.strptime(issued_date, "%Y-%m-%d").strftime("%d-%m-%Y")
        except:
            pass

        # Language-specific config
        lang_cfg = {
            "English": {
                "system": (
                    "You are the official notice writer for a Co-operative Housing Society in Maharashtra, India. "
                    "Write the notice in formal, firm, and legally appropriate English. "
                    "Write ONLY the body paragraphs — no salutation, no subject line, no signature. "
                    "Each paragraph on a new line. "
                    "Reference the Maharashtra Co-operative Societies Act 1960 and society bye-laws where relevant."
                ),
                "user": (
                    f"Write a formal notice in English for {society_name} for the following situation:\n\n"
                    f"Notice Type: {notice_type}\n"
                    f"Member Name: {member_name}\n"
                    f"Flat No: {flat_no}\n"
                    f"Issue Description: {description}\n\n"
                    "Write 3-4 firm but respectful paragraphs covering: what the issue is, "
                    "how it violates society rules/bye-laws, a demand to stop/rectify immediately, "
                    "and consequences if not complied with."
                ),
                "subject_system": "You are the secretary of a Co-operative Housing Society.",
                "subject_user": (
                    f"Write a one-line formal English subject line for a notice regarding '{notice_type}'. "
                    "Output ONLY the subject text — no 'Sub:', 'Subject:' or any prefix. "
                    "Example: No Parking Violation — Immediate Compliance Required."
                ),
                "sub_label": "Sub:",
            },
            "Marathi": {
                "system": (
                    "तुम्ही महाराष्ट्रातील एका सहकारी गृहनिर्माण संस्थेचे अधिकृत नोटीस लेखक आहात. "
                    "नोटीस मराठीत लिहा — औपचारिक, ठाम आणि कायदेशीरदृष्ट्या योग्य भाषेत. "
                    "फक्त नोटीसचे मुख्य परिच्छेद लिहा — अभिवादन, विषय ओळ किंवा स्वाक्षरी नको. "
                    "प्रत्येक परिच्छेद नवीन ओळीवर लिहा. "
                    "महाराष्ट्र सहकारी संस्था अधिनियम १९६० आणि संस्थेच्या उपविधींचा संदर्भ द्या."
                ),
                "user": (
                    f"{society_name} येथील खालील परिस्थितीसाठी मराठीत औपचारिक नोटीस लिहा:\n\n"
                    f"नोटीस प्रकार: {notice_type}\n"
                    f"सदस्याचे नाव: {member_name}\n"
                    f"फ्लॅट क्र.: {flat_no}\n"
                    f"समस्येचे वर्णन: {description}\n\n"
                    "३-४ ठाम पण सभ्य परिच्छेद लिहा. "
                    "समाविष्ट करा: समस्या काय आहे, ती संस्थेच्या नियमांचे/उपविधींचे उल्लंघन कसे करते, "
                    "तात्काळ थांबण्याची/दुरुस्त करण्याची मागणी, आणि पालन न केल्यास होणारे परिणाम."
                ),
                "subject_system": "तुम्ही एका सहकारी गृहनिर्माण संस्थेचे सचिव आहात.",
                "subject_user": (
                    f"'{notice_type}' या विषयावरील नोटीससाठी एक ओळीचा औपचारिक मराठी विषय लिहा. "
                    "फक्त विषय ओळ लिहा — 'विषय:', 'Sub:' किंवा इतर कोणताही उपसर्ग न लिहिता. "
                    "उदा: पार्किंगच्या नियमांचे उल्लंघन — तात्काळ अनुपालन आवश्यक."
                ),
                "sub_label": "विषय:",
            },
            "Hindi": {
                "system": (
                    "आप महाराष्ट्र की एक सहकारी आवास संस्था के आधिकारिक नोटिस लेखक हैं. "
                    "नोटिस हिंदी में लिखें — औपचारिक, दृढ़ और कानूनी रूप से उचित भाषा में. "
                    "केवल नोटिस के मुख्य अनुच्छेद लिखें — अभिवादन, विषय पंक्ति या हस्ताक्षर नहीं. "
                    "प्रत्येक अनुच्छेद नई पंक्ति पर लिखें. "
                    "महाराष्ट्र सहकारी संस्था अधिनियम 1960 और संस्था के उपनियमों का संदर्भ दें."
                ),
                "user": (
                    f"{society_name} के लिए निम्नलिखित स्थिति हेतु हिंदी में औपचारिक नोटिस लिखें:\n\n"
                    f"नोटिस प्रकार: {notice_type}\n"
                    f"सदस्य का नाम: {member_name}\n"
                    f"फ्लैट नं.: {flat_no}\n"
                    f"समस्या का विवरण: {description}\n\n"
                    "3-4 दृढ़ लेकिन शिष्ट अनुच्छेद लिखें जिनमें शामिल हों: समस्या क्या है, "
                    "यह संस्था के नियमों/उपनियमों का उल्लंघन कैसे करती है, "
                    "तत्काल रोकने/सुधारने की मांग, और पालन न करने पर परिणाम."
                ),
                "subject_system": "आप एक सहकारी आवास संस्था के सचिव हैं.",
                "subject_user": (
                    f"'{notice_type}' विषय पर नोटिस के लिए एक पंक्ति का औपचारिक हिंदी विषय लिखें. "
                    "केवल विषय पंक्ति लिखें — 'विषय:', 'Sub:' या कोई उपसर्ग नहीं. "
                    "उदा: पार्किंग नियमों का उल्लंघन — तत्काल अनुपालन आवश्यक."
                ),
                "sub_label": "विषय:",
            },
        }

        cfg = lang_cfg.get(language, lang_cfg["English"])
        print(f"[AI-NOTICE] language={language!r}  sub_label={cfg['sub_label']!r}")

        ai_text     = call_groq(cfg["system"], cfg["user"])
        raw_subject = call_groq(cfg["subject_system"], cfg["subject_user"]).strip().strip('"').strip("'").strip()
        # Strip any prefix the model may have added despite instructions
        for prefix in ("Sub:", "Subject:", "विषय:", "विषय :", "Vishay:"):
            if raw_subject.lower().startswith(prefix.lower()):
                raw_subject = raw_subject[len(prefix):].strip()
                break
        subject = f"{cfg['sub_label']} {raw_subject}"

        docx_bytes = build_ai_notice_docx(ref_no, flat_no, member_name, issued_date, subject, ai_text)

        sess_id  = str(uuid.uuid4())
        sess_dir = os.path.join(TEMP_DIR, sess_id)
        os.makedirs(sess_dir, exist_ok=True)
        fname = f"Notice_{notice_type.replace(' ', '_')}_{flat_no or 'General'}.docx"
        with open(os.path.join(sess_dir, fname), "wb") as f:
            f.write(docx_bytes)

        return jsonify({"success": True, "preview": ai_text, "sess_id": sess_id, "filename": fname})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/ai-notices/generate-mom", methods=["POST"])
@login_required
def ai_generate_mom():
    """Generate MOM in the user's chosen language (English / Marathi / Hindi)."""
    try:
        meeting_date = request.form.get("meeting_date", date.today().strftime("%d-%m-%Y"))
        attendees    = request.form.get("attendees", "").strip()
        language     = request.form.get("language", "English").strip()
        society_name = session.get("society_name", "Shreeji Iconic CHS Ltd.")

        try:
            meeting_date = datetime.strptime(meeting_date, "%Y-%m-%d").strftime("%d-%m-%Y")
        except:
            pass

        # Language-specific prompts for MOM
        mom_lang_cfg = {
            "English": {
                "system": (
                    "You are an experienced secretary of a Co-operative Housing Society in Maharashtra, India. "
                    "You write fluent, formal Minutes of Meeting in English. "
                    "Number all decisions. Use proper legal and administrative terminology. "
                    "Sections: Members Present, Agenda, Discussion & Decisions (numbered), Action Items."
                ),
                "photo_text": (
                    f"This is a handwritten meeting notes photo for {society_name}. "
                    f"Meeting date: {meeting_date}. "
                    f"Attendees: {attendees or 'As visible in the notes'}.\n\n"
                    "Please read all the handwritten content and generate a complete, "
                    "formal Minutes of Meeting in English. "
                    "Sections: Members Present, Agenda, Discussion & Decisions (numbered), Action Items. "
                    "Output ONLY the MOM content, no preamble."
                ),
                "text_prompt": (
                    f"Generate formal Minutes of Meeting in English for {society_name}.\n"
                    f"Meeting date: {meeting_date}\nAttendees: {attendees}\n"
                    f"Meeting notes: {{raw_notes}}\n\n"
                    "Sections: Members Present, Agenda, Discussion & Decisions (numbered), Action Items. "
                    "Output ONLY the MOM content."
                ),
            },
            "Marathi": {
                "system": (
                    "तुम्ही महाराष्ट्रातील एका सहकारी गृहनिर्माण संस्थेचे अनुभवी सचिव आहात. "
                    "तुम्ही अस्खलित, औपचारिक मराठीत इतिवृत्त (Minutes of Meeting) लिहिता. "
                    "निर्णय क्रमांकित करा. योग्य मराठी कायदेशीर आणि प्रशासकीय शब्दावली वापरा. "
                    "विभाग: उपस्थित सदस्य, अजेंडा, चर्चा व निर्णय (क्रमांकित), कृती मुद्दे."
                ),
                "photo_text": (
                    f"हे {society_name} च्या बैठकीच्या हस्तलिखित नोट्सचा फोटो आहे. "
                    f"बैठकीची तारीख: {meeting_date}. "
                    f"उपस्थित सदस्य: {attendees or 'नोट्समध्ये दिसत आहे'}.\n\n"
                    "कृपया सर्व हस्तलिखित मजकूर वाचा आणि संपूर्ण, औपचारिक मराठी इतिवृत्त तयार करा. "
                    "विभाग: उपस्थित सदस्य, अजेंडा, चर्चा व निर्णय (क्रमांकित), कृती मुद्दे. "
                    "फक्त इतिवृत्त मजकूर लिहा, कोणतीही प्रस्तावना नको."
                ),
                "text_prompt": (
                    f"{society_name} साठी मराठीत औपचारिक इतिवृत्त तयार करा.\n"
                    f"बैठकीची तारीख: {meeting_date}\nउपस्थित सदस्य: {attendees}\n"
                    f"बैठकीच्या नोट्स: {{raw_notes}}\n\n"
                    "विभाग: उपस्थित सदस्य, अजेंडा, चर्चा व निर्णय (क्रमांकित), कृती मुद्दे. "
                    "फक्त इतिवृत्त मजकूर लिहा."
                ),
            },
            "Hindi": {
                "system": (
                    "आप महाराष्ट्र की एक सहकारी आवास संस्था के अनुभवी सचिव हैं. "
                    "आप धाराप्रवाह, औपचारिक हिंदी में कार्यवृत्त (Minutes of Meeting) लिखते हैं. "
                    "सभी निर्णयों को क्रमांकित करें. उचित कानूनी और प्रशासनिक शब्दावली का उपयोग करें. "
                    "खंड: उपस्थित सदस्य, एजेंडा, चर्चा और निर्णय (क्रमांकित), कार्य बिंदु."
                ),
                "photo_text": (
                    f"यह {society_name} की बैठक के हस्तलिखित नोट्स का फोटो है. "
                    f"बैठक की तारीख: {meeting_date}. "
                    f"उपस्थित सदस्य: {attendees or 'नोट्स में दिखाई दे रहे हैं'}.\n\n"
                    "कृपया सभी हस्तलिखित सामग्री पढ़ें और पूर्ण, औपचारिक हिंदी कार्यवृत्त तैयार करें. "
                    "खंड: उपस्थित सदस्य, एजेंडा, चर्चा और निर्णय (क्रमांकित), कार्य बिंदु. "
                    "केवल कार्यवृत्त सामग्री लिखें, कोई प्रस्तावना नहीं."
                ),
                "text_prompt": (
                    f"{society_name} के लिए हिंदी में औपचारिक कार्यवृत्त तैयार करें.\n"
                    f"बैठक की तारीख: {meeting_date}\nउपस्थित सदस्य: {attendees}\n"
                    f"बैठक के नोट्स: {{raw_notes}}\n\n"
                    "खंड: उपस्थित सदस्य, एजेंडा, चर्चा और निर्णय (क्रमांकित), कार्य बिंदु. "
                    "केवल कार्यवृत्त सामग्री लिखें."
                ),
            },
        }

        cfg = mom_lang_cfg.get(language, mom_lang_cfg["English"])

        if "photo" in request.files and request.files["photo"].filename:
            photo     = request.files["photo"]
            img_bytes = photo.read()
            img_b64   = base64.standard_b64encode(img_bytes).decode()
            mime      = photo.content_type or "image/jpeg"
            user_content = [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                {"type": "text",  "text": cfg["photo_text"]},
            ]
        else:
            raw_notes    = request.form.get("raw_notes", "").strip()
            user_content = cfg["text_prompt"].format(raw_notes=raw_notes)

        mom_text   = call_groq(cfg["system"], user_content)
        docx_bytes = build_mom_docx(mom_text, meeting_date, society_name)

        sess_id  = str(uuid.uuid4())
        sess_dir = os.path.join(TEMP_DIR, sess_id)
        os.makedirs(sess_dir, exist_ok=True)
        fname = f"MOM_{meeting_date.replace('/', '-')}.docx"
        with open(os.path.join(sess_dir, fname), "wb") as f:
            f.write(docx_bytes)

        return jsonify({"success": True, "preview": mom_text, "sess_id": sess_id, "filename": fname})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/ai-notices/download/<sess_id>/<filename>")
@login_required
def ai_download(sess_id, filename):
    sess_dir = os.path.join(TEMP_DIR, sess_id)
    path = os.path.join(sess_dir, filename)
    if not os.path.exists(path):
        return "File not found", 404
    response = make_response(open(path, "rb").read())
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# ── AI Notices & MOM ───────────────────────────────────────────
if __name__ == "__main__":
    lo = get_libreoffice_path()
    print("="*55)
    print("✅ Society Notice App → http://localhost:5000")
    print(f"🔒 Admin: admin / {ADMIN_PASSWORD}")
    print(f"📄 LibreOffice: {lo or '❌ NOT FOUND'}")
    print("="*55)
    app.run(debug=True)