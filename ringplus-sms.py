#!/usr/bin/env python2

### Configurable Options, change these to suit your needs. ###

# RingPlus API details..
rp_client_id = ''
rp_client_secret = ''
redirect_url = 'https://bitstorm.pw/rp/authenticate'

# IMAP and SMTP information used for SMS-to-Email gateway.
email_user = ''
email_password = ''
email_imap_address = 'imap.gmail.com'
email_smtp_address = 'smtp.gmail.com:587'
email_query_address = 'txt.voice.google.com'

# Locale used for number formatting.
locale_id = 'en_US.UTF-8'

# Database Configuration. We will eventually support remote hosts.
# However, this funcationality has not been added yet.
database_localhost = True # True or False
database_name = 'rp_test'

# Enable / Disable Logging
log_enabled = True # True or False
log_file = 'ringplus-sms.log' # Log filepath
log_level = 'DEBUG' # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Used to override the phone number used for debug / testing purposes.
number_override = False # True or False
number_value = '(123) 456-7890'
#number_value = '(812) 484-9511'
# These strings are used for sending a response to the user.
str_help = 'You can use: balance'
str_unknown_user = 'This phone is not associated with a known RingPlus account. Signup at http://bitstorm.pw/rp'
str_token_error = 'We could not authenticate your account with RingPlus. Please re-authenticate at http://bitstorm.pw/rp'
str_invalid_command = 'Sorry, I do not understand that request. For a list of valid commands, reply with the word: help'
str_balance_info = 'Balance: %(bal)s Usage: %(mins)s, %(txts)s, %(mms)s, & %(data)s. %(time)s remaining.' #Variables: bal, mins, txts, mms, data, time

# These Strings are used for logging purposes.
log_service_start = 'INFO: Starting Service'
log_interrupt = 'INFO: Interrupt signal detected, closing processes.'
log_imap_sucess = 'INFO: IMAP - Login Sucessful'
log_imap_login_error = 'WARNING: IMAP - Login Error, retrying in 5 seconds.'
log_imap_conn_error = 'INFO: IMAP - Connection Error, reconnecting.'
log_imap_sync_event = 'INFO: IMAP - Received a sync event from server.'
log_help = 'INFO: User asked for help.'
log_balance = 'INFO: User requested balance.'
log_balance_sent = 'INFO: User balance sent. %(bal)s, %(mins)s, %(txts)s, %(mms)s, %(data)s, %(time)s'
log_unknown_user = 'INFO: User was not found in the database.'
log_token_error = 'WARNING: User refresh token was invalid.'
log_invalid_command = 'INFO: User issued an invalid command.'
log_plan_name_missing = 'WARNING: Plan details not found for "%(plan_name)s".'
log_plan_details_missing = 'WARNING: Plan name exists, but details not found for "%(plan_name)s" with an id of "%(plan_id)s".'

### The magic happens below this line. Only make changes if you know what you are doing. ###

# Import the required libraries
import sys, imaplib2, time, smtplib, time, urllib, requests, pymongo, locale, datetime, logging, traceback
from threading import *

# Setup Logging
if log_enabled:
    eval('logging.basicConfig(filename=log_file, level=logging.'+log_level+', format="%(asctime)s %(message)s")')
    logging.getLogger().addHandler(logging.StreamHandler())

# Create client client authorization
client_auth = requests.auth.HTTPBasicAuth(rp_client_id, rp_client_secret)

#Connect to the database
if database_localhost:
	db = eval('pymongo.MongoClient().'+database_name)
# TODO - Add remote host support.

# Set our Locale
locale.setlocale( locale.LC_ALL, locale_id )

# This class is used for our primary thread. It handles the IMAP connection & sync events.
class Idler(object):
    known_mail = []
    user = ''
    def __init__(self, conn):
        self.thread = Thread(target=self.idle)
        self.M = conn
        self.event = Event()
        self.doLogin()

    def start(self):
        self.thread.start()

    def stop(self):
        self.event.set()
        self.M.close()
        self.M.logout()

    def join(self):
        self.thread.join()

    # This fucntion is called to login.
    def doLogin(self):
        try:
            try:
                self.M.close()
                self.M.logout()
            except:
                pass
            self.M = imaplib2.IMAP4_SSL(email_imap_address)
            self.M.login(email_user,email_password)
            self.M.select('INBOX')
            logging.info(log_imap_sucess)
        except (imaplib2.IMAP4.abort, imaplib2.IMAP4.error):
            # Login failed, retry in 5 seconds.
            logging.warning(log_imap_login_error)
            traceback.print_exc()
            time.sleep(5)
            self.doLogin()
            pass
        return

    # This is our main idle loop to monitor IMAP events.
    def idle(self):
        # Initialy set all mail as known.
        typ, data = self.M.SEARCH(None, 'ALL')
        self.known_mail = data[0].split()
        # Start the endless loop here.
        while True:
            try:
                # Event used to stop the loop, and close the thread.
                if self.event.isSet():
                    return
                self.needsync = False
                # This callback is used when a sync event is received
                # from the IMAP server.
                def callback(args):
                    if not self.event.isSet():
                        self.needsync = True
                        self.event.set()
                # Do the idle call asynchronously.
                self.M.idle(callback=callback)
                # Wait until the event is set by the callback.
                self.event.wait()
                # Because the function sets the needsync variable,
                # this helps escape the loop without doing
                # anything if the stop() is called.
                if self.needsync:
                    self.event.clear()
                    self.doSync()
            # The connection was closed, let's reconnect.
            except (imaplib2.IMAP4.abort, imaplib2.IMAP4.error):
                logging.warning(log_imap_conn_error)
                self.doLogin()
                pass

    # The method that gets called when a sync event is received.
    def doSync(self):
        logging.info(log_imap_sync_event)
        # Get mail we don't know about yet.
        typ, data = self.M.SEARCH(None, 'UNSEEN')
        for id in data[0].split():
            if not id in self.known_mail:
                # Add this message to the known list.
                self.known_mail.append(id)
                # Get the email headers & content.
                typ, data = self.M.FETCH(id, 'RFC822')
                lines = ()
                # Split the response into a tuple for processing.
                for item in data:
                    for line in item:
                        lines = lines + tuple(line.split('\n'))
                lines = iter(lines)
                # Process the lines, we are looking for the
                # phone number, email, and message content.
                for line in lines:
                    if line.startswith('From'):
                        number = line.replace('From: ','').replace('"','')[:14]
                        email = line.replace('From: ','').replace('"','')[15:].replace('<','').replace('>','')
                    if line.startswith('Content-Type: text/plain;'):
                        next(lines)
                        msg = next(lines)
                if email_query_address in email:
                    # This is where we override the phone number if set.
                    if number_override:
                        number = number_value
                    # Log the details of the message.
                    logging.info('INFO: Email: '+email)
                    logging.info('INFO: Number: '+number)
                    logging.info('INFO: Message: '+msg)
                    # Process the message.
                    self.doReplies(email, number, msg)
    # This function is called to process received messages.
    def doReplies(self, email, number, msg):
        # Commands are processed here.
        if msg.lower().startswith('help'):
            logging.info(log_help)
            self.sendMsg(email, str_help)

        elif msg.lower().startswith('balance'):
            logging.info(log_balance)
            self.checkBalance(email, number, msg)
        elif msg.lower().startswith('debug'):
            self.doLogin()
        # Command was not recognized / failed to process.
        else:
            logging.info(log_invalid_command)
            self.sendMsg(email, str_invalid_command)
        logging.info('INFO: Reply Completed.\n\n')

    # This function is called when the user requests their balance.
    def checkBalance(self, email, number, msg):
        # Format the number in the format we use for the database / API.
        number = '1'+number.replace('(','').replace(') ','').replace('-','')
        # Check if the number is in the database.
        user = db.users.find_one({"accounts.phone_number": number})
        if not user:
            # Number was not found in the database, alert the user and log the event.
            logging.info(log_unknown_user+' '+number)
            self.sendMsg(email,str_unknown_user)
        else:
            # Number was in the database, lets refresh the access_token.
            tokens = self.refreshToken(user)
            if 'error' in tokens:
                # There was an error refreshing the token, alert the user and log the event.
                logging.info(log_token_error)
                self.sendMsg(email, str_token_error)
            else:
                account_id = ''
                account_balance = ''
                self.updateUser(tokens)
                # Get the users account account id and balance.
                user = db.users.find_one({"accounts.phone_number": number})
                for account in user['accounts']:
                    if account['phone_number'] == number:
                        account_id = account['id']
                        account_balance = account['balance']
                response = requests.get("https://api.ringplus.net/accounts/"+str(account_id)+"?access_token="+tokens['access_token'])
                account = response.json()['account']
                mins=0
                txts=0
                data=0
                mms=0
                # Calculate account usage accross all account subscriptions.
                for sub in account['active_billing_subscriptions']:
                    mins = mins + sub['voice_usage_in_mins']
                    txts = txts + sub['text_usage_in_count']
                    data = data + sub['data_usage_in_bytes']/1024/1024
                    mms = mms + sub['mms_usage_in_count']
                # Format usage.
                mins = locale.format("%d", mins, grouping=True)
                txts = locale.format("%d", txts, grouping=True)
                mms = locale.format("%d", mms, grouping=True)
                data = locale.format("%d", data, grouping=True)
                # Get the plan name.
                base_plans = {}
                base_plan_name = 'None'
                for sub in account['active_billing_subscriptions']:
                    plan_name = sub['name']
                    plan_info = db.plan_names.find_one({'name': plan_name})
                    if not plan_info:
                        # Plan was not found in the database, log the details.
                        logging.warning(log_plan_name_missing % {'plan_name': plan_name})
                        plan_details = None
                    else:
                        plan_details = db.plan_details.find_one({'plan_id': plan_info['planMatch']})
                        if not plan_details:
                            # The plan is in the database, but the details are
                            # missing or mapped to the worng plan_id, log the details.
                            logging.warning(log_plan_details_missing % {'plan_name': plan_name,'plan_id': plan_info['planMatch']})
                            logging.warning(plan_info)
                        if plan_info['type'] == 'base':
                            logging.info('Base plan identified: '+plan_name)
                            # Calculate time remaining in billing cycle.
                            recur = sub['end_date']
                            recur = datetime.datetime.strptime( recur[:19], "%Y-%m-%dT%H:%M:%S" )
                            now = datetime.datetime.utcnow().isoformat()
                            now = datetime.datetime.strptime( now[:19], "%Y-%m-%dT%H:%M:%S" )
                            plan_time = recur-now
                            base_plans.update({plan_name:{'time':plan_time}})
                if base_plans:
                    base_plan_name = max(base_plans, key=lambda x: base_plans[x]['time'].days)
                    time = base_plans[base_plan_name]['time']
                else:
                    recur = account['active_billing_subscriptions'][0]['end_date']
                    recur = datetime.datetime.strptime( recur[:19], "%Y-%m-%dT%H:%M:%S" )
                    now = datetime.datetime.utcnow().isoformat()
                    now = datetime.datetime.strptime( now[:19], "%Y-%m-%dT%H:%M:%S" )
                    time = recur-now


                # Check the plan is listed in the database.
                #if number == '18124842647':
                #    base_plan_name = 'Cherry - Unlimited Talk/SMS, 2GB Package'
                plan_info = db.plan_names.find_one({'name': base_plan_name})
                if not plan_info:
                    # Plan was not found in the database, log the details.
                    logging.warning(log_plan_name_missing % {'plan_name': base_plan_name})
                    plan_details = None
                else:
                    # Found the plan name, lets get the details.
                    plan_details = db.plan_details.find_one({'plan_id': plan_info['planMatch']})
                    if not plan_details:
                        # The plan is in the database, but the details are
                        # missing or mapped to the worng plan_id, log the details.
                        logging.warning(log_plan_details_missing % {'plan_name': plan_name,'plan_id': plan_info['planMatch']})
                        logging.warning(plan_info)

                if not plan_details:
                    # We couldn't find the plan details, so let's
                    # continue without the allotments using proper english. ^_^
                    if mins == 1:
                        mins = str(mins)+' minute'
                    else:
                        mins = str(mins)+' minutes'
                    if txts == 1:
                        txts = str(txts)+' text'
                    else:
                        txts = str(txts)+' texts'
                    mms = str(mms)+' mms'
                    data = str(data)+' MB'
                else:
                    # We found the plan details in the database, let's process them.
                    # If the plan is unlimited lets show the user in a better format.
                    mins_allot = plan_details['min_usa_allotment']
                    txts_allot = plan_details['sms_allotment']
                    mms_allot = plan_details['mms_allotment']
                    data_allot = plan_details['mb_allotment']
                    # Lets process all the active subscriptions.
                    for sub in account['active_billing_subscriptions']:
                        plan_info = db.plan_names.find_one({'name': sub['name']})
                        if not plan_info:
                            # Plan / addon details not found in the database, log the details.
                            logging.warning('No details found for plan "'+sub['name']+'".')
                            plan_details = None
                        else:
                            # Plan was found, lets get the details.
                            plan_details = db.plan_details.find_one({'plan_id': plan_info['planMatch']})
                            if not plan_details:
                                # Plan exists the the details are missing, lets log the details.
                                logging.warning(log_plan_details_missing % {'plan_name': sub['name'],'plan_id': plan_info['planMatch']})
                            else:
                                # If the plan is an addon, continue processing.
                                if plan_info['type'] == 'addon':
                                    # If the plan is not unlimited, calculate the allotments.
                                    if mins_allot is not -1 or plan_details['min_usa_allotment'] is not -1:
                                        mins_allot = mins_allot+plan_details['min_usa_allotment']
                                    else:
                                        mins_allot = -1
                                    if txts_allot is not -1 or plan_details['sms_allotment'] is not -1:
                                        txts_allot = txts_allot+plan_details['sms_allotment']
                                    else:
                                        txts_allot = -1
                                    if mms_allot is not -1 or plan_details['mms_allotment'] is not -1:
                                        mms_allot = mms_allot+plan_details['mms_allotment']
                                    else:
                                        mms_allot = -1
                                    if data_allot is not -1 or plan_details['mb_allotment'] is not -1:
                                        data_allot = data_allot+plan_details['mb_allotment']
                                    else:
                                        data_allot = -1

                    # Format the usage and allotments for the response.
                    if mins_allot == -1:
                        mins_allot = 'unlimited'
                    else:
                        mins_allot = locale.format("%d", mins_allot, grouping=True)
                    if txts_allot == -1:
                        txts_allot = 'unlimited'
                    else:
                        txts_allot = locale.format("%d", txts_allot, grouping=True)
                    if mms_allot == -1:
                        mms_allot = 'unlimited'
                    else:
                        mms_allot = locale.format("%d", mms_allot, grouping=True)
                    if data_allot == -1:
                        data_allot = 'unlimited'
                    else:
                        data_allot = locale.format("%d", data_allot, grouping=True)

                    mins = str(mins)+'/'+str(mins_allot)+' minutes'
                    txts =str(txts)+'/'+str(txts_allot)+' texts'
                    mms = str(mms)+'/'+str(mms_allot)+' mms'
                    data = str(data)+'/'+str(data_allot)+' MB'
                bal = locale.currency( account_balance, grouping=True )
                # let's use proper english? ^_^
                timeDays = time.days
                timeHours = time.seconds/60/60
                timeMinutes = time.seconds/60
                timeSeconds = time.seconds
                if time.days > 1:
                    if timeHours >= 12:
                        time = str(time.days+1)+' days'
                    else:
                        time = str(time.days)+' days'
                elif time.days == 1:
                    if timeHours >= 12:
                        time = '2 days'
                    else:
                        '1 day'
                else:
                    if timeHours > 1:
                        time = str(timeHours)+' hours'
                    elif timeHours == 1:
                        time = '1 hour'
                    else:
                        if timeMinutes == 1:
                            if timeSeconds >= 30:
                            time = '2 minutes'
                            else:
                                time = '1 minute'
                        elif timeMinutes < 1:
                                time = '1 minute'
                        else:
                            if timeSeconds >= 30:
                                time = str(timeMinutes+1)+' minutes'
                            else:
                                time = str(timeMinutes)+' minutes'
                # Create a dictionary of all the details.
                details = {'bal':bal,'mins':mins,'txts':txts,'mms':mms,'data':data,'time':time}
                # Send the details to the user, and log the event.
                self.sendMsg(email, str_balance_info % details)
                logging.info(log_balance_sent % details)

    # This fucntion is called to send a message. Pretty self explanatory?
    def sendMsg(self, email, message):
        fromaddr = email_user
        toaddrs  = email
        # Make a newline before the message or URLs will break the whole thing.
        msg = '\n'+message
        username = email_user
        password = email_password
        server = smtplib.SMTP(email_smtp_address)
        server.ehlo()
        server.starttls()
        server.login(username,password)
        server.sendmail(fromaddr, toaddrs, msg)
        server.quit()

    # This fucntion is called to refresh the user's tokens.
    def refreshToken(self, user):
        post_data = {"grant_type": "refresh_token",
                     "refresh_token": user['tokens']['refresh_token'],
                     "redirect_url": redirect_url}
        response = requests.post("https://my.ringplus.net/oauth/token",
                                 auth=client_auth,
                                 data=post_data)
        token_json = response.json()
        return token_json

    # This function is called to update the user's details in the database.
    def updateUser(self, tokens):
        client_auth = requests.auth.HTTPBasicAuth(rp_client_id, rp_client_secret)
        response = requests.get("https://api.ringplus.net/users?access_token="+tokens['access_token'])
        user = response.json()['users'][0]
        user[u'tokens'] = tokens
        found = db.users.find_one({"id": user['id']})
        if not found:
            user_id = db.users.insert_one(user).inserted_id
        else:
            user[u'_id'] = found['_id']
            db.users.save(user)
        return

# The main block of code that starts our application.
try:
    logging.info(log_service_start)
    # Create the IMAP Client Object.
    M = imaplib2.IMAP4_SSL(email_imap_address)
    # Start the idler thread, and pass the IMAP Client Object.
    idler = Idler(M)
    idler.start()
    # Start the endless loop.
    while True:
        try:
            time.sleep(60*60)
        except KeyboardInterrupt:
            logging.info(log_interrupt)
            break
finally:
    # Shutdown gracefully.
    idler.stop()
    idler.join()
    sys.exit()
