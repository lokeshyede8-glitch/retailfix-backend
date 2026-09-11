import os
import json
import uuid
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw, ImageFont
import models

# ─── MOCK IMAGE GENERATORS ────────────────────────────────────────────────────

def generate_mock_logo(path: str):
    """Draw a clean, modern corporate text logo with transparent background."""
    img = Image.new("RGBA", (400, 100), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw simple logo shapes
    draw.rounded_rectangle([10, 15, 80, 85], radius=15, fill=(220, 38, 38, 255))
    draw.rectangle([35, 45, 55, 55], fill=(255, 255, 255, 255))
    draw.rectangle([45, 35, 55, 65], fill=(255, 255, 255, 255))
    
    # Use default font
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    draw.text((100, 25), "RetailFix", fill=(17, 24, 39, 255), font_size=36)
    draw.text((100, 65), "STORE FIXTURES & SOLUTIONS", fill=(107, 114, 128, 255), font_size=10)
    
    img.save(path, "PNG")


def generate_mock_qr(path: str, color=(0, 0, 0, 255)):
    """Generate a realistic mock QR code."""
    img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # Outer boxes (finders)
    draw.rectangle([20, 20, 70, 70], outline=color, width=8)
    draw.rectangle([35, 35, 55, 55], fill=color)
    
    draw.rectangle([130, 20, 180, 70], outline=color, width=8)
    draw.rectangle([145, 145, 165, 165], fill=color) # alignment marker
    
    draw.rectangle([20, 130, 70, 180], outline=color, width=8)
    draw.rectangle([35, 145, 55, 165], fill=color)
    
    # Draw random QR noise/blocks
    import random
    random.seed(path) # consistent generation
    for y in range(80, 120, 10):
        for x in range(20, 180, 10):
            if random.choice([True, False]):
                draw.rectangle([x, y, x+8, y+8], fill=color)
    for y in range(20, 80, 10):
        for x in range(80, 120, 10):
            if random.choice([True, False]):
                draw.rectangle([x, y, x+8, y+8], fill=color)
    for y in range(120, 180, 10):
        for x in range(80, 180, 10):
            if random.choice([True, False]):
                draw.rectangle([x, y, x+8, y+8], fill=color)
                
    img.save(path, "PNG")


def generate_mock_auth_image(path: str):
    """Draw a company seal overlapping with an elegant signature, transparent background."""
    img = Image.new("RGBA", (300, 150), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. Draw Company Seal (Circular stamp in dark red/magenta, slightly rotated or offset)
    seal_color = (185, 28, 28, 200) # Semi-transparent red
    draw.ellipse([30, 10, 150, 130], outline=seal_color, width=4)
    draw.ellipse([38, 18, 142, 122], outline=seal_color, width=1)
    
    draw.text((60, 45), "RETAILFIX", fill=seal_color, font_size=12)
    draw.text((58, 65), "PVT. LTD.", fill=seal_color, font_size=12)
    draw.text((54, 85), "* BHOPAL *", fill=seal_color, font_size=10)
    
    # 2. Draw signature overlap (Blue ink brush strokes)
    sig_color = (29, 78, 216, 255) # Dark Blue signature ink
    points = [
        (80, 95), (100, 75), (120, 60), (135, 80), (145, 90),
        (160, 50), (170, 45), (180, 65), (195, 85), (210, 95),
        (225, 90), (245, 88), (270, 92)
    ]
    draw.line(points, fill=sig_color, width=3, joint="curve")
    # Draw loops
    draw.ellipse([148, 48, 168, 80], outline=sig_color, width=2)
    
    img.save(path, "PNG")


def generate_mock_company_seal(path: str):
    """Draw only the circular stamp company seal on transparent background."""
    img = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    seal_color = (185, 28, 28, 200) # Semi-transparent red
    draw.ellipse([20, 20, 180, 180], outline=seal_color, width=5)
    draw.ellipse([30, 30, 170, 170], outline=seal_color, width=2)
    
    draw.text((55, 65), "RETAILFIX", fill=seal_color, font_size=14)
    draw.text((58, 90), "PVT. LTD.", fill=seal_color, font_size=14)
    draw.text((55, 115), "* BHOPAL *", fill=seal_color, font_size=12)
    img.save(path, "PNG")


def generate_mock_auth_signature(path: str):
    """Draw only the blue ink signature on transparent background."""
    img = Image.new("RGBA", (300, 150), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    sig_color = (29, 78, 216, 255) # Dark Blue signature ink
    points = [
        (30, 95), (60, 75), (90, 60), (115, 80), (135, 95),
        (160, 50), (180, 45), (195, 65), (215, 85), (235, 95),
        (255, 90), (275, 88), (290, 92)
    ]
    draw.line(points, fill=sig_color, width=4, joint="curve")
    draw.ellipse([148, 48, 178, 80], outline=sig_color, width=3)
    img.save(path, "PNG")



# ─── DATABASE SEEDER ──────────────────────────────────────────────────────────

def seed_database(db: Session):
    """Ensure upload files exist and seed settings into PostgreSQL."""
    # 1. Ensure uploads folder exists
    upload_dir = os.path.abspath("uploads")
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    # 2. Generate assets if missing
    logo_path = os.path.join(upload_dir, "logo_retailfix.png")
    payment_qr_path = os.path.join(upload_dir, "payment_qr.png")
    auth_image_path = os.path.join(upload_dir, "auth_image.png")
    
    if not os.path.exists(logo_path):
        try:
            generate_mock_logo(logo_path)
        except Exception as e:
            print(f"Error seeding logo image: {e}")
    if not os.path.exists(payment_qr_path):
        try:
            generate_mock_qr(payment_qr_path, color=(220, 38, 38, 255)) # red/primary QR
        except Exception as e:
            print(f"Error seeding payment QR image: {e}")
    if not os.path.exists(auth_image_path):
        try:
            generate_mock_auth_image(auth_image_path)
        except Exception as e:
            print(f"Error seeding auth image: {e}")
            
    company_seal_path = os.path.join(upload_dir, "company_seal.png")
    auth_signature_path = os.path.join(upload_dir, "auth_signature.png")
    if not os.path.exists(company_seal_path):
        try:
            generate_mock_company_seal(company_seal_path)
        except Exception as e:
            print(f"Error seeding company seal: {e}")
            
    if not os.path.exists(auth_signature_path):
        try:
            generate_mock_auth_signature(auth_signature_path)
        except Exception as e:
            print(f"Error seeding auth signature: {e}")
        
    socials = [
        ("whatsapp", "WhatsApp", (34, 197, 94, 255)),     # green
        ("instagram", "Instagram", (219, 39, 119, 255)),  # gradient/pink
        ("facebook", "Facebook", (59, 130, 246, 255)),    # blue
        ("youtube", "YouTube", (239, 68, 68, 255)),       # red
        ("linkedin", "LinkedIn", (29, 78, 216, 255)),     # dark blue
        ("website", "Website", (220, 38, 38, 255))        # primary red
    ]
    
    for filename, name, col in socials:
        path = os.path.join(upload_dir, f"qr_{filename}.png")
        if not os.path.exists(path):
            try:
                generate_mock_qr(path, color=col)
            except Exception as e:
                print(f"Error seeding social QR {filename}: {e}")
            
    # 3. Seed AppSettings key-value settings
    company_profile = {
        "name": "RetailFix",
        "tagline": "Store Fixtures & Display Solutions",
        "address": "Plot No. 63, Govindpura Industrial Area, Bhopal, Madhya Pradesh, 462023, India",
        "phone": "+91-92019 58481, 92019 58486",
        "email": "info@retailfix.in",
        "web": "retailfix.in",
        "gstin": "23AAAAA0000A1Z0",
        "bankName": "HDFC Bank",
        "accountHolder": "RetailFix",
        "accountNumber": "50200012345678",
        "ifscCode": "HDFC0001234",
        "branch": "Govindpura, Bhopal",
        "logo_url": "/uploads/logo_retailfix.png"
    }
    
    doc_settings = {
        "validityDays": 15,
        "footerNote": "Thank you for choosing RetailFix. We look forward to doing business with you.",
        "advancePercent": 50,
        "fullPaymentDiscount": 5,
        "page2_enabled": True,
        "page3_enabled": True,
        "payment_qr": "/uploads/payment_qr.png",
        "auth_image": "/uploads/auth_image.png",
        "company_seal": "/uploads/company_seal.png",
        "auth_signature": "/uploads/auth_signature.png"
    }
    
    # Upsert Profile
    profile_row = db.query(models.AppSettings).filter(models.AppSettings.key == "company_profile").first()
    if not profile_row:
        db.add(models.AppSettings(key="company_profile", value=json.dumps(company_profile)))
        
    # Upsert Doc Settings
    doc_row = db.query(models.AppSettings).filter(models.AppSettings.key == "doc_settings").first()
    if not doc_row:
        db.add(models.AppSettings(key="doc_settings", value=json.dumps(doc_settings)))
        
    # 4. Seed Terms
    if db.query(models.QuotationTerm).count() == 0:
        default_terms = [
            "Prices are factory rates — no middlemen, no hidden costs.",
            "50% advance payment required to confirm order; balance before/at delivery.",
            "Delivery: 7–15 working days from order confirmation, depending on quantity & customization.",
            "GST as applicable will be charged extra unless already included above.",
            "Installation support available on request.",
            "Quotation valid for 15 days from the date of issue."
        ]
        for i, text in enumerate(default_terms):
            db.add(models.QuotationTerm(id=str(uuid.uuid4()), text=text, display_order=i+1, is_enabled=True))
            
    # 5. Seed Materials
    if db.query(models.QuotationMaterial).count() == 0:
        default_materials = [
            "Mild Steel sheets (18-20 gauge) for heavy loading capacity racks.",
            "Premium epoxy powder coating (80-100 microns) for anti-scratch properties.",
            "Precision CNC laser cut bends and CO2 robotic welding joints.",
            "Heavy-duty adjustable plastic/metal levelers to support uneven floors."
        ]
        for i, text in enumerate(default_materials):
            db.add(models.QuotationMaterial(id=str(uuid.uuid4()), text=text, display_order=i+1, is_enabled=True))
            
    # 6. Seed Banks
    if db.query(models.QuotationBank).count() == 0:
        db.add(models.QuotationBank(
            id=str(uuid.uuid4()),
            bank_name="HDFC Bank",
            account_holder="RetailFix",
            account_number="50200012345678",
            ifsc_code="HDFC0001234",
            branch="Govindpura, Bhopal",
            display_order=1,
            is_enabled=True
        ))
        
    # 7. Seed Socials
    if db.query(models.QuotationSocial).count() == 0:
        default_socials = [
            ("WhatsApp", "whatsapp", "/uploads/qr_whatsapp.png", "Scan to Chat", 1),
            ("Instagram", "instagram", "/uploads/qr_instagram.png", "Follow Us", 2),
            ("Facebook", "facebook", "/uploads/qr_facebook.png", "Like Page", 3),
            ("YouTube", "youtube", "/uploads/qr_youtube.png", "Watch Videos", 4),
            ("LinkedIn", "linkedin", "/uploads/qr_linkedin.png", "Connect", 5),
            ("Website", "globe", "/uploads/qr_website.png", "Visit Website", 6)
        ]
        for platform, icon, qr, cta, order in default_socials:
            db.add(models.QuotationSocial(
                id=str(uuid.uuid4()),
                platform=platform,
                icon=icon,
                qr_code_url=qr,
                cta_text=cta,
                display_order=order,
                is_enabled=True
            ))
            
    # 8. Seed Why Choose
    if db.query(models.QuotationWhyChoose).count() == 0:
        reasons = [
            "Premium Quality",
            "Professional Team",
            "Fast Installation",
            "Affordable Pricing",
            "PAN India Support",
            "Modern Store Design"
        ]
        for i, text in enumerate(reasons):
            db.add(models.QuotationWhyChoose(id=str(uuid.uuid4()), text=text, display_order=i+1, is_enabled=True))
            
    # 9. Seed Services
    if db.query(models.QuotationService).count() == 0:
        services = [
            "Store Planning",
            "Interior Design",
            "Display Racks",
            "Billing Counter",
            "Branding",
            "Installation",
            "3D Layout",
            "Store Renovation"
        ]
        for i, text in enumerate(services):
            db.add(models.QuotationService(id=str(uuid.uuid4()), name=text, display_order=i+1, is_enabled=True))
            
    # 10. Seed Footers
    if db.query(models.QuotationFooter).count() == 0:
        footers = [
            "THANK YOU FOR YOUR BUSINESS",
            "All disputes are subject to Bhopal jurisdiction only."
        ]
        for i, text in enumerate(footers):
            db.add(models.QuotationFooter(id=str(uuid.uuid4()), text=text, display_order=i+1, is_enabled=True))

    # 11. Seed Raw Materials
    from routers.factory import ensure_default_raw_materials
    ensure_default_raw_materials(db)

    # 12. Seed default Factory user if missing
    factory_user = db.query(models.User).filter(models.User.role == "factory").first()
    if not factory_user:
        import time
        from auth_utils import hash_password
        now_ms = int(time.time() * 1000)
        db.add(models.User(
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
        ))

    db.commit()
    print("Database seeding completed successfully.")
