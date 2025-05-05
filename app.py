import re
from flask import Flask, request, jsonify, Response, redirect, url_for, render_template_string,session
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

from dotenv import load_dotenv
import os
load_dotenv()

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv('CORS_SECRET_KEY')
app.config['VERIFICATION_TOKEN_EXPIRY'] = 24  # Hours
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

@app.before_request
def before_request():
    session.modified = True

# Azure SQL Database connection parameters
server = os.getenv('DB_SERVER')
database = os.getenv('DB_NAME')
username = os.getenv('DB_USERNAME')
password = os.getenv('DB_PASSWORD')
driver = '{ODBC Driver 18 for SQL Server}'  # Make sure this driver is installed

# Create connection string
conn_string = f'DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}'

# Function to get database connection
def get_db_connection():
    return pyodbc.connect(conn_string)

# Initialize database tables if they don't exist
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

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
    cursor.close()
    conn.close()

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
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE Users 
        SET is_verified = 1, verification_token = NULL, token_expiry = NULL 
        WHERE id = ?
        """, self.id)

        self.is_verified = True
        self.verification_token = None
        self.token_expiry = None

        conn.commit()
        cursor.close()
        conn.close()

        return True

    def update_verification_token(self):
        """Generate a new verification token"""
        token = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=app.config['VERIFICATION_TOKEN_EXPIRY'])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE Users 
        SET verification_token = ?, token_expiry = ? 
        WHERE id = ?
        """, token, expiry, self.id)

        self.verification_token = token
        self.token_expiry = expiry

        conn.commit()
        cursor.close()
        conn.close()

        return token

    @classmethod
    def create_user(cls, name, surname, email, password):
        """Create a new user with verification token"""
        # Generate password hash
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')

        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        token_expiry = datetime.utcnow() + timedelta(hours=app.config['VERIFICATION_TOKEN_EXPIRY'])

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            raise ValueError("Invalid email format")

        # Insert user into database
        cursor.execute("""
        INSERT INTO Users (name, surname, email, password_hash, is_verified, verification_token, token_expiry)
        VALUES (?, ?, ?, ?, 0, ?, ?)
        """, name, surname, email, password_hash, verification_token, token_expiry)

        cursor.execute("SELECT @@IDENTITY")
        user_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

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
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
        FROM Users 
        WHERE email = ?
        """, email)

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
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
        return None

    @classmethod
    def get_user_by_id(cls, user_id):
        """Get a user by ID"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
        FROM Users 
        WHERE id = ?
        """, user_id)

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
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
        return None

    @classmethod
    def get_user_by_token(cls, token):
        """Get a user by verification token"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, name, surname, email, password_hash, is_verified, verification_token, token_expiry
        FROM Users 
        WHERE verification_token = ?
        """, token)

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
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
        return None


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

# YogaClass model
class YogaClass:
    def __init__(self, id=None, name=None, instructor=None, date_time=None, duration=75,capacity=None, status='active', location=None):
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
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if the class is in the past
        if self.date_time < datetime.now():
            cursor.close()
            conn.close()
            raise ValueError("Cannot create a class in the past")

        if self.id is None:
            cursor.execute("""
            INSERT INTO YogaClasses (name, instructor, date_time, duration, capacity, status, location)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, self.name, self.instructor, self.date_time, self.duration, self.capacity, self.status, self.location)

            cursor.execute("SELECT @@IDENTITY")
            self.id = cursor.fetchone()[0]
        else:
            # This is an existing class being updated
            cursor.execute("""
            UPDATE YogaClasses 
            SET name = ?, instructor = ?, date_time = ?, duration = ?, capacity = ?, status = ?, location = ?
            WHERE id = ?
            """, self.name, self.instructor, self.date_time, self.duration, self.capacity, self.status, self.id, self.location)

        conn.commit()
        cursor.close()
        conn.close()

        return self.id

    def cancel(self):
        """Cancel this yoga class and all associated bookings"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Update the class status to cancelled
        self.status = 'cancelled'
        cursor.execute("UPDATE YogaClasses SET status = 'cancelled' WHERE id = ?", self.id)

        # Update all active bookings for this class to cancelled
        cursor.execute("UPDATE Bookings SET status = 'cancelled' WHERE class_id = ? AND status = 'active'", self.id)

        # Get the count of affected bookings
        cursor.execute("SELECT @@ROWCOUNT")
        affected_bookings = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        return affected_bookings

    def get_booking_count(self):
        """Get the number of active bookings for this class"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT COUNT(*) 
        FROM Bookings 
        WHERE class_id = ? AND status = 'active'
        """, self.id)

        count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return count

    def spots_left(self):
        """Calculate how many spots are left in this class"""
        return self.capacity - self.get_booking_count()

    def is_full(self):
        """Check if the class is fully booked"""
        return self.spots_left() <= 0

    def to_dict(self):
        """Convert class to dictionary format for API responses"""
        formatted_date_time = self.date_time.strftime('%d/%m/%Y %H:%M')

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

        return {
            'class-id': self.id,
            'name': self.name,
            'teacher': self.instructor,
            'date and time': formatted_date_time,
            'duration': self.duration,
            'spots total': self.capacity,
            'spots left': self.spots_left() if self.id else self.capacity,
            'status': self.status,
            'location': self.location,
            'location_url': google_maps_url
        }

    @classmethod
    def get_by_id(cls, class_id):
        """Get a yoga class by ID"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, instructor, date_time, duration, capacity, status, location FROM YogaClasses WHERE id = ?", class_id)
        row = cursor.fetchone()

        cursor.close()
        conn.close()

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
        """Get all future active classes"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT YC.id, YC.name, YC.instructor, YC.date_time, YC.duration, YC.capacity, YC.status, YC.location
        FROM YogaClasses YC
        WHERE YC.date_time > GETDATE() AND YC.status = 'active'
        """)


        classes = []
        for row in cursor.fetchall():
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
            classes.append(yoga_class.to_dict())

        cursor.close()
        conn.close()

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
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get the yoga class
        yoga_class = YogaClass.get_by_id(self.class_id)

        if not yoga_class:
            cursor.close()
            conn.close()
            raise ValueError("Yoga class does not exist")

        # Check if class is in the past
        if yoga_class.date_time < datetime.now():
            cursor.close()
            conn.close()
            raise ValueError("Cannot book a class in the past")

        # Check class capacity
        if yoga_class.is_full():
            cursor.close()
            conn.close()
            raise ValueError(f"Class {self.class_id} is fully booked")

        # Check if user already has a booking for this class
        cursor.execute("SELECT COUNT(*) FROM Bookings WHERE class_id = ? AND user_id = ? AND status = 'active'",
                       self.class_id, self.user_id)
        current_booking = cursor.fetchone()[0]

        if current_booking > 0:
            cursor.close()
            conn.close()
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
            cursor.close()
            conn.close()
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
        cursor.close()
        conn.close()

        return self.id

    def cancel(self):
        """Cancel this booking"""
        conn = get_db_connection()
        cursor = conn.cursor()

        self.status = 'cancelled'
        cursor.execute("UPDATE Bookings SET status = 'cancelled' WHERE id = ?", self.id)

        conn.commit()
        cursor.close()
        conn.close()

        return True

    def to_dict(self):
        """Convert booking to a dictionary for API responses"""
        # First, get the yoga class details
        yoga_class = YogaClass.get_by_id(self.class_id)

        formatted_date_time = None
        class_name = None
        instructor = None
        location=None
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

        return {
            'booking-id': self.id,
            'class-id': self.class_id,
            'class': class_name,
            'teacher': instructor,
            'date and time': formatted_date_time,
            'booking-status': self.status,
            'location_url': location
        }

    @classmethod
    def get_by_id(cls, booking_id):
        """Get a booking by ID"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, user_id, class_id, booking_date, status 
        FROM Bookings 
        WHERE id = ?
        """, booking_id)

        row = cursor.fetchone()

        cursor.close()
        conn.close()

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
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT B.id, B.user_id, B.class_id, B.booking_date, B.status, YC.location
        FROM Bookings B
        JOIN YogaClasses YC ON B.class_id = YC.id
        WHERE B.user_id = ? AND B.status = 'active' AND YC.date_time > GETDATE()
        """, user_id)

        # print(cursor.fetchall())

        bookings = []
        for row in cursor.fetchall():
            booking = cls(
                id=row[0],
                user_id=row[1],
                class_id=row[2],
                booking_date=row[3],
                status=row[4],
            )

            booking_dict = booking.to_dict()
            encoded_location = row[5].replace(' ', '+')
            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"
            booking_dict['location_url'] = google_maps_url  # Add the location url here
            booking_dict['location'] = row[5]  # Add the location here
            bookings.append(booking_dict)

        cursor.close()
        conn.close()

        return bookings

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

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    data = request.get_json()
    user = User.get_user_by_email(data['email'])

    if not user:
        return jsonify({'error': 'User not found'}), 404

    if user.is_verified:
        return jsonify({'message': 'User is already verified'}), 200

    user.update_verification_token()
    send_verification_email(user)

    return jsonify({'message': 'Verification email resent'}), 200

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
    conn = get_db_connection()
    cursor = conn.cursor()

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

    cursor.close()
    conn.close()

    return jsonify(users)

# Admin route to verify users (for testing)
@app.route('/admin/verify-user/<int:user_id>', methods=['POST'])
def admin_verify_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE Users SET is_verified = 1 WHERE id = ?", user_id)

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'message': f'User {user_id} verified successfully'}), 200

# Admin route to get all verification tokens (for testing)
@app.route('/admin/verification-tokens', methods=['GET'])
def admin_get_verification_tokens():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, email, verification_token, token_expiry FROM Users WHERE verification_token IS NOT NULL")

    tokens = []
    for row in cursor.fetchall():
        tokens.append({
            'user_id': row[0],
            'email': row[1],
            'verification_token': row[2],
            'token_expiry': row[3].isoformat() if row[3] else None
        })

    cursor.close()
    conn.close()

    return jsonify(tokens)

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
@login_required
def delete_class(class_id):
    try:
        # Get the class by ID
        yoga_class = YogaClass.get_by_id(class_id)

        if not yoga_class:
            return jsonify({'error': 'Class not found'}), 404

        # Cancel the class
        affected_bookings = yoga_class.cancel()

        return jsonify({
            'message': f'Class {class_id} cancelled successfully',
            'affected_bookings': affected_bookings
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to cancel class: {str(e)}'}), 500

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
    complete_path = os.path.join(root_dir(),"static", path)
    ext = os.path.splitext(path)[1]
    mimetype = mimetypes.get(ext, "text/html")
    content = get_file(complete_path)
    return Response(content, mimetype=mimetype)

if __name__ == '__main__':
    app.run(host='0.0.0.0',debug=True, port=8000)