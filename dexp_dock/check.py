"""One-shot hardware check: reads lighting and indicators, sets the clock, prints raw traffic.

Every step reports its own failure so one broken step never hides the others.
"""
import logging

from .client import DeviceTimeout
from .protocol import CommandRejected

logger = logging.getLogger(__name__)


def _hex(data):
    return bytes(data).hex(' ')


def _step(tr, key, action, on_progress):
    on_progress(tr('check.progress', step=tr(key + '_step')))
    try:
        result = action()
    except DeviceTimeout:
        logger.warning('%s: no reply', key)
        result = tr('check.no_reply')
    except CommandRejected as exc:
        logger.warning('%s: %s', key, exc)
        result = tr('check.unsupported')
    except Exception as exc:
        logger.exception('%s failed', key)
        result = tr('error.generic', error='%s: %s' % (type(exc).__name__, exc))
    return tr(key, result=result)


def run_check(client, tr, moment, on_progress=lambda text: None):
    def light():
        value = client.read_dock_light()
        return tr('check.light_ok', raw=_hex(client.last_response), mode=value.mode,
                  color='#%02X%02X%02X' % (value.red, value.green, value.blue),
                  brightness=value.brightness, speed=value.speed)

    def indicator():
        slots = client.read_indicator()
        return tr('check.indicator_ok', raw=_hex(client.last_response), slots=' '.join(str(s) for s in slots))

    def screen():
        client.sync_screen_clock(moment)
        answer = client.last_screen_response
        return tr('check.screen_ok', sent=_hex(client.last_screen_packet),
                  reply=tr('check.no_reply') if answer is None else _hex(answer))

    return [
        _step(tr, 'check.light', light, on_progress),
        _step(tr, 'check.indicator', indicator, on_progress),
        _step(tr, 'check.screen', screen, on_progress),
        tr('check.look_at_screen', time=moment.strftime('%H:%M')),
    ]
