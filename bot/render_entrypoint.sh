#!/bin/bash

# Decode the base64 encoded firebase key or simply write the json content
# We will use FIREBASE_CREDENTIALS_JSON environment variable in Render

if [ -n "$FIREBASE_CREDENTIALS_JSON" ]; then
    echo "Creating firebase_key.json from environment variable..."
    echo "$FIREBASE_CREDENTIALS_JSON" > firebase_key.json
    export FIREBASE_SERVICE_ACCOUNT_PATH=firebase_key.json
fi

# Run the bot
python bot/main.py
