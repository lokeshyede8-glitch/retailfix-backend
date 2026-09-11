from database import SessionLocal
import models
from auth_utils import hash_password
db = SessionLocal()
pwd = hash_password("password123")
for username in ["lokesh_yede", "lokesh_yede_d4bf", "retailfix"]:
    u = db.query(models.User).filter(models.User.username == username).first()
    if u:
        u.password_hash = pwd
        u.locked_until = 0
        u.failed_login_attempts = 0
        db.commit()
print("Passwords reset to password123")
