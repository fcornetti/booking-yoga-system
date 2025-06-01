#!/usr/bin/env python3
"""
Database Management Script
Like having a toolbox for your workshop database - helps you set up, reset, and inspect your local SQLite database.
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import secrets

# Configuration
LOCAL_DB_PATH = 'yoga_booking_local.db'

def get_db_connection():
    """Get a connection to the local SQLite database"""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def create_tables():
    """Create all necessary tables"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        surname TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_verified INTEGER DEFAULT 0,
        verification_token TEXT DEFAULT NULL,
        token_expiry DATETIME NULL
    )
    """)

    # YogaClasses table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS YogaClasses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        instructor TEXT NOT NULL,
        date_time DATETIME NOT NULL,
        duration INTEGER NOT NULL DEFAULT 75,
        capacity INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        location TEXT NOT NULL
    )
    """)

    # Bookings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        booking_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'active',
        FOREIGN KEY (user_id) REFERENCES Users(id),
        FOREIGN KEY (class_id) REFERENCES YogaClasses(id)
    )
    """)

    conn.commit()
    conn.close()
    print("Tables created successfully!")

def reset_database():
    """Reset the database by deleting the file and recreating tables"""
    if os.path.exists(LOCAL_DB_PATH):
        os.remove(LOCAL_DB_PATH)
        print(f"Deleted existing database: {LOCAL_DB_PATH}")

    create_tables()
    print("Database reset complete!")

def add_sample_data():
    """Add sample data for testing"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Add sample users
    users_data = [
        ('John', 'Doe', 'john@example.com', 'password123'),
        ('Jane', 'Smith', 'jane@example.com', 'password123'),
        ('Admin', 'User', 'admin@jantinevanwijlickyoga.com', 'admin123'),
    ]

    for name, surname, email, password in users_data:
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        verification_token = secrets.token_urlsafe(32)
        token_expiry = datetime.utcnow() + timedelta(hours=24)

        try:
            cursor.execute("""
            INSERT INTO Users (name, surname, email, password_hash, is_verified, verification_token, token_expiry)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (name, surname, email, password_hash, verification_token, token_expiry))
            print(f"Added user: {email} (password: {password})")
        except sqlite3.IntegrityError:
            print(f"User {email} already exists, skipping...")

    # Add sample yoga classes
    future_dates = [
        datetime.now() + timedelta(days=1, hours=10),  # Tomorrow 10 AM
        datetime.now() + timedelta(days=2, hours=18),  # Day after tomorrow 6 PM
        datetime.now() + timedelta(days=7, hours=9),   # Next week 9 AM
        datetime.now() + timedelta(days=14, hours=19), # Two weeks 7 PM
    ]

    classes_data = [
        ('Morning Vinyasa Flow', 'Jantine', future_dates[0], 75, 12, 'Studio A, Main Street 123'),
        ('Evening Yin Yoga', 'Sarah', future_dates[1], 60, 8, 'Studio B, Main Street 123'),
        ('Weekend Power Yoga', 'Mike', future_dates[2], 90, 15, 'Outdoor Pavilion, Park Avenue 45'),
        ('Restorative Yoga', 'Jantine', future_dates[3], 75, 10, 'Studio A, Main Street 123'),
    ]

    for name, instructor, date_time, duration, capacity, location in classes_data:
        cursor.execute("""
        INSERT INTO YogaClasses (name, instructor, date_time, duration, capacity, status, location)
        VALUES (?, ?, ?, ?, ?, 'active', ?)
        """, (name, instructor, date_time, duration, capacity, location))
        print(f"Added class: {name} on {date_time.strftime('%Y-%m-%d %H:%M')}")

    conn.commit()
    conn.close()
    print("Sample data added successfully!")

def show_database_contents():
    """Display all data in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()

    print("\n" + "="*50)
    print("DATABASE CONTENTS")
    print("="*50)

    # Show users
    print("\n👥 USERS:")
    cursor.execute("SELECT id, name, surname, email, is_verified FROM Users")
    users = cursor.fetchall()
    if users:
        for user in users:
            status = "Verified" if user[4] else "Unverified"
            print(f"  {user[0]}: {user[1]} {user[2]} ({user[3]}) - {status}")
    else:
        print("  No users found.")

    # Show yoga classes
    print("\n YOGA CLASSES:")
    cursor.execute("SELECT id, name, instructor, date_time, capacity, status, location FROM YogaClasses")
    classes = cursor.fetchall()
    if classes:
        for cls in classes:
            date_str = datetime.fromisoformat(cls[3]).strftime('%Y-%m-%d %H:%M') if cls[3] else 'Unknown'
            print(f"  {cls[0]}: {cls[1]} with {cls[2]} on {date_str}")
            print(f"      Capacity: {cls[4]}, Status: {cls[5]}, Location: {cls[6]}")
    else:
        print("  No classes found.")

    # Show bookings
    print("\n BOOKINGS:")
    cursor.execute("""
    SELECT b.id, u.name, u.surname, yc.name, b.status, b.booking_date
    FROM Bookings b
    JOIN Users u ON b.user_id = u.id
    JOIN YogaClasses yc ON b.class_id = yc.id
    """)
    bookings = cursor.fetchall()
    if bookings:
        for booking in bookings:
            booking_date = datetime.fromisoformat(booking[5]).strftime('%Y-%m-%d %H:%M') if booking[5] else 'Unknown'
            print(f"  {booking[0]}: {booking[1]} {booking[2]} booked '{booking[3]}' ({booking[4]}) on {booking_date}")
    else:
        print("  No bookings found.")

    conn.close()
    print("\n" + "="*50)

def check_database_exists():
    """Check if the database file exists"""
    if os.path.exists(LOCAL_DB_PATH):
        size = os.path.getsize(LOCAL_DB_PATH)
        print(f" Database exists: {LOCAL_DB_PATH} ({size} bytes)")
        return True
    else:
        print(f" Database does not exist: {LOCAL_DB_PATH}")
        return False

def main():
    """Main function to handle command line arguments"""
    if len(sys.argv) < 2:
        print("Database Management Tool")
        print("Usage: python manage_db.py <command>")
        print("\nAvailable commands:")
        print("  setup       - Create tables (safe to run multiple times)")
        print("  reset       - Delete database and recreate with sample data")
        print("  sample      - Add sample data to existing database")
        print("  show        - Display all database contents")
        print("  check       - Check if database exists")
        print("\nExamples:")
        print("  python manage_db.py setup")
        print("  python manage_db.py reset")
        print("  python manage_db.py show")
        return

    command = sys.argv[1].lower()

    if command == 'setup':
        create_tables()
    elif command == 'reset':
        reset_database()
        add_sample_data()
    elif command == 'sample':
        if check_database_exists():
            add_sample_data()
        else:
            print("Database doesn't exist. Run 'setup' first.")
    elif command == 'show':
        if check_database_exists():
            show_database_contents()
        else:
            print("Database doesn't exist. Run 'setup' first.")
    elif command == 'check':
        check_database_exists()
    else:
        print(f"Unknown command: {command}")
        print("Run without arguments to see available commands.")

if __name__ == '__main__':
    main()