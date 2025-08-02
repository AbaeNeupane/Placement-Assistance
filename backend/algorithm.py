import numpy as np
import pandas as pd
import re
import os
from sklearn.feature_extraction.text import TfidfVectorizer

# This function tokenizes the input text by removing punctuation, converting to lowercase, and splitting into words.
def custom_tokenizer(text):
   #Check if text is None or empty
    text = re.sub(r"[^\w\s]", "", text.lower())
    #yesle chai agi paxi ko space haru lai remove garne
    tokens = text.split()
    
    #yesle chai tokens ma alphabetic characters matra rakhne
    tokens = [t for t in tokens if t.isalpha()]
    return tokens

# This function cleans the experience string to extract the minimum and maximum years of experience.
def clean_experience(experience):
    numbers = re.findall(r"\d+", str(experience))
    return [int(numbers[0]), int(numbers[-1])] if numbers else [0, 0]

# This function calculates the similarity score based on the candidate's experience and the job's experience range.
def experience_similarity(candidate_exp, job_exp_range):
    if candidate_exp < job_exp_range[0]:
        return max(0, 1 - (job_exp_range[0] - candidate_exp) / (job_exp_range[0] + 1e-5))
    elif candidate_exp > job_exp_range[1]:
        return max(0, 1 - (candidate_exp - job_exp_range[1]) / (candidate_exp + 1e-5))
    else:
        return 1

# This function computes the cosine similarity between two matrices.
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

# Load the job data and preprocess the experience range
data = pd.read_csv(os.path.join(os.path.dirname(__file__), "jobs_info.csv"))

data["Experience Range"] = data["Job Experience"].apply(clean_experience)

# Create TF-IDF vectorizers for skills and job titles
skills_vectorizer = TfidfVectorizer(tokenizer=custom_tokenizer, ngram_range=(1, 2))
title_vectorizer = TfidfVectorizer(tokenizer=custom_tokenizer, ngram_range=(1, 2))

tfidf_skills = skills_vectorizer.fit_transform(data["Key Skills"])
tfidf_titles = title_vectorizer.fit_transform(data["Job Title"])

# This function recommends jobs based on the candidate's skills, job title, and experience.
def recommend_jobs(query_skills, query_title, query_experience):
    query_skills_vec = skills_vectorizer.transform([query_skills])
    query_title_vec = title_vectorizer.transform([query_title])

    skills_similarity = cosine_similarity_manual(query_skills_vec, tfidf_skills).flatten()
    title_similarity = cosine_similarity_manual(query_title_vec, tfidf_titles).flatten()

    if skills_similarity.max() > 0:
        skills_similarity = (skills_similarity - skills_similarity.min()) / (skills_similarity.max() - skills_similarity.min() + 1e-5)
    if title_similarity.max() > 0:
        title_similarity = (title_similarity - title_similarity.min()) / (title_similarity.max() - title_similarity.min() + 1e-5)

    combined_similarity = (skills_similarity + title_similarity) / 2
    experience_scores = np.array([experience_similarity(query_experience, r) for r in data["Experience Range"]])
    final_scores = combined_similarity * experience_scores

    indices = np.argsort(-final_scores)[:10]
    if len(indices) == 0 or final_scores[indices[0]] == 0:
        return []

# This function returns the recommended jobs with their scores.
    results = data.iloc[indices].copy()
    results["Skill Score"] = skills_similarity[indices]
    results["Title Score"] = title_similarity[indices]
    results["Experience Score"] = experience_scores[indices]
    results["Final Score"] = final_scores[indices]

    return results.sort_values(by="Final Score", ascending=False).to_dict(orient='records')
