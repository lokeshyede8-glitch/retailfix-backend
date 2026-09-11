"""
One-time script to reset the factory user's password to 'factory123' in the live database.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, Base, engine
import models
from auth_utils import hash_password, verify_password
import time

def reset_factory_password():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        now_ms = int(time.time() * 1000)
        factory_user = db.query(models.User).filter(models.User.role == "factory").first()

        if not factory_user:
            # Create factory user if missing
            import uuid
            factory_user = models.User(
                id=str(uuid.uuid4()),
                employee_id="EMP-FACT-001",
                username="factory",
                email="factory@retailfix.com",
                mobile="9876500001",
                password_hash=hash_password("factory123"),
                role="factory",
                is_active=True,
                must_change_password=False,
                created_at=now_ms,
                updated_at=now_ms
            )
            db.add(factory_user)
            db.commit()
            print("Factory user CREATED with password: factory123")
        else:
            # Update the password hash
            new_hash = hash_password("factory123")
            factory_user.password_hash = new_hash
            factory_user.is_active = True
            factory_user.failed_login_attempts = 0
            factory_user.locked_until = 0
            factory_user.updated_at = now_ms
            db.commit()
            print("Factory user password UPDATED successfully.")
            print("  Email   :", factory_user.email)
            print("  Role    :", factory_user.role)
            print("  Active  :", factory_user.is_active)

        # Verify the fix
        db.refresh(factory_user)
        ok = verify_password("factory123", factory_user.password_hash)
        print("  Verify  :", "PASS" if ok else "FAIL")
        if ok:
            print("\n[OK] factory@retailfix.com can now login with password: factory123")
        else:
            print("\n[ERROR] Still failing - bcrypt issue")

    finally:
        db.close()

if __name__ == "__main__":
    reset_factory_password()
