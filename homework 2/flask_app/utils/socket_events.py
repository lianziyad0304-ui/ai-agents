"""
socket_events.py — handles real-time chat messages using WebSockets.
"""
from flask import current_app, session
from flask_socketio import emit
from flask_app import socketio
from flask_app.utils.llm import (
    handle_ai_chat_request,
    assess_message_risk,
    request_human_validation,
    handle_validation_response,
)


@socketio.on('send_message')
def handle_message(data):
    """
    Called automatically when the browser emits a 'send_message' event.

    Homework 2: before anything reaches the Orchestrator, this checks
    (1) is a yes/no confirmation already pending from the last message?
    (2) does THIS message look risky (delete/remove/etc)?
    Only if neither applies does the message proceed normally.
    """
    user_message = data.get('message', '').strip()

    if not user_message:
        return

    try:
        db = current_app.db
        if session.get('pending_validation'):
            ai_response = handle_validation_response(db, user_message)
        elif assess_message_risk(user_message):
            ai_response = request_human_validation(user_message)
        else:
            ai_response = handle_ai_chat_request(db, role="Orchestrator", message=user_message)
    except Exception as error:
        print(f"LLM error: {error}")
        ai_response = "Sorry, something went wrong answering that."

    emit('receive_message', {'response': ai_response})


def build_resume_system_prompt(db):
    """
    Build the system prompt that gives the AI context about the resume.
    """
    resume_text = db.getResumeText()
    return f"""You are a helpful AI assistant reviewing a resume.
You have been given the resume content below. Use it to answer questions
accurately and helpfully. If asked something not covered in the resume,
say so honestly rather than guessing.

Keep answers concise. You may use light markdown (bold, bullet lists) but
avoid large tables.

RESUME CONTENT:
{resume_text}
"""
