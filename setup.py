import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.theme import Theme

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green"
})
console = Console(theme=custom_theme)


def is_setup_complete():
    credentials_ok = Path("credentials.json").exists()
    env_ok = Path(".env").exists()

    if not env_ok:
        return False

    load_dotenv(override=True)

    api_key = os.getenv("OPENAI_API_KEY")
    email_name = os.getenv("EMAIL_NAME")

    return bool(credentials_ok and api_key and email_name)


def prompt_for_api_key():
    while True:
        api_key = Prompt.ask("[info]Enter your OpenAI API Key[/info]", password=True).strip()

        if not api_key:
            console.print("[warning]API key cannot be empty.[/warning]")
            continue

        if not api_key.startswith("sk-"):
            console.print("[warning]⚠ That doesn't look like a valid OpenAI key, missing 'sk-'.[/warning]")
            confirm = Prompt.ask("Save it anyway?", choices=["y", "n"], default="n")
            if confirm == "n":
                continue

        return api_key


def prompt_for_email_name():
    while True:
        email_name = Prompt.ask("[info]Enter your name for the email signature[/info]").strip()
        if not email_name:
            console.print("[warning]Name cannot be empty.[/warning]")
            continue
        return email_name


def run_setup():
    console.print(Panel.fit(
        "[bold info]Gmail AI Agent, Environment Setup[/bold info]\n"
        "This script will configure your local environment.",
        border_style="info"
    ))

    env_path = Path(".env")

    if not Path("credentials.json").exists():
        console.print("[error]Missing credentials.json in the project root.[/error]")
        console.print("[error]Download credentials from Google Cloud Project and try again.[/error]")
        console.print("[error]See README.md for more details.[/error]")

        return False

    load_dotenv(override=True)

    api_key = os.getenv("OPENAI_API_KEY")
    email_name = os.getenv("EMAIL_NAME")

    if not api_key:
        api_key = prompt_for_api_key()

    if not email_name:
        email_name = prompt_for_email_name()

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={api_key}\n")
            f.write(f"EMAIL_NAME={email_name}\n")

        console.print("[success]✓ Setup completed successfully.[/success]")
        return True

    except Exception as e:
        console.print(f"[error]Failed to write .env file: {e}[/error]")
        return False


if __name__ == "__main__":
    try:
        if is_setup_complete():
            pass
        else:
            run_setup()
    except KeyboardInterrupt:
        console.print("\n[error]Setup cancelled by user.[/error]")
