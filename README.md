# Carevo Backend

A Flask-based backend API for the Carevo career guidance application. This backend provides user authentication, AI-powered career recommendations, and mental health chat functionality.

## Features

- **User Authentication**: Signup and login functionality with password hashing
- **Career Quiz Analysis**: AI-powered analysis of career quiz responses using Google Gemini
- **Mental Health Chat**: AI-assisted mental health support for students
- **User Profile Management**: Update and retrieve user information
- **MongoDB Integration**: Data persistence using MongoDB

## Tech Stack

- **Framework**: Flask
- **Database**: MongoDB (via PyMongo)
- **AI**: Google Gemini API
- **Authentication**: Werkzeug password hashing
- **CORS**: Flask-CORS for cross-origin requests

## API Endpoints

### Authentication
- `POST /signup` - User registration
- `POST /login` - User login
- `GET /user` - Get user profile

### AI Services
- `POST /ai` - Career quiz analysis
- `POST /mental_health_chat` - Mental health chat support

### User Management
- `PATCH /user/update` - Update user data

## Setup Instructions

### Prerequisites
- Python 3.8+
- MongoDB database
- Google Gemini API key

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Pulkit-jhamb/carevo-backend.git
   cd carevo-backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**
   Create a `.env` file in the root directory with:
   ```
   MONGO_URI=your_mongodb_connection_string
   SECRET_KEY=your_secret_key
   GEMINI_API_KEY=your_gemini_api_key
   ```

5. **Run the application**
   ```bash
   python main.py
   ```

The server will start on `http://localhost:5001`

## API Documentation

### Signup
```json
POST /signup
{
  "email": "user@example.com",
  "password": "password123",
  "name": "John Doe",
  "institute": "University Name",
  "dob": "1995-01-01",
  "studentType": "college",
  "degree": "Bachelor's",
  "major": "Computer Science",
  "year": "3"
}
```

### Login
```json
POST /login
{
  "email": "user@example.com",
  "password": "password123"
}
```

### Career Quiz Analysis
```json
POST /ai
{
  "prompt": "Career quiz responses..."
}
```

### Mental Health Chat
```json
POST /mental_health_chat
{
  "email": "user@example.com",
  "message": "I'm feeling stressed about my career choices..."
}
```

## Student Types

The application supports two types of students:

### School Students
- Required fields: `email`, `password`, `name`, `institute`, `dob`, `studentType`, `class`

### College Students
- Required fields: `email`, `password`, `name`, `institute`, `dob`, `studentType`, `degree`, `major`, `year`

## Security Features

- Password hashing using Werkzeug
- CORS configuration for cross-origin requests
- Environment variable management
- Input validation and sanitization

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License. 