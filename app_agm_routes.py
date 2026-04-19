"""
app_agm_routes.py — Virtual AGM/SGM Routes for SocietyNotice Pro
=================================================================
INSTRUCTIONS:
1. Copy agm_db.py functions into database.py
2. Add these imports at the top of app.py (alongside existing imports):
      from database import (... existing ... ,
          init_agm_tables, create_agm_meeting, get_agm_meetings,
          get_agm_meeting, update_agm_status, save_agm_transcript, save_agm_minutes,
          delete_agm_meeting, record_agm_join, record_agm_leave, get_agm_attendance,
          get_agm_present_count, create_agm_vote, open_agm_vote, close_agm_vote,
          get_agm_votes, get_active_vote, cast_agm_vote, get_vote_results, member_has_voted
      )
3. Add call to init_agm_tables() near the other init_*_tables() calls in app.py
4. Add to base.html navigation (inside the admin nav-items section):
      <a class="nav-item {% if 'agm' in request.endpoint %}active{% endif %}" href="/agm">
        <span class="nav-icon">🏛️</span> Virtual AGM/SGM
      </a>
5. Add to portal_dashboard.html (in the portal nav links):
      <a href="/portal/agm" class="btn-nav">🏛️ AGM/SGM</a>

All routes below are 100% free:
  - Video: Jitsi Meet public server (meet.jit.si) - no account needed
  - Transcription: Groq Whisper API (uses existing NOTICE_API_KEY env var)
  - Minutes AI: Groq LLaMA (uses existing NOTICE_API_KEY env var)
  - DB: Neon PostgreSQL (already running)
"""

import io


# ── Groq Whisper transcription (free tier: 28,800s audio/day) ─────────────────
def transcribe_with_groq(audio_bytes, filename="meeting.webm"):
    """
    Transcribe audio using Groq's free Whisper API.
    Supports: webm, mp3, mp4, wav, m4a  (browser MediaRecorder produces webm)
    Free tier: 20 req/min, 28,800 seconds of audio per day.
    """
    if not GROQ_API_KEY:
        raise ValueError("NOTICE_API_KEY not set")
    resp = http_requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": (filename, io.BytesIO(audio_bytes), "audio/webm")},
        data={"model": "whisper-large-v3", "response_format": "json", "language": "en"},
        timeout=120
    )
    resp.raise_for_status()
    return resp.json().get("text", "")


def generate_agm_minutes(meeting, attendance, votes, transcript):
    """Use Groq LLaMA to generate formal Maharashtra CHS meeting minutes."""
    present_list = "\n".join(
        f"  - Flat {a['flat_combo']}: {a['member_name']}" for a in attendance
    )
    votes_text = ""
    for v in votes:
        if v["status"] in ("open", "closed"):
            results = get_vote_results(v["id"])
            tally_str = ", ".join(f"{k}: {n}" for k, n in results.get("tally", {}).items())
            votes_text += f"\n  Resolution: {v['question']}\n  Result: {tally_str}\n"

    system = (
        "You are an expert secretary for co-operative housing societies in Maharashtra, India. "
        "Generate formal Minutes of Meeting strictly following Maharashtra CHS AGM/SGM format "
        "as required under the Maharashtra Co-operative Societies Act, 1960. "
        "Use formal English. Include all statutory elements."
    )
    user = f"""
Meeting Type: {meeting['meeting_type']}
Meeting Title: {meeting['title']}
Date & Time: {meeting['scheduled_at']}
Platform: Virtual meeting via Jitsi (legally valid under MCS Act 2019 Amendment)

Agenda:
{meeting.get('agenda', 'As per notice')}

Members Present ({len(attendance)}):
{present_list}

Quorum Required: {meeting.get('quorum_required', 0)}
Quorum Status: {'QUORUM MET' if len(attendance) >= (meeting.get('quorum_required') or 1) else 'QUORUM NOT MET'}

Resolutions/Voting conducted:
{votes_text if votes_text else 'No formal votes conducted.'}

Meeting notes / transcript:
{transcript[:4000] if transcript else 'Not available.'}

Generate complete formal Minutes of Meeting. Include:
1. Header with society name placeholder [SOCIETY NAME]
2. Meeting details (type, date, time, platform)
3. Confirmation of notice served (digital notice — valid under 2019 Amendment)
4. Attendance and quorum confirmation
5. Chairperson details
6. Agenda items discussed with brief notes
7. All resolutions with vote counts
8. Any other business
9. Date of next meeting (to be filled)
10. Signature blocks for Chairman and Secretary
Use formal language. Mark all placeholders with [PLACEHOLDER].
"""
    return call_groq(system, user)


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTES — requires society login (login_required / society_required)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/agm")
@login_required
def agm_list():
    """Admin: list all meetings for this society."""
    sid = session["society_id"]
    meetings = get_agm_meetings(sid)
    return render_template("agm_list.html", meetings=meetings)


@app.route("/agm/create", methods=["POST"])
@csrf.exempt
@login_required
def agm_create():
    title           = request.form.get("title", "").strip()
    meeting_type    = request.form.get("meeting_type", "AGM")
    scheduled_at    = request.form.get("scheduled_at", "")
    agenda          = request.form.get("agenda", "").strip()
    quorum_required = int(request.form.get("quorum_required") or 0)
    if not title or not scheduled_at:
        return jsonify({"success": False, "error": "Title and date required"}), 400
    result = create_agm_meeting(session["society_id"], title, meeting_type, scheduled_at, agenda, quorum_required)
    return jsonify({"success": True, "id": result["id"]})


@app.route("/agm/<int:mid>")
@login_required
def agm_detail(mid):
    """Admin: meeting control room — manage attendance, votes, recording, minutes."""
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return redirect(url_for("agm_list"))
    attendance = get_agm_attendance(mid)
    votes = get_agm_votes(mid)
    return render_template("agm_detail.html", meeting=meeting, attendance=attendance, votes=votes)


@app.route("/agm/<int:mid>/start", methods=["POST"])
@csrf.exempt
@login_required
def agm_start(mid):
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False}), 404
    update_agm_status(mid, "live")
    return jsonify({"success": True})


@app.route("/agm/<int:mid>/end", methods=["POST"])
@csrf.exempt
@login_required
def agm_end(mid):
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False}), 404
    update_agm_status(mid, "ended")
    # Close any open votes
    for v in get_agm_votes(mid):
        if v["status"] == "open":
            close_agm_vote(v["id"])
    return jsonify({"success": True})


@app.route("/agm/<int:mid>/delete", methods=["POST"])
@csrf.exempt
@login_required
def agm_delete(mid):
    ok = delete_agm_meeting(mid, session["society_id"])
    return jsonify({"success": ok, "error": "" if ok else "Can only delete scheduled meetings"})


# ── Live status polling (admin polls every 4s for attendance count) ────────────
@app.route("/agm/<int:mid>/live-status")
@csrf.exempt
@login_required
def agm_live_status(mid):
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({}), 404
    attendance = get_agm_attendance(mid)
    present = [a for a in attendance if a["current_status"] == "present"]
    active_vote = get_active_vote(mid)
    vote_results = get_vote_results(active_vote["id"]) if active_vote else None
    return jsonify({
        "status": meeting["status"],
        "present_count": len(present),
        "attendance": [{"flat": a["flat_combo"], "name": a["member_name"],
                        "status": a["current_status"]} for a in attendance],
        "active_vote": active_vote,
        "vote_results": vote_results,
    })


# ── Vote management ────────────────────────────────────────────────────────────
@app.route("/agm/<int:mid>/vote/create", methods=["POST"])
@csrf.exempt
@login_required
def agm_vote_create(mid):
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False}), 404
    question = request.json.get("question", "").strip()
    options = request.json.get("options", ["Yes", "No", "Abstain"])
    if not question:
        return jsonify({"success": False, "error": "Question required"}), 400
    vid = create_agm_vote(mid, question, options)
    return jsonify({"success": True, "vote_id": vid})


@app.route("/agm/vote/<int:vid>/open", methods=["POST"])
@csrf.exempt
@login_required
def agm_vote_open(vid):
    open_agm_vote(vid)
    return jsonify({"success": True})


@app.route("/agm/vote/<int:vid>/close", methods=["POST"])
@csrf.exempt
@login_required
def agm_vote_close(vid):
    close_agm_vote(vid)
    results = get_vote_results(vid)
    return jsonify({"success": True, "results": results})


# ── Transcription & Minutes ────────────────────────────────────────────────────
@app.route("/agm/<int:mid>/transcribe", methods=["POST"])
@csrf.exempt
@login_required
def agm_transcribe(mid):
    """Upload audio blob from browser → transcribe with Groq Whisper (free)."""
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False, "error": "Meeting not found"}), 404
    if "audio" not in request.files:
        return jsonify({"success": False, "error": "No audio file"}), 400
    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    if len(audio_bytes) < 1000:
        return jsonify({"success": False, "error": "Audio too short"}), 400
    try:
        transcript = transcribe_with_groq(audio_bytes, audio_file.filename or "meeting.webm")
        save_agm_transcript(mid, transcript)
        return jsonify({"success": True, "transcript": transcript})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:120]}), 500


@app.route("/agm/<int:mid>/save-transcript", methods=["POST"])
@csrf.exempt
@login_required
def agm_save_transcript(mid):
    """Save manually typed transcript/notes."""
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False}), 404
    text = request.json.get("transcript", "").strip()
    save_agm_transcript(mid, text)
    return jsonify({"success": True})


@app.route("/agm/<int:mid>/generate-minutes", methods=["POST"])
@csrf.exempt
@login_required
def agm_generate_minutes(mid):
    """Generate AI minutes from transcript + attendance + votes via Groq LLaMA."""
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False, "error": "Meeting not found"}), 404
    try:
        attendance = get_agm_attendance(mid)
        votes = get_agm_votes(mid)
        minutes = generate_agm_minutes(meeting, attendance, votes, meeting.get("transcript", ""))
        save_agm_minutes(mid, minutes)
        return jsonify({"success": True, "minutes": minutes})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:120]}), 500


@app.route("/agm/<int:mid>/save-minutes", methods=["POST"])
@csrf.exempt
@login_required
def agm_save_minutes_route(mid):
    """Save edited minutes text."""
    meeting = get_agm_meeting(mid, session["society_id"])
    if not meeting:
        return jsonify({"success": False}), 404
    text = request.json.get("minutes", "").strip()
    save_agm_minutes(mid, text)
    # Optionally index minutes into Knowledge Base
    if text and request.json.get("index_kb"):
        try:
            from vector_kb import process_document
            from database import save_kb_chunks
            doc_name = f"AGM Minutes - {meeting['title']} ({meeting['scheduled_at'].strftime('%Y-%m-%d')})"
            chunks, embeddings = process_document(text.encode("utf-8"), "minutes.txt")
            save_kb_chunks(session["society_id"], "rules", doc_name, "txt",
                           list(zip(chunks, embeddings)))
        except Exception as _e:
            pass  # Don't fail the save if KB indexing fails
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# MEMBER (PORTAL) ROUTES — requires portal login
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/portal/agm")
@portal_required
def portal_agm_list():
    """Member: see upcoming and past meetings."""
    sid = session["member_society_id"]
    meetings = get_agm_meetings(sid)
    # Only show live and scheduled meetings (past ones listed too for minutes)
    return render_template("portal_agm_list.html", meetings=meetings)


@app.route("/portal/agm/<int:mid>")
@portal_required
def portal_agm_join(mid):
    """Member: join a live meeting via Jitsi embed."""
    sid = session["member_society_id"]
    meeting = get_agm_meeting(mid, sid)
    if not meeting:
        return redirect(url_for("portal_agm_list"))
    # Only allow joining if meeting is live
    flat = session["member_flat"]
    name = session["member_name"]
    # Check if member already voted any open vote
    active_vote = get_active_vote(mid) if meeting["status"] == "live" else None
    already_voted = member_has_voted(active_vote["id"], flat) if active_vote else False
    return render_template("portal_agm_join.html",
                           meeting=meeting,
                           flat=flat,
                           member_name=name,
                           active_vote=active_vote,
                           already_voted=already_voted)


@app.route("/portal/agm/<int:mid>/join", methods=["POST"])
@csrf.exempt
@portal_required
def portal_agm_mark_join(mid):
    """Record member joining the meeting."""
    meeting = get_agm_meeting(mid, session["member_society_id"])
    if not meeting or meeting["status"] != "live":
        return jsonify({"success": False, "error": "Meeting not live"}), 400
    record_agm_join(mid, session["member_flat"], session["member_name"])
    return jsonify({"success": True})


@app.route("/portal/agm/<int:mid>/leave", methods=["POST"])
@csrf.exempt
@portal_required
def portal_agm_mark_leave(mid):
    """Record member leaving the meeting."""
    record_agm_leave(mid, session["member_flat"])
    return jsonify({"success": True})


@app.route("/portal/agm/<int:mid>/poll")
@csrf.exempt
@portal_required
def portal_agm_poll(mid):
    """
    Member polls every 4 seconds to detect:
    - Meeting status change (live/ended)
    - New open vote
    """
    meeting = get_agm_meeting(mid, session["member_society_id"])
    if not meeting:
        return jsonify({}), 404
    flat = session["member_flat"]
    active_vote = get_active_vote(mid) if meeting["status"] == "live" else None
    already_voted = member_has_voted(active_vote["id"], flat) if active_vote else False
    return jsonify({
        "status": meeting["status"],
        "active_vote": active_vote,
        "already_voted": already_voted,
        "present_count": get_agm_present_count(mid),
    })


@app.route("/portal/agm/vote/<int:vid>/cast", methods=["POST"])
@csrf.exempt
@portal_required
def portal_cast_vote(vid):
    """Member casts their vote."""
    response = request.json.get("response", "").strip()
    if not response:
        return jsonify({"success": False, "error": "No response"}), 400
    ok, msg = cast_agm_vote(vid, session["member_flat"], session["member_name"], response)
    return jsonify({"success": ok, "message": msg})
