from operator import and_

from flask import Flask, request, jsonify, Response, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func
from datetime import datetime, timedelta
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os.path
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yogajan.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'  # Change this to a real secret key in production

# Email configuration
app.config['MAIL_SERVER'] = 'localhost'  # For testing, we'll use a fake SMTP server
app.config['MAIL_PORT'] = 1025  # Default port for the fake SMTP server
app.config['MAIL_USE_TLS'] = False  # Add this line to enable TLS
app.config['MAIL_USERNAME'] = ''  # Not needed for fake SMTP
app.config['MAIL_PASSWORD'] = ''  # Not needed for fake SMTP
app.config['MAIL_DEFAULT_SENDER'] = 'noreply@yogaforjantine.com'
app.config['VERIFICATION_TOKEN_EXPIRY'] = 24  # Hours

db = SQLAlchemy(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True)
    token_expiry = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_verification_token(self):
        # Generate a random token
        self.verification_token = secrets.token_urlsafe(32)
        # Set token expiry (24 hours from now)
        self.token_expiry = datetime.utcnow() + timedelta(hours=app.config['VERIFICATION_TOKEN_EXPIRY'])
        return self.verification_token

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('yoga_class.id'), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')  # active, cancelled

    # Relationships
    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    yoga_class = db.relationship('YogaClass', backref=db.backref('bookings', lazy=True))

    def __init__(self, user_id, class_id):

        # Validate booking constraints
        yoga_class = YogaClass.query.get(class_id)

        # Check if class exists
        # if not yoga_class:
        #     raise ValueError("Yoga class does not exist")

        # Check if class is in the future
        # if yoga_class.date_time < datetime.now():
        #     raise ValueError("Cannot book a class in the past")

        # Check class capacity

        existing_bookings = Booking.query.filter_by(
            class_id=class_id,
            status='active'
        ).count()

        if existing_bookings >= yoga_class.capacity:
            raise ValueError(f"Class {class_id} is fully booked")

        # Student can't book the same class more than one time

        current_booking = Booking.query.filter_by(
            class_id=class_id,
            user_id=user_id,
            status='active'
        ).first()

        if current_booking:
            raise ValueError(f"User {user_id} has already booked for class {class_id}")

        # Student can't book more than one class, that is at the same time

        overlapping_booking = Booking.query.join(YogaClass).filter(
            Booking.user_id == user_id,
            Booking.status == 'active',
            YogaClass.date_time == yoga_class.date_time
        ).first()

        if overlapping_booking:
            raise ValueError(f"User {user_id} already has an active booking at the same time {yoga_class.date_time} in {yoga_class.name} class")

        self.user_id = user_id
        self.class_id = class_id

    def cancel(self):
        """Cancel an existing booking"""
        self.status = 'cancelled'

    def to_dict(self):
        """Convert booking to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'class_id': self.class_id,
            'booking_date': self.booking_date.isoformat(),
            'status': self.status
        }

class YogaClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    instructor = db.Column(db.String(100), nullable=False)
    date_time = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='active')

    def __init__(self, name, instructor, date_time, capacity):
        # Check if the class is in the past
        if date_time < datetime.now():
            raise ValueError("Cannot create a class in the past")
        self.name = name
        self.instructor = instructor
        self.date_time = date_time
        self.capacity = capacity

# Email sending function
def send_verification_email(user):
    # Generate a verification link
    verification_link = f"{request.host_url}verify/{user.verification_token}"

    # Create email content
    html_content = f"""
    <html>
    <body>
        <h1>Welcome to Yoga for Jantine!</h1>
        <p>Hi {user.name}, thank you for signing up. Please click the link below to verify your email address:</p>
        <p><a href="{verification_link}">Verify your email</a></p>
        <p>This link will expire in {app.config['VERIFICATION_TOKEN_EXPIRY']} hours.</p>
        <p>If you didn't create an account, you can ignore this email.</p>
    </body>
    </html>
    """

    # Create email message
    msg = MIMEMultipart()
    msg['Subject'] = 'Verify your email for Yoga for Jantine'
    msg['From'] = app.config['MAIL_DEFAULT_SENDER']
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
        # Uncomment the following lines:
        # with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
        #     server.send_message(msg)

        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            server.starttls()  # Enable TLS
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.send_message(msg)
        return True

    except Exception as e:
        print(f"Error sending verification email: {str(e)}")
        return False

# Create tables
with app.app_context():
    db.create_all()

# User routes
@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()

    # Check if user already exists
    existing_user = User.query.filter_by(email=data['email']).first()
    if existing_user:
        return jsonify({'error': 'Email already registered'}), 400

    new_user = User(
        name=data['name'],
        surname=data['surname'],
        email=data['email'],
        is_verified=False
    )
    new_user.set_password(data['password'])
    new_user.generate_verification_token()

    try:
        db.session.add(new_user)
        db.session.commit()

        # Send verification email
        send_verification_email(new_user)

        return jsonify({
            'message': 'User created! Please check your email to verify your account.',
            'id': new_user.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Could not create user: {str(e)}'}), 400

@app.route('/verify/<token>', methods=['GET'])
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()

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

    user.is_verified = True
    user.verification_token = None
    user.token_expiry = None
    db.session.commit()

    return render_template_string("""
        <h1>Email verified successfully!</h1>
        <p>Your email has been verified. You can now log in to your account.</p>
        <p><a href="/">Return to homepage</a></p>
    """)

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    if user.is_verified:
        return jsonify({'message': 'User is already verified'}), 200

    user.generate_verification_token()
    db.session.commit()

    send_verification_email(user)

    return jsonify({'message': 'Verification email resent'}), 200

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user.check_password(data['password']):
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user.is_verified:
        return jsonify({'error': 'Please verify your email before logging in', 'unverified': True}), 401

    login_user(user)
    return jsonify({'message': 'Logged in successfully!', 'user_id': user.id}), 200

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out successfully!'}), 200

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([
        {
            'id': user.id,
            'name': user.name,
            'surname': user.surname,
            'email': user.email,
            'is_verified': user.is_verified
        } for user in users
    ])

# Admin route to verify users (for testing)
@app.route('/admin/verify-user/<int:user_id>', methods=['POST'])
def admin_verify_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_verified = True
    db.session.commit()
    return jsonify({'message': f'User {user_id} verified successfully'}), 200

# Admin route to get all verification tokens (for testing)
@app.route('/admin/verification-tokens', methods=['GET'])
def admin_get_verification_tokens():
    users = User.query.filter(User.verification_token.isnot(None)).all()
    return jsonify([
        {
            'user_id': user.id,
            'email': user.email,
            'verification_token': user.verification_token,
            'token_expiry': user.token_expiry.isoformat() if user.token_expiry else None
        } for user in users
    ])

# Yoga class routes
@app.route('/classes', methods=['POST'])
def create_class():
    data = request.get_json()
    new_class = YogaClass(
        name=data['name'],
        instructor=data['instructor'],
        date_time=datetime.fromisoformat(data['date_time']),
        capacity=data['capacity']
    )
    db.session.add(new_class)
    db.session.commit()
    return jsonify({'message': 'Class created!', 'id': new_class.id}), 201

# Protect booking routes with login_required
@app.route('/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.get_json()
    try:
        new_booking = Booking(
            user_id=current_user.id,
            class_id=data['class_id']
        )
        db.session.add(new_booking)
        db.session.commit()
        return jsonify({
            'message': 'Booking created!',
            'booking_id': new_booking.id
        }), 201
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400

@app.route('/bookings/<int:booking_id>/cancel', methods=['PUT'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    booking.cancel()
    db.session.commit()
    return jsonify({'message': 'Booking cancelled'})

@app.route('/bookings', methods=['GET'])
@login_required
def get_bookings():
    bookings_to_classes = db.session.query(
        Booking.id.label('booking_id'),
        YogaClass.id.label('class_id'),
        YogaClass.name.label('class_name'),
        YogaClass.instructor.label('class_teacher'),
        YogaClass.date_time.label('class_date_time'),
        Booking.status.label('booking_status')
    ).join(
        YogaClass,
        Booking.class_id == YogaClass.id
    ).filter(
        Booking.status == 'active',
        YogaClass.date_time > datetime.now(),
        Booking.user_id == current_user.id  # Filter by the logged-in user
    ).all()

    return jsonify([{'class': booking_to_class.class_name,
                     'date and time': booking_to_class.class_date_time,
                     'teacher': booking_to_class.class_teacher,
                     'class-id': booking_to_class.class_id,
                     'booking-status': booking_to_class.booking_status,
                     'booking-id': booking_to_class.booking_id
                     }
                    for booking_to_class in bookings_to_classes])


@app.route('/classes', methods=['GET'])
def get_classes():
    classes_with_bookings_count = db.session.query(
        YogaClass,
        func.count(Booking.id).label('booking_count')
    ).outerjoin(
        Booking,
        and_(
            Booking.class_id == YogaClass.id,
            Booking.status == 'active'
        )
    ).filter(
        YogaClass.date_time > datetime.now(),
        YogaClass.status == 'active'
    ).group_by(
        YogaClass.id
    ).all()

    print(classes_with_bookings_count)

    result = [{
        'name': yoga_class.name,
        'date and time': yoga_class.date_time.isoformat(),
        'spots left': f"{yoga_class.capacity-booking_count}",
        'spots total': yoga_class.capacity,
        'teacher': yoga_class.instructor,
        'class-id': yoga_class.id
    } for yoga_class, booking_count in classes_with_bookings_count]

    return jsonify(result)

@app.route('/classes/<int:class_id>', methods=['DELETE'])
@login_required
def delete_class(class_id):
    # Find the class
    yoga_class = YogaClass.query.get_or_404(class_id)

    # Check for active bookings
    active_bookings = Booking.query.filter_by(class_id=class_id, status='active').all()
    booking_count = len(active_bookings)

    # Mark any active bookings as cancelled
    for booking in active_bookings:
        booking.status = 'cancelled'

    # Instead of deleting the class, mark it as "cancelled"
    # You'll need to add a status field to the YogaClass model:
    yoga_class.status = 'cancelled'  # Assume you'll add this field

    # Alternatively, if you don't want to add a status field:
    # Just set the capacity to 0 to prevent new bookings
    # yoga_class.capacity = 0

    try:
        db.session.commit()
        return jsonify({
            'message': f'Class {class_id} cancelled successfully',
            'affected_bookings': booking_count
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to cancel class: {str(e)}'}), 500

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