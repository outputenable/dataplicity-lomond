from __future__ import unicode_literals

"""

Test against a Tornado WebSocket server

"""

import time
import threading

from tornado import gen, ioloop, httpserver, web, websocket

from lomond import WebSocket


class GracefulHandler(websocket.WebSocketHandler):
    """Writes text/binary then closes gracefully."""

    def check_origin(self, origin):
        return True

    @gen.coroutine
    def open(self):
        self.set_nodelay(True)
        yield self.write_message(u'foo')
        yield self.write_message(b'bar', binary=True)
        yield self.close()


class NonGracefulHandler(websocket.WebSocketHandler):
    """Writes text/binary then closes the socket."""

    def check_origin(self, origin):
        return True

    @gen.coroutine
    def open(self):
        self.set_nodelay(True)
        yield self.write_message(u'foo')
        yield self.write_message(b'bar', binary=True)
        yield self.stream.close()


class EchoHandler(websocket.WebSocketHandler):
    """Echos any message sent to it."""

    def check_origin(self, origin):
        return True

    @gen.coroutine
    def on_message(self, message):
        yield self.write_message(message, binary=isinstance(message, bytes))


class TestIntegration(object):

    WS_URL = 'ws://127.0.0.1:8080/'

    @classmethod
    def run_server(cls, port=8080):
        app = web.Application([
            (r'^/graceful$', GracefulHandler),
            (r'^/non-graceful$', NonGracefulHandler),
            (r'^/echo$', EchoHandler)
        ])
        cls.server = server = httpserver.HTTPServer(app)
        cls.loop = ioloop.IOLoop.current()
        server.bind(port, reuse_port=True)
        server.start(1)
        cls.loop.start()

    @classmethod
    def setup_class(cls):
        server_thread = threading.Thread(target=cls.run_server)
        server_thread.daemon = True
        server_thread.start()
        time.sleep(0.1)

    @classmethod
    def teardown_class(cls):
        cls.loop.add_callback(cls.loop.stop)

    def test_graceful(self):
        """Test server that closes gracefully."""
        ws = WebSocket(self.WS_URL + 'graceful')
        events = list(ws.connect(ping_rate=0))

        assert len(events) == 8
        assert events[0].name == 'connecting'
        assert events[1].name == 'connected'
        assert events[2].name == 'ready'
        assert events[3].name == 'poll'
        assert events[4].name == 'text'
        assert events[4].text == u'foo'
        assert events[5].name == 'binary'
        assert events[5].data == b'bar'
        assert events[6].name == 'closing'
        assert events[7].name == 'disconnected'
        assert events[7].graceful

    def test_non_graceful(self):
        """Test server that closes socket."""
        ws = WebSocket(self.WS_URL + 'non-graceful')
        events = list(ws.connect(ping_rate=0))

        assert len(events) == 7
        assert events[0].name == 'connecting'
        assert events[1].name == 'connected'
        assert events[2].name == 'ready'
        assert events[3].name == 'poll'
        assert events[4].name == 'text'
        assert events[4].text == u'foo'
        assert events[5].name == 'binary'
        assert events[5].data == b'bar'
        assert events[6].name == 'disconnected'
        assert not events[6].graceful

    def test_echo(self):
        """Test echo server."""
        ws = WebSocket(self.WS_URL + 'echo')
        events = []
        for event in ws.connect(poll=60, ping_rate=0, auto_pong=False):
            events.append(event)
            if event.name == 'ready':
                ws.send_text(u'echofoo')
                ws.send_binary(b'echobar')
                ws.close()

        assert len(events) == 8
        assert events[0].name == 'connecting'
        assert events[1].name == 'connected'
        assert events[2].name == 'ready'
        assert events[3].name == 'poll'
        assert events[4].name == 'text'
        assert events[4].text == u'echofoo'
        assert events[5].name == 'binary'
        assert events[5].data == b'echobar'
        assert events[6].name == 'closed'
        assert events[7].name == 'disconnected'
        assert events[7].graceful

    def test_premature_close_connecting(self):
        """Test close after connecting event."""
        ws = WebSocket('ws://NEVERCONNECTS')
        for event in ws:
            if event.name == 'connecting':
                ws.close()

    def test_premature_close_connected(self):
        """Test close after connected event."""
        ws = WebSocket(self.WS_URL + 'graceful')
        for event in ws:
            if event.name == 'connected':
                ws.close()
