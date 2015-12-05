#!/usr/bin/env python2

# This Webserver is very basic, and should be updated as soon as possible.
# We Should be using templates, CSS files, etc.
# SSL on the development site is acheved using NGINX.

### Configurable Options, change these to suit your needs. ###

# RingPlus API details...
client_id = ''
client_secret = ''
redirect_uri = 'https://example.com/rp/authenticate'

# Port to run the webserver on.
webserver_port = 65010

# Database Configuration. We will eventually support remote hosts.
# However, this funcationality has not been added yet.
database_localhost = True # True or False
database_name = 'ringplus'

# URI paths
uri_home = '/rp'
uri_authenticate = '/rp/authenticate'

### The magic happens below this line. Only make changes if you know what you are doing. ###

import time, urllib, requests, pymongo
from flask import Flask, abort, request
app = Flask(__name__)
client_auth = requests.auth.HTTPBasicAuth(client_id, client_secret)

#Connect to the database
if database_localhost:
	db = eval('pymongo.MongoClient().'+database_name)
# TODO - Add remote host support.

@app.route(uri_home)
def homepage():
    text = '<div style="text-align: center; font-family: Arial, \'Helvetica Neue\', Helvetica, sans-serif"><br><h1>Automated Account Messages</h1><p>This service provides you with a way to check your account usage via sms (text message). Click the link below to authenticate with RingPlus first. Then send a text to <strong>260-230-1330</strong> to get started. Your web browser may prompt you with a certificate error, as our certificate authority is not yet trusted by some browsers. Follow your browsers procedure for bypassing the message.</p><p style="font-size: 1.5em;"><a href="%s">Authenticate with RingPlus</a></p></div>'
    return text % makeAuthorizationUrl()

def makeAuthorizationUrl():
    # Generate a random string for the state parameter
    # Save it for use later to prevent xsrf attacks
    from uuid import uuid4
    state = str(uuid4())
    saveCreatedState(state)
    params = {"client_id": client_id,
              "response_type": "code",
              "redirect_uri": redirect_uri
             }
    url = "https://my.ringplus.net/oauth/authorize?" + urllib.urlencode(params)
    return url

@app.route(uri_authenticate)
def authenticateCallback():
    error = request.args.get('error', '')
    if error:
        return "Error: " + error
    state = request.args.get('state', '')
    if not isValidState(state):
    # Uh-oh, this request wasn't started by us!
        abort(403)
    code = request.args.get('code')
    tokens = getToken(code)
    updateUser(tokens)
    return '<div style="text-align: center; font-family: Arial, \'Helvetica Neue\', Helvetica, sans-serif"><br><h1>Automated Account Messages</h1><p>Your account has been registered successfully in our system. Send a text message to <strong>260-230-1330</strong> to get started.</div>'

def getToken(code):
    post_data = {"grant_type": "authorization_code",
                 "code": code,
                 "redirect_uri": redirect_uri}
    response = requests.post("https://my.ringplus.net/oauth/token",
                             auth=client_auth,
                             data=post_data)
    token_json = response.json()
    return token_json

def updateUser(tokens):
    client_auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
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

def saveCreatedState(state):
    pass

def isValidState(state):
    return True


if __name__ == '__main__':
    app.run(debug=False, threaded=True, port=webserver_port)
