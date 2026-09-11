import sys
import os
import getpass
import uuid
import time
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
import models
from auth_utils import hash_password

def setup_admin():
    print("==================================================")
    print("      PRODUCTION ADMINISTRATOR SETUP              ")
    print("==================================================")
    
    email = input("Enter production admin email (e.g., admin@retailfix.com): ").strip()
    if not email:
        print("Error: Email cannot be empty.")
        return

    password = getpass.getpass("Enter strong initial password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if not password or password != confirm_password:
        print("Error: Passwords do not match or are empty.")
        return
        
    if len(password) < 8:
        print("Error: Password must be at least 8 characters.")
        return

    db = SessionLocal()
    try:
        # Check if user already exists
        existing = db.query(models.User).filter(models.User.email == email).first()
        if existing:
            print(f"Error: A user with email {email} already exists.")
            return

        now_ms = int(time.time() * 1000)
        user_id = str(uuid.uuid4())
        
        # We need an employee_id for the admin (usually optional, but let's give one)
        employee_id = f"EMP-ADMIN-{int(time.time())}"
        
        hashed = hash_password(password)
        
        # Create user in Unified Users table
        new_user = models.User(
            id=user_id,
            employee_id=employee_id,
            username=email.split("@")[0],  # default username from email
            email=email,
            password_hash=hashed,
            role="admin",
            is_active=True,
            must_change_password=True, # Force change on first login
            created_at=now_ms,
            updated_at=now_ms
        )
        db.add(new_user)
        
        # Create record in Admins table (legacy support)
        new_admin = models.Admin(
            id=user_id,
            username=email.split("@")[0],
            password_hash=hashed,
            email=email
        )
        db.add(new_admin)

        db.commit()
        print("\nSUCCESS: Production Administrator created successfully.")
        print("Note: The user will be required to change this password upon first login.")
    except Exception as e:
        print(f"An error occurred: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    setup_admin()
