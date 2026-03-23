import json
import os
import sys
from pathlib import Path
from typing import Text

try:
    from dotenv import load_dotenv
    from openai import OpenAI, AuthenticationError, BadRequestError
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text

    from auth import get_gmail_service
    from setup import is_setup_complete, run_setup
    from tools import search_gmail_by_subject, send_reply, has_signature_placeholder
except ImportError as e:
    print(
        "Missing a dependency. Run:\n"
        "  pip install -r requirements.txt",
        file=sys.stderr,
    )
    print(f"Import error: {e}", file=sys.stderr)
    raise SystemExit(1) from None

load_dotenv(override=True)

console = Console()

# ==========================================
#  1. Tool Schema 
# ==========================================
TOOLS = [
    {
        "type": "function",
        "name": "search_gmail_by_subject",
        "description": "Search the user's Gmail for a subject.",
        "parameters": {
            "type": "object",
            "properties": {"subject_query": {"type": "string"}},
            "required": ["subject_query"]
        }
    },
    {
        "type": "function",
        "name": "save_and_display_draft",
        "description": (
                "Create and display the proposed draft to the user. "
                "This tool already shows the draft in the UI. "
                "After calling it, do not repeat the draft text in a normal assistant message."
            ),
            "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The subject line for the email."},
                "draft_text": {"type": "string", "description": "The pure email content to be sent"}
            },
            "required": ["subject", "draft_text"]
        }
    },
    {
        "type": "function",
        "name": "send_approved_email",
        "description": "Trigger this ONLY when the user explicitly approves the draft you displayed. It takes no parameters because the system safely uses the last saved draft.",
        "parameters": {
            "type": "object",
            "properties": {} 
        }
    }
]

# ==========================================
# 2. Conversational Agent Logic (Responses API)
# ==========================================
def run_agent():

    # override so it will not grab OPENAI_API_KEY from global env vars.
    # the agent will use only the key supplied in setup
    load_dotenv(override=True)

    ascii_path = Path(__file__).resolve().parent / "assets" / "ascii.txt"
    if ascii_path.is_file():
        ascii_art = ascii_path.read_text(encoding="utf-8")
        console.print(Panel.fit(ascii_art, border_style="cyan", title=Text('Yaron Gefen- Home Assignment', style=""), title_align="left"))

    api_key = os.getenv("OPENAI_API_KEY")
    email_name = os.getenv("EMAIL_NAME")

    client = OpenAI(api_key=api_key)
    
    with console.status("[dim]Authenticating with Gmail...[/dim]"):
        gmail_service = get_gmail_service()
    
    # --- Python State Variables ---
    state_fetched_email = None
    state_current_draft = None

    agent_instructions = f"""
You are an email reply assistant.

Rules:
1. Start by briefly asking what subject to search for.
2. When the user gives a subject or keyword, call search_gmail_by_subject.
3. If an email is found, immediately draft a reply and call save_and_display_draft in the same turn.
4. Do not ask the user whether they want to reply before drafting.
4.5 Use {email_name} as the email signature
5. Do not ask the user what message to include before drafting.
6. After calling save_and_display_draft, do not repeat or quote the draft in a normal assistant message.
7. If the user asks for a change, call save_and_display_draft again with the updated draft.
8. Only call send_approved_email after an explicit approval such as "send it", "looks good", or "approve".
9. Keep normal chat responses short.
"""
    

    # --- history inits with intro message ---
    conversation_history = [
        {"role": "user", "content": "Hello. Please introduce yourself briefly and ask me what email subject I am looking for today."}
    ]

    while True:
        with console.status("[dim]Agent is typing...[/dim]", spinner="dots"):
            try:
                response = client.responses.create(
                    model="gpt-4.1-mini",
                    instructions=agent_instructions,
                    input=conversation_history,
                    tools=TOOLS,
                )
            except AuthenticationError as e:
                console.print(
                    "\n[red]OpenAI authentication failed.[/red] "
                    "The [cyan]OPENAI_API_KEY[/cyan] in your .env file is not valid. "
                )
                return
            except BadRequestError as e:
                console.print(
                    "\n[red]OpenAI rejected the request (400).[/red] "
                    "Often this is an invalid model name, bad tool/message format, or a parameter the API does not accept."
                )
                console.print(f"[dim]{e}[/dim]")
                return 

        # if to ask a follow up question
        requires_user_input = False

        for item in response.output:
            
            # Action A: The LLM used a Tool
            if item.type == "function_call":
                # print(f"DEBUG: Agent is calling tool: {item.name}")
                conversation_history.append({
                    "type": "function_call",
                    "id": item.id,
                    "call_id": item.call_id,
                    "name": item.name,
                    "arguments": item.arguments
                })
                func_name = item.name
                args = json.loads(item.arguments)
                
                if func_name == "search_gmail_by_subject":
                    result = search_gmail_by_subject(gmail_service, args.get("subject_query"))
                    if "error" not in result:
                        state_fetched_email = result 
                        orig_text = f"[bold dim]From:[/bold dim] {result.get('sender')}\n[bold dim]Subj:[/bold dim] {result.get('subject')}\n[bold dim]Date:[/bold dim] {result.get('date')}\n"
                        orig_text += "-" * 40 + "\n" + result.get('body')
                        console.print(Panel.fit(orig_text, title="[bold yellow]Original Email[/bold yellow]", border_style="yellow"))
                    
                    # Append function_call_output to history
                    conversation_history.append({
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(result)
                    })
                
                elif func_name == "save_and_display_draft":
                    state_current_draft = args.get("draft_text") 
                    draft_ui = f"[bold dim]To:[/bold dim] {state_fetched_email.get('sender')}\n"
                    draft_ui += "-" * 40 + "\n" + state_current_draft
                    console.print(Panel.fit(draft_ui, title="[bold green]AI Suggested Draft[/bold green]", border_style="green"))
                    
                    conversation_history.append({
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": '{"status": "draft displayed to user successfully"}'
                    })


                elif func_name == "send_approved_email":
                    if not state_fetched_email or not state_current_draft:
                        error_msg = '{"error": "Missing email or draft context. Cannot send."}'
                        conversation_history.append({"type": "function_call_output", "call_id": item.call_id, "output": error_msg})
                        continue
                    if has_signature_placeholder(state_current_draft):
                        error_msg = '{"error": "Draft contains placeholder [Your name]. Ask user for signature name before sending."}'
                        conversation_history.append({
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": error_msg
                        })
                        continue

                    with console.status("[dim]Executing secure send...[/dim]"):
                        result = send_reply(
                            service=gmail_service,
                            to_address=state_fetched_email.get('sender'), 
                            subject=state_fetched_email.get('subject'),   
                            body_text=state_current_draft,                
                            thread_id=state_fetched_email.get('thread_id'),
                            original_message_id=state_fetched_email.get('message_id')
                        )
                    
                    console.print(f"\n[bold green]🚀 Reply successfully sent to {state_fetched_email.get('sender')}![/bold green]\n")
                    conversation_history.append({"type": "function_call_output", "call_id": item.call_id, "output": json.dumps(result)})
                    # requires_user_input = True # Prompt user for next task

            # Action B: The LLM is talking to the user
            elif item.type == "message":
                # Extract text using the new Responses API structure
                assistant_reply = item.content[0].text if item.content else ""
                if assistant_reply:
                    console.print(f"\n[bold purple]Agent:[/bold purple] {assistant_reply}")
                    conversation_history.append({"role": "assistant", "content": assistant_reply})
                    requires_user_input = True
        
        # After processing all outputs, if the agent spoke or finished a task, ask the human
        if requires_user_input:
            user_input = Prompt.ask("\n[bold blue]You[/bold blue]")
            if user_input.lower() in ['q', 'quit', 'exit']:
                break
            
            conversation_history.append({"role": "user", "content": user_input})

if __name__ == "__main__":
    try:
        if not is_setup_complete():
            ok = run_setup()
            if not ok:
                raise SystemExit("Setup failed or was cancelled.")
        run_agent()
    except KeyboardInterrupt:
        console.print("\n[red]Process interrupted by user. Exiting...[/red]")