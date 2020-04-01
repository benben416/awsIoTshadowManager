from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient
from AWSIoTPythonSDK.core.util.enums import DropBehaviorTypes
import time, json, threading
import subprocess
import updatefunctions

import logging
import logging.handlers

# Init the formatter and log handler
formatter = logging.Formatter(fmt='shadow: %(levelname)s: %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.handlers.SysLogHandler(address = '/dev/log')
handler.setFormatter(formatter)
logger.addHandler(handler)
u = updatefunctions.VariableUpdater(Logger=logger)

# Shadow will have desired and reported jsons
shadow = 	{
		"desired" : { },
		"reported" : { }
		}

# Init the thread locking
updateLock = threading.Lock()

# Process the message payload
def authCallback(client, userdata, message) :

  logger.info("authCallback");
  topic = message.topic

  try:
    payload = json.loads(message.payload.decode('utf-8').replace('\n',''))
  except Exception as e:
    logger.error("authCallback - cant decode message payload");
    return

  cmd = ''
  token = ''

  # Validate input
  if 'cmd' in payload:
    cmd = payload['cmd']
  if 'token' in payload:
    token = payload['token']


  
  if cmd != '' and token != '':
    if cmd == 'AUTH':
      logger.info("AUTHing " + token)
      subprocess.run(['/usr/bin/ndsctl','auth',token], stdout=subprocess.PIPE)
    elif cmd == 'DEAUTH':
      logger.info("DEAUTHing " + token)
      subprocess.run(['/usr/bin/ndsctl','deauth',token], stdout=subprocess.PIPE)
    else:
      logger.info("Unknown cmd [" + token + "]")
  else: 
    logger.warning("Error Decoding Auth Payload")  



def updateCallback(payload, responseStatus, token):
  global shadow
  if responseStatus == 'accepted':
    shadow = json.loads(payload)


# Function called to make changes to the shadow
# If the IoT service deems that there is a delta in the desired and actual shadow
def deltaCallback(payload, responseStatus, token):
  global shadow
  global deviceShadow
  logger.info("[START] DELTA CALLBACK ---")

  # Load the changes 
  changes = json.loads(payload)
  with updateLock:
    states = changes['state']
    uciStates = dict()
    restartStates = dict()
    reloadStates = dict()
    # Sort the states. Put the uci commands first, then { restart,enable,disable } commands, and restart commands last, 
    # so we make sure we restart the device as the last operation
    for k in states:
      v = states[k]
      if 'restart.' in k:
        restartStates[k] = v
      elif 'reload.' in k or 'enable.' in k or 'disable.' in k:
        reloadStates[k] = v
      else:
        uciStates[k] = v


    sortedStates = { **uciStates, **reloadStates, **restartStates }
    changes['state'] = sortedStates
    # End sorting

    errorDict = dict()

    # Process the changes
    for state in changes['state']:
      logger.info("Need to change state .. " + state + " to " + changes['state'][state])    
      if u.doUpdate(state,changes['state'][state]):
        logger.info("UPDATING SHADOW")
        shadow["state"]["reported"][state] = changes['state'][state]
      else:
        logger.error("COULDNT UPDATE SHADOW -> CHANGING DESIRED TO REPORTED")
        errorDict[state] = 'ERROR'

    # Once we've changes states we can set the version to the desired version
    shadow["version"] = changes["version"]

    # Build the new state
    mergedJson = { "state": { 	"reported" : { **shadow['state']['reported'] , **u.zeroUci() , **errorDict }, "desired" : { **u.zeroUci(), **errorDict }}}

    # And report the new shadow
    try:
      logger.info("Updating Changed Shadow")
      deviceShadow.shadowUpdate(json.dumps(mergedJson),updateCallback,10)
    except Exception as e:
      logger.error("Exception: cant update shadow " + e)
      time.sleep(60)

####################################################################################################

def getShadow(payload, responseStatus, token):
  global shadow
  with updateLock:
    shadow = json.loads(payload)


# ----------------------
# Setup the daemon
# ----------------------

# Read in thingName file from the config file
try:
  with open('/root/owifi/config.json', 'r') as f:
    j = json.load(f)
    thingName = j['thingName']

except Exception:
  thingName = '0000'
  logger.error("Exception: thingName cant be read from file")

# Setup the IoT topic
topic = 'ndsStatus/' + thingName
authTopic = 'ndsAuth/' + thingName

# Connect to the AWS IoT
myMQTTClient = AWSIoTMQTTShadowClient(thingName)
myMQTTClient.configureEndpoint("arxldjrins88l-ats.iot.us-east-1.amazonaws.com", 8883) # todo: move endpoint out of here
myMQTTClient.configureCredentials("/root/owifi/cert/root.pem", "/root/owifi/cert/AWSIoTThing.key", "/root/owifi/cert/AWSIoTThing.pem")
myMQTTClient.configureAutoReconnectBackoffTime(1, 32, 20)
myMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
myMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec
myMQTTClient.getMQTTConnection().configureOfflinePublishQueueing(100, DropBehaviorTypes.DROP_OLDEST)
myMQTTClient.connect()


# Get the shadow, async
deviceShadow = myMQTTClient.createShadowHandlerWithName(thingName, True)
deviceShadow.shadowGet(getShadow, 9)

# So we may have to wait for the shadow data to be filled
time.sleep(10)

# Make sure we got the shadow
if shadow and 'state' in shadow and 'delta' in shadow['state']:
  d = shadow['state']['delta']
  # Run the delta callback function, create a json that mimics the delta topic.
  # we're doing this first time the box loads, to run any changes that were made to the shadow while we were offline
  deltaCallback('{ "version": ' + str(shadow['version']) + ', "state": ' + json.dumps(d) + '}', '', '')


# Register the delta function
deviceShadow.shadowRegisterDeltaCallback(deltaCallback)

# sleep for a few seconds, enough to pull any changes that were made while we were offline
time.sleep(20)

# now lets report our current state
# we do this after any changes have been made while we were offline
while True:
  try:
    deviceShadow.shadowUpdate(json.dumps(u.makeShadow()),updateCallback,10)
    # Break out of the loop when shadow reported
    break
  except Exception:
    logger.error("Exception: Cant update shadow (offline)")
    time.sleep(60)



##################################
## Report current stats of device to MQ
##################################

# Get the gateway name
status = subprocess.run(['/sbin/uci','get','nodogsplash.@nodogsplash[0].gatewayname'], stdout=subprocess.PIPE)
gatewayName = status.stdout.decode('utf-8')

# uci get gives a \n delimited JSON which isnt good. Trim the \n to be able to parse the json
gatewayName = gatewayName.replace('\n','')

# Get an MQ connection
mqtt = myMQTTClient.getMQTTConnection()

try:

  mqtt.subscribe(authTopic, 1, authCallback)
  logger.info("Subscribing to " + authTopic);
except Exception:
    logger.error("Exception: Cant Subscribe to " + authTopic)


# Now we're setup, loop forever and report 
while True:

  # the ndsctl json status page
  status = subprocess.run(['/usr/bin/ndsctl','json'], stdout=subprocess.PIPE)
  res = status.stdout.decode('utf-8')
  res = res.replace('\n','')

  # Add some more data to it

  nds = {}

  nds['TimeStamp'] = int(time.time())
  nds['Gateway']   = gatewayName
  nds['Thing']     = thingName
  nds['payload']   = json.loads(res)


  try:
    if nds['payload']['client_length'] > 0:
      # Publish the status message to the MQ
      mqtt.publish(topic, json.dumps(nds), 0)
      logger.info('Sending MQ')
  except Exception:
    logger.error("Exception: Cant read NDS Json Dump")

  # Sleep 5 minutes
  time.sleep(300)
