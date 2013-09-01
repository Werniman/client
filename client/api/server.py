#!/usr/bin/env python
# encoding: utf-8
"""Copyright (C) 2013 COLDWELL AG

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import uuid
import base64
import gevent

from bottle import Bottle, request, response, HTTPError
from socketio import socketio_manage, server
from socketio.namespace import BaseNamespace
from socketio.mixins import BroadcastMixin

from . import proto
from .. import settings, logger, localrpc, login

log = logger.get("api.server")

app = Bottle()

class Namespace(BaseNamespace, BroadcastMixin):
    def __init__(self, *args, **kwargs):
        BaseNamespace.__init__(self, *args, **kwargs)
        BroadcastMixin.__init__(self)
        self.disconnected = False

    #def initalize(self):
        #proto.add_connection(self)
        
    def recv_error(self, packet):
        print "error recv", packet
        pass
    
    def on_message(self, message):
        message = proto.unpack_message(message)
        gevent.spawn(proto.process_message, self.send_message, message)

    def send_message(self, message):
        #print ">>> SEND DIRECT", message['flags'], message.get('command'), message['payload']
        self.emit('message', message)

    def disconnect(self, *args, **kwargs):
        if self.disconnected is False:
            self.disconnected = True
            self.emit('client_leave', settings.app_uuid)
        try:
            proto.remove_connection(self)
        except ValueError:
            pass
        print "client disconnecting", args, kwargs
        
    def on_hello(self, uuid, origin):
        print "received on_hello", uuid, origin
        if str(uuid) == str(settings.app_uuid):
            self.emit('client_join', settings.app_uuid)
            proto.add_connection(self)
        
    def on_bye(self, uuid):
        print "received on_bye", uuid
        if str(uuid) == str(settings.app_uuid):
            proto.remove_connection(self)
        
    def on_service(self, *args):
        print "received on_service", args
        return False

@app.route('/')
def route_index():
    return "websocket client listening"

@app.route('/downloadam.js')
def route_downloadam_js():
    if not login.has_login():
        return
    response.headers['Content-Type'] = 'text/javascript'
    _uuid = base64.b64encode(login.encrypt('frontend', settings.app_uuid))
    return 'var downloadam_client_id="{}";'.format(_uuid)
    
@app.route('/socket.io/<arg:path>')
def route_socket_io(*arg, **kw):
    request.environ["HTTP_ORIGIN"] = "*.download.am"
    socketio_manage(request.environ, {'': Namespace}, request=request)
    return "out"

@app.route('/trylogin')
def route_login_dialog():
    _id = "/" + uuid.uuid4().hex
    username = request.query.username
    @app.route(_id)
    def show_login_dialog():
        try:
            app.routes.remove(route)
        except ValueError:
            return HTTPError(404)
        login.login_dialog(False, username, False)
        return "ok"
    route = app.routes[-1]
    print app.routes
    print route
    return """<a href="{}">Show login dialog for user {}</a>""".format(_id, username)

handle = None

def init():
    global handle
    try:
        handle = server.SocketIOServer(('127.0.0.1', 9090), app, policy_server=False, heartbeat_interval=4, heartbeat_timeout=20, close_timeout=300)
        if not handle.started:
            handle.start()
        localrpc.prevent_socket_inheritance(handle.socket)
    except:
        log.unhandled_exception('error starting local socketio server')

def terminate():
    global handle

    for conn in proto.connections[:]:
        if isinstance(conn, Namespace):
            conn.emit('client_leave', settings.app_uuid)
            proto.remove_connection(conn)

    if handle:
        handle.stop()
        handle = None
