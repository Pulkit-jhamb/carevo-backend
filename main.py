from datetime import datetime, timedelta
import uuid
import random
import json
import re
import requests
from flask import Flask, request, jsonify, make_response
from flask_pymongo import PyMongo
from flask_cors import CORS
from dotenv import load_dotenv
import os
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from gemini_key_manager import get_active_gemini_key

import time

def call_gemini_api_with_retry(prompt, max_retries=3):
    """Call Gemini API with retry mechanism"""
    for attempt in range(max_retries):
        try:
            result = call_gemini_api(prompt)
            if result:
                return result
            print(f"Attempt {attempt + 1} failed, retrying...")
            time.sleep(2)  # Wait 2 seconds before retry
        except Exception as e:
            print(f"Attempt {attempt + 1} error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise e
    return None


def call_gemini_api(prompt):
    try:
        API_KEY = get_active_gemini_key()
        if not API_KEY: 
            print("ERROR: No Gemini API key available")
            return None
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ]
        }
        
        print(f"Making Gemini API call to: {url[:50]}...")
        resp = requests.post(url, headers=headers, json=data, timeout=120)
        
        print(f"Gemini API response status: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"Gemini API error: {resp.text}")
            return None
            
        result = resp.json()
        
        # Check if response has the expected structure
        if "candidates" not in result or not result["candidates"]:
            print(f"Unexpected Gemini response structure: {result}")
            return None
            
        text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        
        if not text:
            print("Empty text response from Gemini API")
            return None
            
        return text
        
    except Exception as e:
        print(f"Exception in call_gemini_api: {str(e)}")
        return None

def format_gemini_response(text):
    # Bold section titles (lines ending with ':')
    text = re.sub(r"^(.*:)", r"**\1**", text, flags=re.MULTILINE)
    # Bullet points (lines starting with '- ' or '* ')
    text = re.sub(r"^\s*[-*]\s+", r"• ", text, flags=re.MULTILINE)
    # Numbered lists (lines starting with '1. ', '2. ', etc.)
    text = re.sub(r"^\s*\d+\.\s+", lambda m: m.group(0).replace(". ", ". "), text, flags=re.MULTILINE)
    # Preserve line breaks
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text

# Load environment variables
load_dotenv()

# Commented out Gemini remnants
#GEMINI_API_KEY = "AIzaSyD7rAU5uO8GLPHWa5UroRCsMpOtgWsAH1U" 
#client = genai.Client(api_key=GEMINI_API_KEY)         

# Create Flask app
app = Flask(__name__)

CORS(app, origins="*", supports_credentials=True, allow_headers=["*"], methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])

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
    """Generate personalized quiz questions based on student profile, with reference quiz support and relaxed length check"""
    try:
        major = student_profile.get('major', student_profile.get('class', 'General'))

        # --- Reference Quiz Retrieval ---
        reference_quiz_doc = mongo.db.quizzes.find_one({"studentId": "pulkitjhamb@gmail.com"}, sort=[("createdAt", -1)])
        reference_quiz = reference_quiz_doc["questions"] if reference_quiz_doc and "questions" in reference_quiz_doc else None

        # --- Prompt Construction ---
        prompt = f"""Generate a psychometric quiz for a {major} student. 
Return ONLY a JSON array with this exact structure:

[
  {{
    "id": "q1",
    "text": "When working on {major} projects, what motivates you most?",
    "options": [
      {{"id": "A", "text": "Achieving perfect results", "weights": {{"analytical": 3, "creative": 1, "leadership": 1, "sociable": 1, "structured": 3}}}},
      {{"id": "B", "text": "Finding creative solutions", "weights": {{"analytical": 1, "creative": 3, "leadership": 1, "sociable": 1, "structured": 1}}}},
      {{"id": "C", "text": "Leading team discussions", "weights": {{"analytical": 1, "creative": 1, "leadership": 3, "sociable": 2, "structured": 1}}}},
      {{"id": "D", "text": "Collaborating with others", "weights": {{"analytical": 1, "creative": 1, "leadership": 1, "sociable": 3, "structured": 1}}}}
    ]
  }}
  // ... more questions ...
]

CRITICAL REQUIREMENTS:
- Return ONLY the JSON array starting with [ and ending with ]
- Use question ids q1, q2, q3... up to qN (N between 25 and 30)
- Each option must have weights for all 5 traits: analytical, creative, leadership, sociable, structured
- Weight values must be integers 0-3
- Questions should be relevant to {major} field
- NO markdown formatting, NO explanations, ONLY the JSON array

Reference Quiz Example (for inspiration, do NOT copy directly):
{json.dumps(reference_quiz, indent=2) if reference_quiz else "No reference quiz available."}
"""
        response = call_gemini_api(prompt)
        if not response:
            print("No response from Gemini API")
            return None

        response_text = response.strip()
        print(f"RAW GEMINI RESPONSE:\nLength: {len(response_text)}\nFull response: {response_text}\n{'='*50}")

        # Extract JSON array
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(0)
        else:
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                response_text = response_text[start_idx:end_idx+1]
            else:
                print("Could not extract JSON array from Gemini response")
                return None
        response_text = response_text.strip()

        print(f"CLEANED RESPONSE:\nLength: {len(response_text)}\nContent: {response_text}\n{'='*50}")

        # Try to parse the JSON
        quiz_data = json.loads(response_text)

        # Relaxed validation: accept 25-30 questions
        if not isinstance(quiz_data, list):
            print(f"Response is not a list: {type(quiz_data)}")
            return None

        if not (25 <= len(quiz_data) <= 30):
            print(f"Expected 25-30 questions, got {len(quiz_data)}")
            return None

        # Quick validation of first question structure
        if quiz_data and 'id' in quiz_data[0] and 'text' in quiz_data[0] and 'options' in quiz_data[0]:
            print("Quiz structure looks valid")
            return quiz_data
        else:
            print("Invalid quiz structure")
            return None

    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        print(f"Problematic text: {response_text[:200] if 'response_text' in locals() else 'No response text'}")
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
        
        grade_class = user.get('class', 'Not specified')
        
        # Convert Roman numerals to understand school grade level
        grade_mapping = {'IX': '9th grade', 'X': '10th grade', 'XI': '11th grade', 'XII': '12th grade'}
        readable_grade = grade_mapping.get(grade_class, grade_class)
        
        student_context = f"""
        Student Profile:
        - Name: {user.get('name', 'Student')}
        - Current School Grade: {readable_grade} (Class {grade_class} - Indian secondary school student)
        - School/Institute: {user.get('institute', 'Not specified')}
        - Stream/Subjects: {user.get('major', user.get('class', 'General'))}
        - Academic Performance: {user.get('academicPerformance', 'Not specified')}
        - Career Interests: {', '.join(user.get('careerInterests', ['Exploring options']))}
        - Skills: {', '.join(user.get('skills', ['Developing']))}
        - Extracurricular: {len(user.get('extracurricularActivities', []))} activities
        
        IMPORTANT: This student is in {readable_grade} of Indian secondary school (ages 14-18). They are NOT in college.
        
        Psychometric Scores:
        - Analytical: {trait_scores['analytical']}/{max_possible} ({trait_percentages['analytical']:.1f}%)
        - Creative: {trait_scores['creative']}/{max_possible} ({trait_percentages['creative']:.1f}%)
        - Leadership: {trait_scores['leadership']}/{max_possible} ({trait_percentages['leadership']:.1f}%)
        - Social: {trait_scores['sociable']}/{max_possible} ({trait_percentages['sociable']:.1f}%)
        - Structured: {trait_scores['structured']}/{max_possible} ({trait_percentages['structured']:.1f}%)
        """
        
        # Adjust analysis based on student type
        if user.get('studentType') == 'school':
            prompt = f"""You are a school career counselor talking to a {readable_grade} student in Indian secondary school. This is a SCHOOL STUDENT, NOT a college student. Give ONLY school-appropriate advice.

            {student_context}

            STRICT RULES:
            - NO company names (Google, Microsoft, TCS, etc.)
            - NO professional terms (internships, networking, GitHub, IEEE, professional societies)
            - NO salary packages or LPA mentions
            - NO college-level activities
            - ONLY things a school student can do THIS ACADEMIC YEAR
            - Focus on CAREER PATHS not job packages

            Create analysis for this school student THIS IS A SCHOOL STUDENT DO NOT MENTION ANYTHING ABOVE THE COMPREHENSION LEVEL OF A NORMAL 14-17 YEAR OLD INDIAN STUDENT:

            1. **Headline**: Cool personality title for a teenager
            
            2. **Summary**: 4-5 sentences about their personality and school strengths
            
            3. **Top Capabilities**: 4-5 strengths for school subjects and activities
            
            4. **Recommended Career Path**: Suggest career FIELDS to explore:
               - Career paths like: doctor, teacher, artist, content creator, scientist, engineer, writer, designer, etc.
               - Which school stream (Science/Commerce/Arts) fits them
               - Modern careers like YouTuber, app developer, environmental activist
               - Skills to develop in school
               - Types of higher education after 12th
               - DO NOT MENTION ANY COMPANY NAMES OR PACKAGES
            
            5. **Strengths**: How their strengths help in current school grade
            
            6. **Growth Areas**: 2-3 areas to improve with school-level tips
            
            7. **Suggested Next Steps**: 6-8 steps for THIS SCHOOL YEAR ONLY:
               - Subject choices for next class
               - School clubs to join (debate, drama, science, art clubs)
               - Skills to learn online (coding basics, art, languages)
               - School competitions (science fair, essay writing, sports)
               - Career exploration (talk to teachers, online research, career day)
               - Study habits and academic planning
               - Personal development activities
               - DO NOT MENTION COLLEGE LEVEL STUFF LIKE SOCIETIES IEEE NPTEL OR ANYTHING JUST NORMAL INDIAN SCHOOL CLUBS AND ACTIVITIES
            
            8. **Confidence Level**: "high"

            Remember: This is a SCHOOL STUDENT. No professional or college activities. Only school-level suggestions.

            Return ONLY valid JSON:
            {{
              "headline": "The [Teen Title]",
              "summary": "School-focused personality analysis...",
              "top_capabilities": ["School strength 1", "Academic skill 2", "Personal ability 3", "Future skill 4"],
              "recommended_path": "Career fields exploration with stream guidance - NO company names...",
              "strengths": "How strengths help in current school grade...",
              "growth_areas": ["School improvement area 1", "Academic development area 2"],
              "suggested_next_steps": [
                "Subject choice for next year",
                "School club to join",
                "Online skill to learn",
                "School competition to enter",
                "Career exploration activity",
                "Study planning step"
              ],
              "confidence": "high"
            }}"""
        else:
            prompt = f"""You are an expert career counselor and psychologist with 15+ years of experience in Indian education and career development. Analyze this student's comprehensive psychometric test results and create an in-depth, personalized career profile.

            {student_context}

            Create a detailed, comprehensive analysis with rich content:

            1. **Headline**: Create a unique, inspiring personality archetype title (e.g., "The Strategic Innovator", "The Analytical Leader")
            
            2. **Summary**: Write 4-5 detailed sentences explaining their core personality, learning style, and natural tendencies. Make it personal and insightful.
            
            3. **Top Capabilities**: List 4-5 specific, detailed capabilities with explanations of how they manifest in academic and professional settings.
            
            4. **Recommended Career Path**: Provide 3-4 specific career paths with:
               - Exact job titles and roles
               - Industry sectors in India with growth potential
               - Salary expectations and career progression
               - Required skills and qualifications
               - Companies/organizations to target
            
            5. **Strengths**: Write 3-4 paragraphs detailing their key strengths with specific examples of how these apply to their field of study and future career.
            
            6. **Growth Areas**: Identify 2-3 areas for development with specific strategies for improvement.
            
            7. **Suggested Next Steps**: Provide 6-8 highly specific, actionable steps including:
               - Specific courses, certifications, or skills to develop
               - Networking strategies and professional associations to join
               - Projects or internships to pursue
               - Books, resources, or mentors to seek
               - Timeline for each step (next 6 months, 1 year, 2 years)
            
            8. **Confidence Level**: Always set to "high" - provide confident, decisive guidance

            Make the analysis deeply personalized using their name, field of study, academic performance, and specific background. Reference Indian job market trends, educational institutions, and career opportunities. Be specific, actionable, and inspiring.

            Return ONLY a valid JSON object with comprehensive content:
            {{
              "headline": "The [Unique Archetype Title]",
              "summary": "Detailed 4-5 sentence personal analysis...",
              "top_capabilities": ["Detailed Capability 1 with context", "Detailed Capability 2 with context", "Detailed Capability 3 with context", "Detailed Capability 4 with context"],
              "recommended_path": "Comprehensive career guidance with specific paths, companies, salaries, and progression...",
              "strengths": "Multiple detailed paragraphs explaining key strengths with examples...",
              "growth_areas": ["Specific Area 1 with improvement strategy", "Specific Area 2 with improvement strategy"],
              "suggested_next_steps": [
                "Specific actionable step 1 with timeline",
                "Specific actionable step 2 with timeline",
                "Specific actionable step 3 with timeline",
                "Specific actionable step 4 with timeline",
                "Specific actionable step 5 with timeline",
                "Specific actionable step 6 with timeline"
              ],
              "confidence": "high"
            }}"""

        response = call_gemini_api(prompt)
        
        
        # Debug: Check if we got a response at all
        if not response:
            print("ERROR: No response from Gemini API in call_llm_conclusion")
            return None
        
        print(f"DEBUG: Raw Gemini response length: {len(response)}")
        print(f"DEBUG: Raw Gemini response: {response[:500]}...")
        
        # Clean and parse response
        response_text = response.strip()
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*$', '', response_text)
        
        print(f"DEBUG: Cleaned response length: {len(response_text)}")
        print(f"DEBUG: Cleaned response: {response_text[:500]}...")
        
        try:
            conclusion_data = json.loads(response_text)
            print(f"DEBUG: Successfully parsed JSON with keys: {list(conclusion_data.keys())}")
        except json.JSONDecodeError as e:
            print(f"ERROR: JSON parsing failed: {e}")
            print(f"ERROR: Problematic text: {response_text[:1000]}")
            return None
        
        # Validate structure
        required_fields = ['headline', 'summary', 'top_capabilities', 'recommended_path', 'strengths', 'growth_areas', 'suggested_next_steps', 'confidence']
        missing_fields = [field for field in required_fields if field not in conclusion_data]
        if missing_fields:
            print(f"ERROR: Missing required fields in conclusion: {missing_fields}")
            print(f"ERROR: Available fields: {list(conclusion_data.keys())}")
            return None
        
        print("SUCCESS: AI conclusion generated successfully")
        return conclusion_data
        
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parsing error in conclusion: {e}")
        print(f"ERROR: Response text: {response_text if 'response_text' in locals() else 'No response text'}")
        return None
    except Exception as e:
        print(f"ERROR: Exception in call_llm_conclusion: {e}")
        print(f"ERROR: Response: {response if 'response' in locals() else 'No response'}")
        return None

# --- Quiz Endpoints ---

@app.route("/quiz/generate", methods=["POST"])
def generate_quiz():
    data = request.get_json()
    student_id = data.get("studentId")
    # Always fetch the latest user profile for quiz generation
    user = users.find_one({"email": student_id})
    if not user:
        return jsonify({"error": "Student not found."}), 404
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

    # Give Gemini more time to generate before erroring out
    print(f"Generating personalized quiz for {student_id} using their latest profile...")
    quiz_json = None
    max_attempts = 3
    for attempt in range(max_attempts):
        quiz_json = call_llm_generate_quiz(user)
        if quiz_json and isinstance(quiz_json, list) and (25 <= len(quiz_json) <= 30):
            break
        print(f"Quiz generation attempt {attempt+1} failed, retrying...")
        time.sleep(3)  # Wait a bit longer between attempts

    if not quiz_json or not isinstance(quiz_json, list) or not (25 <= len(quiz_json) <= 30):
        print(f"Personalized quiz generation failed for {student_id} after {max_attempts} attempts.")
        return jsonify({"error": "Failed to generate quiz questions. Please try again after some time."}), 500

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

    # Only use LLM for analysis, no fallback
    conclusion_json = call_llm_conclusion(student_id, trait_scores)
    if not conclusion_json:
        return jsonify({"error": "Failed to generate analysis"}), 500

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

    # Required fields for signup
    required = ["email", "password", "name", "institutionType", "institutionName"]

    if not all(data.get(f) for f in required):
        return jsonify({"message": "Missing required fields."}), 400

    # Check if user already exists
    if users.find_one({"email": data["email"]}):
        return jsonify({"message": "User already exists"}), 409

    # Hash the password
    hashed_pw = generate_password_hash(data["password"])
    
    # Normalize institution type to studentType
    student_type = data["institutionType"].lower()  # "school" or "college"

    # Create complete user object with profile data
    user_doc = {
        "email": data["email"],
        "password": hashed_pw,
        "name": data["name"],
        "institute": data["institutionName"],
        "studentType": student_type,
        "isOnboardingComplete": True,  # User completed profile during signup
        "createdAt": datetime.utcnow(),
        "onboardingCompletedAt": datetime.utcnow()
    }
    
    # Add class or major field based on institution type
    if student_type == "college":
        user_doc["major"] = ""  # Will be filled later
        user_doc["year"] = ""  # Will be filled later
    else:
        user_doc["class"] = ""  # Will be filled later

    # Insert into MongoDB
    users.insert_one(user_doc)
    
    # Generate JWT token to automatically log them in
    token = jwt.encode(
        {
            'email': data["email"],
            'exp': datetime.utcnow() + timedelta(days=7)
        },
        app.secret_key,
        algorithm='HS256'
    )
    
    print(f"✅ New user signed up: {data['email']} ({student_type})")

    return jsonify({
        "message": "User registered successfully",
        "token": token,
        "user": {
            "email": data["email"],
            "name": data["name"],
            "studentType": student_type,
            "isOnboardingComplete": True
        }
    }), 201

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
                'exp': datetime.utcnow() + timedelta(days=7)
            },
            app.secret_key,
            algorithm='HS256'
        )
        
        # Determine if user needs onboarding or can go to dashboard
        isOnboardingComplete = user.get("isOnboardingComplete", False)
        
        # For existing users who don't have the flag, check if they have profile data
        if isOnboardingComplete is False and not user.get("isOnboardingComplete"):
            # Check if user has profile data (legacy users)
            hasProfileData = bool(
                user.get("name") or 
                user.get("institute") or 
                user.get("class") or 
                user.get("year") or 
                user.get("major") or
                user.get("studentType")
            )
            isOnboardingComplete = hasProfileData
        
        # Determine user type for dashboard routing
        userType = "school"  # default
        if user.get("year") and not user.get("class"):
            userType = "college"
        elif user.get("major"):
            userType = "college"
        elif user.get("institute") and "college" in user.get("institute", "").lower():
            userType = "college"
        elif user.get("studentType") == "college":
            userType = "college"
        
        # Return token and user info
        return jsonify({
            "message": "Login successful",
            "token": token,
            "user": {
                "email": email,
                "name": user.get("name"),
                "studentType": userType,
                "isOnboardingComplete": isOnboardingComplete
            }
        }), 200
    
    return jsonify({"message": "Invalid credentials"}), 401


# ONBOARDING COMPLETE AUTHENTICATION
@app.route("/auth/onboarding-complete", methods=["POST"])
def onboarding_complete_auth():
    data = request.get_json()
    email = data.get("email")
    
    if not email:
        return jsonify({"error": "Missing email"}), 400
    
    user = users.find_one({"email": email})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Check if onboarding is actually complete
    if not user.get("isOnboardingComplete", False):
        return jsonify({"error": "Onboarding not complete"}), 400
    
    # Create JWT token for the authenticated user
    token = jwt.encode(
        {
            'email': email,
            'exp': datetime.utcnow() + timedelta(days=7)
        },
        app.secret_key,
        algorithm='HS256'
    )
    
    # Determine user type for dashboard routing
    userType = "school"  # default
    if user.get("year") and not user.get("class"):
        userType = "college"
    elif user.get("major"):
        userType = "college"
    elif user.get("institute") and "college" in user.get("institute", "").lower():
        userType = "college"
    elif user.get("studentType") == "college":
        userType = "college"
    
    return jsonify({
        "message": "Authentication successful",
        "token": token,
        "user": {
            "email": email,
            "name": user.get("name"),
            "studentType": userType,
            "isOnboardingComplete": True
        }
    }), 200

# LOGOUT ROUTE
@app.route("/logout", methods=["POST"])
def logout():
    # For JWT-based auth, logout is handled client-side by removing the token
    # Server-side logout would require token blacklisting (optional enhancement)
    return jsonify({"message": "Logged out successfully"}), 200



# CHECK AUTH STATUS
@app.route("/auth/status", methods=["GET"])
def check_auth():
    # Look for token in Authorization header first
    auth_header = request.headers.get('Authorization')
    token = None
    
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]  # Get token after "Bearer "
    
    if not token:
        return jsonify({"authenticated": False}), 200
    
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
            return jsonify({"authenticated": False}), 200
            
    except jwt.ExpiredSignatureError:
        return jsonify({"authenticated": False, "message": "Token expired"}), 200
    except jwt.InvalidTokenError:
        return jsonify({"authenticated": False, "message": "Invalid token"}), 200


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
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "No authentication token"}), 401
        
        token = auth_header.split(' ')[1]
        
        # Decode token to get email
        try:
            decoded = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            email = decoded.get('email')
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        user = users.find_one({"email": email}, {"_id": 0, "password": 0})
        res = mongo.db.quiz_results.find_one({"email": email}, {"_id": 0, "password": 0})

        if not email:
            return jsonify({"error": "Email not found in token"}), 400

        # Get prompt from request
        data = request.get_json()
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({"error": "No prompt provided"}), 400

        updprompt = f" this is information about the User/the person you are chatting with : {user} and this is the psycometric quiz results : {res} and this is thePrompt: {prompt} answer in 50 words or less"

        # Call your AI function
        plan = call_gemini_api(updprompt)

        return jsonify({
            "email": email,
            "response": plan
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
  
@app.route("/user/update", methods=["PATCH"])
def update_user():
    data = request.get_json()
    email = data.get("email")
    
    if not email:
        return jsonify({"error": "Missing email"}), 400
    
    update_fields = {}

    # Update onboarding fields (updated format)
    onboarding_fields = [
        "preferred_theme", "name", "instituteName", "year", "preferred_language", 
        "school_or_college", "course"
    ]
    
    for field in onboarding_fields:
        if field in data:
            update_fields[field] = data[field]

    # Update other existing fields
    other_fields = [
        "conclusion", "recommendations", "quiz_result", "institute", 
        "theme", "plan", "category", "language", "class", "major", "studentType"
    ]
    
    for field in other_fields:
        if field in data:
            update_fields[field] = data[field]

    # If this is an onboarding completion, mark it as complete
    if any(field in onboarding_fields for field in update_fields.keys()):
        update_fields["isOnboardingComplete"] = True
        update_fields["onboardingCompletedAt"] = datetime.utcnow()

    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400

    result = users.update_one(
        {"email": email},
        {"$set": update_fields}
    )
    
    if result.matched_count:
        return jsonify({"message": "User updated successfully", "updated_fields": list(update_fields.keys())}), 200
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
        plan = call_gemini_api(plan_prompt)
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
        prompt = (
            "You are a caring friend talking to an Indian student who feels anxious. "
            "First, offer gentle consolation in about 100 words, using a friendly and supportive tone. "
            "Then, ask them kindly to share more about what's making them feel this way. "
            "Do not give solutions or advice yet. Just listen and show empathy, like a friend would."
            f"\n\nStudent's message: {message}\nFriend:"
        )
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
            study_plan_response = call_gemini_api(study_plan_prompt)
            
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
        reply = call_gemini_api(prompt)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def build_anxious_prompt(user_message):
    return (
        "You are a caring friend. When someone says they feel anxious, "
        "first, offer gentle consolation in about 100 words. "
        "Then, ask them kindly to share more about what's making them feel this way. "
        "Do not jump to solutions or advice yet. "
        "Keep your tone friendly and supportive.\n\n"
        f"User: {user_message}\nFriend:"
    )

# Use this function when the 'feeling anxious' button is clicked
# For example, in your endpoint:
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message")
    if data.get("emotion") == "anxious":
        prompt = build_anxious_prompt(user_message)
    else:
        prompt = default_prompt(user_message)
    # ...call LLM with prompt...

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
        study_plan_response = call_gemini_api(study_plan_prompt)
        
        # Generate a structured study plan object with comprehensive tasks
        study_plan = {
            "created_at": datetime.now().isoformat(),
            "goals": "Academic improvement and goal achievement",
            "current_performance": current_grades,
            "plan_content": study_plan_response,
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


# --- Projects Management Endpoints ---

@app.route("/user/projects", methods=["GET"])
def get_projects():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    user = users.find_one({"email": email}, {"_id": 0, "projects": 1})
    projects = user.get("projects", []) if user else []
    return jsonify({"projects": projects}), 200

@app.route("/user/projects", methods=["POST"])
def add_project():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    data = request.get_json()
    project = {
        "id": str(uuid.uuid4()),
        "title": data.get("title", ""),
        "link": data.get("link", ""),
        "createdAt": datetime.utcnow().isoformat()
    }
    
    result = users.update_one(
        {"email": email},
        {"$push": {"projects": project}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Project added", "project": project}), 201
    return jsonify({"error": "User not found"}), 404

@app.route("/user/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    result = users.update_one(
        {"email": email},
        {"$pull": {"projects": {"id": project_id}}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Project deleted"}), 200
    return jsonify({"error": "Project not found"}), 404

# --- Work Experience Management Endpoints ---

@app.route("/user/work-experience", methods=["GET"])
def get_work_experience():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    user = users.find_one({"email": email}, {"_id": 0, "workExperience": 1})
    work_experience = user.get("workExperience", []) if user else []
    return jsonify({"workExperience": work_experience}), 200

@app.route("/user/work-experience", methods=["POST"])
def add_work_experience():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    data = request.get_json()
    experience = {
        "id": str(uuid.uuid4()),
        "title": data.get("title", ""),
        "link": data.get("link", ""),
        "certificate": data.get("certificate", ""),
        "createdAt": datetime.utcnow().isoformat()
    }
    
    result = users.update_one(
        {"email": email},
        {"$push": {"workExperience": experience}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Work experience added", "experience": experience}), 201
    return jsonify({"error": "User not found"}), 404

@app.route("/user/work-experience/<experience_id>", methods=["DELETE"])
def delete_work_experience(experience_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    result = users.update_one(
        {"email": email},
        {"$pull": {"workExperience": {"id": experience_id}}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Work experience deleted"}), 200
    return jsonify({"error": "Work experience not found"}), 404

# --- Events Management Endpoints ---

@app.route("/user/events", methods=["GET"])
def get_events():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    user = users.find_one({"email": email}, {"_id": 0, "events": 1})
    events = user.get("events", []) if user else []
    return jsonify({"events": events}), 200

@app.route("/user/events", methods=["POST"])
def add_event():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    data = request.get_json()
    event = {
        "id": str(uuid.uuid4()),
        "title": data.get("title", ""),
        "date": data.get("date", ""),
        "time": data.get("time", ""),
        "description": data.get("description", ""),
        "createdAt": datetime.utcnow().isoformat()
    }
    
    result = users.update_one(
        {"email": email},
        {"$push": {"events": event}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Event added", "event": event}), 201
    return jsonify({"error": "User not found"}), 404

@app.route("/user/events/<event_id>", methods=["DELETE"])
def delete_event(event_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    result = users.update_one(
        {"email": email},
        {"$pull": {"events": {"id": event_id}}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Event deleted"}), 200
    return jsonify({"error": "Event not found"}), 404

# --- CGPA/Semester Management Endpoints ---

@app.route("/user/semesters", methods=["GET"])
def get_semesters():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    user = users.find_one({"email": email}, {"_id": 0, "semesters": 1})
    semesters = user.get("semesters", []) if user else []
    
    # Calculate overall CGPA
    total_credits = sum(sem.get("credits", 0) for sem in semesters)
    total_grade_points = sum(sem.get("sgpa", 0) * sem.get("credits", 0) for sem in semesters)
    overall_cgpa = round(total_grade_points / total_credits, 2) if total_credits > 0 else 0.0
    
    return jsonify({
        "semesters": semesters,
        "overall_cgpa": overall_cgpa,
        "total_credits": total_credits
    }), 200

@app.route("/user/semesters", methods=["POST"])
def add_semester():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    data = request.get_json()
    semester = {
        "id": str(uuid.uuid4()),
        "semester_number": data.get("semester_number", 1),
        "sgpa": float(data.get("sgpa", 0)),
        "credits": int(data.get("credits", 0)),
        "createdAt": datetime.utcnow().isoformat()
    }
    
    result = users.update_one(
        {"email": email},
        {"$push": {"semesters": semester}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Semester added", "semester": semester}), 201
    return jsonify({"error": "User not found"}), 404

@app.route("/user/semesters/<semester_id>", methods=["DELETE"])
def delete_semester(semester_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "No authentication token"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        email = payload['email']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401
    
    result = users.update_one(
        {"email": email},
        {"$pull": {"semesters": {"id": semester_id}}}
    )
    
    if result.matched_count:
        return jsonify({"message": "Semester deleted"}), 200
    return jsonify({"error": "Semester not found"}), 404

# --- Current Date/Time Endpoint ---

@app.route("/current-date", methods=["GET"])
def get_current_date():
    now = datetime.now()
    return jsonify({
        "date": now.day,
        "month": now.strftime("%B"),
        "year": now.year,
        "weekday": now.strftime("%A"),
        "full_date": now.strftime("%Y-%m-%d"),
        "formatted_date": now.strftime("%A, %d %B")
    }), 200

if __name__ == "__main__":
    app.run(debug=True , port=5001 , host="0.0.0.0")
