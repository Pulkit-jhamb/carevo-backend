from datetime import datetime, timedelta
import uuid
import random
import json
import re
from flask import Flask, request, jsonify, make_response
from flask_pymongo import PyMongo
from flask_cors import CORS
from dotenv import load_dotenv
import os
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
import jwt

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

QUIZ_CACHE_DAYS = int(os.getenv("QUIZ_CACHE_DAYS", "7"))
TRAITS = ["analytical", "creative", "leadership", "sociable", "structured"]

# --- Enhanced AI Quiz Generation Utilities ---

def call_llm_generate_quiz(student_profile):
    """Generate personalized quiz questions based on student profile"""
    try:
        # Create detailed prompt based on student data
        student_context = f"""
        Student Profile:
        - Name: {student_profile.get('name', 'Student')}
        - Type: {student_profile.get('studentType', 'Unknown')}
        - Institute: {student_profile.get('institute', 'Not specified')}
        - CGPA: {student_profile.get('cgpa', 'Not specified')}
        - Major/Degree: {student_profile.get('major', 'Not specified')} / {student_profile.get('degree', 'Not specified')}
        - Year: {student_profile.get('year', 'Not specified')}
        - Projects: {len(student_profile.get('projects', []))} projects completed
        - Certifications: {len(student_profile.get('certifications', []))} certifications
        - Extracurricular: {len(student_profile.get('extracurricularActivities', []))} activities
        - Subjects: {student_profile.get('subjects', 'Not specified')}
        """
        
        prompt = f"""You are an expert psychometric test designer. Create exactly 30 personalized multiple-choice questions for a student based on their profile.

        {student_context}

        Generate questions that assess these 5 personality traits:
        1. analytical - logical thinking, problem-solving, data analysis
        2. creative - imagination, innovation, artistic thinking
        3. leadership - taking charge, influencing others, decision-making
        4. sociable - social skills, teamwork, communication
        5. structured - organization, planning, attention to detail

        Requirements:
        - Questions should be relevant to the student's academic background and experiences
        - Each question should have exactly 4 options (A, B, C, D)
        - Each option should have weights for all 5 traits (0-3 scale)
        - Questions should cover scenarios relevant to their field of study
        - Include questions about study habits, career aspirations, problem-solving approaches
        - Make questions realistic and relatable to Indian students

        Return ONLY a valid JSON array with this exact structure:
        [
          {{
            "id": "q1",
            "text": "When working on a group project in {student_profile.get('major', 'your field')}, what is your preferred approach?",
            "options": [
              {{
                "id": "A",
                "text": "Create a detailed project timeline and assign specific tasks",
                "weights": {{"analytical": 2, "creative": 1, "leadership": 3, "sociable": 2, "structured": 3}}
              }},
              {{
                "id": "B", 
                "text": "Brainstorm innovative solutions and explore creative possibilities",
                "weights": {{"analytical": 1, "creative": 3, "leadership": 2, "sociable": 2, "structured": 1}}
              }},
              {{
                "id": "C",
                "text": "Focus on building team harmony and ensuring everyone contributes",
                "weights": {{"analytical": 1, "creative": 1, "leadership": 2, "sociable": 3, "structured": 2}}
              }},
              {{
                "id": "D",
                "text": "Analyze the problem systematically and create logical solutions",
                "weights": {{"analytical": 3, "creative": 1, "leadership": 2, "sociable": 1, "structured": 2}}
              }}
            ]
          }}
        ]

        Generate exactly 30 questions following this pattern, ensuring variety and relevance to the student's profile."""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        # Clean the response text
        response_text = response.text.strip()
        
        # Remove any markdown formatting
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*$', '', response_text)
        
        # Try to parse the JSON
        quiz_data = json.loads(response_text)
        
        # Validate the structure
        if not isinstance(quiz_data, list) or len(quiz_data) != 30:
            print(f"Invalid quiz structure: expected 30 questions, got {len(quiz_data) if isinstance(quiz_data, list) else 'non-list'}")
            return None
            
        # Validate each question
        for i, question in enumerate(quiz_data):
            if not all(key in question for key in ['id', 'text', 'options']):
                print(f"Question {i} missing required fields")
                return None
                
            if len(question['options']) != 4:
                print(f"Question {i} doesn't have exactly 4 options")
                return None
                
            for j, option in enumerate(question['options']):
                if not all(key in option for key in ['id', 'text', 'weights']):
                    print(f"Question {i}, option {j} missing required fields")
                    return None
                    
                weights = option['weights']
                if not all(trait in weights for trait in TRAITS):
                    print(f"Question {i}, option {j} missing trait weights")
                    return None
        
        return quiz_data
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        return None
    except Exception as e:
        print(f"Error generating quiz: {e}")
        return None

def call_llm_conclusion(student_id, trait_scores):
    """Generate personalized conclusion based on trait scores and student profile"""
    try:
        # Get student profile
        user = users.find_one({"email": student_id})
        if not user:
            return None
            
        # Calculate percentages
        max_possible = 30 * 3  # 30 questions, max 3 points per trait
        trait_percentages = {trait: (score / max_possible) * 100 for trait, score in trait_scores.items()}
        
        student_context = f"""
        Student Profile:
        - Name: {user.get('name', 'Student')}
        - Type: {user.get('studentType', 'Unknown')}
        - Institute: {user.get('institute', 'Not specified')}
        - Major/Field: {user.get('major', user.get('class', 'Not specified'))}
        - CGPA/Performance: {user.get('cgpa', 'Not available')}
        - Projects: {len(user.get('projects', []))} completed
        - Certifications: {len(user.get('certifications', []))} obtained
        - Extracurricular: {len(user.get('extracurricularActivities', []))} activities
        
        Psychometric Scores:
        - Analytical: {trait_scores['analytical']}/{max_possible} ({trait_percentages['analytical']:.1f}%)
        - Creative: {trait_scores['creative']}/{max_possible} ({trait_percentages['creative']:.1f}%)
        - Leadership: {trait_scores['leadership']}/{max_possible} ({trait_percentages['leadership']:.1f}%)
        - Social: {trait_scores['sociable']}/{max_possible} ({trait_percentages['sociable']:.1f}%)
        - Structured: {trait_scores['structured']}/{max_possible} ({trait_percentages['structured']:.1f}%)
        """
        
        prompt = f"""You are an expert career counselor and psychologist. Analyze this student's psychometric test results and create a comprehensive personality profile and career guidance.

        {student_context}

        Create a detailed analysis that includes:

        1. **Headline**: A catchy, personalized headline describing their personality type
        2. **Summary**: 2-3 sentences summarizing their core personality traits
        3. **Top Capabilities**: List their strongest 3-4 capabilities based on highest scores
        4. **Recommended Career Path**: Specific career recommendations that align with their profile and academic background
        5. **Strengths**: Detailed explanation of their key strengths
        6. **Growth Areas**: Areas where they can develop further (lowest scoring traits)
        7. **Suggested Next Steps**: Specific, actionable steps for career development
        8. **Confidence Level**: How confident this assessment is based on score patterns

        Consider:
        - Their academic background and field of study
        - Current projects and achievements
        - Balance of technical vs. soft skills
        - Career opportunities in India
        - Alignment between personality and chosen field

        Return ONLY a valid JSON object with this structure:
        {{
          "headline": "The Strategic Problem-Solver",
          "summary": "You demonstrate strong analytical thinking combined with leadership potential...",
          "top_capabilities": ["Strategic Thinking", "Problem Solving", "Team Leadership"],
          "recommended_path": "Based on your profile, consider roles in...",
          "strengths": "Your analytical mindset and structured approach...",
          "growth_areas": ["Creative Expression", "Social Networking"],
          "suggested_next_steps": [
            "Develop creative problem-solving skills through design thinking workshops",
            "Join leadership roles in college clubs or societies",
            "Build a portfolio showcasing analytical projects"
          ],
          "confidence": "high"
        }}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        # Clean and parse response
        response_text = response.text.strip()
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*$', '', response_text)
        
        conclusion_data = json.loads(response_text)
        
        # Validate structure
        required_fields = ['headline', 'summary', 'top_capabilities', 'recommended_path', 'strengths', 'growth_areas', 'suggested_next_steps', 'confidence']
        if not all(field in conclusion_data for field in required_fields):
            print("Missing required fields in conclusion")
            return None
            
        return conclusion_data
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error in conclusion: {e}")
        return None
    except Exception as e:
        print(f"Error generating conclusion: {e}")
        return None

def fallback_generate_quiz(student_profile):
    """Generate personalized fallback quiz based on student profile"""
    student_type = student_profile.get('studentType', 'college')
    major = student_profile.get('major', student_profile.get('class', 'General'))
    name = student_profile.get('name', 'Student')
    
    # Base personalized questions
    questions_templates = [
        {
            "text": f"When studying {major} concepts, what approach works best for you?",
            "options": [
                {"text": "Create detailed notes and structured study plans", "weights": {"analytical": 2, "creative": 1, "leadership": 1, "sociable": 1, "structured": 3}},
                {"text": "Explore creative applications and real-world connections", "weights": {"analytical": 1, "creative": 3, "leadership": 1, "sociable": 1, "structured": 1}},
                {"text": "Form study groups and discuss concepts with peers", "weights": {"analytical": 1, "creative": 1, "leadership": 2, "sociable": 3, "structured": 1}},
                {"text": "Analyze problems systematically step by step", "weights": {"analytical": 3, "creative": 1, "leadership": 1, "sociable": 1, "structured": 2}}
            ]
        },
        {
            "text": f"In your {major} projects, what role do you naturally take?",
            "options": [
                {"text": "Project manager ensuring deadlines are met", "weights": {"analytical": 2, "creative": 1, "leadership": 3, "sociable": 2, "structured": 3}},
                {"text": "Creative innovator bringing new ideas", "weights": {"analytical": 1, "creative": 3, "leadership": 2, "sociable": 1, "structured": 1}},
                {"text": "Team coordinator facilitating collaboration", "weights": {"analytical": 1, "creative": 1, "leadership": 2, "sociable": 3, "structured": 2}},
                {"text": "Technical analyst solving complex problems", "weights": {"analytical": 3, "creative": 1, "leadership": 1, "sociable": 1, "structured": 2}}
            ]
        }
    ]
    
    # Generate 30 questions with variations
    quiz = []
    for i in range(30):
        template = questions_templates[i % len(questions_templates)]
        question = {
            "id": f"q{i+1}",
            "text": template["text"],
            "options": [
                {"id": "A", "text": template["options"][0]["text"], "weights": template["options"][0]["weights"]},
                {"id": "B", "text": template["options"][1]["text"], "weights": template["options"][1]["weights"]},
                {"id": "C", "text": template["options"][2]["text"], "weights": template["options"][2]["weights"]},
                {"id": "D", "text": template["options"][3]["text"], "weights": template["options"][3]["weights"]}
            ]
        }
        quiz.append(question)
    
    return quiz

def fallback_conclusion(trait_scores, student_id=None):
    """Enhanced fallback conclusion with student context"""
    student_profile = {}
    if student_id:
        user = users.find_one({"email": student_id})
        if user:
            student_profile = user
    
    top_traits = sorted(trait_scores.items(), key=lambda x: -x[1])[:3]
    student_name = student_profile.get('name', 'Student')
    major = student_profile.get('major', student_profile.get('class', 'your field'))
    
    return {
        "headline": f"The {top_traits[0][0].title()} {student_profile.get('studentType', 'Student').title()}",
        "summary": f"Based on your responses, {student_name}, you show strong {top_traits[0][0]} tendencies, making you well-suited for {major} and related fields.",
        "top_capabilities": [trait.title().replace('_', ' ') for trait, _ in top_traits],
        "recommended_path": f"Consider career paths that leverage your {top_traits[0][0]} strengths in {major} field, such as research, analysis, or specialized roles.",
        "strengths": f"Your strongest areas are {', '.join([trait.replace('_', ' ') for trait, _ in top_traits])}, which are valuable in today's competitive landscape.",
        "growth_areas": [trait.title().replace('_', ' ') for trait, score in trait_scores.items() if score < 15],
        "suggested_next_steps": [
            f"Develop your {top_traits[0][0]} skills through relevant projects",
            f"Explore career opportunities in {major} that match your profile",
            "Build a portfolio showcasing your strongest capabilities"
        ],
        "confidence": "medium"
    }

# --- Quiz Endpoints ---

@app.route("/quiz/generate", methods=["POST"])
def generate_quiz():
    data = request.get_json()
    student_id = data.get("studentId")
    user = users.find_one({"email": student_id})
    if not user:
        return jsonify({"error": "Student not found"}), 404
    now = datetime.utcnow()
    quiz_doc = mongo.db.quizzes.find_one({
        "studentId": student_id,
        "expiresAt": {"$gt": now}
    })
    if quiz_doc:
        return jsonify({
            "quizId": quiz_doc["quizId"],
            "questions": quiz_doc["questions"]
        }), 200
    
    # Try AI generation first
    quiz_json = call_llm_generate_quiz(user)
    if not quiz_json:
        # Use enhanced fallback
        quiz_json = fallback_generate_quiz(user)
    
    quiz_id = str(uuid.uuid4())
    mongo.db.quizzes.insert_one({
        "studentId": student_id,
        "quizId": quiz_id,
        "questions": quiz_json,
        "createdAt": now,
        "expiresAt": now + timedelta(days=QUIZ_CACHE_DAYS)
    })
    return jsonify({
        "quizId": quiz_id,
        "questions": quiz_json
    }), 200

@app.route("/quiz/submit", methods=["POST"])
def submit_quiz():
    data = request.get_json()
    student_id = data.get("studentId")
    quiz_id = data.get("quizId")
    answers = data.get("answers")  # {question_id: option_id}
    quiz_doc = mongo.db.quizzes.find_one({"quizId": quiz_id, "studentId": student_id})
    if not quiz_doc:
        return jsonify({"error": "Quiz not found"}), 404
    
    trait_scores = {t: 0 for t in TRAITS}
    for q in quiz_doc["questions"]:
        qid = q["id"]
        opt_id = answers.get(qid)
        opt = next((o for o in q["options"] if o["id"] == opt_id), None)
        if opt:
            for t, v in opt["weights"].items():
                trait_scores[t] += v
    
    mongo.db.quiz_answers.insert_one({
        "studentId": student_id,
        "quizId": quiz_id,
        "answers": answers,
        "submittedAt": datetime.utcnow()
    })
    
    # Try AI conclusion first
    conclusion_json = call_llm_conclusion(student_id, trait_scores)
    if not conclusion_json:
        # Use enhanced fallback
        conclusion_json = fallback_conclusion(trait_scores, student_id)
    
    mongo.db.quiz_results.insert_one({
        "studentId": student_id,
        "quizId": quiz_id,
        "resultJson": conclusion_json,
        "createdAt": datetime.utcnow()
    })
    return jsonify(conclusion_json), 200

@app.route("/quiz/result", methods=["GET"])
def get_quiz_result():
    student_id = request.args.get("studentId")
    result = mongo.db.quiz_results.find_one(
        {"studentId": student_id},
        sort=[("createdAt", -1)]
    )
    if not result:
        return jsonify({"error": "No result found"}), 404
    return jsonify(result["resultJson"]), 200

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
    update_fields = {}

    # Update basic fields
    for field in ["conclusion", "recommendations", "quiz_result"]:
        if field in data:
            update_fields[field] = data[field]

    # Add other fields as needed...

    if not email or not update_fields:
        return jsonify({"error": "Missing email or fields to update"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": update_fields}
    )
    if result.matched_count:
        return jsonify({"message": "User updated"}), 200
    return jsonify({"error": "User not found"}), 404

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
    email = data.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404

    quiz_result = user.get("quiz_result")
    if not quiz_result:
        quiz_doc = mongo.db.quiz_results.find_one({"studentId": email}, sort=[("createdAt", -1)])
        quiz_result = quiz_doc["resultJson"] if quiz_doc else None

    # If either is missing, return a helpful message
    if not user or not quiz_result:
        return jsonify({
            "plan": "Your academic plan cannot be generated until you complete your profile and quiz. Please make sure you have filled out your profile and completed the quiz for a personalized plan."
        })

    plan_prompt = f"""
    You are an expert academic counselor for Indian students.
    ONLY use the information provided below. If any information is missing, DO NOT ask the user for it. Generate a concise, actionable, and achievable academic plan for the next 6 months.

    Student Profile:
    {json.dumps(user, indent=2)}

    Quiz Analysis:
    {json.dumps(quiz_result, indent=2)}

    The plan should:
    - Be tailored to the student's strengths, growth areas, and recommended career path from the quiz analysis
    - Include 3-5 specific, actionable steps for academic improvement
    - Suggest subject-wise focus areas, time management strategies, and skill development tasks
    - Be realistic and achievable for a student in their current grade/year
    - Use clear, encouraging language

    Return only the plan text. Do NOT ask for more information.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=plan_prompt,
        )
        plan = response.text.strip()
    except Exception as e:
        plan = "Sorry, could not generate a personalized academic plan at this time."

    return jsonify({"plan": plan})

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
        quiz_result = user.get("quiz_result")
        if not quiz_result:
            quiz_doc = mongo.db.quiz_results.find_one({"studentId": email}, sort=[("createdAt", -1)])
            quiz_result = quiz_doc["resultJson"] if quiz_doc else None

        prompt = f"""
        You are an expert academic counselor for Indian students.
        Based on the student's profile and quiz analysis below, generate a concise academic plan for the next 6 months.

        REQUIREMENTS:
        - The main expert plan should be around 200 words, clear and actionable.
        - Do NOT include any links or external resources.
        - After the explanation, provide exactly 5 actionable tasks as a bulleted list, each on a new line starting with '- '.
        - For any headings or key points, use Markdown bold (**HEADING**) instead of asterisks or all caps.
        - Use only the information provided below. Do NOT ask the user for more info.

        STUDENT PROFILE:
        {json.dumps(user, indent=2)}

        QUIZ ANALYSIS:
        {json.dumps(quiz_result, indent=2)}

        Return only the plan and the 5 bullet points.
        """
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

@app.route("/user/quiz-result", methods=["POST"])
def save_quiz_result():
    data = request.get_json()
    email = data.get("email")
    quiz_result = data.get("quiz_result")
    if not email or quiz_result is None:
        return jsonify({"error": "Missing email or quiz_result"}), 400
    result = users.update_one(
        {"email": email},
        {"$set": {"quiz_result": quiz_result}}
    )
    if result.matched_count:
        return jsonify({"message": "Quiz result saved"}), 200
    return jsonify({"error": "User not found"}), 404

@app.route("/user/quiz-result/get", methods=["GET"])
def get_user_quiz_result():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400
    user = users.find_one({"email": email}, {"_id": 0, "quiz_result": 1})
    if not user or "quiz_result" not in user:
        return jsonify({"quiz_result": None}), 200
    return jsonify({"quiz_result": user["quiz_result"]}), 200

@app.route("/user/quiz-result", methods=["DELETE"])
def delete_quiz_result():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400
    result = users.update_one(
        {"email": email},
        {"$unset": {"quiz_result": ""}}
    )
    if result.matched_count:
        return jsonify({"message": "Quiz result deleted"}), 200
    return jsonify({"error": "User not found"}), 404

@app.route("/user/save-academic-plan", methods=["POST"])
def save_academic_plan():
    data = request.get_json()
    email = data.get("email")
    academic_plan = data.get("academic_plan")
    print("Saving plan for:", email)
    print("Plan:", academic_plan)
    if not email or not academic_plan:
        return jsonify({"error": "Missing email or academic plan"}), 400

    result = mongo.db.quiz_results.update_one(
        {"studentId": email},
        {"$set": {"accepted_study_plan": academic_plan}},
        upsert=True
    )
    print("Matched count:", result.matched_count, "Upserted id:", result.upserted_id)
    if result.matched_count or result.upserted_id:
        return jsonify({"message": "Academic plan saved!"}), 200
    return jsonify({"error": "User not found"}), 404

@app.route("/user/study-plan", methods=["GET"])
def get_study_plan():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    # Get overall percentage from users database
    user = mongo.db.users.find_one({"email": email}, {"_id": 0, "termData": 1})
    overall_percentage = None
    if user and "termData" in user and user["termData"]:
        valid_terms = [term for term in user["termData"] if term.get("percentage")]
        if valid_terms:
            avg = sum(float(term["percentage"]) for term in valid_terms) / len(valid_terms)
            overall_percentage = round(avg, 1)

    # Get study plan and tasks from quiz_results database
    quiz_doc = mongo.db.quiz_results.find_one({"studentId": email}, {"_id": 0, "accepted_study_plan": 1, "tasks": 1})
    study_plan = quiz_doc.get("accepted_study_plan") if quiz_doc else None
    tasks = quiz_doc.get("tasks") if quiz_doc and "tasks" in quiz_doc else []

    return jsonify({
        "overall_percentage": overall_percentage,
        "study_plan": study_plan,
        "tasks": tasks
    })


if __name__ == "__main__":
    app.run(debug=True , port=5001 , host="0.0.0.0")