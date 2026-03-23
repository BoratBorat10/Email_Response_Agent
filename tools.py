import base64
import re
import html
from email.mime.text import MIMEText


def has_signature_placeholder(text: str) -> bool:
    return bool(re.search(r"\[\s*your name\s*\]", text, re.IGNORECASE))


def get_text_body(payload):
    """
    Recursively parses the Gmail payload to extract text.
    Prioritizes text/plain, but falls back to cleaning text/html if necessary.
    """
    text_body = ""
    html_body = ""

    def extract_parts(part):
        nonlocal text_body, html_body
        mime_type = part.get('mimeType')
        
        if mime_type == 'text/plain':
            data = part.get('body', {}).get('data', '')
            if data:
                text_body += base64.urlsafe_b64decode(data).decode('utf-8')
                
        elif mime_type == 'text/html':
            data = part.get('body', {}).get('data', '')
            if data:
                html_body += base64.urlsafe_b64decode(data).decode('utf-8')
                
        elif 'parts' in part:
            for subpart in part['parts']:
                extract_parts(subpart)

    # Start the extraction
    extract_parts(payload)

    # 1. Return plain text ONLY if it contains actual characters (not just \n)
    if text_body.strip():
        return text_body.strip()
        
    # 2. If no valid plain text, clean up the HTML and return that
    elif html_body.strip():
        # remove <style> and <script> blocks (including their contents)
        clean_text = re.sub(r'<style[^>]*>.*?</style>', ' ', html_body, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r'<script[^>]*>.*?</script>', ' ', clean_text, flags=re.IGNORECASE | re.DOTALL)
        
        # 2. Remove all remaining HTML tags (<p>, <div>, <br>, etc.)
        clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
        
        # 3. Convert HTML entities (like &#39; to ')
        clean_text = html.unescape(clean_text)
        
        # 4. Clean up excessive whitespace/newlines
        clean_text = re.sub(r'\s+', ' ', clean_text)
        return clean_text.strip()
        
    return "No readable text found in email body."

def search_gmail_by_subject(service, subject_query):
    """Searches for the most recent email matching the subject."""
    print(f"Searching Gmail for subject: '{subject_query}'...")
    
    try:
        # 1. Search for the message ID
        results = service.users().messages().list(
            userId='me', 
            q=f"subject:({subject_query}) -from:me in:inbox", 
            maxResults=1
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return {"error": f"No emails found matching subject: {subject_query}. Ask or sugest a new query"}


        # Natively ask Gmail for the exact email address of the authenticated user (You)
        profile = service.users().getProfile(userId='me').execute()
        owner_email = profile.get('emailAddress', '')


        msg_id = messages[0]['id']
        thread_id = messages[0]['threadId']
        
        # 2. Fetch the full message content
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        # 3. Extract Headers
        headers = msg['payload']['headers']
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown")
        recipient = next((h['value'] for h in headers if h['name'].lower() == 'to'), "Unknown")
        date = next((h['value'] for h in headers if h['name'].lower() == 'date'), "No Date")
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
        message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), "")
        
        # 4. Extract Body
        body = get_text_body(msg['payload'])
        return {
            "status": "success",
            "thread_id": thread_id,
            "message_id": message_id, # Needed for replying in thread
            "sender": sender,
            "recipient": recipient,
            "owner_email": owner_email,
            "date": date,
            "subject": subject,
            "body": body.strip()
        }
        
    except Exception as e:
        return {"error": f"Gmail API error: {str(e)}"}

def send_reply(service, to_address, subject, body_text, thread_id, original_message_id):
    """Sends a reply in the same email thread."""
    try:
        # 1. Create the MIME Message
        message = MIMEText(body_text)
        message['to'] = to_address
        message['subject'] = subject
        
        # Threading headers
        if original_message_id:
            message['In-Reply-To'] = original_message_id
            message['References'] = original_message_id

        # 2. Encode for Gmail API
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        # 3. Send
        send_request = {
            'raw': raw_message,
            'threadId': thread_id
        }
        
        service.users().messages().send(userId='me', body=send_request).execute()
        return {"status": "success", "message": "Reply sent successfully."}
        
    except Exception as e:
        return {"error": f"Failed to send email: {str(e)}"}