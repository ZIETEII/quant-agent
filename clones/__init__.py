from .ninja import NinjaClone
from .turtle import TurtleClone
from .trend import TrendClone

def initialize_clones():
    return {
        "clone_scalper": NinjaClone(),
        "clone_conservador": TurtleClone(),
        "clone_inercia": TrendClone()
    }
