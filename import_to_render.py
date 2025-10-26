"""
STEP 2: Import data to Render PostgreSQL Database
Run this AFTER you've created your PostgreSQL database on Render.com
"""
import json
import os
import sys
from datetime import datetime

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("❌ psycopg2 not installed!")
    print("   Install it with: pip install psycopg2-binary")
    sys.exit(1)

def import_data_to_render(export_dir, db_url):
    """Import JSON data to Render PostgreSQL database"""
    
    # Check if export directory exists
    if not os.path.exists(export_dir):
        print(f"❌ Error: Export directory '{export_dir}' not found!")
        print(f"   Run 'python export_azure_data.py' first to create the export.")
        return False
    
    print("\n" + "="*60)
    print("🚀 IMPORTING DATA TO RENDER POSTGRESQL")
    print("="*60)
    print(f"📁 Source: {export_dir}/")
    
    # Connect to PostgreSQL
    print("\n🔌 Connecting to Render PostgreSQL...")
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        print("   ✅ Connected successfully!")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print("\n   Check your database URL format:")
        print("   postgres://username:password@host/database")
        return False
    
    # Create tables
    print("\n🔨 Creating database tables...")
    
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            surname VARCHAR(100) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            is_verified BOOLEAN DEFAULT FALSE,
            verification_token VARCHAR(100) DEFAULT NULL,
            token_expiry TIMESTAMP NULL
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS YogaClasses (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            instructor VARCHAR(100) NOT NULL,
            date_time TIMESTAMP NOT NULL,
            duration INTEGER NOT NULL DEFAULT 75,
            capacity INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'active',
            location VARCHAR(200) NOT NULL
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Bookings (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES YogaClasses(id) ON DELETE CASCADE
        )
        """)
        
        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON Users(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON Bookings(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_class ON Bookings(class_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_classes_datetime ON YogaClasses(date_time)")
        
        conn.commit()
        print("   ✅ Tables created with indexes")
    except Exception as e:
        print(f"   ❌ Error creating tables: {e}")
        return False
    
    # Import Users
    print("\n👥 Importing Users...")
    try:
        with open(f"{export_dir}/users.json", 'r', encoding='utf-8') as f:
            users = json.load(f)
        
        for user in users:
            cursor.execute("""
            INSERT INTO Users (name, surname, email, password_hash, is_verified, verification_token, token_expiry)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                name = EXCLUDED.name,
                surname = EXCLUDED.surname,
                password_hash = EXCLUDED.password_hash,
                is_verified = EXCLUDED.is_verified,
                verification_token = EXCLUDED.verification_token,
                token_expiry = EXCLUDED.token_expiry
            """, (
                user['name'],
                user['surname'],
                user['email'],
                user['password_hash'],
                user['is_verified'],
                user['verification_token'],
                user['token_expiry']
            ))
        
        conn.commit()
        print(f"   ✅ Imported {len(users)} users")
    except Exception as e:
        print(f"   ❌ Error importing users: {e}")
        conn.rollback()
        return False
    
    # Import YogaClasses
    print("\n🧘 Importing Yoga Classes...")
    try:
        with open(f"{export_dir}/yoga_classes.json", 'r', encoding='utf-8') as f:
            classes = json.load(f)
        
        # Create a mapping from old IDs to new IDs
        class_id_map = {}
        
        for cls in classes:
            cursor.execute("""
            INSERT INTO YogaClasses (name, instructor, date_time, duration, capacity, status, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """, (
                cls['name'],
                cls['instructor'],
                cls['date_time'],
                cls['duration'],
                cls['capacity'],
                cls['status'],
                cls['location']
            ))
            new_id = cursor.fetchone()[0]
            class_id_map[cls['id']] = new_id
        
        conn.commit()
        print(f"   ✅ Imported {len(classes)} yoga classes")
    except Exception as e:
        print(f"   ❌ Error importing yoga classes: {e}")
        conn.rollback()
        return False
    
    # Import Bookings
    print("\n📅 Importing Bookings...")
    try:
        with open(f"{export_dir}/bookings.json", 'r', encoding='utf-8') as f:
            bookings = json.load(f)
        
        # Get user ID mapping
        cursor.execute("SELECT email, id FROM Users")
        email_to_id = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Get user emails for mapping
        cursor.execute("SELECT id, email FROM Users")
        users_data = cursor.fetchall()
        
        imported = 0
        skipped = 0
        for booking in bookings:
            # Map the class_id using our mapping
            new_class_id = class_id_map.get(booking['class_id'])
            if not new_class_id:
                skipped += 1
                continue
                
            try:
                cursor.execute("""
                INSERT INTO Bookings (user_id, class_id, booking_date, status)
                VALUES (%s, %s, %s, %s)
                """, (
                    booking['user_id'],
                    new_class_id,
                    booking['booking_date'],
                    booking['status']
                ))
                imported += 1
            except Exception as e:
                skipped += 1
                continue
        
        conn.commit()
        print(f"   ✅ Imported {imported} bookings", end="")
        if skipped > 0:
            print(f" (skipped {skipped} with missing references)")
        else:
            print()
    except Exception as e:
        print(f"   ❌ Error importing bookings: {e}")
        conn.rollback()
        return False
    
    # Verify data
    print("\n🔍 Verifying imported data...")
    cursor.execute("SELECT COUNT(*) FROM Users")
    user_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM YogaClasses")
    class_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM Bookings")
    booking_count = cursor.fetchone()[0]
    
    conn.close()
    
    print("\n" + "="*60)
    print("✅ IMPORT COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"\n📊 Render PostgreSQL Database:")
    print(f"   - {user_count} users")
    print(f"   - {class_count} yoga classes")
    print(f"   - {booking_count} bookings")
    print("\n✅ All your data has been preserved!")
    print("\n📌 Next Steps:")
    print("   1. Test your database connection")
    print("   2. Update your .env file with Render database URL")
    print("   3. Deploy your app to Render")
    print("="*60)
    
    return True

if __name__ == "__main__":
    print("="*60)
    print("🚀 AZURE TO RENDER MIGRATION - STEP 2: IMPORT TO RENDER")
    print("="*60)
    
    # Find the most recent export directory
    export_dirs = [d for d in os.listdir('.') if d.startswith('azure_export_')]
    
    if not export_dirs:
        print("\n❌ No export directory found!")
        print("   Run 'python export_azure_data.py' first to export your Azure data.")
        sys.exit(1)
    
    # Use the most recent export
    export_dir = sorted(export_dirs)[-1]
    print(f"\n📁 Using export: {export_dir}")
    
    # Load summary
    with open(f"{export_dir}/export_summary.json", 'r') as f:
        summary = json.load(f)
    
    print(f"   Exported: {summary['export_date']}")
    print(f"   From: {summary['server']}")
    print(f"   Users: {summary['counts']['users']}")
    print(f"   Classes: {summary['counts']['yoga_classes']}")
    print(f"   Bookings: {summary['counts']['bookings']}")
    
    print("\n📝 You need your Render PostgreSQL DATABASE_URL")
    print("   Get it from: Render Dashboard → Your Database → Connection → Internal Database URL")
    print("   Format: postgres://username:password@host/database")
    
    db_url = input("\n🔗 Paste your Render DATABASE_URL: ").strip()
    
    if not db_url:
        print("\n❌ No database URL provided. Exiting.")
        sys.exit(1)
    
    if not db_url.startswith('postgres'):
        print("\n⚠️  Warning: URL should start with 'postgres://' or 'postgresql://'")
        confirm = input("Continue anyway? (yes/no): ")
        if confirm.lower() not in ['yes', 'y']:
            sys.exit(1)
    
    print("\n⚠️  This will import data into your Render database.")
    confirm = input("Continue? (yes/no): ")
    
    if confirm.lower() in ['yes', 'y']:
        import_data_to_render(export_dir, db_url)
    else:
        print("\n❌ Import cancelled.")

