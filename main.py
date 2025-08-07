from flask import Flask, request, jsonify, make_response
from flask_pymongo import PyMongo
from flask_cors import CORS
from dotenv import load_dotenv
import os
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
import jwt
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
GEMINI_API_KEY = "AIzaSyD7rAU5uO8GLPHWa5UroRCsMpOtgWsAH1U" 
client = genai.Client(api_key=GEMINI_API_KEY)         
# Create Flask app
app = Flask(__name__)

CORS(app, origins="*", supports_credentials=True, allow_headers=["*"], methods=["GET", "POST", "PATCH", "OPTIONS"])

# Configure MongoDB
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.secret_key = os.getenv("SECRET_KEY") or "your-secret-key-here"
GEMINI_API_KEY = "AIzaSyCE11D_xtWFBn1SvZE4CHRo9_gl17Ue910"
# Debug if MONGO_URI is missing
if not app.config["MONGO_URI"]:
    raise EnvironmentError("MONGO_URI not found. Check your .env file or os.environ.")

# Initialize Mongo connection
mongo = PyMongo(app)

# Check if mongo instance is valid
if not mongo:
    raise RuntimeError("Failed to initialize PyMongo. Check MONGO_URI connection.")

# Get the "users" collection from the MongoDB database
users = mongo.db.users  # ✅ Only accessed after Mongo is confirmed working

# SIGNUP ROUTE
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()

    # Universal required fields
    required = ["email", "password", "name", "institute", "dob", "studentType"]

    if not all(data.get(f) for f in required):
        return jsonify({"message": "Missing required fields."}), 400

    # Validate studentType-specific required fields
    if data["studentType"] == "school":
        if not data.get("class"):
            return jsonify({"message": "Missing 'class' for school student."}), 400
    elif data["studentType"] == "college":
        for f in ["degree", "major", "year"]:
            if not data.get(f):
                return jsonify({"message": f"Missing '{f}' for college student."}), 400
    else:
        return jsonify({"message": "Invalid student type."}), 400

    # Check if user already exists
    if users.find_one({"email": data["email"]}):
        return jsonify({"message": "User already exists"}), 409

    # Hash the password
    hashed_pw = generate_password_hash(data["password"])

    # Construct full user object
    user_doc = {
        "email": data["email"],
        "password": hashed_pw,
        "name": data["name"],
        "institute": data["institute"],
        "dob": data["dob"],
        "studentType": data["studentType"]
    }

    # Add role-specific fields
    if data["studentType"] == "school":
        user_doc["class"] = data["class"]
    elif data["studentType"] == "college":
        user_doc.update({
            "degree": data["degree"],
            "major": data["major"],
            "year": data["year"]
        })

    # Insert into MongoDB
    users.insert_one(user_doc)

    return jsonify({"message": "User registered successfully"}), 201

# LOGIN ROUTE
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Missing email or password"}), 400

    user = users.find_one({"email": email})
    if user and check_password_hash(user["password"], password):
        # Create JWT token
        token = jwt.encode(
            {
                'email': email,
                'exp': datetime.utcnow() + timedelta(days=7)  # Token expires in 7 days
            },
            app.secret_key,
            algorithm='HS256'
        )
        
        # Create response with user data
        response = make_response(jsonify({
            "message": "Login successful",
            "user": {
                "email": email,
                "name": user.get("name"),
                "studentType": user.get("studentType")
            }
        }), 200)
        
        # Set HTTP-only cookie
        response.set_cookie(
            'auth_token',
            token,
            max_age=7*24*60*60,  # 7 days in seconds
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite='Lax'
        )
        
        return response
    return jsonify({"message": "Invalid credentials"}), 401

# LOGOUT ROUTE
@app.route("/logout", methods=["POST"])
def logout():
    response = make_response(jsonify({"message": "Logged out successfully"}), 200)
    response.delete_cookie('auth_token')
    return response

# CHECK AUTH STATUS
@app.route("/auth/status", methods=["GET"])
def check_auth():
    token = request.cookies.get('auth_token')
    
    if not token:
        return jsonify({"authenticated": False}), 401
    
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
        
        user = users.find_one({"email": email}, {"_id": 0, "password": 0})
        if user:
            return jsonify({
                "authenticated": True,
                "user": user
            }), 200
        else:
            return jsonify({"authenticated": False}), 401
            
    except jwt.ExpiredSignatureError:
        return jsonify({"authenticated": False, "message": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"authenticated": False, "message": "Invalid token"}), 401


@app.route("/user", methods=["GET"])
def get_user():
    email = request.args.get("email")
    if not email:
        return jsonify({"message": "Missing email"}), 400

    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify(user), 200


@app.route('/ai', methods=['POST'])
def ai():
   data = request.get_json()
   prompt = data.get('prompt')
   if not prompt:
       return jsonify({"error": "No prompt provided"}), 400
   try:
       response = client.models.generate_content(
           model="gemini-2.5-flash",
           contents=prompt,
       )
       return jsonify({"response": response.text})
   except Exception as e:
       return jsonify({"error": str(e)}), 500
  
@app.route("/user/update", methods=["PATCH"])
def update_user():
    data = request.get_json()
    email = data.get("email")
    conclusion = data.get("conclusion")
    recommendations = data.get("recommendations")

    if not email:
        return jsonify({"error": "Missing user email"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {
            "conclusion": conclusion,
            "recommendations": recommendations
        }}
    )
    if result.matched_count:
        return jsonify({"message": "User data updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/cgpa", methods=["PATCH"])
def update_cgpa():
    data = request.get_json()
    email = data.get("email")
    cgpa = data.get("cgpa")

    if not email or cgpa is None:
        return jsonify({"error": "Missing email or cgpa"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"cgpa": cgpa}}
    )
    if result.matched_count:
        return jsonify({"message": "CGPA updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/projects", methods=["PATCH"])
def update_projects():
    data = request.get_json()
    email = data.get("email")
    projects = data.get("projects")

    if not email or projects is None:
        return jsonify({"error": "Missing email or projects"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"projects": projects}}
    )
    if result.matched_count:
        return jsonify({"message": "Projects updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/experiences", methods=["PATCH"])
def update_experiences():
    data = request.get_json()
    email = data.get("email")
    experiences = data.get("experiences")

    if not email or experiences is None:
        return jsonify({"error": "Missing email or experiences"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"experiences": experiences}}
    )
    if result.matched_count:
        return jsonify({"message": "Experiences updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/certifications", methods=["PATCH"])
def update_certifications():
    data = request.get_json()
    email = data.get("email")
    certifications = data.get("certifications")

    if not email or certifications is None:
        return jsonify({"error": "Missing email or certifications"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"certifications": certifications}}
    )
    if result.matched_count:
        return jsonify({"message": "Certifications updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/term-data", methods=["PATCH"])
def update_term_data():
    data = request.get_json()
    email = data.get("email")
    term_data = data.get("termData")

    if not email or term_data is None:
        return jsonify({"error": "Missing email or term data"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"termData": term_data}}
    )
    if result.matched_count:
        return jsonify({"message": "Term data updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/extracurricular", methods=["PATCH"])
def update_extracurricular():
    data = request.get_json()
    email = data.get("email")
    extracurricular_activities = data.get("extracurricularActivities")

    if not email or extracurricular_activities is None:
        return jsonify({"error": "Missing email or extracurricular activities"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"extracurricularActivities": extracurricular_activities}}
    )
    if result.matched_count:
        return jsonify({"message": "Extracurricular activities updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/subjects", methods=["PATCH"])
def update_subjects():
    data = request.get_json()
    email = data.get("email")
    subjects = data.get("subjects")

    if not email or subjects is None:
        return jsonify({"error": "Missing email or subjects"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"subjects": subjects}}
    )
    if result.matched_count:
        return jsonify({"message": "Subjects updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/user/study-plan", methods=["PATCH"])
def update_study_plan():
    data = request.get_json()
    email = data.get("email")
    study_plan = data.get("studyPlan")

    if not email or study_plan is None:
        return jsonify({"error": "Missing email or study plan"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": {"studyPlan": study_plan}}
    )
    if result.matched_count:
        return jsonify({"message": "Study plan updated"}), 200
    return jsonify({"message": "User not found"}), 404

@app.route("/academic-planning", methods=["POST"])
def academic_planning():
    data = request.get_json()
    message = data.get("message")
    goals = data.get("goals")
    
    if not message:
        return jsonify({"error": "Missing message"}), 400
    
    # Get user email from JWT token in cookies
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid or expired token"}), 401
    
    # Fetch student details
    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Analyze current academic performance
    current_grades = {}
    if user.get("studentType") == "college":
        if user.get("cgpa"):
            current_grades["CGPA"] = user["cgpa"]
    elif user.get("studentType") == "school":
        if user.get("termData"):
            current_grades["Term Data"] = user["termData"]
        if user.get("subjects"):
            current_grades["Subjects"] = user["subjects"]
    
    # Create comprehensive academic planning prompt
    prompt = f"""You are an expert academic counselor for Indian students. Analyze this student's profile and create a comprehensive study plan.

Student Profile: {user}
Current Academic Performance: {current_grades}
Student's Academic Goals: {goals or "Not specified"}

Based on their current performance and goals, provide:

1. **Grade Analysis**: Compare current performance with past trends
2. **Goal Assessment**: Evaluate if their goals are realistic and achievable
3. **Comprehensive Study Plan**: Create a detailed, structured study plan with:
   - Weekly study schedule
   - Subject-wise focus areas
   - Time management strategies
   - Study techniques recommendations
   - Progress tracking methods
   - Exam preparation timeline

Format the response as a structured study plan that can be saved and followed. Keep it practical and actionable for Indian students."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        # Generate a structured study plan object
        study_plan = {
            "created_at": datetime.now().isoformat(),
            "goals": goals,
            "current_performance": current_grades,
            "plan_content": response.text,
            "tasks": [
                {
                    "id": "1",
                    "title": "Review current academic performance",
                    "completed": False,
                    "category": "analysis"
                },
                {
                    "id": "2", 
                    "title": "Set specific academic goals",
                    "completed": False,
                    "category": "planning"
                },
                {
                    "id": "3",
                    "title": "Create weekly study schedule",
                    "completed": False,
                    "category": "scheduling"
                }
            ]
        }
        
        return jsonify({
            "reply": response.text,
            "study_plan": study_plan
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/mental_health_chat", methods=["POST"])
def mental_health_chat():
    data = request.get_json()
    message = data.get("message")
    
    if not message:
        return jsonify({"error": "Missing message"}), 400
    
    # Get user email from JWT token in cookies
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid or expired token"}), 401
    
    # Fetch student details
    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Compose prompt for AI based on message content
    message_lower = message.lower()
    
    if "anxious" in message_lower or "stressed" in message_lower or "worried" in message_lower:
        prompt = f"You are a mental health counselor for Indian students. Here is the student's profile: {user}.\n\nStudent's message: {message}\n\nProvide empathetic support and practical anxiety management techniques. Focus on breathing exercises, time management, and seeking help from college counselors. Keep response under 50 words and use Indian context."
    elif "academic planning" in message_lower or "academic journey" in message_lower or "subjects" in message_lower or "courses" in message_lower:
        # Enhanced academic planning response
        current_grades = {}
        if user.get("studentType") == "college" and user.get("cgpa"):
            current_grades["CGPA"] = user["cgpa"]
        elif user.get("studentType") == "school":
            if user.get("termData"):
                current_grades["Term Data"] = user["termData"]
            if user.get("subjects"):
                current_grades["Subjects"] = user["subjects"]
        
        prompt = f"""You are an expert academic counselor for Indian students. Here is the student's profile: {user}
Current Academic Performance: {current_grades}

Student's message: {message}

Provide a comprehensive response that:
1. Analyzes their current academic performance in detail with specific observations
2. Identifies strengths and areas for improvement
3. Asks about their specific academic goals and what they want to improve
4. Offers to create a personalized study plan with detailed strategies
5. Mentions that you'll create a comprehensive plan with actionable tasks

Keep response under 200 words and be encouraging. Ask them to share their specific goals."""
    elif "goals" in message_lower and ("academic" in message_lower or "study" in message_lower):
        # User is providing their academic goals
        prompt = f"""You are an academic counselor for Indian students. The student has shared their academic goals: {message}

Based on their goals and profile: {user}

1. Acknowledge their goals and show understanding
2. Ask if they want you to create a comprehensive study plan
3. Mention that you'll analyze their current performance and create a detailed plan with:
   - Weekly study schedules
   - Subject-wise focus areas
   - Time management strategies
   - Study techniques and exam preparation timeline
   - Progress tracking methods
4. Ask for confirmation to proceed

Keep response under 100 words and be encouraging."""
    elif "yes" in message_lower and ("create" in message_lower or "plan" in message_lower or "proceed" in message_lower):
        # User confirmed to create study plan
        current_grades = {}
        if user.get("studentType") == "college" and user.get("cgpa"):
            current_grades["CGPA"] = user["cgpa"]
        elif user.get("studentType") == "school":
            if user.get("termData"):
                current_grades["Term Data"] = user["termData"]
            if user.get("subjects"):
                current_grades["Subjects"] = user["subjects"]
        
        # Create comprehensive study plan
        study_plan_prompt = f"""You are an expert academic counselor for Indian students. Create a comprehensive, detailed study plan.

Student Profile: {user}
Current Academic Performance: {current_grades}

Based on their profile and performance, create a detailed, structured study plan with:

1. **Grade Analysis**: Compare current performance with past trends and identify areas for improvement
2. **Goal Assessment**: Evaluate if their goals are realistic and achievable
3. **Comprehensive Study Plan**: Include:
   - Weekly study schedule with specific time slots
   - Subject-wise focus areas with priority levels
   - Time management strategies and techniques
   - Study techniques and learning methods
   - Progress tracking methods and milestones
   - Exam preparation timeline with specific dates
   - Daily and weekly goals
   - Study environment recommendations
   - Break and rest schedules
   - Motivation and stress management tips

Format the response as a detailed, actionable study plan that can be saved and followed. Make it comprehensive and practical for Indian students. Include specific actionable items and detailed strategies."""

        try:
            study_plan_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=study_plan_prompt,
            )
            
            prompt = f"""Perfect! I've created a comprehensive study plan for you based on your academic profile and goals.

Here's what I've included:
• Analysis of your current performance
• Personalized study schedule
• Subject-wise focus areas
• Time management strategies
• Study techniques and exam preparation timeline

Would you like me to save this study plan to your Study Plan page so you can track your progress and manage your tasks?

Just say "Yes, save it" and I'll add it to your Study Plan page with actionable tasks you can check off as you complete them."""
            
        except Exception as e:
            prompt = f"Sorry, there was an error creating your study plan. Please try again. Error: {str(e)}"
    elif "save" in message_lower and ("yes" in message_lower or "okay" in message_lower):
        # User wants to save the study plan
        prompt = """Excellent! I've saved your study plan to your Study Plan page. 

You can now:
• Visit the Study Plan page to see your complete plan
• Check off tasks as you complete them
• Add new tasks or edit existing ones
• Track your progress over time

Your study plan is now ready to help you achieve your academic goals! 🎯"""
    elif "satisfied" in message_lower or "good" in message_lower or "perfect" in message_lower or "great" in message_lower:
        # User is satisfied with the plan
        prompt = """Great! I'm glad you're satisfied with the study plan. 

Would you like me to save this study plan to your Study Plan page so you can track your progress and manage your tasks?

Just say "Yes, save it" and I'll add it to your Study Plan page with actionable tasks you can check off as you complete them."""
    elif "not satisfied" in message_lower or "change" in message_lower or "modify" in message_lower or "different" in message_lower:
        # User wants changes to the plan
        prompt = """I understand you'd like some changes to the study plan. 

Please let me know what specific aspects you'd like me to modify:
• Study schedule timing
• Subject priorities
• Study techniques
• Time management approach
• Or any other specific areas

I'll create a revised plan that better meets your needs."""
    else:
        # For specific subject/course queries, provide detailed responses
        if any(word in message_lower for word in ["math", "mathematics", "english", "grammar", "science", "physics", "chemistry", "biology", "history", "geography", "economics", "computer", "programming"]):
            prompt = f"""You are an expert academic counselor for Indian students. The student is asking about: {message}

Student Profile: {user}

Provide a comprehensive, detailed response that includes:

1. **Detailed Analysis**: Analyze their current performance in this subject
2. **Specific Recommendations**: 
   - Recommended books and resources
   - Study techniques and strategies
   - Practice methods and exercises
   - Time allocation for this subject
3. **Actionable Steps**: Provide specific, actionable steps they can take
4. **Progress Tracking**: How to measure improvement
5. **Additional Resources**: Online courses, apps, or supplementary materials

Make the response detailed, practical, and actionable. Include specific book recommendations, study schedules, and practice exercises. Keep it comprehensive and helpful for Indian students."""
        else:
            prompt = f"You are an academic counselor for Indian students. Here is the student's profile: {user}.\n\nStudent's message: {message}\n\nRespond empathetically and helpfully, considering their background. Provide practical academic and career guidance. Keep response under 100 words and use Indian context."
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save-study-plan", methods=["POST"])
def save_study_plan():
    data = request.get_json()
    email = data.get("email")
    
    if not email:
        return jsonify({"error": "Missing email"}), 400
    
    # Get user email from JWT token in cookies
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid or expired token"}), 401
    
    # Fetch student details
    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Analyze current academic performance
    current_grades = {}
    if user.get("studentType") == "college":
        if user.get("cgpa"):
            current_grades["CGPA"] = user["cgpa"]
    elif user.get("studentType") == "school":
        if user.get("termData"):
            current_grades["Term Data"] = user["termData"]
        if user.get("subjects"):
            current_grades["Subjects"] = user["subjects"]
    
    # Create comprehensive study plan
    study_plan_prompt = f"""You are an expert academic counselor for Indian students. Create a comprehensive, detailed study plan.

Student Profile: {user}
Current Academic Performance: {current_grades}

Based on their profile and performance, create a detailed, structured study plan with:

1. **Grade Analysis**: Compare current performance with past trends and identify areas for improvement
2. **Goal Assessment**: Evaluate if their goals are realistic and achievable
3. **Comprehensive Study Plan**: Include:
   - Weekly study schedule with specific time slots
   - Subject-wise focus areas with priority levels
   - Time management strategies and techniques
   - Study techniques and learning methods
   - Progress tracking methods and milestones
   - Exam preparation timeline with specific dates
   - Daily and weekly goals
   - Study environment recommendations
   - Break and rest schedules
   - Motivation and stress management tips

Format the response as a detailed, actionable study plan that can be saved and followed. Make it comprehensive and practical for Indian students. Include specific actionable items and detailed strategies."""

    try:
        study_plan_response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=study_plan_prompt,
        )
        
        # Generate a structured study plan object with comprehensive tasks
        study_plan = {
            "created_at": datetime.now().isoformat(),
            "goals": "Academic improvement and goal achievement",
            "current_performance": current_grades,
            "plan_content": study_plan_response.text,
            "tasks": [
                {
                    "id": "1",
                    "title": "Review current academic performance and identify weak areas",
                    "completed": False,
                    "category": "analysis"
                },
                {
                    "id": "2", 
                    "title": "Set specific academic goals for each subject",
                    "completed": False,
                    "category": "planning"
                },
                {
                    "id": "3",
                    "title": "Create weekly study schedule with time slots",
                    "completed": False,
                    "category": "scheduling"
                },
                {
                    "id": "4",
                    "title": "Implement recommended study techniques",
                    "completed": False,
                    "category": "implementation"
                },
                {
                    "id": "5",
                    "title": "Set up progress tracking system",
                    "completed": False,
                    "category": "tracking"
                },
                {
                    "id": "6",
                    "title": "Prepare exam study timeline",
                    "completed": False,
                    "category": "exam-prep"
                },
                {
                    "id": "7",
                    "title": "Organize study materials and resources",
                    "completed": False,
                    "category": "organization"
                },
                {
                    "id": "8",
                    "title": "Create daily study routine",
                    "completed": False,
                    "category": "routine"
                }
            ]
        }
        
        # Save to database
        result = users.update_one(
            {"email": email},
            {"$set": {"studyPlan": study_plan}}
        )
        
        if result.matched_count:
            return jsonify({
                "message": "Study plan saved successfully",
                "study_plan": study_plan
            }), 200
        else:
            return jsonify({"error": "User not found"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True , port=5001 , host="0.0.0.0")
