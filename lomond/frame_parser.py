"""
Parse a stream of Websocket frames, and optional HTTP headers.

"""

from __future__ import unicode_literals

import logging
import struct

from . import errors
from .frame import CompressedFrame, Frame
from .parser import Parser
from .utf8validator import Utf8Validator


log = logging.getLogger("lomond")


class FrameParser(Parser):
    """Parses a stream of data in to HTTP headers + WS frames."""

    unpack16 = struct.Struct(b"!H").unpack
    unpack64 = struct.Struct(b"!Q").unpack

    def __init__(self, parse_headers=True):
        self._is_text = False
        self._utf8_validator = Utf8Validator()
        self._frame_class = Frame
        self._compression = False
        self._parser_headers = parse_headers
        super(FrameParser, self).__init__()

    def enable_compression(self):
        """Enable compressed packets."""
        self._compression = True
        self._frame_class = CompressedFrame

    def read_text(self, length):
        """Read encoded text."""
        if self._compression:
            return self.read(length)
        else:
            return self.read_utf8(length, self._utf8_validator)

    def parse(self):
        # Get any WS frames
        if self._parser_headers:
            header_data = yield self.read_until(
                b"\r\n\r\n", max_bytes=16 * 1024
            )
            yield header_data

        while True:
            byte1, byte2 = bytearray((yield self.read(2)))

            fin = byte1 >> 7
            rsv1 = (byte1 >> 6) & 1
            rsv2 = (byte1 >> 5) & 1
            rsv3 = (byte1 >> 4) & 1
            opcode = byte1 & 0b00001111
            mask_bit = byte2 >> 7
            payload_length = byte2 & 0b01111111

            if payload_length == 126:
                (payload_length,) = self.unpack16((yield self.read(2)))
            elif payload_length == 127:
                (payload_length,) = self.unpack64((yield self.read(8)))
            if payload_length > 0x7fffffffffffffff:
                raise errors.PayloadTooLarge("payload is too large")

            if mask_bit:
                masking_key = yield self.read(4)
            else:
                masking_key = None

            frame = self._frame_class(
                opcode,
                fin=fin,
                rsv1=rsv1,
                rsv2=rsv2,
                rsv3=rsv3,
            )
            frame.validate()

            if frame.is_text:
                self._is_text = True

            if payload_length:
                _is_text_continuation = (
                    frame.is_continuation and self._is_text
                )
                if frame.is_text or _is_text_continuation:
                    frame.payload = yield self.read_text(payload_length)
                else:
                    frame.payload = yield self.read(payload_length)

            self.on_frame(frame)
            yield frame

    def on_frame(self, frame):
        """Called with new frames."""
        if (
            not self._compression
            and frame.fin
            and (frame.is_text or frame.is_continuation)
        ):
            self._utf8_validator.reset()
        if frame.fin:
            self._is_text = False
