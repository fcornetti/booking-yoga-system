import re
from flask import Flask, request, jsonify, Response, redirect, url_for, render_template_string, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os.path
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pyodbc
from datetime import datetime, timedelta
import contextlib
from dotenv import load_dotenv
import time
import threading
import queue
import sqlite3
import resend
# from database_keepalive import *  # Disabled for Render - not needed with PostgreSQL

# PostgreSQL support
try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv('CORS_SECRET_KEY')
app.config['VERIFICATION_TOKEN_EXPIRY'] = 24  # Hours
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configure session handling
@app.before_request
def before_request():
    session.modified = True

# Database configuration with environment detection
def get_database_config():
    """
    Get database configuration based on environment.
    Supports SQLite (local), PostgreSQL (Render/Railway), and Azure SQL Server.
    """
    # Check for PostgreSQL first (Render/Railway/Heroku use DATABASE_URL)
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # Render.com and Railway.app use postgres:// which psycopg2 needs as postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        return {
            'type': 'postgresql',
            'conn_string': database_url
        }
    
    # Check if local development
    is_local = (
            os.getenv('FLASK_ENV') == 'development' or
            os.getenv('ENVIRONMENT') == 'local' or
            'localhost' in os.getenv('FLASK_RUN_HOST', '') or
            os.getenv('DB_USE_LOCAL', 'false').lower() == 'true'
    )

    if is_local:
        # Local SQLite configuration
        db_path = os.getenv('LOCAL_DB_PATH', 'yoga_booking_local.db')
        return {
            'type': 'sqlite',
            'database': db_path,
            'conn_string': db_path
        }
    else:
        # OPTIMIZED Production Azure SQL Server configuration
        return {
            'type': 'sqlserver',
            'server': os.getenv('DB_SERVER'),
            'database': os.getenv('DB_NAME'),
            'username': os.getenv('DB_USERNAME'),
            'password': os.getenv('DB_PASSWORD'),
            'driver': '{ODBC Driver 18 for SQL Server}',
            "conn_string": (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={os.getenv('DB_SERVER')};"
                f"DATABASE={os.getenv('DB_NAME')};"
                f"UID={os.getenv('DB_USERNAME')};"
                f"PWD={os.getenv('DB_PASSWORD')};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
                "Connection Timeout=60;"
                "Login Timeout=60;"       
                "Command Timeout=15;"     
                "ConnectRetryCount=1;"    
                "ConnectRetryInterval=5;"
                "Pooling=true;"
                "Max Pool Size=5;"        
                "Min Pool Size=2;"
                "Connection Lifetime=180;"
            )
        }

# Get database configuration
DB_CONFIG = get_database_config()
print(f"Using {DB_CONFIG['type']} database: {DB_CONFIG.get('database', DB_CONFIG.get('server'))}")

def get_sql_queries():
    """Get SQL queries appropriate for the database type"""
    if DB_CONFIG['type'] == 'sqlite':
        return {
            'create_users_table': """
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
            """,
            'create_yoga_classes_table': """
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
            """,
            'create_bookings_table': """
            CREATE TABLE IF NOT EXISTS Bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                booking_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES Users(id),
                FOREIGN KEY (class_id) REFERENCES YogaClasses(id)
            )
            """,
            'get_identity': 'SELECT last_insert_rowid()',
            'get_current_timestamp': 'CURRENT_TIMESTAMP',
            'get_date_now': 'datetime("now")'
        }
    elif DB_CONFIG['type'] == 'postgresql':
        return {
            'create_users_table': """
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
            """,
            'create_yoga_classes_table': """
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
            """,
            'create_bookings_table': """
            CREATE TABLE IF NOT EXISTS Bookings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (class_id) REFERENCES YogaClasses(id) ON DELETE CASCADE
            )
            """,
            'get_identity': 'SELECT lastval()',
            'get_current_timestamp': 'CURRENT_TIMESTAMP',
            'get_date_now': 'CURRENT_TIMESTAMP'
        }
    else:
        return {
            'create_users_table': """
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
            """,
            'create_yoga_classes_table': """
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
            """,
            'create_bookings_table': """
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
            """,
            'get_identity': 'SELECT @@IDENTITY',
            'get_current_timestamp': 'GETDATE()',
            'get_date_now': 'GETDATE()'
        }

SQL_QUERIES = get_sql_queries()

# Parameter placeholder for different databases
def get_param_placeholder():
    """Get the correct parameter placeholder for the current database type"""
    if DB_CONFIG['type'] == 'postgresql':
        return '%s'
    else:
        return '?'

PARAM = get_param_placeholder()

def convert_query(query):
    """Convert query placeholders to match the current database type"""
    if DB_CONFIG['type'] == 'postgresql':
        # Replace ? with %s for PostgreSQL
        return query.replace('?', '%s')
    return query

# Configure SQLite to automatically handle datetime conversion
def adapt_datetime(dt):
    """Convert datetime to ISO string for SQLite storage"""
    return dt.isoformat()

def convert_datetime(s):
    """Convert ISO string back to datetime when reading from SQLite"""
    try:
        # Handle both with and without microseconds
        if '.' in s.decode():
            return datetime.fromisoformat(s.decode())
        else:
            return datetime.fromisoformat(s.decode())
    except:
        # If conversion fails, try strptime as fallback
        try:
            return datetime.strptime(s.decode(), '%Y-%m-%d %H:%M:%S')
        except:
            return s.decode()  # Return as string if all else fails

# Register the converters
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("DATETIME", convert_datetime)

# Database connection classes
class SQLiteConnectionPool:
    """Simple SQLite connection manager (SQLite doesn't need true pooling)"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.Lock()

    def get_connection(self):
        """Get a SQLite connection with datetime conversion enabled"""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        # Enable foreign keys in SQLite
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def release_connection(self, conn):
        """Close SQLite connection"""
        if conn:
            try:
                conn.close()
            except:
                pass

    def close_all(self):
        """No-op for SQLite"""
        pass

    def get_pool_stats(self):
        """Return dummy stats for SQLite"""
        return {
            'pool_size': 1,
            'created_connections': 1,
            'max_pool_size': 1,
            'is_closed': False
        }

class PostgreSQLConnectionPool:
    """PostgreSQL connection pool using psycopg2"""
    
    def __init__(self, conn_string, max_pool_size=10, min_pool_size=2):
        self.conn_string = conn_string
        self.max_pool_size = max_pool_size
        self.min_pool_size = min_pool_size
        print(f"Initializing PostgreSQL connection pool (max: {max_pool_size}, min: {min_pool_size})...")
        
        try:
            # Create connection pool
            self._pool = pg_pool.SimpleConnectionPool(
                min_pool_size,
                max_pool_size,
                conn_string
            )
            print("✅ PostgreSQL connection pool initialized successfully!")
        except Exception as e:
            print(f"❌ PostgreSQL connection pool initialization failed: {e}")
            raise
    
    def get_connection(self):
        """Get a connection from the pool"""
        try:
            conn = self._pool.getconn()
            if conn:
                return conn
            else:
                raise Exception("Failed to get connection from pool")
        except Exception as e:
            print(f"Error getting PostgreSQL connection: {e}")
            raise
    
    def release_connection(self, conn):
        """Return a connection to the pool"""
        if conn:
            try:
                # Rollback any uncommitted transactions
                if not conn.closed:
                    conn.rollback()
                self._pool.putconn(conn)
            except Exception as e:
                print(f"Error releasing PostgreSQL connection: {e}")
    
    def close_all(self):
        """Close all connections in the pool"""
        try:
            self._pool.closeall()
        except:
            pass
    
    def get_pool_stats(self):
        """Get pool statistics"""
        return {
            'pool_size': self.max_pool_size,
            'created_connections': self.max_pool_size,
            'max_pool_size': self.max_pool_size,
            'is_closed': False
        }

class SQLServerConnectionPool:
    """
    Simplified and optimized SQL Server connection pool.
    Think of this as a smart restaurant manager who keeps tables ready
    and serves customers efficiently without overwhelming the kitchen.
    """

    def __init__(self, conn_string, max_pool_size=5, min_pool_size=2):
        self.conn_string = conn_string
        self.max_pool_size = max_pool_size
        self.min_pool_size = min_pool_size
        self._pool = queue.Queue(maxsize=max_pool_size)
        self._lock = threading.Lock()
        self._created_connections = 0
        self._closed = False
        print(f"Initializing connection pool (max: {max_pool_size}, min: {min_pool_size})...")
        self._fast_warmup()

    def _fast_warmup(self):
        # Create exactly the minimum number of connections we specified
        target_connections = self.min_pool_size
        successful = 0

        for i in range(target_connections):
            try:
                print(f"Creating initial connection {i+1}/{target_connections}...")
                start_time = time.time()

                # Create connection with optimized timeout
                conn = pyodbc.connect(self.conn_string, autocommit=False, timeout=30)

                conn_time = time.time() - start_time
                print(f"Connection {i+1} ready in {conn_time:.1f}s")

                self._pool.put(conn)
                with self._lock:
                    self._created_connections += 1
                successful += 1

            except Exception as e:
                print(f"Initial connection {i+1} failed: {str(e)[:80]}...")
                # For warmup, we continue but don't fail completely
                continue

    def get_connection(self):
        """Get a connection from the pool or create a new one"""
        if self._closed:
            raise Exception("Connection pool is closed")

        # Try to get from pool first (fast path)
        try:
            conn = self._pool.get_nowait()
            if self._is_connection_valid(conn):
                return conn
            else:
                # Connection is stale, create a new one
                with self._lock:
                    self._created_connections -= 1
                return self._create_new_connection()
        except queue.Empty:
            # No connections available, create a new one
            return self._create_new_connection()

    def _create_new_connection(self):
        """Create a new database connection with optimized settings"""
        with self._lock:
            if self._created_connections >= self.max_pool_size:
                raise Exception("Maximum connection limit reached")
            self._created_connections += 1

        try:
            # Single attempt connection with proper timeout
            conn = pyodbc.connect(self.conn_string, autocommit=False, timeout=60)
            return conn
        except Exception as e:
            with self._lock:
                self._created_connections -= 1
            raise e

    def _is_connection_valid(self, conn):
        """Quick connection validation"""
        try:
            # Simple, fast validation query
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except:
            return False

    def release_connection(self, conn):
        """Return a connection to the pool"""
        if self._closed or not conn:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return

        try:
            # Always rollback to clean state
            conn.rollback()
        except:
            pass

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
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except:
                pass
        with self._lock:
            self._created_connections = 0

    def get_pool_stats(self):
        """Get pool statistics"""
        return {
            'pool_size': self._pool.qsize(),
            'created_connections': self._created_connections,
            'max_pool_size': self.max_pool_size,
            'is_closed': self._closed
        }

# Initialize the appropriate connection pool based on database type
if DB_CONFIG['type'] == 'sqlite':
    connection_pool = SQLiteConnectionPool(DB_CONFIG['conn_string'])
elif DB_CONFIG['type'] == 'postgresql':
    pool_size = int(os.getenv('DB_POOL_SIZE', '10'))
    min_pool_size = max(2, pool_size // 5)
    connection_pool = PostgreSQLConnectionPool(
        DB_CONFIG['conn_string'],
        max_pool_size=pool_size,
        min_pool_size=min_pool_size
    )
else:
    pool_size = int(os.getenv('DB_POOL_SIZE', '5'))
    min_pool_size = max(2, pool_size // 2)
    connection_pool = SQLServerConnectionPool(
        DB_CONFIG['conn_string'],
        max_pool_size=pool_size,
        min_pool_size=min_pool_size
    )

@contextlib.contextmanager
def db_connection():
    conn = None
    try:
        start_time = time.time()
        conn = connection_pool.get_connection()
        conn_time = time.time() - start_time

        if conn_time > 5:  # Only log if connection takes more than 5 seconds
            print(f"Slow connection: {conn_time:.1f}s")

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
            connection_pool.release_connection(conn)

@contextlib.contextmanager
def db_connection_with_retry(max_retries=2, initial_delay=3):
    """Context manager with faster retry for warmed pool"""
    retries = 0
    last_exception = None

    while retries < max_retries:
        try:
            start_time = time.time()
            with db_connection() as conn:
                conn_time = time.time() - start_time
                if conn_time > 2:  # Log slow connections
                    print(f"Slow connection: {conn_time:.1f}s")
                yield conn
                return

        except Exception as e:
            conn_time = time.time() - start_time
            print(f"Connection failed after {conn_time:.1f}s: {str(e)[:50]}...")

            # For SQLite and PostgreSQL, don't retry on errors (they handle connections differently)
            if DB_CONFIG['type'] in ['sqlite', 'postgresql']:
                raise

            # Check if it's worth retrying
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ['timeout', 'connection', 'login']):
                last_exception = e
                retries += 1
                if retries < max_retries:
                    delay = initial_delay * retries  # 3s, 6s (faster than before)
                    print(f"Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

            raise e

    raise last_exception or Exception("Connection failed after retries")

@contextlib.contextmanager
def db_connection_with_resume_retry(max_retries=3, resume_delay=10):
    """
    Context manager with special handling for Azure SQL Database auto-pause/resume.
    """
    retries = 0
    last_exception = None

    while retries < max_retries:
        try:
            start_time = time.time()
            with db_connection() as conn:
                conn_time = time.time() - start_time
                if conn_time > 2:
                    print(f"Database connection took {conn_time:.1f}s (resume scenario)")
                yield conn
                return

        except Exception as e:
            conn_time = time.time() - start_time
            error_msg = str(e).lower()

            # Check for Azure SQL Database unavailable errors (auto-pause scenario)
            if any(keyword in error_msg for keyword in [
                'not currently available',
                'database.*is not currently available',
                '40613',  # Specific Azure error code for database unavailable
                'server is not currently available'
            ]):
                print(f"Database appears to be resuming from auto-pause (attempt {retries + 1})")
                last_exception = e
                retries += 1

                if retries < max_retries:
                    # Use longer delay for database resume scenarios
                    delay = resume_delay * retries  # 10s, 20s, 30s
                    print(f"Waiting {delay}s for database to resume...")
                    time.sleep(delay)
                    continue

            # For SQLite and PostgreSQL, don't retry on errors (they handle connections differently)
            if DB_CONFIG['type'] in ['sqlite', 'postgresql']:
                raise

            # Check if it's worth retrying for other connection issues
            if any(keyword in error_msg for keyword in ['timeout', 'connection', 'login']):
                last_exception = e
                retries += 1
                if retries < max_retries:
                    delay = 3 * retries  # Faster retry for regular timeouts
                    print(f"Connection timeout, retrying in {delay}s...")
                    time.sleep(delay)
                    continue

            raise e

    raise last_exception or Exception("Database connection failed after retries")

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
    """
    Optimized database initialization with connection validation.
    """
    try:
        print("Initializing database tables...")
        init_start = time.time()

        with db_connection_with_resume_retry() as conn:
            with db_cursor(conn) as cursor:
                # Create tables with better error handling
                try:
                    cursor.execute(SQL_QUERIES['create_users_table'])
                    cursor.execute(SQL_QUERIES['create_yoga_classes_table'])
                    cursor.execute(SQL_QUERIES['create_bookings_table'])
                    conn.commit()

                    init_time = time.time() - init_start
                    print(f"Database initialized successfully in {init_time:.1f}s")

                except Exception as table_error:
                    print(f"Table creation error: {table_error}")
                    conn.rollback()
                    raise

    except Exception as e:
        print(f"Database initialization failed: {str(e)}")
        print("Application will continue but database operations may fail")


# Initialize database on startup
with app.app_context():
    init_db()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)

# User model for Flask-Login (keeping your existing User class with minor SQL adaptations)
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
                # Use TRUE for PostgreSQL, 1 for others
                is_verified_value = True if DB_CONFIG['type'] == 'postgresql' else 1
                cursor.execute(convert_query("""
                UPDATE Users 
                SET is_verified = ?, verification_token = NULL, token_expiry = NULL 
                WHERE id = ?
                """), (is_verified_value, self.id))
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
                cursor.execute(convert_query("""
                UPDATE Users 
                SET verification_token = ?, token_expiry = ? 
                WHERE id = ?
                """), (token, expiry, self.id))
                conn.commit()

        self.verification_token = token
        self.token_expiry = expiry
        return token

    @classmethod
    def create_user(cls, name, surname, email, password):
        """Create a new user with verification token"""
        # queries = get_sql_queries()

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
                # Use FALSE for is_verified (works in PostgreSQL and SQL Server)
                is_verified_value = False if DB_CONFIG['type'] == 'postgresql' else 0
                cursor.execute(convert_query("""
                INSERT INTO Users (name, surname, email, password_hash, is_verified, verification_token, token_expiry)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (name, surname, email, password_hash, is_verified_value, verification_token, token_expiry))

                cursor.execute(SQL_QUERIES['get_identity'])
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
    def get_user_by_token(cls, token):
        """Get a user by verification token"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    cursor.execute(convert_query("""
                        SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                        FROM Users 
                        WHERE verification_token = ?
                        """), (token,))
                    row = cursor.fetchone()

                    if not row:
                        return None

                    return cls(
                        id=row[0],
                        name=row[1],
                        surname=row[2],
                        email=row[3],
                        password_hash=row[4],
                        is_verified=bool(row[5]),
                        verification_token=row[6],
                        token_expiry=row[7]  # Already converted to datetime
                    )
        except Exception as e:
            print(f"Error in get_user_by_token: {str(e)}")
        return None

    @classmethod
    def get_user_by_email(cls, email):
        """
        Enhanced user lookup with database resume handling.
        Like a smart librarian who waits patiently when the library is reopening.
        """
        try:
            print(f"Looking up user: {email}")
            total_start = time.time()

            # Use the enhanced connection context manager
            with db_connection_with_resume_retry() as conn:
                query_start = time.time()

                with db_cursor(conn) as cursor:
                    cursor.execute(convert_query("""
                        SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                        FROM Users 
                        WHERE email = ?
                        """), (email,))

                    row = cursor.fetchone()

                    query_time = time.time() - query_start
                    total_time = time.time() - total_start

                    # Log timing info for monitoring
                    if total_time > 5:
                        print(f"User lookup - Query: {query_time:.1f}s, Total: {total_time:.1f}s")

                    if not row:
                        return None

                    return cls(
                        id=row[0], name=row[1], surname=row[2], email=row[3],
                        password_hash=row[4], is_verified=bool(row[5]),
                        verification_token=row[6], token_expiry=row[7]
                    )

        except Exception as e:
            print(f"get_user_by_email error: {str(e)}")
            return None

    @classmethod
    def get_user_by_id(cls, user_id):
                """Get a user by ID"""
                try:
                    with db_connection_with_retry() as conn:
                        with db_cursor(conn) as cursor:
                            cursor.execute(convert_query("""
                                SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
                                FROM Users 
                                WHERE id = ?
                                """), (user_id,))
                            row = cursor.fetchone()

                            if not row:
                                return None

                            return cls(
                                id=row[0],
                                name=row[1],
                                surname=row[2],
                                email=row[3],
                                password_hash=row[4],
                                is_verified=bool(row[5]),
                                verification_token=row[6],
                                token_expiry=row[7]  # Already converted to datetime
                            )
                except Exception as e:
                    print(f"Error in get_user_by_id: {str(e)}")
                    return None

    @staticmethod
    def get_user_count():
        """
        Get total count of users in the system.
        This is a lightweight query perfect for database keepalive pings.

        Returns:
            int: Total number of users
        """
        try:
            with db_connection_with_resume_retry() as conn:
                with db_cursor(conn) as cursor:
                    cursor.execute("SELECT COUNT(*) FROM Users")
                    result = cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            print(f"Error getting user count: {str(e)}")
            return 0

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

        # queries = get_sql_queries()

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                if self.id is None:
                    cursor.execute(convert_query("""
                    INSERT INTO YogaClasses (name, instructor, date_time, duration, capacity, status, location)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """), (self.name, self.instructor, self.date_time, self.duration,
                          self.capacity, self.status, self.location))

                    cursor.execute(SQL_QUERIES['get_identity'])
                    self.id = cursor.fetchone()[0]
                else:
                    # This is an existing class being updated
                    cursor.execute(convert_query("""
                    UPDATE YogaClasses 
                    SET name = ?, instructor = ?, date_time = ?, duration = ?, capacity = ?, status = ?, location = ?
                    WHERE id = ?
                    """), (self.name, self.instructor, self.date_time, self.duration,
                          self.capacity, self.status, self.location, self.id))

                conn.commit()
        return self.id

    def cancel(self):
        """Cancel this yoga class and all associated bookings"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Update the class status to cancelled
                self.status = 'cancelled'
                cursor.execute(convert_query("UPDATE YogaClasses SET status = 'cancelled' WHERE id = ?"), (self.id,))

                # Update all active bookings for this class to cancelled
                cursor.execute(convert_query("UPDATE Bookings SET status = 'cancelled' WHERE class_id = ? AND status = 'active'"), (self.id,))

                # For SQLite, we need to get row count differently
                if DB_CONFIG['type'] == 'sqlite':
                    affected_bookings = cursor.rowcount
                else:
                    cursor.execute("SELECT @@ROWCOUNT")
                    affected_bookings = cursor.fetchone()[0]

                conn.commit()
        return affected_bookings

    def get_booking_count(self):
        """Get the number of active bookings for this class"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute(convert_query("""
                SELECT COUNT(*) 
                FROM Bookings 
                WHERE class_id = ? AND status = 'active'
                """), (self.id,))
                count = cursor.fetchone()[0]
        return count

    def spots_left(self):
        """Calculate how many spots are left in this class"""
        return self.capacity - self.get_booking_count()

    def is_full(self):
        """Check if the class is fully booked"""
        return self.spots_left() <= 0

    def to_dict(self, booking_count=None):
        """Convert class to dictionary format for API responses"""
        formatted_date_time = None

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

    @classmethod
    def get_by_id(cls, class_id):
        """Get a yoga class by ID"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute(convert_query("""
                SELECT id, name, instructor, date_time, duration, capacity, status, location 
                FROM YogaClasses 
                WHERE id = ?
                """), (class_id,))
                row = cursor.fetchone()

        if row:
            return cls(
                id=row[0],
                name=row[1],
                instructor=row[2],
                date_time=row[3],  # Already converted to datetime by SQLite configuration
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
                # Build database-specific query
                if DB_CONFIG['type'] == 'sqlite':
                    query = """
                    SELECT 
                        YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                        YC.capacity, YC.status, YC.location,
                        COUNT(CASE WHEN B.status = 'active' THEN 1 ELSE NULL END) as booking_count
                    FROM YogaClasses YC
                    LEFT JOIN Bookings B ON YC.id = B.class_id
                    WHERE YC.date_time > datetime('now') AND YC.status = 'active'
                    GROUP BY 
                        YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                        YC.capacity, YC.status, YC.location
                    ORDER BY YC.date_time
                    """
                else:
                    query = """
                    SELECT 
                        YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                        YC.capacity, YC.status, YC.location,
                        COUNT(CASE WHEN B.status = 'active' THEN 1 ELSE NULL END) as booking_count
                    FROM YogaClasses YC
                    LEFT JOIN Bookings B ON YC.id = B.class_id
                    WHERE YC.date_time > CURRENT_TIMESTAMP AND YC.status = 'active'
                    GROUP BY 
                        YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, 
                        YC.capacity, YC.status, YC.location
                    ORDER BY YC.date_time
                    """

                cursor.execute(query)
                rows = cursor.fetchall()

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

                booking_count = row[8]
                class_dict = yoga_class.to_dict(booking_count=booking_count)
                classes.append(class_dict)

            return classes

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

        # Check if class is in the past - no conversion needed!
        if yoga_class.date_time < datetime.now():
            raise ValueError("Cannot book a class in the past")

        # Check class capacity
        if yoga_class.is_full():
            raise ValueError(f"Class {self.class_id} is fully booked")

        # queries = get_sql_queries()

        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                # Check if user already has a booking for this class
                cursor.execute(convert_query("""
                SELECT COUNT(*) FROM Bookings 
                WHERE class_id = ? AND user_id = ? AND status = 'active'
                """), (self.class_id, self.user_id))
                current_booking = cursor.fetchone()[0]

                if current_booking > 0:
                    raise ValueError(f"User {self.user_id} has already booked for class {self.class_id}")

                # Check for overlapping bookings
                if DB_CONFIG['type'] == 'sqlite':
                    overlap_query = """
                    SELECT COUNT(*) FROM Bookings B
                    JOIN YogaClasses YC1 ON B.class_id = YC1.id
                    JOIN YogaClasses YC2 ON YC2.id = ?
                    WHERE B.user_id = ? AND B.status = 'active' AND YC1.date_time = YC2.date_time
                    """
                else:
                    overlap_query = """
                    SELECT COUNT(*) FROM Bookings B
                    JOIN YogaClasses YC1 ON B.class_id = YC1.id
                    JOIN YogaClasses YC2 ON YC2.id = ?
                    WHERE B.user_id = ? AND B.status = 'active' AND YC1.date_time = YC2.date_time
                    """

                cursor.execute(convert_query(overlap_query), (self.class_id, self.user_id))
                overlapping_booking = cursor.fetchone()[0]

                if overlapping_booking > 0:
                    raise ValueError(f"User {self.user_id} already has an active booking at the same time")

                if self.id is None:
                    # Create the booking
                    cursor.execute(convert_query("""
                    INSERT INTO Bookings (user_id, class_id, booking_date, status)
                    VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                    """), (self.user_id, self.class_id, self.status))

                    cursor.execute(SQL_QUERIES['get_identity'])
                    self.id = cursor.fetchone()[0]
                else:
                    # Update existing booking
                    cursor.execute(convert_query("""
                    UPDATE Bookings 
                    SET user_id = ?, class_id = ?, status = ?
                    WHERE id = ?
                    """), (self.user_id, self.class_id, self.status, self.id))

                conn.commit()

        return self.id

    def cancel(self):
        """Cancel this booking"""
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                self.status = 'cancelled'
                cursor.execute(convert_query("UPDATE Bookings SET status = 'cancelled' WHERE id = ?"), (self.id,))
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
            # No datetime conversion needed - it's already a datetime object!
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
                cursor.execute(convert_query("""
                SELECT id, user_id, class_id, booking_date, status 
                FROM Bookings 
                WHERE id = ?
                """), (booking_id,))
                row = cursor.fetchone()

        if row:
            return cls(
                id=row[0],
                user_id=row[1],
                class_id=row[2],
                booking_date=row[3],  # Already converted to datetime
                status=row[4]
            )
        return None

    @classmethod
    def get_user_active_bookings(cls, user_id):
        """Get all active bookings for a user"""
        try:
            with db_connection_with_retry() as conn:
                with db_cursor(conn) as cursor:
                    # Build database-specific query
                    if DB_CONFIG['type'] == 'sqlite':
                        query = """
                        SELECT 
                            B.id, B.user_id, B.class_id, B.booking_date, B.status,
                            YC.name, YC.instructor, YC.date_time, YC.duration, YC.location
                        FROM Bookings B
                        JOIN YogaClasses YC ON B.class_id = YC.id
                        WHERE B.user_id = ? AND B.status = 'active' AND YC.date_time > datetime('now')
                        ORDER BY YC.date_time
                        """
                    else:
                        query = """
                        SELECT 
                            B.id, B.user_id, B.class_id, B.booking_date, B.status,
                            YC.name, YC.instructor, YC.date_time, YC.duration, YC.location
                        FROM Bookings B
                        JOIN YogaClasses YC ON B.class_id = YC.id
                        WHERE B.user_id = ? AND B.status = 'active' AND YC.date_time > CURRENT_TIMESTAMP
                        ORDER BY YC.date_time
                        """

                    cursor.execute(convert_query(query), (user_id,))
                    rows = cursor.fetchall()

                    bookings = []
                    for row in rows:
                        # No datetime conversion needed - already datetime objects!
                        date_time = row[7]  # YC.date_time
                        duration = row[8]   # YC.duration

                        formatted_date_time = None
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

# --------------------------------------
# Route Definitions
# --------------------------------------

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()

    # Check if user already exists
    # existing_user = User.get_user_by_email(data['email'])
    # if existing_user:
    #     return jsonify({'error': 'Email already registered'}), 400

    existing_user = User.get_user_by_email(data['email'])
    if existing_user:
        if not existing_user.is_verified:
            existing_user.update_verification_token()
            send_verification_email(existing_user)
            return jsonify({
                'message': 'Account exists but unverified. New verification email sent!'
            }), 200
        else:
            return jsonify({'error': 'Email already registered and verified'}), 400

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


def send_verification_email(user):
    """
    Send verification email via Resend
    """
    # Set API key
    resend.api_key = os.getenv("RESEND_API_KEY")
    print(resend.api_key)

    verification_link = f"{request.host_url}verify/{user.verification_token}"

    # Professional email content with peach color scheme
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Verify Your Email - Yoga with Jantine</title>
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f4f4f4;">
        <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #FF8C69; margin: 0; font-size: 28px;">🧘‍♀️ Yoga with Jantine</h1>
            </div>
            
            <h2 style="color: #FF8C69; margin-top: 0;">Welcome, {user.name}!</h2>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                Thank you for joining our peaceful yoga community. We're excited to have you on this journey of movement, stillness, and connection.
            </p>
            
            <p style="font-size: 16px; margin-bottom: 30px;">
                To complete your registration and start booking your yoga classes, please verify your email address by clicking the button below:
            </p>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="{verification_link}" 
                   style="background: linear-gradient(135deg, #FF8C69, #FF7F50); 
                          color: white; 
                          padding: 15px 35px; 
                          text-decoration: none; 
                          border-radius: 25px; 
                          display: inline-block;
                          font-weight: bold;
                          font-size: 16px;
                          box-shadow: 0 4px 15px rgba(255, 140, 105, 0.3);
                          transition: all 0.3s ease;">
                    ✨ Verify My Email Address
                </a>
            </div>
            
            <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; margin: 30px 0;">
                <p style="margin: 0; font-size: 14px; color: #666;">
                    <strong>Trouble clicking the button?</strong><br>
                    Copy and paste this link into your browser:
                </p>
                <p style="word-break: break-all; background: white; padding: 10px; border-radius: 5px; margin: 10px 0 0 0; font-family: monospace; font-size: 12px;">
                    {verification_link}
                </p>
            </div>
            
            <div style="border-top: 2px solid #FF8C69; margin: 30px 0; padding-top: 20px;">
                <p style="margin-bottom: 10px;">
                    <strong>What's next?</strong>
                </p>
                <ul style="padding-left: 20px; color: #555;">
                    <li>Browse our available yoga classes</li>
                    <li>Book your first session</li>
                    <li>Join our welcoming community</li>
                </ul>
            </div>
            
            <div style="background: linear-gradient(135deg, #FFEEE6, #FFE4D6); padding: 20px; border-radius: 8px; margin: 30px 0; text-align: center;">
                <p style="margin: 0; font-style: italic; color: #FF8C69;">
                    "Yoga is not about touching your toes. It is about what you learn on the way down."
                </p>
            </div>
            
            <p style="margin-top: 30px;">
                <strong>Namaste,</strong><br>
                <span style="color: #FF8C69; font-weight: bold; font-size: 18px;">Jantine</span><br>
                <span style="color: #666; font-size: 14px;">Certified Yoga Instructor</span><br>
            </p>
            
            <div style="border-top: 1px solid #eee; margin-top: 30px; padding-top: 20px;">
                <p style="font-size: 12px; color: #888; margin: 0; line-height: 1.4;">
                    This verification link will expire in {app.config['VERIFICATION_TOKEN_EXPIRY']} hours for security.<br>
                    If you didn't create an account with us, you can safely ignore this email.<br>
                    This email was sent to {user.email}
                </p>
            </div>
        </div>
        
        <div style="text-align: center; margin-top: 20px;">
            <p style="font-size: 12px; color: #999; margin: 0;">
                © 2025 Yoga with Jantine.
            </p>
        </div>
    </body>
    </html>
    """

    # Plain text version (important for deliverability)
    text_content = f"""
    🧘‍♀️ YOGA WITH JANTINE

    Welcome, {user.name}!

    Thank you for joining our peaceful yoga community. We're excited to have you on this journey of movement, stillness, and connection.

    To complete your registration and start booking your yoga classes, please verify your email address by visiting this link:

    {verification_link}

    What's next?
    • Browse our available yoga classes
    • Book your first session  
    • Join our welcoming community

    "Yoga is not about touching your toes. It is about what you learn on the way down."

    Namaste,
    Jantine
    Certified Yoga Instructor

    ---
    This verification link will expire in {app.config['VERIFICATION_TOKEN_EXPIRY']} hours for security.
    If you didn't create an account with us, you can safely ignore this email.
    This email was sent to {user.email}

    © 2025 Yoga with Jantine.
    """

    try:
        # Send via Resend
        params = {
            "from": "Jantine - Yoga Classes <noreply@jantinevanwijlick.com>",
            "to": [user.email],
            "subject": f"🧘‍♀️ Welcome {user.name}! Please verify your email",
            "html": html_content,
            "text": text_content,
            "tags": [
                {"name": "category", "value": "verification"},
                {"name": "user_id", "value": str(user.id)}
            ]
        }

        email_response = resend.Emails.send(params)

        print(f"------- RESEND EMAIL SENT -------")
        print(f"To: {user.email}")
        print(f"Subject: 🧘‍♀️ Welcome {user.name}! Please verify your email")
        print(f"Email ID: {email_response.get('id', 'N/A')}")
        print(f"Verification link: {verification_link}")
        print(f"------- EMAIL SENT SUCCESSFULLY -------")

        return True

    except Exception as e:
        print(f"❌ Resend error: {str(e)}")

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

    # No datetime conversion needed - token_expiry is already a datetime object!
    if user.token_expiry and user.token_expiry < datetime.utcnow():
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
    """
    Enhanced login route with database resume awareness.
    """
    data = request.get_json()

    try:
        login_start = time.time()
        print(f"Login attempt for: {data['email']}")

        # Try to get user with resume retry logic
        user = User.get_user_by_email(data['email'])

        login_time = time.time() - login_start

        # Provide different messages based on timing
        if login_time > 15:
            print(f"Extended login time: {login_time:.1f}s (likely database resume)")

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.check_password(data['password']):
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.is_verified:
            return jsonify({'error': 'Please verify your email before logging in', 'unverified': True}), 401

        session.permanent = True
        login_user(user)

        # Include timing info for slow logins (database resume scenarios)
        response_data = {'message': 'Logged in successfully!', 'user_id': user.id}
        if login_time > 10:
            response_data['notice'] = 'Login took longer than usual - our system was warming up!'

        return jsonify(response_data), 200

    except Exception as e:
        error_msg = str(e).lower()

        # Provide user-friendly messages for different scenarios
        if 'not currently available' in error_msg or '40613' in error_msg:
            return jsonify({
                'error': 'Our system is starting up. Please try again in a moment.',
                'retry_suggested': True
            }), 503

        print(f"Login error: {str(e)}")
        return jsonify({'error': 'Login service temporarily unavailable. Please try again.'}), 503

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

@app.route('/classes/<int:class_id>', methods=['DELETE'])
def delete_class(class_id):
    try:
        # Get the yoga class
        yoga_class = YogaClass.get_by_id(class_id)

        if not yoga_class:
            return jsonify({'error': 'Class not found'}), 404

        # Cancel the class and get affected bookings count
        affected_bookings = yoga_class.cancel()

        return jsonify({
            'message': 'Class cancelled successfully',
            'affected_bookings': affected_bookings
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email to user"""
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    try:
        # Find the user by email
        user = User.get_user_by_email(email)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Check if user is already verified
        if user.is_verified:
            return jsonify({'error': 'User is already verified'}), 400

        # Generate a new verification token (refreshes expiry)
        user.update_verification_token()

        # Reuse existing email function
        send_verification_email(user)

        return jsonify({
            'message': 'Verification email has been resent successfully. Please check your inbox.'
        }), 200

    except Exception as e:
        print(f"Error in resend_verification: {str(e)}")
        return jsonify({'error': 'Failed to resend verification email. Please try again later.'}), 500

@app.route('/request-password-reset', methods=['POST'])
def request_password_reset():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    try:
        # Find the user by email
        user = User.get_user_by_email(email)

        if not user:
            # Don't reveal whether user exists for security
            return jsonify({'message': 'If an account exists with this email, a password reset link has been sent'}), 200

        # Generate a password reset token
        reset_token = secrets.token_urlsafe(32)
        token_expiry = datetime.utcnow() + timedelta(hours=1)  # 1 hour expiry for password reset

        # Store the token in the database
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute(convert_query("""
                UPDATE Users 
                SET verification_token = ?, token_expiry = ?
                WHERE id = ?
                """), (reset_token, token_expiry, user.id))
                conn.commit()

        # Send password reset email
        send_password_reset_email(user, reset_token)

        return jsonify({
            'message': 'If an account exists with this email, a password reset link has been sent'
        }), 200

    except Exception as e:
        print(f"Error in request_password_reset: {str(e)}")
        return jsonify({'error': 'Failed to process password reset request'}), 500

@app.route('/reset-password/<token>', methods=['POST'])
def reset_password(token):
    data = request.get_json()
    new_password = data.get('new_password')

    if not new_password:
        return jsonify({'error': 'New password is required'}), 400

    try:
        # Find user by reset token (using verification_token column)
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute(convert_query("""
                SELECT id, token_expiry 
                FROM Users 
                WHERE verification_token = ?
                """), (token,))
                row = cursor.fetchone()

                if not row:
                    return jsonify({'error': 'Invalid or expired reset token'}), 400

                user_id = row[0]
                expiry = row[1]

                # Check if token is expired
                if expiry < datetime.utcnow():
                    return jsonify({'error': 'Reset token has expired'}), 400

                # Update password and clear token
                password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
                cursor.execute(convert_query("""
                UPDATE Users 
                SET password_hash = ?, verification_token = NULL, token_expiry = NULL
                WHERE id = ?
                """), (password_hash, user_id))
                conn.commit()

        return jsonify({'message': 'Password reset successfully'}), 200

    except Exception as e:
        print(f"Error in reset_password: {str(e)}")
        return jsonify({'error': 'Failed to reset password'}), 500

@app.route('/reset-password/<token>', methods=['GET'])
def show_password_reset_form(token):
    # First, validate the token to ensure it's still active and belongs to a user
    try:
        with db_connection_with_retry() as conn:
            with db_cursor(conn) as cursor:
                cursor.execute(convert_query("""
                SELECT id, token_expiry
                FROM Users
                WHERE verification_token = ?
                """), (token,))
                row = cursor.fetchone()

                if not row:
                    return render_template_string("""
                        <h1>Invalid or Expired Link</h1>
                        <p>The password reset link is invalid or has already been used/expired.</p>
                        <p><a href="/">Return to homepage</a></p>
                    """)

                expiry = row[1]
                if expiry < datetime.utcnow():
                    return render_template_string("""
                        <h1>Link Expired</h1>
                        <p>The password reset link has expired. Please request a new one.</p>
                        <p><a href="/request-password-reset">Request New Password Reset Link</a></p>
                    """)
        # If token is valid and not expired, render the form
        return render_template_string(get_file("static/reset_password.html"), token=token)
    except Exception as e:
        print(f"Error serving password reset form: {str(e)}")
        return render_template_string("""
            <h1>Error</h1>
            <p>An unexpected error occurred. Please try again later.</p>
            <p><a href="/">Return to homepage</a></p>
        """)

def send_password_reset_email(user, reset_token):
    """Send password reset email via Resend"""
    resend.api_key = os.getenv("RESEND_API_KEY")

    reset_link = f"{request.host_url}reset-password/{reset_token}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset - Yoga with Jantine</title>
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f4f4f4;">
        <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #FF8C69; margin: 0; font-size: 28px;">🧘‍♀️ Yoga with Jantine</h1>
            </div>
            
            <h2 style="color: #FF8C69; margin-top: 0;">Password Reset Request</h2>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                We received a request to reset your password. If you didn't make this request, you can safely ignore this email.
            </p>
            
            <p style="font-size: 16px; margin-bottom: 30px;">
                To reset your password, please click the button below:
            </p>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="{reset_link}" 
                   style="background: linear-gradient(135deg, #FF8C69, #FF7F50); 
                          color: white; 
                          padding: 15px 35px; 
                          text-decoration: none; 
                          border-radius: 25px; 
                          display: inline-block;
                          font-weight: bold;
                          font-size: 16px;
                          box-shadow: 0 4px 15px rgba(255, 140, 105, 0.3);
                          transition: all 0.3s ease;">
                    🔒 Reset My Password
                </a>
            </div>
            
            <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; margin: 30px 0;">
                <p style="margin: 0; font-size: 14px; color: #666;">
                    <strong>Trouble clicking the button?</strong><br>
                    Copy and paste this link into your browser:
                </p>
                <p style="word-break: break-all; background: white; padding: 10px; border-radius: 5px; margin: 10px 0 0 0; font-family: monospace; font-size: 12px;">
                    {reset_link}
                </p>
            </div>
            
            <div style="border-top: 2px solid #FF8C69; margin: 30px 0; padding-top: 20px;">
                <p style="margin-bottom: 10px;">
                    <strong>Important:</strong>
                </p>
                <ul style="padding-left: 20px; color: #555;">
                    <li>This link will expire in 1 hour</li>
                    <li>For security reasons, don't share this link with anyone</li>
                    <li>If you didn't request this, your account may be compromised</li>
                </ul>
            </div>
            
            <p style="margin-top: 30px;">
                <strong>Namaste,</strong><br>
                <span style="color: #FF8C69; font-weight: bold; font-size: 18px;">Jantine</span><br>
                <span style="color: #666; font-size: 14px;">Certified Yoga Instructor</span><br>
            </p>
        </div>
    </body>
    </html>
    """

    text_content = f"""
    🧘‍♀️ YOGA WITH JANTINE - PASSWORD RESET

    We received a request to reset your password. If you didn't make this request, you can safely ignore this email.

    To reset your password, please visit this link:
    {reset_link}

    Important:
    • This link will expire in 1 hour
    • For security reasons, don't share this link with anyone
    • If you didn't request this, your account may be compromised

    Namaste,
    Jantine
    Certified Yoga Instructor
    """

    try:
        params = {
            "from": "Jantine - Yoga Classes <noreply@jantinevanwijlick.com>",
            "to": [user.email],
            "subject": "🧘‍♀️ Password Reset Request",
            "html": html_content,
            "text": text_content,
            "tags": [
                {"name": "category", "value": "password_reset"},
                {"name": "user_id", "value": str(user.id)}
            ]
        }

        resend.Emails.send(params)
        print(f"Password reset email sent to {user.email}")
        return True

    except Exception as e:
        print(f"Error sending password reset email: {str(e)}")
        return False

@login_manager.user_loader
def load_user(user_id):
    return User.get_user_by_id(int(user_id))

# [Keep all your existing static file serving code...]
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
    pass

# Register a function to close the pool on app shutdown
import atexit
atexit.register(connection_pool.close_all)

if __name__ == '__main__':
    try:
        # Start the database keepalive service (disabled for Render/PostgreSQL)
        print("Starting Yoga Booking System...")
        # start_database_keepalive()  # Not needed with PostgreSQL

        # Start your Flask app
        app.run(host='0.0.0.0', debug=True, port=8000)
    finally:
        # Clean shutdown
        print("Shutting down services...")
        # stop_database_keepalive()  # Not needed with PostgreSQL
        connection_pool.close_all()