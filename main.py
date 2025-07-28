from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_cors import CORS
from dotenv import load_dotenv
import os
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai

# Load environment variables
load_dotenv()
GEMINI_API_KEY = "AIzaSyD7rAU5uO8GLPHWa5UroRCsMpOtgWsAH1U" 
client = genai.Client(api_key=GEMINI_API_KEY)         
# Create Flask app
app = Flask(__name__)

CORS(app, origins="*", supports_credentials=True, allow_headers=["*"], methods=["GET", "POST", "PATCH", "OPTIONS"])

# Configure MongoDB
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.secret_key = os.getenv("SECRET_KEY")
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
        return jsonify({"message": "Login successful"}), 200
    return jsonify({"message": "Invalid credentials"}), 401


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
           contents='''"Analyze this career quiz. Respond in two clearly marked Markdown headings:\n"
    "### Conclusion\n"
    "(Brief summary, positive, actionable, max 6 sentences)\n"
    "### Career Recommendations\n"
    "(List top 4 career/job recommendations with a short reason for each, based on the answers.)\n"
    "Answers:\n\n"
    + "\n\n".join([f"{i+1}. Q: {qa['question']}\nA: {qa['answer']}" for i, qa in enumerate(qaPairs)])''',
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

@app.route("/mental_health_chat", methods=["POST"])
def mental_health_chat():
    data = request.get_json()
    message = data.get("message")
    email = data.get("email")
    if not message or not email:
        return jsonify({"error": "Missing message or email"}), 400
    # Fetch student details
    user = users.find_one({"email": email}, {"_id": 0, "password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    # Compose prompt for AI
    prompt = f"You are a mental health assistant for students. Here is the student's profile: {user}.\n\nStudent's message: {message}\n\nRespond empathetically and helpfully, considering their background.answer in 50 words. tell your answers in indian context."
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True , port=5001 , host="0.0.0.0")
