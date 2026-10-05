"""Safe public error codes: never attach raw HTTP bodies or token exceptions."""


class AIError(RuntimeError):
    def __init__(self, code, *, http_status=None, request_id=None):
        self.code = code
        self.http_status = http_status
        self.request_id = request_id
        super().__init__(code)
