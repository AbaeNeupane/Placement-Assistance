from flask import Flask, request, render_template, redirect, url_for, session
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from algorithm import recommend_jobs
from flask import Flask, render_template

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)




# MongoDB sanga connection garako


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


#Yo chai login ko lagi
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

       
        if not username or not password:
            return render_template('login.html', error='missing_fields')

       
        user = db.userinfo.find_one({'username': username})

        if user is None:
            return render_template('login.html', error='username_not_found')
        elif not check_password_hash(user['password'], password):
            return render_template('login.html', error='invalid_password')
        else:
            session['username'] = username  
            
            # Pass user details to viewprofile.html
            return render_template('viewprofile.html', recommendations=[], username=username , email=user['email'], name=user['name'], experience=user['experience'], designation=user['designation'], skills=user['skills'])

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))
   
#Pailey account xaina vani signup garni
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
            'skills': skills
        })
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/recommend_jobs')
def recommend_jobs_route():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))

    user = userinfo_collection.find_one({'username': username})
    if not user:
        return redirect(url_for('login'))

    skills = user.get('skills', '')
    designation = user.get('designation', '')
    experience = user.get('experience', 0)

    recommendations = recommend_jobs(skills, designation, experience)

    if not recommendations:
        recommendations = [{"message": "No recommendations found!"}]
    else:
        # Company ko url ma change garni
        for job in recommendations:
            company_id = job.get("company id")
            company_info = companies_collection.find_one({'company_id': int(company_id)})
            if company_info and "domain" in company_info:
                job["application_url"] = f"https://{company_info['domain']}"
            else:
                job["application_url"] = "https://example.com"  

        # Save to DB
        recommendations_collection.insert_one({
            'username': username,
            'recommendations': recommendations
        })

    return render_template('recommendations.html', recommendations=recommendations, username=username)


@app.route('/recruiter_login', methods=['GET', 'POST'])
def recruiter_login():
    if request.method == 'POST':
        company_id = request.form.get('companyid')
        company_password = request.form.get('companypassword')

        
        if not company_id or not company_password:
            return render_template('recruiter_login.html', error='missing_fields')

     
        # Check if the company ID exists in the database
        company_info = db.companies.find_one({'company_id': int(company_id)})
        if company_info is None:
            # Alert if the company ID does not exist
            return render_template('recruiter_login.html', error='id_not_found')
        elif company_password != company_info.get('company_pwd'):
            # Alert if the password is incorrect for the given company ID
            return render_template('recruiter_login.html', error='incorrect_password')
        else:
            # Session ma company ko info save garni
            session['company_id'] = company_id
            session['company'] = company_info.get('company')
            session['domain'] = company_info.get('domain')
            
            #Login vayo vani dashbord ma redirect garni
            return redirect(url_for('dashboard'))
    return render_template('recruiter_login.html')


@app.route('/dashboard')
def dashboard():
    company = session.get('company')
    domain = session.get('domain')
    return render_template('dashboard.html', company=company, domain=domain)

#Company ley khulako job ko list
@app.route('/job_postings')
def job_postings():
    import pandas as pd
    company = session.get('company')
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    df = pd.read_csv('backend/jobs_info.csv')
    filtered_jobs = df[df['company id'] == int(company_id)]
    jobs_list = filtered_jobs.to_dict('records')
    return render_template('job_postings.html', jobs=jobs_list, company=company)

# Apply gareko candidates haruko list
@app.route('/candidates')
def candidates():
    company_id = session.get('company_id')
    if not company_id:
        return redirect(url_for('recruiter_login'))

    # Step 1: Find all applications for this company
    applied_users = db['applications'].find({'company_id': int(company_id)})
    usernames = [app['username'] for app in applied_users]

    # Step 2: Fetch user details
    candidates = list(userinfo_collection.find({'username': {'$in': usernames}}))
    
    return render_template('candidates.html', candidates=candidates)

@app.route('/apply_job', methods=['POST'])
def apply_job():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company_id = int(request.form.get('company_id'))
    job_title = request.form.get('job_title')

    # Update user document to track applications
    userinfo_collection.update_one(
        {'username': username},
        {'$addToSet': {'applied_company_id': company_id}}  # prevent duplicates
    )

    # Optionally, log application details
    db['applications'].insert_one({
        'username': username,
        'company_id': company_id,
        'job_title': job_title
    })

    return redirect(url_for('recommend_jobs_route'))


if __name__ == '__main__':
    app.run()
