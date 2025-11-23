from flask import Flask, render_template, request, redirect, url_for, session
import datetime
import pytz
import random
import string
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret-key"

# -------- PROFILE PICTURE CONFIG --------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# Absolute path para sure kahit saan ka mag-run
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------------------------
# IN-MEMORY "DATABASE"
# -------------------------
USERS = {}           # username -> password
USER_FULLNAME = {}   # username -> FULL NAME (uppercase)

MOOD_LOGS = {}       # username -> {date: mood_text}
STUDY_LOGS = {}      # username -> [ {date, minutes, rest_seconds?} ]
HELP_REQUESTS = {}   # simple personal help (/help page)

FRIENDS = {}          # username -> [friend_usernames]
FRIEND_REQUESTS = {}  # username -> [sender_usernames]
USER_STATUS = {}      # username -> "studying" / "resting" / "offline"

CLASSROOMS = {}       # code -> {"name": ..., "owner": username, "members": set([...])}
USER_CLASSROOMS = {}  # username -> [classroom_code, ...]

CLASS_EMOTIONS = {}   # code -> {username: {"emotion": str, "date": iso, "time": str}}
CLASS_HELP = {}       # code -> [ {"message": str, "date": iso, "time": str, "seen_by": [usernames]} ]
CLASS_ANNOUNCEMENTS = {}  # code -> [ {"sender": str, "message": str, "date": iso} ]

PROFILE_PICS = {}     # username -> filename ng profile pic

PH_TZ = pytz.timezone("Asia/Manila")

# choices for classroom emotions
EMOTION_CHOICES = [
    "Happy", "Excited", "Calm", "Motivated",
    "Tired", "Sad", "Stressed", "Anxious",
    "Overwhelmed", "Bored",
]

# message per emotion (lalabas sa feelings page after mag-submit)
EMOTION_MESSAGES = {
    "Happy": "Ang saya! Share mo yang good energy sa classmates mo today 🤍",
    "Excited": "Ang excitement mo ay pwedeng makahawa. Use that energy to learn and connect! ✨",
    "Calm": "Calm is a superpower. Breathe in, breathe out, one step at a time 🌿",
    "Motivated": "While you feel motivated, gawin mo na yung small tasks na matagal mo nang gustong simulan 🚀",
    "Tired": "Pagod ka na, and that’s valid. Try to rest when you can—hindi ka tamad, napapagod ka lang 💤",
    "Sad": "Mabigat man ang pakiramdam, hindi ka nag-iisa. Reach out to a friend or teacher you trust 💙",
    "Stressed": "Isang bagay lang muna. Break big tasks into tiny steps. God cares even about your stress.",
    "Anxious": "Your worries are real, pero hindi ka defined by them. Slow breaths, one small action at a time 🤍",
    "Overwhelmed": "Kung sabay-sabay lahat, pili ka lang ng *next best step*. Hindi mo kailangang tapusin lahat ngayon.",
    "Bored": "Maybe your mind wants something new—try a new way of studying or helping a classmate today 🙂",
}

# -------------------------
# HELPER FUNCTIONS
# -------------------------
def today():
    return datetime.date.today().isoformat()


def last_7_days():
    today_d = datetime.date.today()
    return [(today_d - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]


def compute_study(username, days):
    totals = {d: 0 for d in days}
    for record in STUDY_LOGS.get(username, []):
        if record.get("date") in totals:
            totals[record["date"]] += record.get("minutes", 0)
    return totals


def generate_advice(avg, moods):
    negative = ["sad", "stressed", "tired", "lonely", "anxious", "overwhelmed"]
    mood_bad = sum(1 for m in moods if m and any(x in m.lower() for x in negative))

    # 0 minutes average
    if avg == 0:
        adv = (
            "Wala ka pang na-record na study time this week, pero okay lang iyon. "
            "Every big journey starts with one small step. Pwede kang magsimula sa 5–10 minute session—"
            "ang importante ay consistency, hindi big actions. "
            "Sabi nga ni Lord sa Zechariah 4:10, “Do not despise these small beginnings, "
            "for the Lord rejoices to see the work begin.”"
        )
    # Less than 30 minutes
    elif avg < 30:
        adv = (
            "Nice! May effort ka na. Kahit maikli pa ang study time mo per day, "
            "it already shows discipline and willingness to grow. "
            "Subukan mong dahan-dahang dagdagan pa ng 5–10 minutes daily. "
            "Sabi nga ni Lord sa Colossians 3:23, “Whatever you do, work at it with all your heart, "
            "as working for the Lord, not for people.”"
        )
    # Less than 60 minutes
    elif avg < 60:
        adv = (
            "Consistent ka mag-aral—good job! Mahalaga yan sa long-term growth. "
            "Pero huwag din kalimutan ang pahinga; hindi mo kailangang maging perfect everyday. "
            "Sabi nga ni Lord sa Galatians 6:9, “Let us not become weary in doing good, "
            "for in the proper time we will reap a harvest if we do not give up.”"
        )
    # 60 minutes or more
    else:
        adv = (
            "Solid ang study time mo this week! Ang dedication mo is something to celebrate. "
            "Pero mahalaga rin ang balance—study hard pero rest well. "
            "Sabi nga ni Lord sa Matthew 11:28, “Come to Me, all you who are weary and burdened, "
            "and I will give you rest.”"
        )

    if mood_bad >= 3:
        adv += (
            " Napansin ko rin na madalas mabigat ang mood mo this week. "
            "Please be gentle with yourself. Maaari kang magpahinga, magdasal, "
            "o mag-share sa taong pinagkakatiwalaan mo. Hindi ka nag-iisa—God is with you."
        )

    return adv


def generate_class_code():
    """Simple random 6-char code for classrooms."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# -------------------------
# CONTEXT PROCESSOR
# -------------------------
@app.context_processor
def inject_profile_pic():
    """
    Para accessible sa lahat ng template:
    - kasalukuyang profile pic
    - bilang ng pending friend requests (badge)
    """
    user = session.get("user")
    pic = PROFILE_PICS.get(user)
    pending_requests = 0
    if user:
        pending_requests = len(FRIEND_REQUESTS.get(user, []))
    return {
        "current_profile_pic": pic,
        "friend_request_count": pending_requests,
    }


# -------------------------
# BASIC PAGES & AUTH
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip().upper()
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        file = request.files.get("photo")

        # validation
        if not fullname or not u or not p:
            error = "Please fill in all fields."
        elif u in USERS:
            error = "That username is already taken."
        elif not file or file.filename == "":
            error = "Please upload a profile picture."
        elif not allowed_file(file.filename):
            error = "Invalid file type. Use PNG, JPG, JPEG, or GIF."
        else:
            # Save the profile picture
            ext = file.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{u}.{ext}")
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)

            # Save user info
            USERS[u] = p
            USER_FULLNAME[u] = fullname
            PROFILE_PICS[u] = filename

            MOOD_LOGS[u] = {}
            STUDY_LOGS[u] = []
            HELP_REQUESTS[u] = []
            FRIENDS[u] = []
            USER_STATUS[u] = "offline"
            USER_CLASSROOMS[u] = []

            return redirect(url_for("login"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"].strip()

        if USERS.get(u) == p:
            session["user"] = u
            # clear previous settings
            session.pop("study_mode", None)
            session.pop("role", None)
            USER_STATUS[u] = "offline"
            return redirect(url_for("mode"))
        else:
            error = "Invalid login."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    user = session.get("user")
    if user:
        USER_STATUS[user] = "offline"
        session.pop("user", None)
        session.pop("study_mode", None)
        session.pop("role", None)
    return redirect(url_for("index"))


# -------------------------
# STUDY MODE PAGE (HOME / SCHOOL)
# -------------------------
@app.route("/mode", methods=["GET", "POST"])
def mode():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        mode_value = request.form.get("mode")
        if mode_value in ("Home", "School"):
            session["study_mode"] = mode_value
            session.pop("role", None)
            return redirect(url_for("dashboard"))

    return render_template("mode.html")


# -------------------------
# DASHBOARD (HOME)
# -------------------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    full_name = USER_FULLNAME.get(user, user)

    # Count unseen classroom help messages
    notif_count = 0
    for code in USER_CLASSROOMS.get(user, []):
        for msg in CLASS_HELP.get(code, []):
            if user not in msg.get("seen_by", []):
                notif_count += 1

    return render_template(
        "dashboard.html",
        user=user,
        full_name=full_name,
        study_mode=session.get("study_mode"),
        notif_count=notif_count,
    )


# -------------------------
# TIMER PAGE + STATUS UPDATES
# -------------------------
@app.route("/timer")
def timer():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("timer.html")


@app.route("/timer_done", methods=["POST"])
def timer_done():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    try:
        study_seconds = int(request.form.get("study_seconds", 0))
        rest_seconds = int(request.form.get("rest_seconds", 0))
    except ValueError:
        study_seconds = 0
        rest_seconds = 0

    minutes = round(study_seconds / 60)
    if minutes > 0:
        STUDY_LOGS.setdefault(user, [])
        STUDY_LOGS[user].append({
            "date": today(),
            "minutes": minutes,
            "rest_seconds": rest_seconds,
        })

    USER_STATUS[user] = "offline"
    return redirect(url_for("summary"))


@app.route("/set_status/<state>", methods=["POST"])
def set_status(state):
    if "user" not in session:
        return ("unauthorized", 401)
    if state not in ("studying", "resting", "offline"):
        return ("invalid", 400)
    USER_STATUS[session["user"]] = state
    return ("", 204)


# -------------------------
# FRIENDS PAGES
# -------------------------
@app.route("/friends", methods=["GET", "POST"])
def friends():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    msg = None
    error = None

    # SEND FRIEND REQUEST
    if request.method == "POST":
        friend = request.form["friend"].strip()
        if friend == user:
            error = "You cannot add yourself."
        elif friend not in USERS:
            error = "User does not exist."
        else:
            # already friends?
            if friend in FRIENDS.get(user, []):
                msg = "You are already friends."
            else:
                pending_for_friend = FRIEND_REQUESTS.setdefault(friend, [])
                if user in pending_for_friend:
                    msg = "Friend request already sent."
                else:
                    pending_for_friend.append(user)
                    msg = "Friend request sent!"

    # BUILD FRIEND LIST
    friend_list = FRIENDS.get(user, [])
    friend_data = []
    for f in friend_list:
        status = USER_STATUS.get(f, "offline")
        friend_data.append({
            "name": f,
            "fullname": USER_FULLNAME.get(f, f),
            "status": status,
            "pic": PROFILE_PICS.get(f)
        })

    incoming = FRIEND_REQUESTS.get(user, [])

    return render_template(
        "friends.html",
        friends=friend_data,
        incoming_requests=incoming,
        message=msg,
        error=error,
        USER_FULLNAME=USER_FULLNAME,
    )


@app.route("/friends/accept/<sender>", methods=["POST"])
def accept_friend(sender):
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    pending = FRIEND_REQUESTS.get(user, [])
    if sender in pending:
        pending.remove(sender)
        if not pending:
            FRIEND_REQUESTS.pop(user, None)

        FRIENDS.setdefault(user, [])
        FRIENDS.setdefault(sender, [])
        if sender not in FRIENDS[user]:
            FRIENDS[user].append(sender)
        if user not in FRIENDS[sender]:
            FRIENDS[sender].append(user)

    return redirect(url_for("friends"))


@app.route("/friends/decline/<sender>", methods=["POST"])
def decline_friend(sender):
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    pending = FRIEND_REQUESTS.get(user, [])
    if sender in pending:
        pending.remove(sender)
        if not pending:
            FRIEND_REQUESTS.pop(user, None)

    return redirect(url_for("friends"))


# -------------------------
# MOOD, MANUAL STUDY, SUMMARY, HELP
# -------------------------
@app.route("/mood", methods=["GET", "POST"])
def mood():
    if "user" not in session:
        return redirect(url_for("login"))

    msg = None
    if request.method == "POST":
        mood_text = request.form["mood"].strip()
        MOOD_LOGS.setdefault(session["user"], {})
        MOOD_LOGS[session["user"]][today()] = mood_text
        msg = f"Mood '{mood_text}' saved for today."

    return render_template("mood.html", message=msg)


@app.route("/study", methods=["GET", "POST"])
def study():
    if "user" not in session:
        return redirect(url_for("login"))

    msg = None
    error = None

    if request.method == "POST":
        try:
            minutes = int(request.form["minutes"])
            if minutes <= 0:
                error = "Minutes must be positive."
            else:
                STUDY_LOGS.setdefault(session["user"], [])
                STUDY_LOGS[session["user"]].append({
                    "date": today(),
                    "minutes": minutes
                })
                msg = f"Recorded {minutes} minutes."
        except Exception:
            error = "Invalid number."

    return render_template("study.html", message=msg, error=error)


@app.route("/summary")
def summary():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    days = last_7_days()
    study_totals = compute_study(user, days)

    rows = []
    moods = []
    for d in days:
        mood_val = MOOD_LOGS.get(user, {}).get(d, "-")
        moods.append(mood_val)
        rows.append({
            "date": d,
            "mood": mood_val,
            "minutes": study_totals[d],
        })

    avg = sum(study_totals.values()) / 7
    advice = generate_advice(avg, moods)

    total_study_minutes = sum(study_totals.values())

    total_rest_seconds = 0
    for log in STUDY_LOGS.get(user, []):
        total_rest_seconds += log.get("rest_seconds", 0)
    total_rest_minutes = round(total_rest_seconds / 60)

    if total_study_minutes == 0:
        productivity = "No Study"
    elif total_study_minutes < 30:
        productivity = "Low Productivity"
    elif total_study_minutes < 90:
        productivity = "Moderately Productive"
    else:
        productivity = "Highly Productive"

    if total_study_minutes == 0:
        recommendation = "Start a small 5-minute study to build momentum."
    elif total_rest_minutes > total_study_minutes:
        recommendation = "You rested more than you studied. Try to focus more tomorrow."
    elif total_study_minutes > 120:
        recommendation = "Great job! But remember to take healthy breaks."
    else:
        recommendation = "Nice balance today. Keep your routine going!"

    return render_template(
        "summary.html",
        rows=rows,
        total=total_study_minutes,
        avg=round(avg, 2),
        advice=advice,
        total_study_minutes=total_study_minutes,
        total_rest_minutes=total_rest_minutes,
        productivity=productivity,
        recommendation=recommendation,
    )


@app.route("/help", methods=["GET", "POST"])
def help_page():
    if "user" not in session:
        return redirect(url_for("login"))

    msg = None
    if request.method == "POST":
        message = request.form["message"]
        HELP_REQUESTS.setdefault(session["user"], [])
        HELP_REQUESTS[session["user"]].append({
            "date": today(),
            "message": message
        })
        msg = "Your anonymous message has been sent."

    return render_template("help.html", message=msg)


# -------------------------
# PROFILE PAGE (UPLOAD PIC)
# -------------------------
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    msg = None
    error = None

    if request.method == "POST":
        file = request.files.get("photo")
        if not file or file.filename == "":
            error = "Please choose an image file."
        elif not allowed_file(file.filename):
            error = "Invalid file type. Use PNG, JPG, or GIF."
        else:
            ext = file.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{user}.{ext}")
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
            PROFILE_PICS[user] = filename
            msg = "Profile picture updated!"

    return render_template("profile.html", message=msg, error=error)


# -------------------------
# CLASSROOMS (School Mode)
# -------------------------
@app.route("/classrooms")
def my_classrooms():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    user_codes = USER_CLASSROOMS.get(user, [])

    classrooms = []
    for code in user_codes:
        data = CLASSROOMS.get(code)
        if not data:
            continue

        is_owner = (data["owner"] == user)
        role = "Class Rep" if is_owner else "Student"

        classrooms.append({
            "code": code,
            "name": data["name"],
            "role": role,
            "is_owner": is_owner,
        })

    return render_template("classrooms.html", classrooms=classrooms)


@app.route("/classroom/<code>")
def enter_classroom(code):
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)
    if not data:
        return "Classroom does not exist."

    if code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    role = "Class Rep" if data["owner"] == user else "Student"

    return render_template(
        "classroom_view.html",
        code=code,
        class_name=data["name"],
        role=role,
    )


@app.route("/classrooms/manage", methods=["GET", "POST"])
def classroom_join_create():
    """
    Join or Create classroom page.
    - Create: ikaw ang owner -> Class Rep
    - Join: magiging Student
    """
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    msg = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            name = request.form.get("classname", "").strip()
            if not name:
                error = "Class name is required."
            else:
                code = generate_class_code()
                CLASSROOMS[code] = {
                    "name": name,
                    "owner": user,
                    "members": {user},
                }
                USER_CLASSROOMS.setdefault(user, []).append(code)
                msg = f"Classroom created! Code: {code} (you are Class Rep)."

        elif action == "join":
            code = request.form.get("code", "").strip().upper()
            if code not in CLASSROOMS:
                error = "Classroom code not found."
            else:
                CLASSROOMS[code]["members"].add(user)
                USER_CLASSROOMS.setdefault(user, [])
                if code not in USER_CLASSROOMS[user]:
                    USER_CLASSROOMS[user].append(code)
                msg = f"Joined classroom {code} as Student."

    return render_template("classroom_manage.html", message=msg, error=error)


# --------- LEAVE CLASSROOM (students only) ---------
@app.route("/classroom/<code>/leave", methods=["POST"])
def leave_classroom(code):
    """Students can leave a classroom. Class Rep must delete if ayaw na."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    if data.get("owner") == user:
        return "Class Rep cannot leave. Use Delete Classroom instead."

    codes = USER_CLASSROOMS.get(user, [])
    if code in codes:
        codes.remove(code)

    members = data.get("members", [])
    if user in members:
        members.remove(user)

    return redirect(url_for("my_classrooms"))


# --------- DELETE CLASSROOM (Class Rep + password) ---------
@app.route("/classroom/<code>/delete", methods=["GET", "POST"])
def classroom_delete(code):
    """Class Rep only: delete a classroom after confirming account password."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    if data.get("owner") != user:
        return "Only the Class Rep can delete this classroom."

    error = None

    if request.method == "POST":
        pw = request.form.get("password", "").strip()
        real_pw = USERS.get(user)

        if real_pw is None or real_pw != pw:
            error = "Maling password. Classroom was not deleted."
        else:
            # 1) alisin yung classroom sa list ng lahat ng members
            members = list(data.get("members", []))
            for m in members:
                codes = USER_CLASSROOMS.get(m, [])
                if code in codes:
                    codes.remove(code)
                USER_CLASSROOMS[m] = codes

            # 2) burahin yung classroom mismo
            CLASSROOMS.pop(code, None)

            # 3) linisin related data kung meron
            for store_name in ("CLASS_EMOTIONS", "CLASS_ANNOUNCEMENTS", "CLASS_HELP"):
                store = globals().get(store_name)
                if isinstance(store, dict):
                    store.pop(code, None)

            return redirect(url_for("my_classrooms"))

    return render_template(
        "classroom_delete.html",
        code=code,
        class_name=data.get("name", code),
        error=error,
    )


# --------- CLASSROOM MOOD & FEELINGS ---------
@app.route("/classroom/<code>/mood", methods=["GET", "POST"])
def classroom_mood(code):
    """Student/Class rep: pili ng emotion (10 choices, once per day)."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    existing = CLASS_EMOTIONS.get(code, {}).get(user)
    if existing and existing["date"] == today():
        chosen = existing["emotion"]
        return redirect(url_for("classroom_feelings", code=code, emotion=chosen))

    if request.method == "POST":
        chosen = request.form.get("emotion")
        if chosen in EMOTION_CHOICES:
            now = datetime.datetime.now(PH_TZ)
            CLASS_EMOTIONS.setdefault(code, {})
            CLASS_EMOTIONS[code][user] = {
                "emotion": chosen,
                "date": now.date().isoformat(),
                "time": now.strftime("%I:%M %p"),
            }
            return redirect(url_for("classroom_feelings", code=code, emotion=chosen))

        return redirect(url_for("classroom_mood", code=code))

    return render_template(
        "classroom_mood.html",
        code=code,
        class_name=data["name"],
        emotions=EMOTION_CHOICES,
    )


@app.route("/classroom/<code>/feelings")
def classroom_feelings(code):
    """Listahan ng classmates at latest emotion nila (TODAY ONLY)."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    class_emotions = CLASS_EMOTIONS.get(code, {})
    rows = []
    today_str = today()

    for member in sorted(data["members"]):
        info = class_emotions.get(member)
        if info and info.get("date") == today_str:
            rows.append({
                "username": member,
                "fullname": USER_FULLNAME.get(member, member),
                "emotion": info["emotion"],
                "date": info["date"],
                "time": info.get("time", ""),
                "pic": PROFILE_PICS.get(member),
            })

    role = "Class Rep" if data["owner"] == user else "Student"
    user_emotion = request.args.get("emotion")
    user_message = EMOTION_MESSAGES.get(user_emotion)

    return render_template(
        "classroom_feelings.html",
        code=code,
        class_name=data["name"],
        role=role,
        rows=rows,
        user_emotion=user_emotion,
        user_message=user_message,
    )


# --------- CLASSROOM HELP (ANONYMOUS) ---------
@app.route("/classroom/<code>/help", methods=["GET", "POST"])
def classroom_help(code):
    """Anonymous help request para sa buong classroom."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    msg = None

    # POST: send new anonymous message
    if request.method == "POST":
        text = request.form.get("message", "").strip()
        if text:
            now = datetime.datetime.now(PH_TZ)
            CLASS_HELP.setdefault(code, [])
            CLASS_HELP[code].append({
                "message": text,
                "date": now.date().isoformat(),
                "time": now.strftime("%I:%M %p"),
                "seen_by": [user],   # sender has already "seen" it
            })
            msg = "Your anonymous message has been sent to the classroom."

    # Mark all messages as seen by current user
    for h in CLASS_HELP.get(code, []):
        if "seen_by" not in h:
            h["seen_by"] = []
        if user not in h["seen_by"]:
            h["seen_by"].append(user)

    help_list = list(reversed(CLASS_HELP.get(code, [])))

    return render_template(
        "classroom_help.html",
        code=code,
        class_name=data["name"],
        message=msg,
        help_list=help_list,
    )


# --------- CLASSROOM ANNOUNCEMENTS ---------
@app.route("/classroom/<code>/announce", methods=["GET", "POST"])
def classroom_announce(code):
    """Class Rep: send announcement to the whole classroom."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    if data["owner"] != user:
        return "Only the Class Rep can send announcements."

    msg = None
    error = None

    if request.method == "POST":
        text = request.form.get("message", "").strip()
        if not text:
            error = "Announcement cannot be empty."
        else:
            CLASS_ANNOUNCEMENTS.setdefault(code, [])
            CLASS_ANNOUNCEMENTS[code].append({
                "sender": USER_FULLNAME.get(user, user),
                "message": text,
                "date": today(),
            })
            msg = "Announcement sent to the classroom."

    announcements = list(reversed(CLASS_ANNOUNCEMENTS.get(code, [])))

    return render_template(
        "classroom_announce.html",
        code=code,
        class_name=data["name"],
        message=msg,
        error=error,
        announcements=announcements,
    )


@app.route("/classroom/<code>/announcements")
def classroom_announcements(code):
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    ann_list = list(reversed(CLASS_ANNOUNCEMENTS.get(code, [])))

    return render_template(
        "classroom_announcements.html",
        code=code,
        class_name=data["name"],
        announcements=ann_list,
    )


# --------- CLASSROOM ANALYTICS ---------
@app.route("/classroom/<code>/analytics")
def classroom_analytics(code):
    """Class Rep only: simple emotion analytics for the last 7 days."""
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    data = CLASSROOMS.get(code)

    if not data or code not in USER_CLASSROOMS.get(user, []):
        return "You are not a member of this classroom."

    if data["owner"] != user:
        return "Only the Class Rep can view classroom analytics."

    days = last_7_days()
    class_emotions = CLASS_EMOTIONS.get(code, {})

    emotion_counts = {e: 0 for e in EMOTION_CHOICES}
    detailed = []

    for member, info in class_emotions.items():
        date = info["date"]
        emotion = info["emotion"]
        if date in days:
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
            detailed.append({
                "name": member,
                "fullname": USER_FULLNAME.get(member, member),
                "emotion": emotion,
                "date": date,
            })

    top_emotion = None
    top_count = 0
    for emo, cnt in emotion_counts.items():
        if cnt > top_count:
            top_emotion = emo
            top_count = cnt

    if top_emotion and top_count > 0:
        emotion_based_messages = {
            "Happy": "Mukhang ang daming masaya this week — puwedeng i-acknowledge yan and celebrate small wins sa class!",
            "Excited": "Maraming excited this week. Perfect time mag-intro ng bagong activity o project.",
            "Calm": "Class looks calm overall. Pwede mo pang i-maintain yung peaceful pace ng klase.",
            "Motivated": "Ang daming motivated! Sulitin, baka pwedeng magbigay ng konting challenge o enrichment task.",
            "Tired": "Marami ang pagod. Maybe mag-start with a light warm-up o short breathing break sa class.",
            "Sad": "Maraming nalulungkot this week. Baka helpful maglaan ng sandali to check in and encourage the class.",
            "Stressed": "Most students feel stressed. Puwedeng mag-slow down ng konti, mag-clarify ng deadlines, o magbigay ng study tips.",
            "Anxious": "Maraming kabado. Clear instructions and reassurance from you could really help.",
            "Overwhelmed": "Madaming overwhelmed. Maybe i-break down yung tasks into smaller steps for them.",
            "Bored": "Maraming bored. Puwede mong lagyan ng konting movement, games, o group activity ang lesson.",
        }
        top_message = emotion_based_messages.get(
            top_emotion,
            f"Many students feel {top_emotion.lower()} this week. You might want to acknowledge this in class."
        )
    else:
        top_emotion = None
        top_message = "Wala pang sapat na data this week para makita ang overall mood ng class."

    return render_template(
        "classroom_analytics.html",
        code=code,
        class_name=data["name"],
        days=days,
        emotion_counts=emotion_counts,
        detailed=detailed,
        top_emotion=top_emotion,
        top_message=top_message,
    )


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)