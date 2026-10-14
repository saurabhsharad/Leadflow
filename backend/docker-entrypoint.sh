#!/bin/sh
# Start-up for the LeadFlow API container (production image):
#   1. apply database migrations (nothing to do when already at the latest revision);
#   2. insert demo data, only if SEED_DEMO_DATA=true and both tables are empty.
#      This is the insert-only --auto mode: it never resets or changes existing rows;
#   3. replace this shell with the container command (Uvicorn by default).
# Any failure stops the container rather than serving an unmigrated API.
# Nothing here prints DATABASE_URL.
set -eu

echo "entrypoint: applying database migrations"
alembic upgrade head

python -m scripts.seed --auto

exec "$@"
