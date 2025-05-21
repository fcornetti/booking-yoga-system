import re
from flask import Flask, request, jsonify, Response, redirect, url_for, render_template_string, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os.path
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pyodbc
from datetime import datetime, timedelta
import contextlib
from typing import Optional, List, Dict, Any, Union
from dotenv import load_dotenv
import time
import threading
import queue

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv('CORS_SECRET_KEY')
app.config['VERIFICATION_TOKEN_EXPIRY'] = 24  # Hours
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Configure session handling
@app.before_request
def before_request():
    session.modified = True

# Database configuration
DB_CONFIG = {
    'server': os.getenv('DB_SERVER'),
    'database': os.getenv('DB_NAME'),
    'username': os.getenv('DB_USERNAME'),
    'password': os.getenv('DB_PASSWORD'),
    'driver': '{ODBC Driver 18 for SQL Server}',
    'conn_string': None
}

# Set up connection string
connection_timeout = os.getenv('DB_CONNECTION_TIMEOUT')

DB_CONFIG['conn_string'] = (
    f"DRIVER={DB_CONFIG['driver']};"
    f"SERVER={DB_CONFIG['server']};"
    f"DATABASE={DB_CONFIG['database']};"
    f"UID={DB_CONFIG['username']};"
    f"PWD={DB_CONFIG['password']};"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
    f"connection timeout={connection_timeout};"
)

# Improved connection pool implementation
class ConnectionPool:
    def __init__(self, conn_string, max_pool_size=5, min_pool_size=2):
        self.conn_string = conn_string
        self.max_pool_size = max_pool_size
        self.min_pool_size = min_pool_size
        self._pool = queue.Queue(maxsize=max_pool_size)
        self._lock = threading.Lock()
        self._created_connections = 0
        self._closed = False

        # Initialize minimum connections
        self._initialize_pool()

    def _initialize_pool(self):
        """Initialize the pool with minimum connections"""
        for _ in range(self.min_pool_size):
            try:
                conn = self._create_connection()
                self._pool.put(conn)
            except Exception as e:
                print(f"Failed to initialize pool connection: {e}")
                break

    def _create_connection(self):
        """Create a new database connection"""
        with self._lock:
            if self._created_connections >= self.max_pool_size:
                raise Exception("Maximum connection limit reached")

            conn = pyodbc.connect(self.conn_string, autocommit=False)
            self._created_connections += 1
            return conn

    def _is_connection_valid(self, conn):
        """Check if a connection is still valid"""
        try:
            # Simple test query
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except:
            return False

    def get_connection(self):
        """Get a connection from the pool"""
        if self._closed:
            raise Exception("Connection pool is closed")

        # Try to get a connection from the pool
        try:
            # Try to get a connection with a short timeout
            conn = self._pool.get(timeout=1)

            # Validate the connection
            if self._is_connection_valid(conn):
                return conn
            else:
                # Connection is invalid, create a new one
                self._created_connections -= 1  # Decrement count for the invalid connection
                return self._create_connection()

        except queue.Empty:
            # No connections available, create a new one if under limit
            return self._create_connection()

    def release_connection(self, conn):
        """Return a connection to the pool"""
        if self._closed or not conn:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return

        # Rollback any uncommitted transactions
        try:
            conn.rollback()
        except:
            pass

        # Validate connection before returning to pool
        if self._is_connection_valid(conn):
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                # Pool is full, close this connection
                try:
                    conn.close()
                    with self._lock:
                        self._created_connections -= 1
                except:
                    pass
        else:
            # Connection is invalid, close it
            try:
                conn.close()
                with self._lock:
                    self._created_connections -= 1
            except:
                pass

    def close_all(self):
        """Close all connections in the pool"""
        self._closed = True

        # Close all connections in the queue
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except:
                pass

        with self._lock:
            self._created_connections = 0

    def get_pool_stats(self):
        """Get pool statistics for monitoring"""
        return {
            'pool_size': self._pool.qsize(),
            'created_connections': self._created_connections,
            'max_pool_size': self.max_pool_size,
            'is_closed': self._closed
        }

# Initialize the connection pool
pool_size = int(os.getenv('DB_POOL_SIZE', '5'))
min_pool_size = max(2, pool_size // 2)  # Minimum is half of max, at least 2
connection_pool = ConnectionPool(DB_CONFIG['conn_string'], max_pool_size=pool_size, min_pool_size=min_pool_size)

@contextlib.contextmanager
def db_connection():
    """Context manager for database connections from the pool"""
    conn = None
    try:
        conn = connection_pool.get_connection()
        yield conn
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        raise e
    finally:
        if conn:
            # Close any open cursors before returning connection to pool
            try:
                # This ensures any open cursors are closed
                conn.execute("-- connection cleanup")
            except:
                pass
            connection_pool.release_connection(conn)

@contextlib.contextmanager
def db_connection_with_retry(max_retries=3, initial_delay=5):
    """Context manager for database connections with exponential backoff retry logic"""
    retries = 0
    last_exception = None

    while retries < max_retries:
        try:
            with db_connection() as conn:
                yield conn
                return
        except pyodbc.OperationalError as e:
            # Only retry on timeout or connection errors
            if 'timeout' in str(e).lower() or 'connection' in str(e).lower():
                last_exception = e
                retries += 1
                if retries < max_retries:  # Don't sleep on the last attempt
                    # Calculate exponential backoff delay (5, 10, 20 seconds)
                    delay = initial_delay * (2 ** (retries - 1))
                    # Cap the delay at 60 seconds
                    delay = min(delay, 60)
                    print(f"Connection attempt {retries} failed: {str(e)}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            else:
                # Other database errors should not trigger retries
                raise
        except Exception as e:
            # Don't retry on non-connection related errors
            raise

    # If we get here, all retries failed
    raise last_exception or Exception("Failed to connect to database after retries")

@contextlib.contextmanager
def db_cursor(connection):
    """Context manager for database cursors"""
    cursor = None
    try:
        cursor = connection.cursor()
        yield cursor
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass

def init_db():
    """Initialize database tables if they don't exist"""
    with db_connection_with_retry() as conn:
        with db_cursor(conn) as cursor:
            # Create User table if it doesn't exist
            cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Users')
            BEGIN
                CREATE TABLE Users (
                    id INT PRIMARY KEY IDENTITY(1,1),
                    name NVARCHAR(100) NOT NULL,
                    surname NVARCHAR(100) NOT NULL,
                    email NVARCHAR(120) NOT NULL UNIQUE,
                    password_hash NVARCHAR(128) NOT NULL,
                    is_verified BIT DEFAULT 0,
                    verification_token NVARCHAR(100) DEFAULT NULL,
                    token_expiry DATETIME NULL
                )
            END
            """)

            # Create YogaClass table if it doesn't exist
            cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'YogaClasses')
            BEGIN
                CREATE TABLE YogaClasses (
                    id INT PRIMARY KEY IDENTITY(1,1),
                    name NVARCHAR(100) NOT NULL,
                    instructor NVARCHAR(100) NOT NULL,
                    date_time DATETIME NOT NULL,
                    duration INT NOT NULL DEFAULT 75,
                    capacity INT NOT NULL,
                    status NVARCHAR(20) DEFAULT 'active',
                    location NVARCHAR(200) NOT NULL
                )
            END
            """)

            # Create Booking table if it doesn't exist
            cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Bookings')
            BEGIN
                CREATE TABLE Bookings (
                    id INT PRIMARY KEY IDENTITY(1,1),
                    user_id INT NOT NULL,
                    class_id INT NOT NULL,
                    booking_date DATETIME DEFAULT GETDATE(),
                    status NVARCHAR(20) DEFAULT 'active',
                    FOREIGN KEY (user_id) REFERENCES Users(id),
                    FOREIGN KEY (class_id) REFERENCES YogaClasses(id)
                )
            END
            """)

            conn.commit()

# Initialize database on startup
with app.app_context():
    init_db()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)

# User model for Flask-Login
class User(UserMixin):
    def __init__(self, id=None, name=None, surname=None, email=None, password_hash=None,
                 is_verified=False, verification_token=None, token_expiry=None):
        self.id = id
        self.name = name
        self.surname = surname
        self.email = email
        self.password_hash = password_hash
        self.is_verified = is_verified
        self.verification_token = verification_token
        self.token_expiry = token_expiry

    def check_password(self, password):
        """Check if the password matches the hash"""
        return check_password_hash(self.password_hash, password)

    def update_verification_status(self):
        """Update the user's verification status"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute("""
                UPDATE Users 
                SET is_verified = 1, verification_token = NULL, token_expiry = NULL 
                WHERE id = ?
                """, self.id)
                conn.commit()

        self.is_verified = True
        self.verification_token = None
        self.token_expiry = None
        return True

    def update_verification_token(self):
        """Generate a new verification token"""
        token = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=app.config['VERIFICATION_TOKEN_EXPIRY'])

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute("""
                UPDATE Users 
                SET verification_token = ?, token_expiry = ? 
                WHERE id = ?
                """, token, expiry, self.id)
                conn.commit()

        self.verification_token = token
        self.token_expiry = expiry
        return token

    @classmethod
    def create_user(cls, name, surname, email, password):
        """Create a new user with verification token"""
        # Generate password hash
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')

        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        token_expiry = datetime.utcnow() + timedelta(hours=app.config['VERIFICATION_TOKEN_EXPIRY'])

        # Check email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            raise ValueError("Invalid email format")

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Insert user into database
                cursor.execute("""
                INSERT INTO Users (name, surname, email, password_hash, is_verified, verification_token, token_expiry)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """, name, surname, email, password_hash, verification_token, token_expiry)

                cursor.execute("SELECT @@IDENTITY")
                user_id = cursor.fetchone()[0]
                conn.commit()

        # Return user object
        return cls(
            id=user_id,
            name=name,
            surname=surname,
            email=email,
            password_hash=password_hash,
            is_verified=False,
            verification_token=verification_token,
            token_expiry=token_expiry
        )

    @classmethod
    def get_user_by_email(cls, email):
        """Get a user by email"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    cursor.execute("""
                    SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                    FROM Users 
                    WHERE email = ?
                    """, email)
                    row = cursor.fetchone()

                    if not row:
                        return None

                    # Create user object outside the cursor context
                    return cls(
                        id=row[0],
                        name=row[1],
                        surname=row[2],
                        email=row[3],
                        password_hash=row[4],
                        is_verified=bool(row[5]),
                        verification_token=row[6],
                        token_expiry=row[7]
                    )
        except Exception as e:
            print(f"Error in get_user_by_email: {str(e)}")
            return None

    @classmethod
    def get_user_by_id(cls, user_id):
        """Get a user by ID"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    cursor.execute("""
                    SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                    FROM Users 
                    WHERE id = ?
                    """, user_id)
                    row = cursor.fetchone()

                    if not row:
                        return None

                    # Create user object outside the cursor context
                    return cls(
                        id=row[0],
                        name=row[1],
                        surname=row[2],
                        email=row[3],
                        password_hash=row[4],
                        is_verified=bool(row[5]),
                        verification_token=row[6],
                        token_expiry=row[7]
                    )
        except Exception as e:
            print(f"Error in get_user_by_id: {str(e)}")
            return None

    @classmethod
    def get_user_by_token(cls, token):
        """Get a user by verification token"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    cursor.execute("""
                    SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                    FROM Users 
                    WHERE verification_token = ?
                    """, token)
                    row = cursor.fetchone()

                    if not row:
                        return None

                    # Create user object outside the cursor context
                    return cls(
                        id=row[0],
                        name=row[1],
                        surname=row[2],
                        email=row[3],
                        password_hash=row[4],
                        is_verified=bool(row[5]),
                        verification_token=row[6],
                        token_expiry=row[7]
                    )
        except Exception as e:
            print(f"Error in get_user_by_token: {str(e)}")
            return None

# YogaClass model
class YogaClass:
    def __init__(self, id=None, name=None, instructor=None, date_time=None, duration=75,
                 capacity=None, status='active', location=None):
        self.id = id
        self.name = name
        self.instructor = instructor
        self.date_time = date_time
        self.duration = duration
        self.capacity = capacity
        self.status = status
        self.location = location

    def save(self):
        """Create a new yoga class or update an existing one"""
        # Check if the class is in the past
        if self.date_time < datetime.now():
            raise ValueError("Cannot create a class in the past")

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                if self.id is None:
                    cursor.execute("""
                    INSERT INTO YogaClasses (name, instructor, date_time, duration, capacity, status, location)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, self.name, self.instructor, self.date_time, self.duration,
                                   self.capacity, self.status, self.location)

                    cursor.execute("SELECT @@IDENTITY")
                    self.id = cursor.fetchone()[0]
                else:
                    # This is an existing class being updated
                    cursor.execute("""
                    UPDATE YogaClasses 
                    SET name = ?, instructor = ?, date_time = ?, duration = ?, capacity = ?, status = ?, location = ?
                    WHERE id = ?
                    """, self.name, self.instructor, self.date_time, self.duration,
                                   self.capacity, self.status, self.location, self.id)

                conn.commit()
        return self.id

    def cancel(self):
        """Cancel this yoga class and all associated bookings"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Update the class status to cancelled
                self.status = 'cancelled'
                cursor.execute("UPDATE YogaClasses SET status = 'cancelled' WHERE id = ?", self.id)

                # Update all active bookings for this class to cancelled
                cursor.execute("UPDATE Bookings SET status = 'cancelled' WHERE class_id = ? AND status = 'active'", self.id)

                # Get the count of affected bookings
                cursor.execute("SELECT @@ROWCOUNT")
                affected_bookings = cursor.fetchone()[0]

                conn.commit()
        return affected_bookings

    def get_booking_count(self):
        """Get the number of active bookings for this class"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute("""
                SELECT COUNT(*) 
                FROM Bookings 
                WHERE class_id = ? AND status = 'active'
                """, self.id)
                count = cursor.fetchone()[0]
        return count

    def spots_left(self):
        """Calculate how many spots are left in this class"""
        return self.capacity - self.get_booking_count()

    def is_full(self):
        """Check if the class is fully booked"""
        return self.spots_left() <= 0

    @classmethod
    def get_by_id(cls, class_id):
        """Get a yoga class by ID"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute("""
                SELECT id, name, instructor, date_time, duration, capacity, status, location 
                FROM YogaClasses 
                WHERE id = ?
                """, class_id)
                row = cursor.fetchone()

        if row:
            return cls(
                id=row[0],
                name=row[1],
                instructor=row[2],
                date_time=row[3],
                duration=row[4],
                capacity=row[5],
                status=row[6],
                location=row[7]
            )
        return None

    @classmethod
    def get_future_active_classes(cls):
        """Get all future active classes with booking counts"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Execute a single query that gets both class data and booking counts
                cursor.execute("""
                SELECT 
                    YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                    YC.capacity, YC.status, YC.location,
                    COUNT(CASE WHEN B.status = 'active' THEN 1 ELSE NULL END) as booking_count
                FROM YogaClasses YC
                LEFT JOIN Bookings B ON YC.id = B.class_id
                WHERE YC.date_time > GETDATE() AND YC.status = 'active'
                GROUP BY 
                    YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                    YC.capacity, YC.status, YC.location
                """)

                # Fetch all rows at once
                rows = cursor.fetchall()

            # Process results after the cursor is closed
            classes = []
            for row in rows:
                yoga_class = cls(
                    id=row[0],
                    name=row[1],
                    instructor=row[2],
                    date_time=row[3],
                    duration=row[4],
                    capacity=row[5],
                    status=row[6],
                    location=row[7]
                )

                # Get the booking count from the query result
                booking_count = row[8]

                # Use the booking_count parameter when calling to_dict
                class_dict = yoga_class.to_dict(booking_count=booking_count)
                classes.append(class_dict)

            return classes

    def to_dict(self, booking_count=None):
        """Convert class to dictionary format for API responses"""
        formatted_date_time = self.date_time.strftime('%d/%m/%Y %H:%M') if self.date_time else None

        if self.date_time:
            # Calculate end time
            end_time = self.date_time + timedelta(minutes=self.duration)

            # Format start time
            start_str = self.date_time.strftime('%d/%m/%Y %H:%M')

            # Format end time (only the time part)
            end_str = end_time.strftime('%H:%M')

            # Combine them
            formatted_date_time = f"{start_str}-{end_str}"

        # Create Google Maps URL
        google_maps_url = None
        if self.location:
            # URL encode the location for Google Maps
            encoded_location = self.location.replace(' ', '+')
            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"

        # Calculate spots left
        spots_left = self.capacity
        if self.id:
            if booking_count is not None:
                spots_left = self.capacity - booking_count
            else:
                spots_left = self.spots_left()

        return {
            'class-id': self.id,
            'name': self.name,
            'teacher': self.instructor,
            'date and time': formatted_date_time,
            'duration': self.duration,
            'spots total': self.capacity,
            'spots left': spots_left,
            'status': self.status,
            'location': self.location,
            'location_url': google_maps_url
        }

class Booking:
    def __init__(self, id=None, user_id=None, class_id=None, booking_date=None, status='active'):
        self.id = id
        self.user_id = user_id
        self.class_id = class_id
        self.booking_date = booking_date
        self.status = status

    def save(self):
        """Create a new booking or update an existing one"""
        # Get the yoga class
        yoga_class = YogaClass.get_by_id(self.class_id)

        if not yoga_class:
            raise ValueError("Yoga class does not exist")

        # Check if class is in the past
        if yoga_class.date_time < datetime.now():
            raise ValueError("Cannot book a class in the past")

        # Check class capacity
        if yoga_class.is_full():
            raise ValueError(f"Class {self.class_id} is fully booked")

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Check if user already has a booking for this class
                cursor.execute("""
                SELECT COUNT(*) FROM Bookings 
                WHERE class_id = ? AND user_id = ? AND status = 'active'
                """, self.class_id, self.user_id)
                current_booking = cursor.fetchone()[0]

                if current_booking > 0:
                    raise ValueError(f"User {self.user_id} has already booked for class {self.class_id}")

                # Check for overlapping bookings
                cursor.execute("""
                SELECT COUNT(*) FROM Bookings B
                JOIN YogaClasses YC1 ON B.class_id = YC1.id
                JOIN YogaClasses YC2 ON YC2.id = ?
                WHERE B.user_id = ? AND B.status = 'active' AND YC1.date_time = YC2.date_time
                """, self.class_id, self.user_id)

                overlapping_booking = cursor.fetchone()[0]

                if overlapping_booking > 0:
                    raise ValueError(f"User {self.user_id} already has an active booking at the same time")

                if self.id is None:
                    # Create the booking
                    cursor.execute("""
                    INSERT INTO Bookings (user_id, class_id, booking_date, status)
                    VALUES (?, ?, GETDATE(), ?)
                    """, self.user_id, self.class_id, self.status)

                    cursor.execute("SELECT @@IDENTITY")
                    self.id = cursor.fetchone()[0]
                else:
                    # Update existing booking
                    cursor.execute("""
                    UPDATE Bookings 
                    SET user_id = ?, class_id = ?, status = ?
                    WHERE id = ?
                    """, self.user_id, self.class_id, self.status, self.id)

                conn.commit()

        return self.id

    def cancel(self):
        """Cancel this booking"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                self.status = 'cancelled'
                cursor.execute("UPDATE Bookings SET status = 'cancelled' WHERE id = ?", self.id)
                conn.commit()
        return True

    def to_dict(self):
        """Convert booking to a dictionary for API responses"""
        # First, get the yoga class details
        yoga_class = YogaClass.get_by_id(self.class_id)

        formatted_date_time = None
        class_name = None
        instructor = None
        location = None
        google_maps_url = None

        if yoga_class:
            # Use the same formatting from YogaClass.to_dict()
            if yoga_class.date_time:
                end_time = yoga_class.date_time + timedelta(minutes=yoga_class.duration)
                start_str = yoga_class.date_time.strftime('%d/%m/%Y %H:%M')
                end_str = end_time.strftime('%H:%M')
                formatted_date_time = f"{start_str}-{end_str}"

            class_name = yoga_class.name
            instructor = yoga_class.instructor
            location = yoga_class.location

            if location:
                encoded_location = location.replace(' ', '+')
                google_maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"

        return {
            'booking-id': self.id,
            'class-id': self.class_id,
            'class': class_name,
            'teacher': instructor,
            'date and time': formatted_date_time,
            'booking-status': self.status,
            'location': location,
            'location_url': google_maps_url
        }

    @classmethod
    def get_by_id(cls, booking_id):
        """Get a booking by ID"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute("""
                SELECT id, user_id, class_id, booking_date, status 
                FROM Bookings 
                WHERE id = ?
                """, booking_id)
                row = cursor.fetchone()

        if row:
            return cls(
                id=row[0],
                user_id=row[1],
                class_id=row[2],
                booking_date=row[3],
                status=row[4]
            )
        return None

    @classmethod
    def get_user_active_bookings(cls, user_id):
        """Get all active bookings for a user"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    # Get all data in a single query to avoid nested database calls
                    query = """
                    SELECT 
                        B.id, B.user_id, B.class_id, B.booking_date, B.status,
                        YC.name, YC.instructor, YC.date_time, YC.duration, YC.location
                    FROM Bookings B
                    JOIN YogaClasses YC ON B.class_id = YC.id
                    WHERE B.user_id = ? AND B.status = 'active' AND YC.date_time > GETDATE()
                    """
                    cursor.execute(query, user_id)
                    rows = cursor.fetchall()

                    bookings = []
                    for row in rows:
                        # Calculate formatted time directly here without additional DB calls
                        formatted_date_time = None
                        date_time = row[7]  # YC.date_time
                        duration = row[8]   # YC.duration

                        if date_time:
                            end_time = date_time + timedelta(minutes=duration)
                            start_str = date_time.strftime('%d/%m/%Y %H:%M')
                            end_str = end_time.strftime('%H:%M')
                            formatted_date_time = f"{start_str}-{end_str}"

                        # Google Maps URL
                        location = row[9]  # YC.location
                        google_maps_url = None
                        if location:
                            encoded_location = location.replace(' ', '+')
                            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"

                        booking_dict = {
                            'booking-id': row[0],     # B.id
                            'class-id': row[2],       # B.class_id
                            'class': row[5],          # YC.name
                            'teacher': row[6],        # YC.instructor
                            'date and time': formatted_date_time,
                            'booking-status': row[4], # B.status
                            'location': location,
                            'location_url': google_maps_url
                        }
                        bookings.append(booking_dict)

                return bookings
        except Exception as e:
            print(f"Error in get_user_active_bookings: {str(e)}")
            return []

    @classmethod
    def create_booking(cls, user_id, class_id):
        """Create a new booking"""
        booking = cls(
            user_id=user_id,
            class_id=class_id,
            status='active'
        )

        booking_id = booking.save()
        return booking_id

# Email sending function
def send_verification_email(user):
    # Generate a verification link
    verification_link = f"{request.host_url}verify/{user.verification_token}"

    # Create email content
    html_content = f"""
    <html>
    <body>
        <p>Hi {user.name}, thank you for signing up. Please click the button below to verify your email address:</p>
        <button style="background-color: #4CAF50; border: none; color: white; padding: 10px 20px; text-align: center; text-decoration: none; display: inline-block; font-size: 16px; margin: 4px 2px; cursor: pointer; border-radius: 5px;">
            <a href="{verification_link}" style="color: white; text-decoration: none;">Verify your email</a>
        </button>
        <p>This link will expire in {app.config['VERIFICATION_TOKEN_EXPIRY']} hours.</p>
        <p>If you didn't create an account, you can ignore this email.</p>
    </body>
    </html>
    """

    # Create email message
    msg = MIMEMultipart()
    msg['Subject'] = 'Verify your email for Yoga with Jantine'
    msg['From'] = os.getenv('MAIL_USERNAME')
    msg['To'] = user.email

    # Attach HTML content
    msg.attach(MIMEText(html_content, 'html'))

    try:
        # For testing, we'll just log the email instead of sending it
        print(f"------- VERIFICATION EMAIL -------")
        print(f"To: {user.email}")
        print(f"Subject: Verify your email for Yoga for Jantine")
        print(f"Verification link: {verification_link}")
        print(f"Token: {user.verification_token}")
        print(f"------- END OF EMAIL -------")

        # If you want to actually send emails (with a real SMTP server)
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Enable TLS
            server.login(os.getenv('MAIL_USERNAME'), os.getenv('MAIL_PASSWORD'))
            server.send_message(msg)

        return True

    except Exception as e:
        print(f"Error sending verification email: {str(e)}")
        return False

# --------------------------------------
# Route Definitions
# --------------------------------------

# User routes
@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()

    # Check if user already exists
    existing_user = User.get_user_by_email(data['email'])
    if existing_user:
        return jsonify({'error': 'Email already registered'}), 400

    try:
        new_user = User.create_user(
            name=data['name'],
            surname=data['surname'],
            email=data['email'],
            password=data['password']
        )

        # Send verification email
        send_verification_email(new_user)

        return jsonify({
            'message': 'User created! Please check your email to verify your account.',
            'id': new_user.id
        }), 201
    except Exception as e:
        return jsonify({'error': f'Could not create user: {str(e)}'}), 400

@login_manager.user_loader
def load_user(user_id):
    return User.get_user_by_id(int(user_id))

@app.route('/verify/<token>', methods=['GET'])
def verify_email(token):
    user = User.get_user_by_token(token)

    if not user:
        return render_template_string("""
            <h1>Invalid verification link</h1>
            <p>The verification link is invalid or has expired.</p>
            <p><a href="/">Return to homepage</a></p>
        """)

    if user.token_expiry < datetime.utcnow():
        return render_template_string("""
            <h1>Expired verification link</h1>
            <p>The verification link has expired. Please request a new one.</p>
            <p><a href="/resend-verification?email={{user.email}}">Resend verification email</a></p>
            <p><a href="/">Return to homepage</a></p>
        """)

    user.update_verification_status()

    return render_template_string("""
        <h1>Email verified successfully!</h1>
        <p>Your email has been verified. You can now log in to your account.</p>
        <p><a href="/">Return to homepage</a></p>
    """)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.get_user_by_email(data['email'])

    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user.check_password(data['password']):
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user.is_verified:
        return jsonify({'error': 'Please verify your email before logging in', 'unverified': True}), 401

    session.permanent = True

    login_user(user)
    return jsonify({'message': 'Logged in successfully!', 'user_id': user.id}), 200

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out successfully!'}), 200

@app.route('/users', methods=['GET'])
def get_users():
    with db_connection_with_retry() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT id, name, surname, email, is_verified FROM Users")
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'name': row[1],
                    'surname': row[2],
                    'email': row[3],
                    'is_verified': bool(row[4])
                })
    return jsonify(users)

# Yoga class routes - Updated to use OO YogaClass
@app.route('/classes', methods=['POST'])
def create_class():
    data = request.get_json()

    try:
        # Create a new YogaClass instance
        date_format = "%d/%m/%Y %H:%M"
        yoga_class = YogaClass(
            name=data['name'],
            instructor=data['instructor'],
            date_time=datetime.strptime(data['date_time'], date_format),
            duration=data.get('duration', 75),
            capacity=data['capacity'],
            location=data.get('location')
        )

        # Save it to the database
        class_id = yoga_class.save()

        return jsonify({'message': 'Class created!', 'id': class_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/classes', methods=['GET'])
def get_classes():
    return jsonify(YogaClass.get_future_active_classes())

# Booking routes
@app.route('/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.get_json()
    try:
        booking_id = Booking.create_booking(
            user_id=current_user.id,
            class_id=data['class_id']
        )

        return jsonify({
            'message': 'Booking created!',
            'booking_id': booking_id
        }), 201
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400

@app.route('/bookings/<int:booking_id>/cancel', methods=['PUT'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.get_by_id(booking_id)

    if not booking:
        return jsonify({'error': 'Booking not found'}), 404

    if booking.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    booking.cancel()

    return jsonify({'message': 'Booking cancelled'})

@app.route('/bookings', methods=['GET'])
@login_required
def get_bookings():
    return jsonify(Booking.get_user_active_bookings(current_user.id))

@app.route('/api/check-session', methods=['GET'])
@login_required
def check_session():
    if current_user.is_authenticated:
        return jsonify({'authenticated': True}), 200
    else:
        return jsonify({'authenticated': False, 'message': 'Session expired'}), 401

# Add a route to check pool health
@app.route('/api/pool-status', methods=['GET'])
def pool_status():
    """Get connection pool status for monitoring"""
    stats = connection_pool.get_pool_stats()
    return jsonify(stats)

def root_dir():  # pragma: no cover
    return os.path.abspath(os.path.dirname(__file__))

def get_file(filename):  # pragma: no cover
    try:
        src = os.path.join(root_dir(), filename)
        # Figure out how flask returns static files
        # Tried:
        # - render_template
        # - send_file
        # This should not be so non-obvious
        return open(src).read()
    except IOError as exc:
        return str(exc)

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def get_resource(path):  # pragma: no cover
    mimetypes = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "application/javascript",
    }
    complete_path = os.path.join(root_dir(), "static", path)
    ext = os.path.splitext(path)[1]
    mimetype = mimetypes.get(ext, "text/html")
    content = get_file(complete_path)
    return Response(content, mimetype=mimetype)

# Cleanup function for graceful shutdown
@app.teardown_appcontext
def close_db(error):
    """Close the pool when the app context tears down"""
    pass  # The pool will be closed when the app shuts down

# Register a function to close the pool on app shutdown
import atexit
atexit.register(connection_pool.close_all)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', debug=True, port=8000)
    finally:
        # Ensure pool is closed on shutdown
        connection_pool.close_all()