import pandas as pd

# Load your original file
df = pd.read_csv("jobs_info.csv")

def generate_job_description(row):
    skills = row['Key Skills']
    role = row['Role Category']
    area = row['Functional Area']
    exp = row['Job Experience']

    desc = f"This role falls under {area} with a focus on {role}. The candidate should have skills in {skills}."

    # Add fresher eligibility
    if "0 -" in str(exp) or "0-" in str(exp):
        desc += " Freshers may also apply for this position."

    # Add generic requirements
    desc += " The job requires good communication skills, problem-solving ability, teamwork, and adaptability to new technologies."
    return desc

# Fill job descriptions where missing
df['Job Description'] = df.apply(
    lambda row: generate_job_description(row) if pd.isna(row['Job Description']) else row['Job Description'],
    axis=1
)

# Save the updated file
df.to_csv("updated_job_descriptions.csv", index=False)

print("✅ File saved as updated_job_descriptions.csv")
