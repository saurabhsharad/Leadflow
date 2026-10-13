import os

# app.main loads settings at import time; give tests a harmless default so they
# do not depend on a developer's .env. Nothing listens on port 1.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:1/test")
