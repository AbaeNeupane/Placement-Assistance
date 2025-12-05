# For backfilling missing job_id in applications_collection
import os
import re
import sys
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv

# configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "backend", "jobs_info.csv")
DB_NAME = "final"                      
COL_APPS = "applications"
COL_USERS = "userinfo"

#  Ensure we load .env from the backend folder for MONGO_URI
load_dotenv(os.path.join(BASE_DIR, "backend", ".env"))

def norm_title(s: str) -> str:
    """Normalize a job title for matching."""
    if s is None:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def main():
    load_dotenv()
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("ERROR: MONGO_URI not set in environment/.env")
        sys.exit(1)

    if not os.path.exists(CSV_PATH):
        print(f"ERROR: jobs_info.csv not found at: {CSV_PATH}")
        sys.exit(1)

    # Read jobs_info.csv
    df = pd.read_csv(CSV_PATH, dtype={"job id": str, "company id": str})
    if not {"job id", "company id", "Job Title"}.issubset(df.columns):
        print("ERROR: jobs_info.csv is missing required columns: 'job id','company id','Job Title'")
        sys.exit(1)

    df["__norm_title"] = df["Job Title"].map(norm_title)
    # prefer string job_id; app code compares as int sometimes, but we can store int safely
    # Use int if numeric, else keep string
    def coerce_job_id(x):
        try:
            return int(str(x).strip())
        except:
            return str(x).strip()

    df["__job_id_clean"] = df["job id"].map(coerce_job_id)

    csv_index = {}
    for _, row in df.iterrows():
        try:
            key = (int(str(row["company id"]).strip()), row["__norm_title"])
        except:
            # company id might be non-numeric in CSV (unlikely)
            continue
        csv_index[key] = row["__job_id_clean"]

    # connect to MongoDB
    client = MongoClient(mongo_uri)
    db = client[DB_NAME]
    apps = db[COL_APPS]
    users = db[COL_USERS]

    # Cursor for legacy applications (missing or null job_id) ---
    legacy_filter = {"$or": [{"job_id": {"$exists": False}}, {"job_id": None}]}
    cursor = apps.find(legacy_filter)

    updated = 0
    skipped = 0
    total = 0
    missing_pairs = 0
    missing_user = 0

    print("Starting backfill...\n")

    for doc in cursor:
        total += 1
        _id = doc.get("_id")
        username = doc.get("username")
        job_title = doc.get("job_title")
        company_id = doc.get("company_id")

        # Ensure user_id present by username
        user_id_to_set = None
        if username:
            udoc = users.find_one({"username": username}, {"_id": 1})
            if udoc:
                user_id_to_set = udoc["_id"]
            else:
                missing_user += 1
        else:
            missing_user += 1

        # Determine company_id must be int for lookup. If missing, skip or infer later.
        if company_id is None:
            # Could try to infer from CSV if titles are unique, but safer to skip
            print(f"- SKIP (no company_id): app {_id}, title='{job_title}', username='{username}'")
            skipped += 1
            continue
        try:
            company_id_int = int(company_id)
        except:
            print(f"- SKIP (bad company_id): app {_id}, company_id='{company_id}'")
            skipped += 1
            continue

        #  Find job_id in CSV using pair company_id, normalized title
        norm = norm_title(job_title)
        key = (company_id_int, norm)
        job_id_clean = csv_index.get(key)

        if job_id_clean is None:
            # No exact match (company_id + title). Report and skip.
            print(f"- NO MATCH (CSV): app {_id}, company_id={company_id_int}, title='{job_title}'")
            missing_pairs += 1
            skipped += 1
            continue

        # Update the applications_collection document
        update = {}
        if doc.get("job_id") is None:
            update["job_id"] = job_id_clean
        if doc.get("company_id") is None:
            update["company_id"] = company_id_int
        if user_id_to_set is not None and doc.get("user_id") is None:
            update["user_id"] = user_id_to_set

        if update:
            apps.update_one({"_id": _id}, {"$set": update})
            updated += 1
            print(f"+ UPDATED app {_id}: set {update}")
        else:
            print(f"= NO CHANGE app {_id}: already consistent")


    print(f"Total legacy apps scanned: {total}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"  - Missing CSV pair (company_id + job_title not found): {missing_pairs}")
    print(f"  - Missing user (username not found in userinfo): {missing_user}")

if __name__ == "__main__":
    main()
