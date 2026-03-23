import os
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
# We need 'modify' so we can read emails AND send replies.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing access token...")
            creds.refresh(Request())
        else:
            print("No token found. Opening browser to log in...")
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found! Please download it from Google Cloud Console.")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            print("Token saved successfully.")

    # Build and return the actual Gmail service object
    service = build('gmail', 'v1', credentials=creds)
    return service

# --- Quick Test Block ---
if __name__ == '__main__':
    print("Testing Gmail Authentication...")
    service = get_gmail_service()
    print("Success! Gmail service is ready.")