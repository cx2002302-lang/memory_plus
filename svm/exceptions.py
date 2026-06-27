class SVMError(Exception):
    pass


class BlockNotFoundError(SVMError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Block not found: {key}")


class SlotNotFoundError(SVMError):
    def __init__(self, slot_id: str) -> None:
        self.slot_id = slot_id
        super().__init__(f"Slot not found: {slot_id}")


class MemoryFullError(SVMError):
    def __init__(self, current: int, maximum: int) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(f"Memory full: {current}/{maximum} bytes")


class ConfigError(SVMError):
    pass


class TenantMismatchError(SVMError):
    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Tenant mismatch: expected '{expected}', got '{actual}'")
