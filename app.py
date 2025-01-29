from operator import and_
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yogaforjantine.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config["JSON_SORT_KEYS"] = False
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    def __init__(self, name, surname, email):
        self.name = name
        self.surname = surname
        self.email = email.lower()

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

    def __init__(self, name, instructor, date_time, capacity):
        # Check if the class is in the past
        if date_time < datetime.now():
            raise ValueError("Cannot create a class in the past")
        self.name = name
        self.instructor = instructor
        self.date_time = date_time
        self.capacity = capacity

# Create tables
with app.app_context():
    db.create_all()

# User routes
@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    new_user = User(name=data['name'], surname=data['surname'], email=data['email'])
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'message': 'User created!', 'id': new_user.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Could not create user'}), 400

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([{'id': user.id, 'name': user.name, 'surname': user.surname, 'email': user.email} for user in users])

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

@app.route('/bookings', methods=['POST'])
def create_booking():
    data = request.get_json()
    try:
        new_booking = Booking(
            user_id=data['user_id'],
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
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.cancel()
    db.session.commit()
    return jsonify({'message': 'Booking cancelled'})

@app.route('/bookings', methods=['GET'])
def get_bookings():
    # Get active bookings for classes in the future
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
        YogaClass.date_time > datetime.now()
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
        YogaClass.date_time > datetime.now()
    ).group_by(
        YogaClass.id
    ).all()

    print(classes_with_bookings_count)

    result = [{
        'name': yoga_class.name,
        'date and time': yoga_class.date_time.isoformat(),
        'spots left': f"{yoga_class.capacity-booking_count} out of {yoga_class.capacity}",
        'teacher': yoga_class.instructor,
        'class-id': yoga_class.id
    } for yoga_class, booking_count in classes_with_bookings_count]

    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True, port=5001)