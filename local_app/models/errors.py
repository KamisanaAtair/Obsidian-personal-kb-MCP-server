"""Stable, deliberately redacted errors safe for local UI and MCP responses."""


class ModelError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
