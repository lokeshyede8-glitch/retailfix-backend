import os
import psycopg2
from passlib.context import CryptContext
import uuid
import datetime
from dotenv import load_dotenv

load_dotenv()

DB = os.getenv("DATABASE_URL")
if not DB:
    raise ValueError("DATABASE_URL environment variable is required.")
if DB.startswith("postgres://"):
    DB = DB.replace("postgres://", "postgresql://", 1)

conn = psycopg2.connect(DB)
cur = conn.cursor()

# Check schema first
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position")
cols = [r[0] for r in cur.fetchall()]
print("Columns:", cols)

# Hash password
pwd_ctx = CryptContext(schemes=['bcrypt'], deprecated='auto')
hashed = pwd_ctx.hash('factory123')

uid = str(uuid.uuid4())
now = datetime.datetime.now(datetime.timezone.utc)

# Find password column name
pw_col = 'password' if 'password' in cols else 'hashed_password'
print("Password column:", pw_col)

cur.execute(
    f"INSERT INTO users (id, username, {pw_col}, role, employee_id, is_active, must_change_password, email, created_at, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
    (uid, 'factory2', hashed, 'factory', 'FACT-002', True, False, 'factory2@retailfix.com', now, now)
)
conn.commit()

cur.execute("SELECT username, role, employee_id, is_active FROM users WHERE username = 'factory2'")
row = cur.fetchone()
if row:
    print('USER CREATED SUCCESSFULLY')
    print('Username :', row[0])
    print('Password : factory123')
    print('Role     :', row[1])
    print('Emp ID   :', row[2])
else:
    print('ERROR: User not created')

cur.close()
conn.close()
