import argparse
import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from twilio.rest import Client

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.services.openai import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from medical_intake import MedicalIntakeProcessor

# Load environment variables
load_dotenv(override=True)

# Setup logging
logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

# Initialize Twilio client
twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilioclient = Client(twilio_account_sid, twilio_auth_token)

async def main(room_url: str, token: str, callId: str, sipUri: str):
    # Initialize Daily transport
    transport = DailyTransport(
        room_url,
        token,
        "Chatbot",
        DailyParams(
            api_key=os.getenv("DAILY_API_KEY", ""),
            dialin_settings=None,  # Not required for Twilio
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_out_enabled=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            transcription_enabled=True,
        ),
    )

    # Initialize services
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4")

    # Setup conversation context
    context = OpenAILLMContext([])
    context_aggregator = llm.create_context_aggregator(context)

    # Initialize and register medical intake processor
    intake = MedicalIntakeProcessor(context)
    llm.register_function("collect_name", intake.collect_name)
    llm.register_function("collect_birthday", intake.collect_birthday)
    llm.register_function("collect_insurance", intake.collect_insurance)
    llm.register_function("collect_referral", intake.collect_referral)
    llm.register_function("collect_complaint", intake.collect_complaint)
    llm.register_function("collect_address", intake.collect_address)
    llm.register_function("collect_phone", intake.collect_phone)
    llm.register_function("collect_email", intake.collect_email)
    llm.register_function("offer_appointments", intake.offer_appointments)

    # Setup pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    # Event handlers
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        await transport.capture_participant_transcription(participant["id"])
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        await task.cancel()

    @transport.event_handler("on_dialin_ready")
    async def on_dialin_ready(transport, cdata):
        try:
            call = twilioclient.calls(callId).update(
                twiml=f"<Response><Dial><Sip>{sipUri}</Sip></Dial></Response>"
            )
        except Exception as e:
            logger.error(f"Failed to forward call: {str(e)}")

    # Run the pipeline
    runner = PipelineRunner()
    await runner.run(task)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Twilio ChatBot")
    parser.add_argument("-u", type=str, help="Room URL")
    parser.add_argument("-t", type=str, help="Token")
    parser.add_argument("-i", type=str, help="Call ID")
    parser.add_argument("-s", type=str, help="SIP URI")
    config = parser.parse_args()

    asyncio.run(main(config.u, config.t, config.i, config.s))