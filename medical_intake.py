from loguru import logger
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
from dotenv import load_dotenv

load_dotenv()

class MedicalIntakeProcessor:
    def __init__(self, context: OpenAILLMContext):
        print("Initializing MedicalIntakeProcessor")
        self.patient_info = {}
        self.sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        
        context.add_message({
            "role": "system",
            "content": """You are Jessica, a medical scheduling assistant for Tri-County Health Services. 
            You're talking to a patient. Address them by their first name and be polite and professional. 
            You're not a medical professional, so don't provide medical advice. Keep responses short and focused on collecting information.
            
            Follow this conversation flow:
            1. Introduce yourself and ask for their first and last name
            2. Ask for their birthday (accept any date format)
            3. Collect insurance information (payer name and ID)
            4. Ask about referral and physician
               - If they have a referral, collect the physician's name
               - If they don't have a referral, call collect_referral with has_referral: false and move to step 5
            5. Collect chief medical complaint
            6. Get their address
            7. Get phone number and optionally email
            8. Offer two appointment options
            9. Log their choice and confirm
            
            Your first message should be:
            "Hello, I'm Jessica from Tri-County Health Services. I'll help you schedule your appointment today. Could you please tell me your first and last name?"
            
            After they provide their name, call the collect_name function with their first and last name."""
        })
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_name",
                    "description": "Collect the user's first and last name",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "first_name": {
                                "type": "string",
                                "description": "User's first name"
                            },
                            "last_name": {
                                "type": "string",
                                "description": "User's last name"
                            }
                        }
                    }
                }
            }
        ])

    async def collect_name(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['first_name'] = args['first_name']
        self.patient_info['last_name'] = args['last_name']
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_birthday",
                    "description": "Collect the user's birthday",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "birthday": {
                                "type": "string",
                                "description": "User's birthdate in any format"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": f"Thank them for providing their name. Now ask for their birthday."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_birthday(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['birthday'] = args['birthday']
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_insurance",
                    "description": "Collect insurance information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "payer_name": {
                                "type": "string",
                                "description": "Insurance payer name"
                            },
                            "payer_id": {
                                "type": "string",
                                "description": "Insurance payer ID"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": "Thank them for providing their birthday. Now ask for their insurance information (payer name and ID)."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_insurance(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['insurance'] = {
            'payer_name': args['payer_name'],
            'payer_id': args['payer_id']
        }
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_referral",
                    "description": "Collect referral information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "has_referral": {
                                "type": "boolean",
                                "description": "Whether they have a referral"
                            },
                            "referring_physician": {
                                "type": "string",
                                "description": "Name of referring physician if applicable"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": "Now ask if they have a referral and to which physician."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_referral(self, function_name, tool_call_id, args, llm, context, result_callback):
        try:
            self.patient_info['referral'] = {
                'has_referral': args['has_referral'],
                'referring_physician': args.get('referring_physician', 'N/A')
            }
            
            context.set_tools([
                {
                    "type": "function",
                    "function": {
                        "name": "collect_complaint",
                        "description": "Collect chief medical complaint",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "chief_complaint": {
                                    "type": "string",
                                    "description": "Patient's chief medical complaint"
                                }
                            }
                        }
                    }
                }
            ])
            
            # Different messages based on whether they have a referral
            if args['has_referral']:
                message = "Thank you for providing the referral information. Now, what is your chief medical complaint?"
            else:
                message = "I understand you don't have a referral. That's fine. What is your chief medical complaint?"
                
            await result_callback([
                {
                    "role": "system",
                    "content": message
                }
            ])
            await self.save_data(args, result_callback)
        except Exception as e:
            logger.error(f"Error in collect_referral: {str(e)}")
            raise

    async def collect_complaint(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['chief_complaint'] = args['chief_complaint']
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_address",
                    "description": "Collect patient's address",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "string",
                                "description": "Patient's address"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": "Now ask for their address."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_address(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['contact'] = self.patient_info.get('contact', {})
        self.patient_info['contact']['address'] = args['address']
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_phone",
                    "description": "Collect patient's phone number",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {
                                "type": "string",
                                "description": "Patient's phone number"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": "Thank them for providing their address. Now ask for their phone number."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_phone(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['contact']['phone'] = args['phone']
        
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "collect_email",
                    "description": "Collect patient's email (optional)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {
                                "type": "string",
                                "description": "Patient's email (optional)"
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": "Thank them for providing their phone number. Now ask if they'd like to provide their email address (optional)."
            }
        ])
        await self.save_data(args, result_callback)

    async def collect_email(self, function_name, tool_call_id, args, llm, context, result_callback):
        self.patient_info['contact']['email'] = args.get('email', '')
        
        # Move to appointment selection
        context.set_tools([
            {
                "type": "function",
                "function": {
                    "name": "offer_appointments",
                    "description": "Offer appointment options and collect choice",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selected_option": {
                                "type": "integer",
                                "description": "1 for first option, 2 for second option",
                                "enum": [1, 2]
                            }
                        }
                    }
                }
            }
        ])
        await result_callback([
            {
                "role": "system",
                "content": """Offer these two appointment options:
                1. Dr. John Doe on March 22, 2025 at 4:00 PM
                2. Dr. John Doe on March 22, 2025 at 4:30 PM
                
                Ask which option they prefer."""
            }
        ])
        await self.save_data(args, result_callback)

    async def offer_appointments(self, function_name, tool_call_id, args, llm, context, result_callback):
        selected_option = args['selected_option']
        appointment_time = "4:00 PM" if selected_option == 1 else "4:30 PM"
        
        self.patient_info['appointment'] = {
            'doctor': 'Dr. John Doe',
            'date': 'March 22, 2025',
            'time': appointment_time
        }
        
        # Send email with appointment details
        await self.send_appointment_email()
        
        context.set_tools([])
        await result_callback([
            {
                "role": "system",
                "content": "Thank them for their time and confirm their appointment details."
            }
        ])
        await self.save_data(args, result_callback)

    async def send_appointment_email(self):
        try:
            # Check if SendGrid API key is set
            if not os.getenv('SENDGRID_API_KEY'):
                logger.error("SENDGRID_API_KEY is not set in environment variables")
                return
                
            patient_name = f"{self.patient_info['first_name']} {self.patient_info['last_name']}"
            appointment = self.patient_info['appointment']
            
            message = Mail(
                from_email='abdul.elsaied2@gmail.com',
                to_emails='abdul.elsaied2@gmail.com',
                subject=f'New Appointment Scheduled - {patient_name}',
                html_content=f"""
                <h2>New Appointment Scheduled</h2>
                <p><strong>Patient:</strong> {patient_name}</p>
                <p><strong>Date of Birth:</strong> {self.patient_info['birthday']}</p>
                <p><strong>Insurance:</strong> {self.patient_info['insurance']['payer_name']} (ID: {self.patient_info['insurance']['payer_id']})</p>
                <p><strong>Referral:</strong> {'Yes' if self.patient_info['referral']['has_referral'] else 'No'}</p>
                <p><strong>Referring Physician:</strong> {self.patient_info['referral']['referring_physician'] or 'N/A'}</p>
                <p><strong>Chief Complaint:</strong> {self.patient_info['chief_complaint']}</p>
                <p><strong>Contact:</strong></p>
                <ul>
                    <li>Address: {self.patient_info['contact']['address']}</li>
                    <li>Phone: {self.patient_info['contact']['phone']}</li>
                    <li>Email: {self.patient_info['contact']['email'] or 'N/A'}</li>
                </ul>
                <p><strong>Appointment Details:</strong></p>
                <ul>
                    <li>Doctor: {appointment['doctor']}</li>
                    <li>Date: {appointment['date']}</li>
                    <li>Time: {appointment['time']}</li>
                </ul>
                """
            )
            
            response = self.sg.send(message)
            logger.info(f"Appointment email sent to {patient_name}")
            
        except Exception as e:
            logger.error(f"Failed to send appointment email: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def save_data(self, args, result_callback):
        await result_callback(None) 