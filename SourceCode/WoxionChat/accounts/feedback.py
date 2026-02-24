from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import os
from flask_cors import CORS 


app = Flask(__name__)
CORS(app)

MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME = os.environ.get("DB_NAME", "local-bot")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "feedback")

try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    feedback_collection = db[COLLECTION_NAME]
    client.admin.command('ping')
    print("Kết nối MongoDB thành công!")
except Exception as e:
    print(f"Lỗi kết nối MongoDB: {e}")


@app.route('/api/submit_feedback', methods=['POST'])
def submit_feedback():

    data = request.json
    
    user_id = data.get('user_id')
    answers = data.get('answers')
    session_id = data.get('session_id') 

    if not user_id or not answers:
        return jsonify({"message": "Missing user_id or answers in request"}), 400

    try:
        feedback_document = {
            "user_id": user_id,
            "session_id": session_id if session_id else f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now(),
        }
        feedback_document.update(answers)

        feedback_collection.insert_one(feedback_document)
        print(f"Feedback cho user {user_id} đã được lưu vào MongoDB.")
        return jsonify({"message": "Feedback submitted successfully", "status": "success"}), 200
    except Exception as e:
        print(f"Lỗi khi lưu feedback vào MongoDB: {e}")
        return jsonify({"message": "Error saving feedback", "error": str(e), "status": "error"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)