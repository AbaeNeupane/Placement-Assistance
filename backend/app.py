from flask import Flask, request, render_template, redirect, url_for, session, flash, send_from_directory, jsonify
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import pandas as pd
from dotenv import load_dotenv
from algorithm import recommend_jobs
from bson import ObjectId

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, '../frontend/templates')
STATIC_DIR = os.path.join(BASE_DIR, '../frontend/static')
JOBS_FILE = os.path.join(BASE_DIR, 'jobs_info.csv')

# Helper function to get job by ID from CSV for job details page
def get_job_by_id(job_id: int):
    # Ensure we read 'job id' as string and compare as string
    df = pd.read_csv(JOBS_FILE, dtype={'job id': str})
    row = df.loc[df['job id'] == str(job_id)]
    if row.empty:
        return None
    return row.iloc[0].to_dict()

load_dotenv()

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv("SECRET_KEY")

# Database setup
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client['final']
userinfo_collection = db['userinfo']
companies_collection = db['companies']
applications_collection = db['applications']
recommendations_collection = db['recommendations']

# Basic routes for static pages I mean home, about, choice
@app.route('/')
@app.route('/welcome')
def welcome():
    return render_template('welcome.html')

@app.route('/choice')
def choice():
    return render_template('choice.html')

@app.route('/about')
def about():
    return render_template('aboutus.html')

# (Authentication) Login route And session management
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            return render_template('login.html', error='missing_fields')
        user = userinfo_collection.find_one({'username': username})
        if user is None:
            return render_template('login.html', error='username_not_found')
        elif not check_password_hash(user['password'], password):
            return render_template('login.html', error='invalid_password')
        else:
            session['username'] = username
            return render_template('viewprofile.html',
                                   username=username,
                                   email=user['email'],
                                   name=user['name'],
                                   experience=user['experience'],
                                   designation=user['designation'],
                                   skills=user['skills'],
                                   recommendations=[])
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))

# Signup route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        email = request.form['email']
        experience = int(request.form['experience'])
        designation = request.form['designation']
        skills = request.form['skills']
        if userinfo_collection.find_one({'username': username}):
            return render_template('signup.html', error="Username already exists")
        hashed_password = generate_password_hash(password)
        userinfo_collection.insert_one({
            'username': username,
            'password': hashed_password,
            'name': name,
            'email': email,
            'experience': experience,
            'designation': designation,
            'skills': skills,
            # Optional flag users can toggle to appear in "Best Matches"
            'asked_recommendation': False
        })
        flash("Signup successful! Please login.")
        return redirect(url_for('login'))
    return render_template('signup.html')

# CV upload and retrieval
UPLOAD_FOLDER = os.path.join(STATIC_DIR, "cv_uploads")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
ALLOWED_EXT        = {".pdf", ".docx", ".doc", ".txt"} # for API

def allowed_file(filename):
    _, ext = os.path.splitext(filename)
    return ext.lower() in ALLOWED_EXTENSIONS

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# Use dynamic import to avoid static analyzers flagging a missing optional dependency
import importlib
parse_resume = None
try:
    spec = importlib.util.find_spec("resume_parser")
    if spec is not None:
        module = importlib.import_module("resume_parser")
        parse_resume = getattr(module, "parse_resume", None)
except Exception:
    parse_resume = None
    
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/upload_cv", methods=["POST"])
def upload_cv():
    if "username" not in session:
        return redirect(url_for("login"))

    if "cv" not in request.files:
        flash("No file selected", "error")
        return redirect(request.referrer)

    file = request.files["cv"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(request.referrer)

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        username = session["username"]
        filename = f"{username}_{filename}"
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # Delete old CV if exists
        old_user = userinfo_collection.find_one({"username": username})
        if old_user and "cv_filename" in old_user:
            old_path = os.path.join(app.config["UPLOAD_FOLDER"], old_user["cv_filename"])
            if os.path.exists(old_path):
                os.remove(old_path)

        file.save(file_path)
        userinfo_collection.update_one({"username": username}, {"$set": {"cv_filename": filename}})
        flash("CV uploaded successfully!", "success")
        return redirect(url_for("view_my_profile"))
    else:
        flash("Invalid file type. Allowed: pdf, doc, docx", "error")
        return redirect(request.referrer)

@app.route("/uploads/cv/<filename>")
def uploaded_cv(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# Applicant details route with email query param
@app.route("/applicantdetails")
def view_profile():
    email = request.args.get("email")  # get email from query param
    user = userinfo_collection.find_one({"email": email})
    if not user:
        return "User not found", 404

    # Check if user has uploaded a CV
    cv_filename = user.get("cv_filename")
    user["cv_url"] = url_for("uploaded_cv", filename=cv_filename) if cv_filename else None
    # Provide both keys so template can handle either
    return render_template("applicantdetails.html", user=user, applicant=user)

# User profile routes
@app.route('/viewprofile')
def view_my_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user = userinfo_collection.find_one({'username': username})
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('login'))

    cv_filename = user.get('cv_filename')
    cv_url = url_for('uploaded_cv', filename=cv_filename) if cv_filename else None

    return render_template('viewprofile.html',
                           username=user['username'],
                           email=user['email'],
                           name=user['name'],
                           experience=user['experience'],
                           designation=user['designation'],
                           skills=user['skills'],
                           cv_url=cv_url)
# Edit profile route
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user = userinfo_collection.find_one({'username': username})

    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        updated_data = {
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'experience': int(request.form.get('experience')),
            'designation': request.form.get('designation'),
            'skills': request.form.get('skills')
        }
        userinfo_collection.update_one({'username': username}, {'$set': updated_data})
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('view_my_profile'))

    return render_template('edit_profile.html', user=user)

@app.route('/delete_profile', methods=['POST'])
def delete_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user = userinfo_collection.find_one({'username': username})

    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('login'))

    # Delete CV if exists
    if 'cv_filename' in user:
        cv_path = os.path.join(app.config['UPLOAD_FOLDER'], user['cv_filename'])
        if os.path.exists(cv_path):
            os.remove(cv_path)

    # Remove user data
    userinfo_collection.delete_one({'username': username})
    applications_collection.delete_many({'username': username})
    recommendations_collection.delete_many({'username': username})

    session.clear()
    flash('Your account has been permanently deleted.', 'success')
    return redirect(url_for('welcome'))

# Recommendation route
@app.route('/recommend_jobs')
def recommend_jobs_route():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))
# Job recommendation with caching
    user = userinfo_collection.find_one({'username': username})
    if not user:
        return redirect(url_for('login'))
# Ensure jobs_info.csv exists
    if not os.path.exists(JOBS_FILE):
        return "Error: jobs_info.csv not found", 500
# Get last modified timestamp
    csv_last_modified = int(os.path.getmtime(JOBS_FILE))
# Snapshot of user profile fields relevant for recommendation
    user_profile_snapshot = {
        "skills": user.get("skills", ""),
        "designation": user.get("designation", ""),
        "experience": user.get("experience", 0)
    }
# Check cache
    cached_recommendation = recommendations_collection.find_one({"username": username})
    if cached_recommendation:
        stored_timestamp = cached_recommendation.get("csv_last_modified", 0)
        stored_profile = cached_recommendation.get("user_profile_snapshot", {})
        if stored_timestamp == csv_last_modified and stored_profile == user_profile_snapshot:
            return render_template(
                "recommendations.html",
                recommendations=cached_recommendation["recommendations"],
                username=username
            )

    # if we reach here, we need to compute new recommendations
    skills = user_profile_snapshot["skills"]
    designation = user_profile_snapshot["designation"]
    experience = user_profile_snapshot["experience"]

    recommendations = recommend_jobs(skills, designation, experience)

    if not recommendations:
        recommendations = [{"message": "No recommendations found!"}]
    else:
        company_ids = [int(job["company id"]) for job in recommendations if "company id" in job]

        companies = companies_collection.find(
            {"company_id": {"$in": company_ids}},
            {"_id": 0, "company_id": 1, "company": 1, "domain": 1}
        )
        company_lookup = {c["company_id"]: c for c in companies}
        for job in recommendations:
            company_id = int(job.get("company id", 0))
            company_info = company_lookup.get(company_id)
            if company_info:
                job["company_name"] = company_info.get("company", "Unknown Company")
                job["application_url"] = f"https://{company_info['domain']}" if "domain" in company_info else "https://example.com"
            else:
                job["company_name"] = "Unknown Company"
                job["application_url"] = "https://example.com"

    recommendations_collection.update_one(
        {"username": username},
        {
            "$set": {
                "recommendations": recommendations,
                "csv_last_modified": csv_last_modified,
                "user_profile_snapshot": user_profile_snapshot
            }
        },
        upsert=True
    )

    return render_template("recommendations.html", recommendations=recommendations, username=username)

# Recruiter routes
@app.route('/recruiter_login', methods=['GET', 'POST'])
def recruiter_login():
    if request.method == 'POST':
        company_id = request.form.get('companyid')
        company_password = request.form.get('companypassword')
        if not company_id or not company_password:
            return render_template('recruiter_login.html', error='missing_fields')
        company_info = db.companies.find_one({'company_id': int(company_id)})
        if company_info is None:
            return render_template('recruiter_login.html', error='id_not_found')
        elif company_password != company_info.get('company_pwd'):
            return render_template('recruiter_login.html', error='incorrect_password')
        else:
            session['company_id'] = int(company_id)
            session['company'] = company_info.get('company')
            session['domain'] = company_info.get('domain')
            return redirect(url_for('dashboard'))
    return render_template('recruiter_login.html')

@app.route('/dashboard')
def dashboard():
    company = session.get('company')
    domain = session.get('domain')
    return render_template('dashboard.html', company=company, domain=domain)

# Job postings management
@app.route('/job_postings')
def job_postings():
    company = session.get('company')
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    df = pd.read_csv(JOBS_FILE, dtype={'job id': str})
    if 'Job Description' not in df.columns:
        df['Job Description'] = ""

    filtered_jobs = df[df['company id'] == int(company_id)]
    jobs_list = filtered_jobs.to_dict('records')
    return render_template('job_postings.html', jobs=jobs_list, company=company)

@app.route('/add_job', methods=['GET', 'POST'])
def add_job():
    company_id = session.get('company_id')
    company = session.get('company')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    if request.method == 'POST':
        job_id = request.form['job_id']
        title = request.form['title']
        salary = request.form['salary']
        experience = request.form['experience']
        skills = request.form['skills']
        description = request.form['description']

        df = pd.read_csv(JOBS_FILE, dtype={'job id': str})
        if 'Job Description' not in df.columns:
            df['Job Description'] = ""

        new_job = {
            'job id': job_id,
            'Job Title': title,
            'Salary': salary,
            'Job Experience': experience,
            'Key Skills': skills,
            'Job Description': description,
            'company id': int(company_id),
            'company': company
        }

        df = pd.concat([df, pd.DataFrame([new_job])], ignore_index=True)
        df.to_csv(JOBS_FILE, index=False)

        flash(f"Job '{title}' added successfully!")
        return redirect(url_for('job_postings'))

    return render_template('add_job.html', company=company)


@app.route('/edit_job/<job_id>', methods=['GET', 'POST'])
def edit_job(job_id):
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    df = pd.read_csv(JOBS_FILE, dtype={'job id': str})
    if 'Job Description' not in df.columns:
        df['Job Description'] = ""

    job = df[(df['job id'] == str(job_id)) & (df['company id'] == int(company_id))].to_dict('records')
    if not job:
        return "Job not found", 404
    job = job[0]

    if request.method == 'POST':
        df.loc[df['job id'] == str(job_id),
               ['Job Title', 'Salary', 'Job Experience', 'Key Skills', 'Job Description']] = [
            request.form['title'],
            request.form['salary'],
            request.form['experience'],
            request.form['skills'],
            request.form['description']
        ]
        df.to_csv(JOBS_FILE, index=False)
        flash(f"Job '{request.form['title']}' updated successfully!")
        return redirect(url_for('job_postings'))

    return render_template('edit_job.html', job=job)

@app.route('/delete_job/<job_id>', methods=['POST'])
def delete_job(job_id):
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    df = pd.read_csv(JOBS_FILE, dtype={'job id': str})
    df = df[(df['job id'] != str(job_id)) | (df['company id'] != int(company_id))]
    df.to_csv(JOBS_FILE, index=False)

    flash("Job deleted successfully!")
    return redirect(url_for('job_postings'))

# View candidates who applied to recruiter's jobs
@app.route('/candidates')
def candidates():
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    applied_users = db['applications'].find({'company_id': int(company_id)})
    usernames = [app['username'] for app in applied_users if app.get('username')]
    candidates = list(userinfo_collection.find({'username': {'$in': usernames}}))
    return render_template('candidates.html', candidates=candidates)

# Apply for a job and track applications whether applied to job or not
@app.route('/apply_job', methods=['POST'])
def apply_job():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company_id = int(request.form.get('company_id'))
    job_title = request.form.get('job_title')
    job_id = request.form.get('job_id')  # must be provided by the form

    user = userinfo_collection.find_one({'username': username})
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('recommend_jobs_route'))

    # Optional: track applied company IDs on profile
    userinfo_collection.update_one(
        {'username': username},
        {'$addToSet': {'applied_company_id': company_id}}
    )

    applications_collection.insert_one({
        'user_id': user['_id'],                 # ObjectId for robust matching
        'username': username,                   # Username for robust matching
        'job_id': int(job_id) if job_id else None,
        'company_id': company_id,
        'job_title': job_title
    })

    flash(f"Applied for '{job_title}' successfully!")
    return redirect(url_for('recommend_jobs_route'))

# Job details and candidate ranking
@app.route('/jobs/<int:job_id>')
def job_details(job_id):
    job = get_job_by_id(job_id)
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for('job_postings'))

    # Everyone who asked for recommendation
    rec_query = {}
    all_candidates = list(userinfo_collection.find(rec_query))

    # Users who already applied for THIS job
    applied_user_ids = set()
    applied_usernames = set()
    for app_doc in applications_collection.find({"job_id": int(job_id)}, {"user_id": 1, "username": 1}):
        uid = app_doc.get("user_id")
        if uid is not None:
            applied_user_ids.add(str(uid))
        uname = app_doc.get("username")
        if uname:
            applied_usernames.add(uname)

    # Split candidates (match by _id or username)
    applied_candidates, not_applied_candidates = [], []
    for c in all_candidates:
        cid_str = str(c.get("_id"))
        uname = c.get("username")
        if cid_str in applied_user_ids or (uname and uname in applied_usernames):
            applied_candidates.append(c)
        else:
            not_applied_candidates.append(c)

    # Rank both groups for this job
    from algorithm import rank_candidates_for_job
    ranked_not_applied = rank_candidates_for_job(
        job_skills=job.get("Key Skills", ""),
        job_title=job.get("Job Title", ""),
        job_experience_text=job.get("Job Experience", ""),
        candidates=not_applied_candidates,
        top_n=5
    )
    ranked_applied = rank_candidates_for_job(
        job_skills=job.get("Key Skills", ""),
        job_title=job.get("Job Title", ""),
        job_experience_text=job.get("Job Experience", ""),
        candidates=applied_candidates,
        top_n=8
    )

    return render_template(
        'jobdetails.html',
        job=job,
        best_candidates_not_applied=ranked_not_applied,
        best_candidates_applied=ranked_applied
    )

# Applicant details by user_id (ObjectId or string)
@app.route('/applicants/<user_id>')
def applicant_details(user_id):
    try:
        # Fetch applicant by ObjectId or fallback to string/username
        try:
            user = userinfo_collection.find_one({"_id": ObjectId(user_id)})
        except Exception:
            user = (userinfo_collection.find_one({"_id": user_id})
                    or userinfo_collection.find_one({"username": user_id}))

        if not user:
            flash("Applicant not found.", "error")
            return redirect(url_for('job_postings'))

        # Build CV URL if available
        cv_filename = user.get("cv_filename")
        cv_url = url_for("uploaded_cv", filename=cv_filename) if cv_filename else None

        # Optional context passed from jobdetails
        job_id = request.args.get("job_id")           # string (fine)
        similarity_score = request.args.get("score")  # already formatted like '0.87' if provided

        return render_template('applicantdetails.html',
                               user=user,
                               applicant=user,
                               job_id=job_id,
                               similarity_score=similarity_score,
                               cv_url=cv_url)
    except Exception as e:
        flash(f"Error loading applicant: {e}", "error")
        return redirect(url_for('job_postings'))
    
# Applicant profile route for recruiter view with email param    
@app.route("/applicantprofile")
def applicant_profile():
    email = request.args.get("email")
    job_id = request.args.get("job_id")        # optional
    similarity_score = request.args.get("score")  # optional
    company_id = session.get("company_id")

    if not email:
        flash("Missing email.", "error")
        return redirect(url_for("dashboard"))

    user = userinfo_collection.find_one({"email": email})
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("dashboard"))

    # ensure this user actually applied to THIS company (if company in session)
    applied = None
    if company_id is not None:
        q = {"username": user.get("username"), "company_id": int(company_id)}
        # if job_id provided, match it too (string/int tolerant)
        if job_id is not None:
            q["$or"] = [{"job_id": int(job_id)}, {"job_id": str(job_id)}]
        applied = applications_collection.find_one(q)

        # If job_id missing in query, try to fill from their latest app to this company
        if not job_id and applied and applied.get("job_id") is not None:
            job_id = applied.get("job_id")

    # Build CV URL if available
    cv_filename = user.get("cv_filename")
    cv_url = url_for("uploaded_cv", filename=cv_filename) if cv_filename else None


    return render_template(
        "applicantprofile.html",
        user=user,
        job_id=job_id,
        similarity_score=similarity_score,
        applied=applied,
        cv_url=cv_url
    )

# Use the already defined UPLOAD_FOLDER as CV_UPLOAD_DIR
CV_UPLOAD_DIR = UPLOAD_FOLDER
os.makedirs(CV_UPLOAD_DIR, exist_ok=True)

# API endpoint for CV parsing
@app.route("/api/parse_cv", methods=["POST"])
def api_parse_cv():
    if parse_resume is None:
        return jsonify({"success": False, "message": "Parser unavailable (missing deps)"}), 500

    if "cv" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded with key 'cv'"}), 400

    f = request.files["cv"]
    if f.filename == "":
        return jsonify({"success": False, "message": "Empty filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"success": False, "message": "Only .pdf, .docx or .txt allowed"}), 400

    filename = secure_filename(f.filename)
    save_path = os.path.join(CV_UPLOAD_DIR, filename)
    f.save(save_path)


    parsed = parse_resume(save_path) or {}
    payload = {
        "name": parsed.get("name", ""),
        "email": parsed.get("email", ""),
        "phone": parsed.get("phone", ""),
        "designation": parsed.get("designation", ""),
        "experience": parsed.get("experience", ""),
        "skills": parsed.get("skills", []),
        "education": parsed.get("education", ""),
    }

    return jsonify({"success": True, "data": payload}), 200


# Run the app
if __name__ == '__main__':
    app.run(debug=True)
