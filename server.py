#!/usr/bin/env python3

from bottle import (
    get, post, run, static_file, template, request, response, redirect
)

from base64 import urlsafe_b64decode as b64dec
import json
from os import getenv
from random import getrandbits
import re
from time import time

SECRET = getenv('COOKIE_SECRET', '%x' % getrandbits(128))

META = {
    'LA_HOSTNAME': 'laoidc.herokuapp.com',
    'RP_ORIGIN': 'http://localhost:%s' % getenv('PORT', '8080'),
}

if getenv('HEROKU_APP_NAME'):
    META['RP_ORIGIN'] = 'https://%s.herokuapp.com' % getenv('HEROKU_APP_NAME')


@get('/')
def index():
    # TODO: Move session handling to middleware
    # TODO: Check cookie expiration, once added
    session = request.get_cookie('session', secret=SECRET)
    if session is None:
        session = {'email': None}

    return template('template/index',
                    email=session['email'],
                    META=META)


@get('/login')
def login_get():
    redirect('/')


@post('/login')
def login_post():
    jwt = request.forms.get('id_token')

    result = get_verified_email(jwt)
    if 'error' in result:
        response.status = 400
        response.set_header('X-Failure-Reason', result['error'])
        return {'error': result['error']}

    # TODO: Bake an expiration date into the cookie
    # TODO: Add some other way to selectively, proactively invalidate sessions?
    response.set_cookie('session', {'email': result['email']},
                        path="/",
                        secret=SECRET,
                        httponly=True,
                        secure=META['RP_ORIGIN'].startswith('https://'))

    redirect('/')


@get('/logout')
def logout():
    # TODO: Switch to a POST / add CSRF protections?
    response.delete_cookie('session', path="/")
    redirect('/')


@get('/static/<path:path>')
def static(path):
    return static_file(path, root='./static')


def get_verified_email(jwt):
    # FIXME: This blindly trusts the JWT. Need to verify:
    # [ ] header is using an appropriate signing algorithm
    # [ ] signature is valid and matches a key from the LA provider's JWK Set
    # [x] iss matches a trusted LA provider's origin
    # [x] aud matches this site's origin
    # [x] exp > (now) > iat, with some margin
    # [-] sub is a valid email address

    (raw_header, raw_payload, raw_signature) = jwt.split('.')
    payload = json.loads(b64dec(raw_payload + '====').decode('utf-8'))

    iss = payload['iss']
    known_iss = 'https://%s' % META['LA_HOSTNAME']
    if iss != known_iss:
        return {'error':
                'Untrusted issuer. Expected %s, got %s' % (known_iss, iss)}

    aud = payload['aud']
    known_aud = META['RP_ORIGIN']
    if aud != known_aud:
        return {'error':
                'Audience mismatch. Expected %s, got %s' % (known_aud, aud)}

    iat = payload['iat']
    exp = payload['exp']
    now = int(time())
    slack = 3 * 60  # 3 minutes
    currently_valid = (iat - slack) < now < (exp + slack)
    if not currently_valid:
        return {'error':
                'Timestamp error. iat %d < now %d < exp %d' % (iat, now, exp)}

    sub = payload['sub']
    if not re.match('.+@.+', sub):  # <-- TODO: Use a proper parser.
        return {'error': 'Invalid email: %s' % sub}

    return {'email': payload['sub']}


host = 'localhost' if 'localhost' in META['RP_ORIGIN'] else '0.0.0.0'
run(server='gunicorn', host=host, port=int(getenv('PORT', '8080')))
