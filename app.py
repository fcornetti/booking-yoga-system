from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yogaforjantine.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

class YogaClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    instructor = db.Column(db.String(100), nullable=False)
    date_time = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)

# Create tables
with app.app_context():
    db.create_all()

# Test route
@app.route('/')
def home():
    return jsonify({'message': 'Welcome to Yoga Booking API!'})

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

@app.route('/classes', methods=['GET'])
def get_classes():
    classes = YogaClass.query.all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'instructor': c.instructor,
        'date_time': c.date_time.isoformat(),
        'capacity': c.capacity
    } for c in classes])

if __name__ == '__main__':
    app.run(debug=True, port=5001)