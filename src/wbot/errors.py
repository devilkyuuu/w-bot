from __future__ import annotations

from enum import Enum


class ErrorCode(Enum):
    BAD_REQUEST = "bad_request"
    UNSUPPORTED = "unsupported"
    TOO_LONG = "too_long"
    TOO_LARGE = "too_large"
    RETRIEVAL = "retrieval"


ERROR_TEXT = {
    ErrorCode.BAD_REQUEST: "Send one supported link after /w.",
    ErrorCode.UNSUPPORTED: "That link isn't supported.",
    ErrorCode.TOO_LONG: "That video is longer than 5 minutes.",
    ErrorCode.TOO_LARGE: "That file is too large to send.",
    ErrorCode.RETRIEVAL: "I couldn't retrieve that content.",
}


class BotError(RuntimeError):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class RetrievalError(BotError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.RETRIEVAL)


class VideoTooLongError(BotError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.TOO_LONG)


class MediaTooLargeError(BotError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.TOO_LARGE)
