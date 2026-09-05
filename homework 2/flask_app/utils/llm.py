"""
llm.py â€” sends messages to an AI language model via the OpenRouter API.

This file is the bridge between your Flask app and an AI model (GPT-3.5).
When a student types a message in the chat, it travels here, gets sent to
OpenRouter, and the AI's reply comes back.

KEY CONCEPTS:
  - API (Application Programming Interface): a way for two programs to talk
    to each other over the internet. OpenRouter exposes an API we can call.
  - HTTP POST request: sending data to a server (like submitting a form).
    We POST the conversation to OpenRouter and it POSTs back the AI reply.
  - System prompt: instructions given to the AI before the conversation starts.
    Think of it as the AI's job description.
"""

import os
import re
import requests
from flask import session
from flask import session
from jinja2 import Template

# The URL we send our messages to.
# OpenRouter acts as a single gateway to many different AI models.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Which AI model to use. OpenRouter supports many models.
# Models with ':free' suffix are free to use â€” no API credits needed.
# See all available models at: https://openrouter.ai/models
DEFAULT_MODEL = "openai/gpt-4o-mini"

# One shared template for every expert's system prompt. Each expert just
# fills in different values for role/domain/instructions/context/examples.
MASTER_TEMPLATE = Template("""\
You are a {{ role }}, an expert in {{ domain }}.

{{ specific_instructions }}
{% if background_context %}
Context:
{{ background_context }}
{% endif %}
{% if few_shot_examples %}
Examples:
{{ few_shot_examples }}
{% endif %}
Request: {{ request }}
""", trim_blocks=True, lstrip_blocks=True)


def fill_template(role, domain, specific_instructions, request,
                   background_context="", few_shot_examples=""):
    """
    Render MASTER_TEMPLATE into one expert's full system prompt.
    """
    return MASTER_TEMPLATE.render(
        role=role,
        domain=domain,
        specific_instructions=specific_instructions,
        background_context=background_context,
        few_shot_examples=few_shot_examples,
        request=request,
    ).strip()


def send_message(user_message, system_prompt="You are a helpful assistant."):
    """
    Send a message to the AI and return its response as a string.
    """
    api_key = os.getenv('OPENROUTER_API_KEY')

    if not api_key or api_key == 'paste-your-key-here':
        return "âڑ ï¸ڈ No API key found. Add your OpenRouter key to the .env file and restart the app."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8080"
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message}
    ]

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json={"model": DEFAULT_MODEL, "messages": messages},
        timeout=30
    )

    result = response.json()

    if 'error' in result:
        error_message = result['error'].get('message', 'Unknown API error')
        return f"âڑ ï¸ڈ OpenRouter error: {error_message}"

    if 'choices' not in result:
        return f"âڑ ï¸ڈ Unexpected response from OpenRouter: {result}"

    return result['choices'][0]['message']['content']


def handle_ai_chat_request(db, role, message):
    """
    Route a chat message to the named expert. role=None keeps Homework 0's
    original single-prompt behavior as a fallback, so nothing about the
    basic chat flow breaks while you're building this out.
    """
    if role is None:
        return send_message(message)

    config = db.getLLMRoles()[role]
    background_context = config['background_context'] or ""
    if role == "Content Expert":
        background_context += "\n" + db.getResumeText()

    system_prompt = fill_template(
        role=config['role'],
        domain=config['domain'],
        specific_instructions=config['specific_instructions'],
        background_context=background_context,
        few_shot_examples=config['few_shot_examples'] or "",
        request=message,
    )
    output = send_message(message, system_prompt).strip()
    print(f"[{role}] generated:\n{output}\n")   # the rubric checks this output

    if role == "Database Read Expert":
        return execute_read_query(db, output)
    if role == "Database Write Expert":
        return execute_write_action(db, output)
    if role == "Database Semantic Search Expert":
        return execute_semantic_search(db, output)
    if role == "Orchestrator":
        return run_orchestrator_plan(db, message, output)
    return output   # Content Expert -- output is already the final answer


def execute_read_query(db, sql):
    """
    Run the Database Read Expert's generated SQL. We refuse anything that
    isn't a SELECT -- this expert is read-only by design.
    """
    if not sql.strip().upper().startswith("SELECT"):
        return "Sorry, I couldn't safely answer that question."
    try:
        return str(db.query(sql))
    except Exception as error:
        print(f"Read Expert query failed: {error}")
        return "Sorry, that question couldn't be answered."


def execute_semantic_search(db, output):
    """
    Run the Database Semantic Search Expert's output.

    Homework 2: this is a separate expert (its own role, its own executor
    function here) rather than a second thing the Read Expert might say --
    the Orchestrator picks this role instead of "Database Read Expert" in
    its plan whenever a request names something by an abbreviation,
    paraphrase, or general category that might not match the database's
    exact wording (e.g. "MSU", "AI skills"). See semanticSearch() in
    database.py for how the actual comparison works.

    The expert is told (see llm_roles.csv) to respond with exactly one
    line in the form "<table>|<search text>" -- deliberately the simplest
    format that still carries both pieces of information, so parsing it
    is one string split, not a regex.
    """
    try:
        table, query_text = output.strip().split('|', 1)
        return str(db.semanticSearch(table.strip(), query_text.strip()))
    except Exception as error:
        print(f"Semantic search failed: {error}")
        return "Sorry, that question couldn't be answered."


def execute_write_action(db, generated_code):
    """
    Run the Database Write Expert's generated Python. This genuinely
    executes model-generated code with exec(). `db` is the only thing
    exposed to it.
    """
    local_vars = {}
    try:
        exec(generated_code, {"db": db, "NULL": None}, local_vars)
    except Exception as error:
        print(f"Write Expert code failed: {error}")
        return "Operation was unsuccessful."
    return local_vars.get("outcome", "Operation was unsuccessful.")


def run_orchestrator_plan(db, original_request, plan_text):
    """
    Parse the Orchestrator's plan (a Python list of call strings), run each
    expert call in order, then make one final call to turn the raw results
    into a single clean reply for the chat UI.
    """
    try:
        call_strings = eval(plan_text)   # the Orchestrator's own list literal
    except Exception:
        print(f"Orchestrator returned an unparseable plan: {plan_text}")
        return "Sorry, I couldn't plan a response to that."

    results = []
    for call_string in call_strings:
        print(f"[Orchestrator] executing: {call_string}")
        match = re.search(r'''role=['"]([^'"]*)['"],\s*message=['"]([^'"]*)['"]''', call_string)
        role, message = match.group(1), match.group(2)
        response = handle_ai_chat_request(db, role, message)
        results.append((role, message, response))

    steps_summary = "\n".join(f"{r}: {resp}" for r, m, resp in results)
    synthesis_prompt = (
        f'The user asked: "{original_request}"\n\n'
        f"Here is what each expert found or did:\n{steps_summary}\n\n"
        "Write ONE short, clear reply. A Database Write Expert step's result "
        "is already the exact message to show the user (e.g. 'New Python "
        "added to the skills table.') -- if one is present, reuse it "
        "verbatim rather than rephrasing it. Otherwise, summarize the "
        "other results in plain language. Never mention SQL, Python, code, "
        "or these internal steps."
    )
    return send_message(original_request, synthesis_prompt)

DANGEROUS_KEYWORDS = ['delete', 'remove', 'clear', 'drop', 'destroy']


def assess_message_risk(message):
    """
    Return True if `message` contains a keyword associated with a
    destructive/irreversible database action.
    """
    lowered = message.lower()
    return any(keyword in lowered for keyword in DANGEROUS_KEYWORDS)


def request_human_validation(message):
    """
    Pause a risky request and ask the user to confirm before anything
    runs.
    """
    session['pending_validation'] = message
    return (
        f'This looks like it could delete or modify data: "{message}". '
        f'Are you sure you want to proceed? (yes/no)'
    )


def handle_validation_response(db, response):
    """
    Called instead of the normal chat flow whenever a confirmation
    is pending.
    """
    original_message = session['pending_validation']
    normalized = response.strip().lower()

    if normalized in ('yes', 'y'):
        session.pop('pending_validation')
        return handle_ai_chat_request(db, role="Orchestrator", message=original_message)

    if normalized in ('no', 'n'):
        session.pop('pending_validation')
        return "Okay, I won't do that. The request was cancelled."

    return f'Please answer "yes" or "no" -- do you want me to proceed with: "{original_message}"?'
