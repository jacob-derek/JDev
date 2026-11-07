
from pathlib import Path
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE / "credentials.json"
TOKEN_FILE = BASE / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def autenticar():
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            "Não encontrei credentials.json na pasta do projeto."
        )

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return build("classroom", "v1", credentials=creds)


def main():
    service = autenticar()

    print("\n=== JClass: cursos disponíveis ===\n")
    resultado = service.courses().list(pageSize=100).execute()
    cursos = resultado.get("courses", [])

    if not cursos:
        print("Nenhum curso retornado para esta conta.")
        return

    for curso in cursos:
        print(f'{curso["name"]}  |  ID: {curso["id"]}')

    print(f"\nTotal de cursos nesta página: {len(cursos)}")


if __name__ == "__main__":
    main()
