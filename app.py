from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import sys
import os
import datetime

# Ensure we can import rishi.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from rishi import RishiAI

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rishi_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

rishi = RishiAI(use_tor=True)

# Database Models
class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), default="New Chat")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    messages = db.relationship('ChatMessage', backref='session', lazy=True, cascade="all, delete-orphan")

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False) # 'user' or 'ai'
    content = db.Column(db.Text, nullable=False)
    provider = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Ensure database exists
with app.app_context():
    db.create_all()

# Global for current session ID
current_session_id = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/new_chat', methods=['POST'])
def new_chat():
    global current_session_id
    new_session = ChatSession(title="New Chat")
    db.session.add(new_session)
    db.session.commit()
    current_session_id = new_session.id
    return jsonify({'status': 'new session started', 'session_id': current_session_id})

@app.route('/chat', methods=['POST'])
def chat():
    global current_session_id
    data = request.json
    message_text = data.get('message')
    history = data.get('history', [])
    
    # If no active session, start one
    if not current_session_id:
        new_session = ChatSession(title=message_text[:30] + "...")
        db.session.add(new_session)
        db.session.commit()
        current_session_id = new_session.id
    else:
        # Update title if it's still the default
        session = ChatSession.query.get(current_session_id)
        if session and session.title == "New Chat":
            session.title = message_text[:30] + "..."
            db.session.commit()

    # Save user message
    user_msg = ChatMessage(session_id=current_session_id, role='user', content=message_text)
    db.session.add(user_msg)
    
    response_text, provider = rishi.chat(message_text, history)
    
    # Save AI response
    ai_msg = ChatMessage(session_id=current_session_id, role='ai', content=response_text, provider=provider)
    db.session.add(ai_msg)
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error saving message to DB: {e}")
    
    # Check for command execution request
    command = None
    if "EXECUTE:" in response_text:
        command = response_text.split("EXECUTE:")[1].strip().split("\n")[0]
        
    return jsonify({
        'response': response_text,
        'provider': provider,
        'command': command,
        'tor_active': rishi.tor_verified,
        'session_id': current_session_id
    })

@app.route('/execute', methods=['POST'])
def execute():
    data = request.json
    command = data.get('command')
    output = rishi.execute_command(command)
    return jsonify({'output': output})

@app.route('/files', methods=['GET'])
def list_history_sessions():
    sessions = ChatSession.query.order_by(ChatSession.created_at.desc()).all()
    return jsonify({'sessions': [{'id': s.id, 'title': s.title, 'date': s.created_at.strftime("%Y-%m-%d %H:%M")} for s in sessions]})

@app.route('/read_history', methods=['POST'])
def read_history_db():
    global current_session_id
    data = request.json
    session_id = data.get('session_id')
    current_session_id = session_id # Switch current context
    
    session = ChatSession.query.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'})
    
    messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp.asc()).all()
    
    # Format messages nicely for display or return as JSON
    # For now, we'll return a formatted string for the front-end to "replay" or simple JSON
    msg_list = [{'role': m.role, 'content': m.content, 'provider': m.provider} for m in messages]
    return jsonify({'session_title': session.title, 'messages': msg_list})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
