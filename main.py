import os
import json
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from auth import get_gmail_service
from tools import search_gmail_by_subject, send_reply

console = Console()

# ==========================================
# 1. The 3-Tool Schema
# ==========================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_gmail_by_subject",
            "description": "Search the user's Gmail for a subject.",
            "parameters": {
                "type": "object",
                "properties": {"subject_query": {"type": "string", "description": "only one query at a time."}},
                "required": ["subject_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_and_display_draft",
            "description": "Use this to show your proposed email draft to the user for approval. Pass ONLY the raw email text.",
            "parameters": {
                "type": "object",
                "properties": {"draft_text": {"type": "string", "description": "The pure email content to be sent."}},
                "required": ["draft_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_approved_email",
            "description": "Trigger this ONLY when the user explicitly approves the draft you displayed. It takes no parameters because the system safely uses the last saved draft.",
            "parameters": {
                "type": "object",
                "properties": {} # ZERO PARAMETERS - 100% Deterministic execution
            }
        }
    }
]

# ==========================================
# 2. Conversational Agent Logic
# ==========================================
def run_agent():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        api_key = Prompt.ask("[bold cyan]Please enter your OpenAI API Key[/bold cyan]", password=True)
        os.environ["OPENAI_API_KEY"] = api_key

    # user_name = os.getenv("AGENT_USER_NAME")
    # if not user_name:
    #     user_name = Prompt.ask("[bold cyan]What is your name? (Used for email signatures)[/bold cyan]")
    #     os.environ["AGENT_USER_NAME"] = user_name

    client = OpenAI(api_key=api_key)
    
    with console.status("[dim]Authenticating with Gmail...[/dim]"):
        gmail_service = get_gmail_service()
    
    # --- Python State Variables (The Deterministic Safety Net) ---
    state_fetched_email = None
    state_current_draft = None

    messages = [
        {"role": "system", "content": f"""You are an elite, conversational AI email assistant. 
        Your rules:
        1. Greet the user. Explain that your are an email assistant. You will help them draft and send emails. Ask what email they are looking for.
        1.1 If asked explain that your are only searching the subject line of the email.
        2. Use 'search_gmail_by_subject' when they tell you what to look for. If nothing is found, ask them for a different keyword.
        3. Once an email is found, WRITE A PROFESSIONAL REPLY IMMEDIATELY. DONT ASK. use 'save_and_display_draft' tool
        4. Use the 'save_and_display_draft' tool to securely pass your newly drafted reply to the system.
        This is very important. You are passing a pure email text to the system. Do not repeat the text in your response.
        5. CRITICAL: NEVER repeat the text of the draft in your conversational response. The system will display the draft automatically. Your chat response should ONLY ask the user: "I have prepared a draft. Would you like to send it or make changes?"
        6. Once they approve the draft, call 'send_approved_email'.
        Never output raw JSON to the user. Keep conversation friendly but concise."""}
    ]

    console.print(Panel.fit("[bold cyan]✉️ Conversational Gmail Agent[/bold cyan]\n[dim]Type 'quit' to exit.[/dim]", border_style="cyan"))

    # The Continuous Chat Loop
    while True:
        # Call OpenAI
        with console.status("[dim]Agent is typing...[/dim]", spinner="dots"):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )
        response_message = response.choices[0].message
        
        # --- Handle Tool Calls (Agent Actions) ---
        if response_message.tool_calls:
            messages.append(response_message)
            
            for tool_call in response_message.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                # Action 1: Search
                if func_name == "search_gmail_by_subject":
                    result = search_gmail_by_subject(gmail_service, args.get("subject_query"))
                    
                    if "error" not in result:
                        state_fetched_email = result # Save the email
                        
                        # Print original email UI
                        orig_text = f"[bold dim]From:[/bold dim] {result.get('sender')}\n[bold dim]Subj:[/bold dim] {result.get('subject')}\n[bold dim]Date:[/bold dim] {result.get('date')}\n"
                        orig_text += "-" * 40 + "\n" + result.get('body')
                        console.print(Panel(orig_text, title="[bold yellow]Original Email[/bold yellow]", border_style="yellow"))
                    
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result)})
                
                # Action 2: Present Draft
                elif func_name == "save_and_display_draft":
                    state_current_draft = args.get("draft_text") # Save securely in Python
                    print(state_current_draft)
                    # Print Draft UI
                    draft_ui = f"[bold dim]To:[/bold dim] {state_fetched_email.get('sender')}\n"
                    draft_ui += "-" * 40 + "\n" + state_current_draft
                    console.print(Panel(draft_ui, title="[bold green]AI Suggested Draft[/bold green]", border_style="green"))
                    
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": '{"status": "draft displayed to user successfully"}'})

                # Action 3: Send (The Deterministic Switch)
                elif func_name == "send_approved_email":
                    if not state_fetched_email or not state_current_draft:
                        error_msg = '{"error": "Missing email or draft context. Cannot send."}'
                        messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": error_msg})
                        continue

                    with console.status("[dim]Executing secure send...[/dim]"):
                        result = send_reply(
                            service=gmail_service,
                            to_address=state_fetched_email.get('sender'), # Hardcoded from state
                            subject=state_fetched_email.get('subject'),   # Hardcoded from state
                            body_text=state_current_draft,                # Hardcoded from state
                            thread_id=state_fetched_email.get('thread_id'),
                            original_message_id=state_fetched_email.get('message_id')
                        )
                    
                    console.print(f"\n[bold green]🚀 Reply successfully sent to {state_fetched_email.get('sender')}![/bold green]\n")
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result)})

        # --- Handle Normal Conversation (Agent Talking) ---
        else:
            assistant_reply = response_message.content
            if assistant_reply:
                console.print(f"\n[bold purple]Agent:[/bold purple] {assistant_reply}")
                messages.append({"role": "assistant", "content": assistant_reply})
            
            # Now wait for the human to reply naturally
            user_input = Prompt.ask("\n[bold blue]You[/bold blue]")
            if user_input.lower() in ['q', 'quit', 'exit']:
                break
            
            messages.append({"role": "user", "content": user_input})

if __name__ == "__main__":
    try:
        run_agent()
    except KeyboardInterrupt:
        console.print("\n[red]Process interrupted by user. Exiting...[/red]")