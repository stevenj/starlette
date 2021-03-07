import enum
import json
import typing

from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send

import datetime

def trace_it(message, scope: Scope):
    print(
        f"{datetime.datetime.utcnow()} : Starlette Low Level Trace {scope['client']}  : {message}"
    )

class WebSocketState(enum.Enum):
    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2


class WebSocketDisconnect(Exception):
    def __init__(self, code: int = 1000) -> None:
        self.code = code


class WebSocket(HTTPConnection):
    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        super().__init__(scope)
        assert scope["type"] == "websocket"
        self._receive = receive
        self._send = send
        self.client_state = WebSocketState.CONNECTING
        self.application_state = WebSocketState.CONNECTING

    async def receive(self) -> Message:
        """
        Receive ASGI websocket messages, ensuring valid state transitions.
        """
        trace_it("Websocket receive started", self.scope)
        if self.client_state == WebSocketState.CONNECTING:
            trace_it("Websocket _receive started #1", self.scope)
            message = await self._receive()
            trace_it(f"Websocket _receive {message} ended #1", self.scope)
            message_type = message["type"]
            assert message_type == "websocket.connect"
            self.client_state = WebSocketState.CONNECTED
            trace_it(f"Websocket receive ended {message} - CONNECTING", self.scope)
            return message
        elif self.client_state == WebSocketState.CONNECTED:
            trace_it("Websocket _receive started #2", self.scope)
            message = await self._receive()
            trace_it(f"Websocket _receive {message} ended #2", self.scope)
            message_type = message["type"]
            assert message_type in {"websocket.receive", "websocket.disconnect"}
            if message_type == "websocket.disconnect":
                trace_it(f"Websocket disconnected on RX {message}", self.scope)
                self.client_state = WebSocketState.DISCONNECTED
            trace_it(f"Websocket receive ended {message} - CONNECTED", self.scope)
            return message
        else:
            raise RuntimeError(
                'Cannot call "receive" once a disconnect message has been received.'
            )

    async def send(self, message: Message) -> None:
        """
        Send ASGI websocket messages, ensuring valid state transitions.
        """
        trace_it(f"Websocket send start {message}", self.scope)
        if self.application_state == WebSocketState.CONNECTING:
            trace_it(f"Websocket send {message} - connecting", self.scope)
            message_type = message["type"]
            assert message_type in {"websocket.accept", "websocket.close"}
            if message_type == "websocket.close":
                self.application_state = WebSocketState.DISCONNECTED
            else:
                self.application_state = WebSocketState.CONNECTED
            trace_it(f"Websocket awaiting _send {message} #1", self.scope)
            await self._send(message)
            trace_it(f"Websocket awaiting _send {message} done #1", self.scope)
        elif self.application_state == WebSocketState.CONNECTED:
            trace_it(f"Websocket send - {message} connected", self.scope)
            message_type = message["type"]
            assert message_type in {"websocket.send", "websocket.close"}
            if message_type == "websocket.close":
                trace_it(f"Websocket now disconnected {message}", self.scope)
                self.application_state = WebSocketState.DISCONNECTED
            trace_it(f"Websocket awaiting _send {message} #2", self.scope)
            await self._send(message)
            trace_it(f"Websocket awaiting _send {message} done #2", self.scope)
        else:
            trace_it(f"Websocket send {message} - error", self.scope)
            raise RuntimeError('Cannot call "send" once a close message has been sent.')
        trace_it(f"Websocket send {message} end", self.scope)

    async def accept(self, subprotocol: str = None) -> None:
        if self.client_state == WebSocketState.CONNECTING:
            # If we haven't yet seen the 'connect' message, then wait for it first.
            await self.receive()
        await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    def _raise_on_disconnect(self, message: Message) -> None:
        if message["type"] == "websocket.disconnect":
            trace_it(f"Websocket _raise_on_disconnect {message} TRUE", self.scope)
            raise WebSocketDisconnect(message["code"])

    async def receive_text(self) -> str:
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["text"]

    async def receive_bytes(self) -> bytes:
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["bytes"]

    async def receive_json(self, mode: str = "text") -> typing.Any:
        trace_it("Websocket receive_json", self.scope)
        assert mode in ["text", "binary"]
        assert self.application_state == WebSocketState.CONNECTED
        trace_it("Websocket receive_json - waiting for message", self.scope)
        message = await self.receive()
        trace_it(f"Websocket receive_json - waiting for message {message} ended", self.scope)
        self._raise_on_disconnect(message)

        if mode == "text":
            text = message["text"]
        else:
            text = message["bytes"].decode("utf-8")
        trace_it(f"Websocket receive_json {text} - ended", self.scope)
        return json.loads(text)

    async def iter_text(self) -> typing.AsyncIterator[str]:
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self) -> typing.AsyncIterator[bytes]:
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def iter_json(self) -> typing.AsyncIterator[typing.Any]:
        try:
            while True:
                yield await self.receive_json()
        except WebSocketDisconnect:
            pass

    async def send_text(self, data: str) -> None:
        await self.send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        await self.send({"type": "websocket.send", "bytes": data})

    async def send_json(self, data: typing.Any, mode: str = "text") -> None:
        assert mode in ["text", "binary"]
        text = json.dumps(data)
        if mode == "text":
            await self.send({"type": "websocket.send", "text": text})
        else:
            await self.send({"type": "websocket.send", "bytes": text.encode("utf-8")})

    async def close(self, code: int = 1000) -> None:
        trace_it(f"Websocket Close start. ({code}) ", self.scope)
        await self.send({"type": "websocket.close", "code": code})
        trace_it(f"Websocket Close end. ({code}) ", self.scope)


class WebSocketClose:
    def __init__(self, code: int = 1000) -> None:
        self.code = code

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        trace_it(f"WebSocketClose _call_ ({self.code}) ", scope)
        await send({"type": "websocket.close", "code": self.code})
        trace_it(f"WebSocketClose _call_ ({self.code}) ended", scope)
