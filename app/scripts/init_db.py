# app/scripts/init_db.py
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("DB initialized. Ensure pgvector extension exists in Postgres (CREATE EXTENSION vector;).")
