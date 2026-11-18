class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, **details):
        self.status = status
        self.payload = {"code": code, "message": message, **details}
        super().__init__(message)
