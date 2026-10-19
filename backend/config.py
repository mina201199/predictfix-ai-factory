"""Explicit modes: an empty operational installation is the default."""
import os

def demo():
    return os.getenv('APP_MODE', 'production') == 'demo'

def lan():
  return os.getenv('LAN_MODE') == '1'

def validate():
    if lan() and os.getenv('DEMO_MODE') == '1':
        raise RuntimeError('LAN mode forbids quick login')
    if os.getenv('APP_MODE', 'production') not in ('production', 'demo'):
        raise RuntimeError('APP_MODE must be production or demo')
    if not demo() and os.getenv('DEMO_MODE') == '1':
        raise RuntimeError('Quick login is forbidden in production mode')
