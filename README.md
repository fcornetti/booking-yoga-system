
# 🧘 Yoga Class Booking System

This is a full-stack web application for managing yoga class bookings. It allows users to sign up, log in, verify their email, book yoga classes, and manage their bookings. Admin users can manage classes and users, including manual verification and viewing verification tokens

## 🌐 Live 

> _https://jantinevanwijlickbooking-e5ehekcmb5gkg2ha.italynorth-01.azurewebsites.net._

---

## 📦 Features

### User Functionality
- User registration and email verification
- Login/logout functionality
- View available yoga classes
- Book or cancel class bookings
- Session timeout with warning modal
- Responsive design and modern UI

### Admin Panel
- View all registered users and their verification status
- View and test email verification tokens
- Manually verify users
- Cancel yoga classes (with booking impact reporting)

---

## 🧰 Tech Stack

| Layer      | Technology        |
|------------|-------------------|
| Frontend   | HTML, CSS, JavaScript |
| Backend    | Python |
| Database   | PostgreSQL |
| Email      | Integrated email verification and token management |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- Node.js (optional, for frontend tooling if needed)

### Backend Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the backend server:

```bash
python app.py
```

3. The server will typically start on `http://127.0.0.1:5000/`

### Frontend Setup

No build tools required—just open `index.html` in your browser.

To connect to the backend, update the `API_URL` value inside the `<script>` section of `index.html`:

```js
const API_URL = 'http://127.0.0.1:5000'; // or your deployed backend URL
```

---

## 🔐 Admin Access

To access the admin panel, log in using:

- **Email:** `admin@jantinevanwijlickyoga.com`
- **Password:** _[Set this in your backend or seed script]_

Admin functionalities include:
- Viewing users
- Managing verification
- Cancelling classes

---

## ✉️ Email Verification

Upon signup, users must verify their email address using a link sent via email. This system supports:

- Manual verification (admin-only)
- Token viewing for testing purposes
- Token expiration handling

---

## 🛡️ Session Timeout

Inactive users are automatically logged out after 10 minutes, with a warning shown 5 minutes beforehand.

---

## 📁 File Structure

```
├── app.py                # Python backend
├── index.html            # Frontend interface
├── static/ or templates/ # (Optional) static assets / HTML templates
├── README.md             # Project documentation
```

---

## 🧪 Testing

- Test user registration, login, class booking and cancellation.
- Admin testing includes token validation and class cancellation impact.

---

## 🙏 Credits

Created for Jantine van Wijlick.
