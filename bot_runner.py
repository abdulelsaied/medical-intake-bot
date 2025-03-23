import argparse
import os
import subprocess
from contextlib import asynccontextmanager
import time

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse

from pipecat.transports.services.helpers.daily_rest import (
    DailyRESTHelper,
    DailyRoomObject,
    DailyRoomParams,
    DailyRoomProperties,
    DailyRoomSipParams,
)

# Load environment variables
load_dotenv(override=True)

# Configuration
MAX_SESSION_TIME = 5 * 60  # 5 minutes
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "DAILY_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN"
]

daily_helpers = {}

# FastAPI setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY", ""),
        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()

app = FastAPI(lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def create_daily_room(callId: str):
    # Create room properties with SIP settings
    properties = DailyRoomProperties(
        sip=DailyRoomSipParams(
            display_name="dialin-user",
            video=False,
            sip_mode="dial-in",
            num_endpoints=1
        )
    )
    
    params = DailyRoomParams(properties=properties)
    
    # Create new room
    room: DailyRoomObject = await daily_helpers["rest"].create_room(params=params)
    
    # Get token for bot
    token = await daily_helpers["rest"].get_token(room.url, MAX_SESSION_TIME)
    
    if not room or not token:
        raise HTTPException(status_code=500, detail="Failed to create room or get token")
    
    return room, token

@app.post("/twilio_start_bot", response_class=PlainTextResponse)
async def twilio_start_bot(request: Request):
    try:
        # Get form data from Twilio
        form_data = await request.form()
        data = dict(form_data)
        callId = data.get("CallSid")
        
        if not callId:
            raise HTTPException(status_code=500, detail="Missing 'CallSid' in request")
        
        # Create Daily room and get token
        room, token = await create_daily_room(callId)
        
        # Start bot process using system Python
        bot_cmd = ["python3", "bot_twilio.py", "-u", room.url, "-t", token, "-i", callId, "-s", room.config.sip_endpoint]
        
        try:
            process = subprocess.Popen(
                bot_cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            
            def print_output(pipe, prefix):
                for line in pipe:
                    print(f"{prefix}: {line.strip()}")
            
            # Start threads to handle output
            import threading
            stdout_thread = threading.Thread(target=print_output, args=(process.stdout, "BOT_OUT"), daemon=True)
            stderr_thread = threading.Thread(target=print_output, args=(process.stderr, "BOT_ERR"), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # Wait briefly and check for immediate startup errors
            time.sleep(1)
            if process.poll() is not None:
                # Process ended immediately
                stdout_thread.join(timeout=0.1)
                stderr_thread.join(timeout=0.1)
                raise HTTPException(status_code=500, detail="Bot failed to start")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Failed to start bot: {e}")
        
        # Put caller on hold with music
        resp = VoiceResponse()
        resp.play(
            url="http://com.twilio.sounds.music.s3.amazonaws.com/MARKOVICHAMP-Borghestral.mp3",
            loop=10
        )
        return str(resp)
    except Exception as e:
        print("Endpoint error:", str(e))
        raise

# Vercel handler
def handler(request):
    """Handle incoming requests for Vercel serverless functions"""
    return app(request)

if __name__ == "__main__":
    # Check environment variables
    for env_var in REQUIRED_ENV_VARS:
        if env_var not in os.environ:
            raise Exception(f"Missing environment variable: {env_var}")
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)