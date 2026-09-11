import os
from sqlalchemy import text
from database import engine

def migrate():
    with engine.connect() as conn:
        try:
            print("Adding manufacturing_materials_json to products table...")
            conn.execute(text("ALTER TABLE products ADD COLUMN manufacturing_materials_json TEXT DEFAULT '[]';"))
            print("Added manufacturing_materials_json successfully.")
        except Exception as e:
            print(f"Column might already exist: {e}")
        
        try:
            print("Adding material_description to production_material_requirements table...")
            conn.execute(text("ALTER TABLE production_material_requirements ADD COLUMN material_description TEXT DEFAULT '';"))
            print("Added material_description successfully.")
        except Exception as e:
            print(f"Column might already exist: {e}")
            
        try:
            print("Altering material_id to be nullable in production_material_requirements table...")
            conn.execute(text("ALTER TABLE production_material_requirements ALTER COLUMN material_id DROP NOT NULL;"))
            print("Altered material_id successfully.")
        except Exception as e:
            print(f"Alter might have failed: {e}")
            
        conn.commit()

if __name__ == "__main__":
    migrate()
