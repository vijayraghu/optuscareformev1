# -*- coding: utf-8 -*-
import os
import sys
import urllib
import requests
import json
from flask import Flask, request, Response, make_response, jsonify, url_for
from contextlib import closing
# Twilio Helper Library
from twilio.twiml.voice_response import VoiceResponse, Gather, Say, Dial
import re
import datetime
# Google Text To Speech SDK
from google.oauth2 import service_account
from google.cloud import texttospeech_v1beta1 as texttospeech

# Declare global variables
apiai_client_access_key = os.environ["APIAPI_CLIENT_ACCESS_KEY"]
apiai_url = "https://api.api.ai/v1/query"
apiai_querystring = {"v": "20150910"}

# Setup hints for better speech recognition
hints = "1,2,3,4,5,6,7,8,9,0, 1 one first, 2 two second, 3 three third, 4 four fourth, 5 five fifth, 6 six sixth, 7 seven seventh, 8 eight eighth,9 nine ninth, 10 ten tenth, 0 zero o, light. lights, application, outlook, fax, phone, phones, PC, system, store, infra, rebooting"

app = Flask(__name__)

@app.route('/start', methods=['GET','POST'])
def start():
	caller_phone_number = request.values.get('From')
	user_id = request.values.get('CallSid')
	twilio_asr_language = request.values.get('twilio_asr_language', 'en-AU')
	apiai_language = request.values.get('apiai_language', 'en')
	hostname = request.url_root
	
	# Check for HOOP (hours of operations)
	start = datetime.time(0, 00)
	end = datetime.time(23, 59)
	timestamp = datetime.datetime.now().time()
	resp = VoiceResponse()
	if (end <= timestamp >= start):
		# If call time not within hours of operation, play appropriate prompt and transfer to general line
		values = {"text": 'Hi! The store helpline team is currently closed, the team is opened from 8:30 till 6 P M weekdays. Please hold and I’ll transfer your call to the General Customer Service Number.'}
		print 'In start: before Google TTS'
		resp.play(hostname + 'goog_text2speech?' + qs)
		print 'In start: after Google TTS'
		resp.dial('+61450178418')
		return str(resp)
	else:
		# If call within office hours, triggering Dialogflow "Welcome" event
		headers = {'authorization': 'Bearer ' + apiai_client_access_key, 
			   'content-type': 'application/json'
			  }
		payload = {'event': {'name': 'Welcome'}, 
			   'lang': apiai_language, 
			   'sessionId': user_id
			  }
		response = requests.request("POST", url=apiai_url, data=json.dumps(payload), headers=headers, params=apiai_querystring)
		print response.text
		output = json.loads(response.text)
		output_text = output['result']['fulfillment']['speech']
		output_text = output_text.decode('utf-8')
		resp = VoiceResponse()
		
		# Prepare for collecting subsequent user input
		values = {'prior_text': output_text}
		qs = urllib.urlencode(values)
		action_url = '/process_speech?' + qs
		gather = Gather(input="speech", hints=hints, language=twilio_asr_language, speechTimeout="auto", action=action_url, method="POST")
		
		# Welcome prompt played to callers during office hours
		values = {"text": output_text}
		qs = urllib.urlencode(values)
		print 'In start: before Google TTS'
		gather.play(hostname + 'goog_text2speech?' + qs)
		print 'In start: after Google TTS'
		resp.append(gather)
		
		# If user input is missing after welcome prompt (no speech input), redirect to collect speech input again
		values = {'prior_text': output_text, 
			  'twilio_asr_language': twilio_asr_language, 
			  'apiai_language': apiai_language, 
			  'SpeechResult': '', 
			  'Confidence': 0.0
			 }
		qs = urllib.urlencode(values)
		action_url = '/process_speech?' + qs
		resp.redirect(action_url)
		print str(resp)
		return str(resp)
    
#####
##### Process Twilio ASR: "Speech to Text" to Dialogflow Intent analysis
#####
@app.route('/process_speech', methods=['GET', 'POST'])
def process_speech():
	caller_phone_number = request.values.get('From')
	user_id = request.values.get('CallSid')
	twilio_asr_language = request.values.get('twilio_asr_language', 'en-AU')
	apiai_language = request.values.get('apiai_language', 'en')
	prior_text = request.values.get('prior_text', 'Prior text missing')
	input_text = request.values.get('SpeechResult', '')
	confidence = float(request.values.get('Confidence', 0.0))
	hostname = request.url_root
	print "Twilio Speech to Text: " + input_text + " Confidence: " + str(confidence)
	#Check for any blanks between digits (both for employee number and mobile number)
	if re.search(r'\b\d{1,16}\b', input_text):
		input_text = re.sub('(?<=\d) (?=\d)', '', input_text)
		print "Changed input: " + input_text
	sys.stdout.flush()
	resp = VoiceResponse()
	
	if (confidence >= 0.0):
		# Step 1: Call Dialogflow for intent analysis
		intent_name, output_text, category, dealer_code = apiai_text_to_intent(apiai_client_access_key, input_text, user_id, apiai_language)
		
		# Step 2: Speech input processing by Twilio
		values = {'prior_text': output_text}
        	qs2 = urllib.urlencode(values)
        	action_url = '/process_speech?' + qs2
        	gather = Gather(input="speech", hints=hints, language=twilio_asr_language, speechTimeout="auto", action=action_url, method="POST")
        	values = {"text": output_text}
		qs1 = urllib.urlencode(values)
		print 'In-progress: Before Google tts'
		gather.play(hostname + 'goog_text2speech?' + qs1)
		print 'In progress: After Google tts'
		resp.append(gather)
			
		# If gather is missing (no speech input), redirect to process incomplete speech via Dialogflow
		values = {'prior_text': output_text, 
			  'twilio_asr_language': twilio_asr_language, 
			  'apiai_language': apiai_language, 
			  'SpeechResult': '', 
			  'Confidence': 0.0}
		qs3 = urllib.urlencode(values)
		action_url = '/process_speech?' + qs3
		resp.redirect(action_url)
			
	# When confidence of speech recogniton is not enough, replay the previous conversation
	else:
		output_text = prior_text
        	values = {"prior_text": output_text}
		qs2 = urllib.urlencode(values)
		action_url = "/process_speech?" + qs2
		gather = Gather(input="speech", hints=hints, language=twilio_asr_language, speechTimeout="auto", action=action_url, method="POST")
		values = {"text": output_text}
		qs1 = urllib.urlencode(values)
		print 'Before Google tts'
		gather.play(hostname + 'goog_text2speech?' + qs1)
		print 'After Google tts read'
		resp.append(gather)
		values = {"prior_text": output_text}
		qs2 = urllib.urlencode(values)
		action_url = "/process_speech?" + qs2
		resp.redirect(action_url)
	print str(resp)
	return str(resp)

@app.route('/process_close', methods=['GET', 'POST'])
def process_close():
	print 'in process_close'
	
	
#####
##### Google Dialogflow - Intent identification from text
#####
#@app.route('/apiai_text_to_intent', methods=['GET', 'POST'])
def apiai_text_to_intent(apiapi_client_access_key, input_text, user_id, language):
	print "Inside apiai_text_to_intent"
	headers = {
		'authorization': "Bearer " + apiapi_client_access_key, 
		'content-type': "application/json"
	}
	payload = {'query': input_text, 
		   'lang': language, 
		   'sessionId': user_id
		  }
	response = requests.request("POST", url=apiai_url, data=json.dumps(payload), headers=headers, params=apiai_querystring)
	output = json.loads(response.text)
	print output
	print json.dumps(output, indent=2)
	
	# Get values from Dialogflow
	try:
		intent_name = output['result']['metadata']['intentName']
	except:
		intent_name = ""
	try:
		category = output['result']['parameters']['category']
	except:
		category = ""
	try:
		dealer_code = output['result']['parameters']['dealer_code']
	except:
		dealer_code= ""	
	try:
		output_text = output['result']['fulfillment']['speech']
		output_text = output_text.encode('utf-8')
	except:
		output_text = ""
	    	
	return intent_name, output_text, category, dealer_code

#####
##### Dialogflow fulfillment webhook
#####
@app.route('/webhook', methods=['POST'])
def webhook():
	req = request.get_json(silent=True, force=True)
	print 'Request:'
	print json.dumps(req, indent=4)
	res = processRequest(req)
	res = json.dumps(res, indent=4)
	r = make_response(res)
	r.headers['Content-Type'] = 'application/json'
	return r

def processRequest(req):
	caller_phone_number = request.values.get('From')
	result = req.get('result')
	metadata = result.get('metadata')
	intentname = metadata.get('intentName')
	parameters = result.get('parameters')
	actionname = parameters.get('action')
	category = parameters.get('category')
	dealer_code = parameters.get('dealer_code')
	print dealer_code, category
	resp = VoiceResponse()
	
	# Handle Default Fallback Intent
	if intentname in ['Default Fallback Intent', 'application_services_cartwright-no', 'infra_services_cartwright-no', 'voice_services_cartwright-no']:
		print 'Intent :' + intentname
		speech = 'I not sure I quite understand. Apologies!. I’m new here at Optus and still in training and learning about how to help you. Maybe if you could tell me the general reason for your call today like phone or application or perhaps infra.'
	
    	# Log ticket message upon positive confirmation
    	if intentname in ['application_services_cartwright-yes', 'voice_services_cartwright-yes', 'infra_services_cartwright-yes']:
		print 'Intent :' + intentname
		speech = 'Ok. I will log a ticket on your behalf and have a colleague from IT call you back shortly to sort this out'
	
	return {'speech': speech, 'displayText': speech, 'source': 'careformev1'
	       }
	return res

#####
##### Google Cloud Text to speech for Speech Synthesis
##### This function calls Google TTS and then streams out the output media in mp3 format
#####
@app.route('/goog_text2speech', methods=['GET', 'POST'])
def goog_text2speech():
	text = request.args.get('text', "Oh No! There seems to be something wrong with my ram. Can you try calling back a little later after i talk to my friends in IT")

	# Setting profile id
	effects_profile_id = 'telephony-class-application'
	
	#Setting credentials -  Read env data
	credentials_raw = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
	
	#Generate Google TTS Credentials
	service_account_info = json.loads(credentials_raw)
	credentials = service_account.Credentials.from_service_account_info(service_account_info)
		    
	# Create Google Text-To-Speech client
    	client = texttospeech.TextToSpeechClient(credentials=credentials)
	
	#pass the text to be synthesized by Google Text-To-Speech
	input_text = texttospeech.types.SynthesisInput(text=text)
		
	#Set the Google Text-To-Speech voice parameters
    	voice = texttospeech.types.VoiceSelectionParams(language_code='en-AU', name='en-AU-Wavenet-B', ssml_gender=texttospeech.enums.SsmlVoiceGender.MALE)

	#Set Google Text-To-Speech audio configuration parameters
    	audio_config = texttospeech.types.AudioConfig( 
        	audio_encoding=texttospeech.enums.AudioEncoding.MP3, 
		effects_profile_id=[effects_profile_id])

	# Request speech synthesis from Google Text-To-Speech
    	response = client.synthesize_speech(input_text, voice, audio_config)
	
	# Write the output to a temp file
	with open('output.mp3', 'wb') as out:
		out.write(response.audio_content)
		print('Audio content written to file "output.mp3"')
	
	if response.audio_content:
		# Read the audio stream from the response
		def generate():
			print 'inside google tts generate method'
			with open('output.mp3', 'rb') as dmp3:
				data = dmp3.read(1024)
				while data:
					yield data
					data = dmp3.read(1024)
			print 'generate complete for google tts'
		return Response(generate(), mimetype="audio/mpeg")
    	else:
		# The response didn't contain audio data, exit gracefully
		print("Could not stream audio")
        	return "Error"
    
if __name__ == '__main__':
	app.run(host='0.0.0.0', debug = True)
