from enum import Enum

class Platform(Enum):
    VC4 = 0
    PISP = 1

def get_platform() -> Platform: ...
