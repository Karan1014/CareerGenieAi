import os
import re
import io
import json
from groq import Groq
from functools import wraps
from PyPDF2 import PdfReader
from datetime import datetime
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

app = Flask(__name__)
@app.after_request
def set_headers(response):
    if request.path == '/':
        response.headers['X-Robots-Tag'] = 'index, follow'
    else:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response
app.secret_key = "careergenie_secret_2026"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///careergenie.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── Admin credentials (change these) ──
ADMIN_EMAIL    = "admin@careergenie.com"
ADMIN_PASSWORD = "admin@123"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = " Login Here."

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("GROQ_API_KEY not found in .env file!")
client = Groq(api_key=api_key)


# ── Models ──────────────────────────────────────────────
class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    analyses      = db.relationship('Analysis', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Analysis(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename       = db.Column(db.String(256))
    career         = db.Column(db.String(256))
    user_name      = db.Column(db.String(256))
    score          = db.Column(db.Integer)
    current_skills = db.Column(db.Text)
    missing_skills = db.Column(db.Text)
    industry_req   = db.Column(db.Text)
    projects       = db.Column(db.Text)
    certificates   = db.Column(db.Text)
    roadmap        = db.Column(db.Text)
    improvements   = db.Column(db.Text)
    suggested_jobs = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ── Admin decorator ──────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ── Helpers ─────────────────────────────────────────────
def extract_name_from_resume(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for line in lines[:5]:
        if re.match(r'^[A-Za-z]+(?: [A-Za-z]+){1,3}$', line):
            return line
    return "Candidate"


def extract_section(text, heading_number):
    pattern = rf"{heading_number}\.\s.*?\n(.*?)(?=\n{heading_number + 1}\.|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def parse_list(raw_text):
    lines = raw_text.split("\n")
    items = []
    for line in lines:
        line = re.sub(r"^[\s*\-•\d\.]+", "", line).strip()
        if line:
            items.append(line)
    return items


def extract_score(raw_text):
    match = re.search(r"\b(\d{1,3})\b", raw_text)
    if match:
        return min(int(match.group(1)), 100)
    return 0


def parse_certificates(raw_text):
    certs = []
    for line in parse_list(raw_text):
        if line.lower() not in ["none", "n/a", "no certifications", ""]:
            certs.append({"name": line})
    return certs


# ── Auth Routes ─────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if User.query.filter_by(email=email).first():
            flash('Yeh email pehle se registered hai.', 'danger')
            return redirect(url_for('register'))
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Email or  password are worng.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Main Routes ─────────────────────────────────────────
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('landing'))

@app.route('/landing')
def landing():
    return render_template('landing.html')



@app.route('/dashboard')
@login_required
def dashboard():
    analyses = Analysis.query.filter_by(user_id=current_user.id)\
                             .order_by(Analysis.created_at.desc()).all()
    total_analyses = len(analyses)
    last_analysis  = analyses[0] if analyses else None
    avg_score = round(sum(a.score for a in analyses) / total_analyses, 1) if total_analyses else None
    return render_template('dashboard.html',
        total_analyses=total_analyses,
        last_analysis=last_analysis,
        avg_score=avg_score
    )

@app.route('/result', methods=['POST'])
@login_required
def result():
    resume = request.files.get('resume')
    career = request.form.get('career', '').strip()

    if resume is None:
        return "Resume file not received."

    pdf = PdfReader(resume)
    text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text

    user_name = extract_name_from_resume(text)

    prompt = f"""
You are an expert ATS Resume Analyzer and Career Coach.
Analyze the following resume for the target career.

Resume:
{text}

Target Career: {career}

IMPORTANT SCORING RULES:
- Score is based ONLY on resume content — skills, experience, projects, education
- Score must be a fixed number between 0-100
- Score 80-100: Excellent (5+ years experience, strong skills match)
- Score 60-79: Good (2-4 years or strong fresher with projects)
- Score 40-59: Average (some skills, lacks experience or projects)
- Score 0-39: Weak (very few relevant skills or empty resume)

Reply in EXACTLY this numbered format (no extra commentary before or after):

1. Resume Score (0-100)
<just a single number like 72>

2. Skills Found
<bullet list of skills found in resume>

3. Missing Skills
<bullet list of important missing skills>

4. Industry Requirements
<bullet list of what the industry expects in 2026>

5. Recommended Projects
<bullet list of 3-4 projects candidate should build>

6. Certifications Found in Resume
<bullet list of certifications mentioned, or "None">

7. Learning Roadmap (3 Months)
Month 1: <2-3 key focus areas only, long explanations>
Month 2: <2-3 key focus areas only>
Month 3: <2-3 key focus areas only>

8. Resume Improvements
<bullet list of specific improvements>

9. Jobs You Can Apply For Right Now
<bullet list of 4-5 job titles>
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        ai_raw = response.choices[0].message.content
    except Exception as e:
        return f"<h2>Error: {str(e)}</h2><a href='/'>Go Back</a>"

    score_raw    = extract_section(ai_raw, 1)
    skills_raw   = extract_section(ai_raw, 2)
    missing_raw  = extract_section(ai_raw, 3)
    industry_raw = extract_section(ai_raw, 4)
    projects_raw = extract_section(ai_raw, 5)
    certs_raw    = extract_section(ai_raw, 6)
    roadmap_raw  = extract_section(ai_raw, 7)
    improve_raw  = extract_section(ai_raw, 8)
    jobs_raw     = extract_section(ai_raw, 9)

    score          = extract_score(score_raw)
    current_skills = parse_list(skills_raw)
    missing_skills = parse_list(missing_raw)
    industry_req   = parse_list(industry_raw)
    projects       = parse_list(projects_raw)
    certificates   = parse_certificates(certs_raw)
    roadmap        = roadmap_raw
    improvements   = parse_list(improve_raw)
    suggested_jobs = parse_list(jobs_raw)

    analysis = Analysis(
        user_id        = current_user.id,
        filename       = resume.filename,
        career         = career,
        user_name      = user_name,
        score          = score,
        current_skills = json.dumps(current_skills),
        missing_skills = json.dumps(missing_skills),
        industry_req   = json.dumps(industry_req),
        projects       = json.dumps(projects),
        certificates   = json.dumps(certificates),
        roadmap        = roadmap,
        improvements   = json.dumps(improvements),
        suggested_jobs = json.dumps(suggested_jobs),
    )
    db.session.add(analysis)
    db.session.commit()

    return render_template(
        'result.html',
        filename=resume.filename,
        career=career,
        user_name=user_name,
        score=score,
        current_skills=current_skills,
        missing_skills=missing_skills,
        industry_req=industry_req,
        projects=projects,
        certificates=certificates,
        roadmap=roadmap,
        improvements=improvements,
        suggested_jobs=suggested_jobs,
        analysis_id=analysis.id
    )


@app.route('/history')
@login_required
def history():
    analyses = Analysis.query.filter_by(user_id=current_user.id)\
                             .order_by(Analysis.created_at.desc()).all()
    return render_template('history.html', analyses=analyses)


@app.route('/history/<int:analysis_id>')
@login_required
def view_analysis(analysis_id):
    a = Analysis.query.get_or_404(analysis_id)
    if a.user_id != current_user.id:
        return "Access denied.", 403
    return render_template(
        'result.html',
        filename       = a.filename,
        career         = a.career,
        user_name      = a.user_name,
        score          = a.score,
        current_skills = json.loads(a.current_skills),
        missing_skills = json.loads(a.missing_skills),
        industry_req   = json.loads(a.industry_req),
        projects       = json.loads(a.projects),
        certificates   = json.loads(a.certificates),
        roadmap        = a.roadmap,
        improvements   = json.loads(a.improvements),
        suggested_jobs = json.loads(a.suggested_jobs),
        analysis_id    = a.id
    )


@app.route('/download/<int:analysis_id>')
@login_required
def download_analysis(analysis_id):
    a = Analysis.query.get_or_404(analysis_id)
    if a.user_id != current_user.id:
        return "Access denied.", 403

    current_skills = json.loads(a.current_skills)
    missing_skills = json.loads(a.missing_skills)
    industry_req   = json.loads(a.industry_req)
    projects       = json.loads(a.projects)
    improvements   = json.loads(a.improvements)
    suggested_jobs = json.loads(a.suggested_jobs)
    certificates   = json.loads(a.certificates)

    content = f"""CareerGenie AI - Resume Analysis Report
==========================================
Candidate  : {a.user_name}
Career     : {a.career}
File       : {a.filename}
Date       : {a.created_at.strftime('%d %b %Y, %I:%M %p')}
Score      : {a.score}/100

------------------------------------------
SKILLS FOUND
------------------------------------------
{chr(10).join(f'- {s}' for s in current_skills)}

------------------------------------------
MISSING SKILLS
------------------------------------------
{chr(10).join(f'- {s}' for s in missing_skills)}

------------------------------------------
INDUSTRY REQUIREMENTS (2026)
------------------------------------------
{chr(10).join(f'- {s}' for s in industry_req)}

------------------------------------------
RECOMMENDED PROJECTS
------------------------------------------
{chr(10).join(f'- {s}' for s in projects)}

------------------------------------------
CERTIFICATIONS
------------------------------------------
{chr(10).join(f'- {c["name"]}' for c in certificates) if certificates else 'None'}

------------------------------------------
3-MONTH LEARNING ROADMAP
------------------------------------------
{a.roadmap}

------------------------------------------
RESUME IMPROVEMENTS
------------------------------------------
{chr(10).join(f'- {s}' for s in improvements)}

------------------------------------------
JOBS TO APPLY RIGHT NOW
------------------------------------------
{chr(10).join(f'- {s}' for s in suggested_jobs)}

==========================================
Generated by CareerGenie AI
"""

    buffer = io.BytesIO()
    buffer.write(content.encode('utf-8'))
    buffer.seek(0)
    filename = f"analysis_{a.user_name.replace(' ', '_')}_{a.id}.txt"
    return send_file(buffer, as_attachment=True,
                     download_name=filename, mimetype='text/plain')


# ── Delete Analysis Route ────────────────────────────────
@app.route('/delete/<int:analysis_id>', methods=['POST'])
@login_required
def delete_analysis(analysis_id):
    a = Analysis.query.get_or_404(analysis_id)
    if a.user_id != current_user.id:
        return "Access denied.", 403
    db.session.delete(a)
    db.session.commit()
    return '', 200


# ── Admin Routes ─────────────────────────────────────────
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Worng credentials.', 'danger')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    total_users    = User.query.count()
    total_analyses = Analysis.query.count()
    avg_score      = db.session.query(db.func.avg(Analysis.score)).scalar()
    avg_score      = round(avg_score, 1) if avg_score else 0
    recent         = Analysis.query.order_by(Analysis.created_at.desc()).limit(5).all()
    users          = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_dashboard.html',
        total_users=total_users,
        total_analyses=total_analyses,
        avg_score=avg_score,
        recent=recent,
        users=users
    )


@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user     = User.query.get_or_404(user_id)
    analyses = Analysis.query.filter_by(user_id=user_id)\
                             .order_by(Analysis.created_at.desc()).all()
    return render_template('admin_user_detail.html', user=user, analyses=analyses)


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    Analysis.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)