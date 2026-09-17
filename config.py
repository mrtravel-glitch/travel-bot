import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

# Neon (yoki boshqa Postgres) ulanish satri, masalan:
# postgresql://user:password@host/dbname?sslmode=require
DATABASE_URL = os.environ.get("DATABASE_URL", "")
