import subprocess, threading, time

class VariableUpdater:

  logger = ''

  def __init__(self,Logger):
    self.logger = Logger


  # Log a message
  def syslog(self,message):
    self.logger.info(message)

  # Log an error
  def syslogError(self,message):
    self.logger.error(message)

  # Restart command based on the key/value
  def __restart(self,key,value):
    if key == 'nds':
      self.syslog("Restarting NDS")
      cp = subprocess.run(['/etc/init.d/nodogsplash','restart'], stdout=subprocess.PIPE)
    elif key == 'network':
      self.syslog("Restarting NETWORK");
      cp = subprocess.run(['/etc/init.d/network','restart'], stdout=subprocess.PIPE)
      # Go To Sleep, wait for network to come back up before continuing
      time.sleep(30)
    elif key == 'qos':
      self.syslog("Restarting QOS")
      cp = subprocess.run(['/etc/init.d/qos','restart'], stdout=subprocess.PIPE)
    elif key == 'shadow':
      self.syslog("Restarting Shadow")
      cp = subprocess.run(['/etc/init.d/owifi','restart'], stdout=subprocess.PIPE)
    elif key == 'system':
      self.syslog("Rebooting")
      subprocess.run(['/sbin/reboot','-d','30'], stdout=subprocess.PIPE)
    elif key == 'uhttpd':
      __class.__restartHTTPD()

    return True

  # Process a reload command based on the key/value
  def __reload(self,key,value):
    if key == 'nds':
      self.syslog("Reloading NDS")
      cp = subprocess.run(['/etc/init.d/nodogsplash','reload'], stdout=subprocess.PIPE)
    elif key == 'qos':
      self.syslog("Reloading QOS")
      cp = subprocess.run(['/etc/init.d/qos','reload'], stdout=subprocess.PIPE)
    elif key == 'uhttpd':
      self.syslog("Reloading UHTTPD")
      cp = subprocess.run(['/etc/init.d/uhttpd','reload'], stdout=subprocess.PIPE)

    return True

  # Process an enable command based on key/value
  def __enable(self,key,value):
    if key == 'nds':
      self.syslog("Enabling NDS")
      cp = subprocess.run(['/etc/init.d/nodogsplash','enable'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/nodogsplash','start'], stdout=subprocess.PIPE)
    elif key == 'qos':
      self.syslog("Enabling QOS")
      cp = subprocess.run(['/sbin/uci','set','qos.wwan.enabled=1'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/sbin/uci','set','qos.wan.enabled=1'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/sbin/uci','commit','qos'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/qos','enable'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/qos','start'], stdout=subprocess.PIPE)
    elif key == 'uhttpd':
      self.syslog("Enabling UHTTPD")
      cp = subprocess.run(['/etc/init.d/uhttpd','enable'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/uhttpd','start'], stdout=subprocess.PIPE)

    return True

  # Process a disable command based on key/value
  def __disable(self,key,value):
    if key == 'nds':
      self.syslog("Disabling NDS")
      cp = subprocess.run(['/etc/init.d/nodogsplash','disable'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/nodogsplash','stop'], stdout=subprocess.PIPE)
    elif key == 'qos':
      self.syslog("Disabling QOS")
      cp = subprocess.run(['/sbin/uci','set','qos.wwan.enabled=0'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/sbin/uci','set','qos.wan.enabled=0'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/sbin/uci','commit','qos'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/qos','reload'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/qos','disable'], stdout=subprocess.PIPE)
    elif key == 'uhttpd':
      self.syslog("Disabling UHTTPD")
      cp = subprocess.run(['/etc/init.d/uhttpd','disable'], stdout=subprocess.PIPE)
      cp = subprocess.run(['/etc/init.d/uhttpd','stop'], stdout=subprocess.PIPE)

    return True

  # Restart the HTTPD server
  def __restartHTTPD():
    self.syslog("Restarting UHTTPD");
    cp = subprocess.run(['/etc/init.d/uhttpd','restart'], stdout=subprocess.PIPE)

  # Build the shadow JSON from an (name,value) string pair
  def __makeShadowJSON(name,v):
   v = v.replace('\n','')
   return { "state": { "desired" : {}, "reported": { name : v } } }

  # Build the shadow JSON from an array
  def __makeShadowJSONarr(a):
   res = { "state": { "desired" : {}, "reported": {  } } }

   for k in a:
     res['state']['reported'][str(k)] = str(a[k])

   return res

  # Get the result of a uci get command
  def __uciShadow(name):
    cp = subprocess.run(['/sbin/uci','get',name], stdout=subprocess.PIPE)
    res = cp.stdout.decode('utf-8')
    return res


  # Build the shadow of the uci variables we have deemed to be updatable
  def makeShadow(self):

    # Only these uci variables will be included in the shadow
    setUci = {	'wireless',
		'uhttpd',
		'qos',
		'nodogsplash',
		'dropbear',
		'ssids',
		'system',
		'network'
	     }

    uciUpdates = {}     

    for u in setUci:
      # Run UCI show for these variables
      cp = subprocess.run(['/sbin/uci','-d',';;','show',u], stdout=subprocess.PIPE)
      res = cp.stdout.decode('utf-8')
      for arr in res.split('\n'):
        e = arr.split('=')
        # If its a valid k=v pair
        if len(e) == 2:
          k = 'uci.' + e[0]
          v = e[1]
	  # The value is Just a string
          v = v.replace("'","")
          # Do not allow the following variables to be updatable -- a bit messy.. fix
          if not '.ifname' in k and not '.device' in k and not '.gatewayinterface' in k and not '.loopback' in k and not '.sta.network' in k and not '.sta.mode' in k and not '.hostname' in k:
            uciUpdates[k] = v


    # Return the zeroed toggle variables as definaed in zeriUci() and the uci variables defined by this function
    return __class__.__makeShadowJSONarr({**uciUpdates,**self.zeroUci()})


  # Build a dict of certain values we wish to be able to toggle. All set to zero
  def zeroUci(self):

    uciUpdates = {}

    uciUpdates['reload.nds']	= '0'   
    uciUpdates['reload.uhttpd']	= '0'    
    uciUpdates['reload.qos']	= '0'  

    uciUpdates['enable.nds']	= '0'   
    uciUpdates['enable.uhttpd']	= '0'    
    uciUpdates['enable.qos']	= '0'  

    uciUpdates['disable.nds']	= '0'   
    uciUpdates['disable.uhttpd']= '0'    
    uciUpdates['disable.qos']	= '0'  

    uciUpdates['restart.nds']	= '0'  
    uciUpdates['restart.uhttpd']= '0'    
    uciUpdates['restart.shadow']= '0'    
    uciUpdates['restart.qos']	= '0'    
    uciUpdates['restart.syatem']= '0'    
    uciUpdates['restart.network']= '0'    

    return uciUpdates


  # Update a uci variable
  def __updateUCI(self,key,value):

    key = key.strip()
    uci = key.split('.')
    # The cmd will be everything in the varaible name after uci.
    cmd = ".".join(uci[1:])
    if uci[0] == 'uci' and cmd != '':

      # The commit variable is the first variable after uci.
      commit = cmd.split('.')

      # If the value has ';;' characters its an array, so delete the UCI and readd the array of variables
      if len(value.split(';;')) > 1:
        values = value.split(';;')
        self.syslog("DELETING UCI " + cmd)
        cp = subprocess.run(['/sbin/uci','delete',cmd], stdout=subprocess.PIPE)
        for v in values:
          runCmd = cmd + '=' + v.strip()
          self.syslog("UPDATING: " + runCmd)
          cp = subprocess.run(['/sbin/uci','add_list',runCmd], stdout=subprocess.PIPE,stderr=subprocess.PIPE)
          # There was an error
          if cp.returncode != 0:
            self.syslogError("Failure to bulk update UCI: [" + cmd + "]" + cp.stderr.decode('utf-8'))

      else:
        # Append the value to the command to be variable=value
        cmd = cmd + '=' + value.strip()
        self.syslog("UPDATING: " + cmd)
        # And finally run the set and commit programs
        cp = subprocess.run(['/sbin/uci','set',cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if cp.returncode != 0:
          self.syslogError("Failure to update UCI: [" + cmd + "]" + cp.stderr.decode('utf-8'))

      # Now commit the whole thing
      cp = subprocess.run(['/sbin/uci','commit',commit[0]], stdout=subprocess.PIPE)

    return True


  # Call the correct function based on the key to update. Its either a uci. or a special function which are defined below
  def doUpdate(self,key,value) :

    self.syslog("FUNCTION UPDATING " + key + " to " + value)
    uci = key.split('.')
    if uci[0] == 'uci':
      return self.__updateUCI(key,value)
    elif uci[1] and uci[0] == 'enable':
      return self.__enable(uci[1],value)
    elif uci[1] and uci[0] == 'disable':
      return self.__disable(uci[1],value)
    elif uci[1] and uci[0] == 'reload':
      return self.__reload(uci[1],value)
    elif uci[1] and uci[0] == 'restart':
      return self.__restart(uci[1],value)

