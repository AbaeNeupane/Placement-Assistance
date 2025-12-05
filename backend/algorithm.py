import numpy as np
import pandas as pd
import re
import os
from sklearn.feature_extraction.text import TfidfVectorizer

# Tokenizer: remove punctuation, lowercase, split to words, keep alphabetic
def custom_tokenizer(text):
    text = re.sub(r"[^\w\s]", "", str(text).lower())
    tokens = str(text).split()
    tokens = [t for t in tokens if t.isalpha()]
    return tokens

# Extract min/max years from "Job Experience" strings
def clean_experience(experience):
    numbers = re.findall(r"\d+", str(experience))
    return [int(numbers[0]), int(numbers[-1])] if numbers else [0, 0]

# Experience similarity vs range
def experience_similarity(candidate_exp, job_exp_range):
    if candidate_exp < job_exp_range[0]:
        return max(0, 1 - (job_exp_range[0] - candidate_exp) / (job_exp_range[0] + 1e-5))
    elif candidate_exp > job_exp_range[1]:
        return max(0, 1 - (candidate_exp - job_exp_range[1]) / (candidate_exp + 1e-5))
    else:
        return 1

# Cosine similarity that also handles sparse matrices
def cosine_similarity_manual(matrix_a, matrix_b):
    if hasattr(matrix_a, "toarray"):
        matrix_a = matrix_a.toarray()
    if hasattr(matrix_b, "toarray"):
        matrix_b = matrix_b.toarray()

    norm_a = np.linalg.norm(matrix_a, axis=1, keepdims=True)
    norm_b = np.linalg.norm(matrix_b, axis=1, keepdims=True)
    norm_a[norm_a == 0] = 1e-10
    norm_b[norm_b == 0] = 1e-10

    matrix_a_norm = matrix_a / norm_a
    matrix_b_norm = matrix_b / norm_b
    similarity = np.dot(matrix_a_norm, matrix_b_norm.T)
    return similarity

# Load job data from CSV
data = pd.read_csv(os.path.join(os.path.dirname(__file__), "jobs_info.csv"))
# Preprocess experience ranges
data["Experience Range"] = data["Job Experience"].apply(clean_experience)

# TF-IDF vectorizers for skills and titles
skills_vectorizer = TfidfVectorizer(tokenizer=custom_tokenizer, ngram_range=(1, 2))
title_vectorizer  = TfidfVectorizer(tokenizer=custom_tokenizer, ngram_range=(1, 2))
# Fit vectorizers and transform data
tfidf_skills = skills_vectorizer.fit_transform(data["Key Skills"])
tfidf_titles = title_vectorizer.fit_transform(data["Job Title"])

# Main recommendation function
def recommend_jobs(query_skills, query_title, query_experience):
    query_skills_vec = skills_vectorizer.transform([query_skills])
    query_title_vec  = title_vectorizer.transform([query_title])

    skills_similarity = cosine_similarity_manual(query_skills_vec, tfidf_skills).flatten()
    title_similarity  = cosine_similarity_manual(query_title_vec,  tfidf_titles).flatten()

    if skills_similarity.max() > 0:
        skills_similarity = (skills_similarity - skills_similarity.min()) / (skills_similarity.max() - skills_similarity.min() + 1e-5)
    if title_similarity.max() > 0:
        title_similarity = (title_similarity - title_similarity.min()) / (title_similarity.max() - title_similarity.min() + 1e-5)

    combined_similarity = (skills_similarity + title_similarity) / 2.0
    experience_scores = np.array([experience_similarity(query_experience, r) for r in data["Experience Range"]])
    final_scores = combined_similarity * experience_scores

    indices = np.argsort(-final_scores)[:10]
    if len(indices) == 0 or final_scores[indices[0]] == 0:
        return []

    results = data.iloc[indices].copy()
    results["Skill Score"] = skills_similarity[indices]
    results["Title Score"] = title_similarity[indices]
    results["Experience Score"] = experience_scores[indices]
    results["Final Score"] = final_scores[indices]

    return results.sort_values(by="Final Score", ascending=False).to_dict(orient='records')

# Candidate ranking for a job
def _split_skills(s):
    if s is None:
        return set()
    if isinstance(s, list):
        parts = s
    else:
        parts = re.split(r"[,;/|]", str(s))
    return {p.strip().lower() for p in parts if p and p.strip()}

# Jaccard similarity between two sets
def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

# Parse experience requirement text into a (min, max) tuple
def _parse_experience_window(text: str):
    t = (text or "").lower().strip()
    if t in {"fresher", "freshers"}:
        return (0.0, 0.5)
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*year", t)
    if m:
        x = float(m.group(1)); return (x, x + 20.0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(\d+(?:\.\d+)?)", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if a > b: a, b = b, a
        return (a, b)
    m = re.search(r"(\d+(?:\.\d+)?)\s*year", t)
    if m:
        x = float(m.group(1)); return (x, x)
    return (0.0, 50.0)
# Experience fit score
def _experience_fit(experience_years, window):
    try:
        q = float(experience_years or 0.0)
    except:
        q = 0.0
    a, b = window
    if a <= q <= b:
        return 1.0
    dist = (a - q) if q < a else (q - b)
    return max(0.0, 1.0 / (1.0 + dist/2.0))

# Rank candidates for a job based on skills, title, and experience
def rank_candidates_for_job(job_skills: str, job_title: str, job_experience_text: str,
                            candidates, top_n=8):
    job_skill_set = _split_skills(job_skills)
    job_title_set = _split_skills(job_title)
    exp_window = _parse_experience_window(job_experience_text)

    scored = []
    for c in candidates:
        cand_skills = c.get("skills") or c.get("skills_text") or ""
        cand_skill_set = _split_skills(cand_skills)

        title_source = c.get("headline") or c.get("desired_title") or c.get("title") or cand_skills
        cand_title_set = _split_skills(title_source)

        # Accept either 'experience_years' or 'experience'
        exp_years = c.get("experience_years", c.get("experience", 0))

        s_skills = _jaccard(job_skill_set, cand_skill_set)
        s_title  = _jaccard(job_title_set, cand_title_set)
        s_exp    = _experience_fit(exp_years, exp_window)

        score = 0.5 * s_skills + 0.3 * s_title + 0.2 * s_exp

        cc = dict(c)
        cc["match_score"] = float(score)
        
        try:
            cc["experience_years"] = float(exp_years)
        except:
            cc["experience_years"] = 0
            
        if "skills_text" not in cc:
            cc["skills_text"] = ", ".join(sorted(cand_skill_set)) if cand_skill_set else ""
        scored.append(cc)

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:top_n]
