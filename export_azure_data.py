"""
STEP 1: Export data from Azure SQL Database
Run this script to backup all your production data before migration
"""
import pyodbc
import json
from datetime import datetime
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def export_azure_data():
    """Export all data from Azure SQL Server to JSON files"""
    
    # Connect to Azure SQL Server
    conn_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USERNAME')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    
    print("🔌 Connecting to Azure SQL Server...")
    print(f"   Server: {os.getenv('DB_SERVER')}")
    print(f"   Database: {os.getenv('DB_NAME')}")
    
    try:
        conn = pyodbc.connect(conn_string)
        cursor = conn.cursor()
        print("✅ Connected successfully!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\nPlease check your .env file has:")
        print("  DB_SERVER=your-server.database.windows.net")
        print("  DB_NAME=your-database-name")
        print("  DB_USERNAME=your-username")
        print("  DB_PASSWORD=your-password")
        return None
    
    # Create export directory
    export_dir = "azure_export_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(export_dir, exist_ok=True)
    print(f"\n📁 Exporting data to {export_dir}/")
    print("="*60)
    
    # Export Users
    print("\n👥 Exporting Users...")
    cursor.execute("SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry FROM Users")
    users = []
    for row in cursor.fetchall():
        users.append({
            'id': row[0],
            'name': row[1],
            'surname': row[2],
            'email': row[3],
            'password_hash': row[4],
            'is_verified': row[5],
            'verification_token': row[6],
            'token_expiry': row[7].isoformat() if row[7] else None
        })
    
    with open(f"{export_dir}/users.json", 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Exported {len(users)} users")
    
    # Export YogaClasses
    print("\n🧘 Exporting Yoga Classes...")
    cursor.execute("SELECT id, name, instructor, date_time, duration, capacity, status, location FROM YogaClasses")
    classes = []
    for row in cursor.fetchall():
        classes.append({
            'id': row[0],
            'name': row[1],
            'instructor': row[2],
            'date_time': row[3].isoformat() if row[3] else None,
            'duration': row[4],
            'capacity': row[5],
            'status': row[6],
            'location': row[7]
        })
    
    with open(f"{export_dir}/yoga_classes.json", 'w', encoding='utf-8') as f:
        json.dump(classes, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Exported {len(classes)} yoga classes")
    
    # Export Bookings
    print("\n📅 Exporting Bookings...")
    cursor.execute("SELECT id, user_id, class_id, booking_date, status FROM Bookings")
    bookings = []
    for row in cursor.fetchall():
        bookings.append({
            'id': row[0],
            'user_id': row[1],
            'class_id': row[2],
            'booking_date': row[3].isoformat() if row[3] else None,
            'status': row[4]
        })
    
    with open(f"{export_dir}/bookings.json", 'w', encoding='utf-8') as f:
        json.dump(bookings, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Exported {len(bookings)} bookings")
    
    # Create summary
    summary = {
        'export_date': datetime.now().isoformat(),
        'source': 'Azure SQL Server',
        'database': os.getenv('DB_NAME'),
        'server': os.getenv('DB_SERVER'),
        'counts': {
            'users': len(users),
            'yoga_classes': len(classes),
            'bookings': len(bookings)
        }
    }
    
    with open(f"{export_dir}/export_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    conn.close()
    
    print("\n" + "="*60)
    print("✅ EXPORT COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"\n📁 All data saved to: {export_dir}/")
    print(f"   - users.json ({len(users)} records)")
    print(f"   - yoga_classes.json ({len(classes)} records)")
    print(f"   - bookings.json ({len(bookings)} records)")
    print(f"   - export_summary.json")
    print("\n⚠️  IMPORTANT: Keep these files safe! They contain:")
    print("   - User emails and password hashes")
    print("   - All yoga classes and bookings")
    print("\n📌 Next Step: Run 'python import_to_render.py'")
    print("="*60)
    
    return export_dir

if __name__ == "__main__":
    print("="*60)
    print("🚀 AZURE TO RENDER MIGRATION - STEP 1: EXPORT DATA")
    print("="*60)
    
    try:
        export_dir = export_azure_data()
        if export_dir:
            print(f"\n✅ Success! Data exported to {export_dir}/")
    except Exception as e:
        print(f"\n❌ Error exporting data: {e}")
        print("\nTroubleshooting:")
        print("1. Check your .env file has correct Azure credentials")
        print("2. Make sure you can connect to Azure SQL Database")
        print("3. Verify your firewall allows connections from your IP")

