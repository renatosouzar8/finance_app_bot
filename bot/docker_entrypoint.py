import os
import subprocess
import sys

def main():
    # 1. Handle Firebase Credentials from Env Var (Render)
    firebase_json_content = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    
    if firebase_json_content:
        print("Creating firebase_key.json from environment variable...")
        # Write to root director (current working dir)
        key_path = "firebase_key.json"
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(firebase_json_content)
        
        # Set the path env var so main.py finds it
        os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = key_path

    # 2. Start the Bot
    # calls "python bot/main.py"
    print("Starting bot...")
    subprocess.run([sys.executable, "bot/main.py"], check=True)

if __name__ == "__main__":
    main()
