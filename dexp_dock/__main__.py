"""Command line entry point. Without arguments it opens the window."""
import argparse
import datetime
import faulthandler
import logging
import os
import sys
import threading
import time

from . import __version__, device, log, protocol
from .client import DeviceTimeout
from .i18n import system_translator

logger = logging.getLogger('dexp_dock.cli')
HANG_SECONDS = 20


def _connect(tr):
    connection, _ = device.find_dock()
    if connection is None:
        print(tr('cli.not_found'), file=sys.stderr)
        sys.exit(2)
    return connection


def cmd_list(args, tr):
    connection, interfaces = device.find_dock()
    channels = connection.channels if connection else None
    print(device.diagnostics_report(interfaces, channels, tr, device.report_ids()))
    if connection:
        connection.close()


def cmd_sync_time(args, tr):
    connection = _connect(tr)
    try:
        now = datetime.datetime.now().replace(microsecond=0)
        confirmed = connection.client.sync_screen_clock(now)
        key = 'cli.synced_confirmed' if confirmed else 'cli.synced_sent'
        print(tr(key, time=now.strftime('%Y-%m-%d %H:%M:%S')))
    finally:
        connection.close()


def _start_hang_watchdog(tr, seconds):
    """If the check is stuck (e.g. inside a Win32 call), dump every thread's stack to the log and exit."""
    def fire():
        stream = log.stream()
        if stream is not None:
            stream.write('\n=== hang after %d s, thread stacks ===\n' % seconds)
            faulthandler.dump_traceback(file=stream, all_threads=True)
            stream.flush()
        print(tr('check.hang', seconds=seconds), flush=True)
        print(tr('check.log_path', path=args_log_path[0]), flush=True)
        os._exit(4)

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    timer.start()
    return timer


args_log_path = [None]


def cmd_check(args, tr):
    from .check import run_check
    watchdog = _start_hang_watchdog(tr, HANG_SECONDS)
    connection = None
    try:
        connection, interfaces = device.find_dock()
        print(device.diagnostics_report(interfaces, connection.channels if connection else None, tr,
                                        device.report_ids()), flush=True)
        if connection is None:
            sys.exit(2)
        print(flush=True)
        moment = datetime.datetime.now().replace(microsecond=0)
        for line in run_check(connection.client, tr, moment, on_progress=lambda text: print(text, flush=True)):
            print(line, flush=True)
    finally:
        if connection is not None:
            connection.close()
        watchdog.cancel()
        print(tr('check.log_path', path=args_log_path[0]), flush=True)


def cmd_screen_probe(args, tr):
    connection = _connect(tr)
    try:
        client = connection.client
        length, report_id = client.screen_report_shape()
        print(tr('probe.intro', pause=args.pause), flush=True)
        for number in protocol.CLOCK_VARIANTS:
            marker = protocol.variant_marker_time(number, datetime.datetime.now())
            packet = protocol.build_screen_clock_variant(number, marker, length=length, report_id=report_id)
            answer = client.send_screen(packet)
            logger.info('clock variant %d sent %s reply %s', number, packet.hex(' '),
                        answer.hex(' ') if answer else None)
            print(tr('probe.sent', number=number, time=marker.strftime('%H:%M'),
                     reply=answer.hex(' ') if answer else tr('check.no_reply')), flush=True)
            time.sleep(args.pause)
        print(tr('probe.outro'), flush=True)
        print(tr('check.log_path', path=args_log_path[0]), flush=True)
    finally:
        connection.close()


def cmd_read(args, tr):
    connection = _connect(tr)
    try:
        light = connection.client.read_dock_light()
        print(tr('cli.light', **light.__dict__))
        slots = connection.client.read_indicator()
        print(tr('cli.indicator', slots=' '.join(str(s) for s in slots)))
    finally:
        connection.close()


def cmd_light(args, tr):
    connection = _connect(tr)
    try:
        current = connection.client.read_dock_light()
        red, green, blue = device.parse_color(args.color) if args.color else (current.red, current.green, current.blue)
        light = protocol.DockLight(
            mode=current.mode if args.mode is None else args.mode,
            red=red, green=green, blue=blue,
            speed=current.speed if args.speed is None else args.speed,
            brightness=current.brightness if args.brightness is None else args.brightness)
        connection.client.set_dock_light(light)
        print(tr('cli.light', **light.__dict__))
    finally:
        connection.close()


def cmd_indicator(args, tr):
    connection = _connect(tr)
    try:
        connection.client.set_indicator(tuple(args.slots))
        print(tr('cli.applied'))
    finally:
        connection.close()


def cmd_daemon(args, tr):
    print(tr('cli.daemon_started', interval=args.interval))
    connection = None
    next_sync = 0.0
    while True:
        try:
            if connection is None:
                connection, _ = device.find_dock()
                next_sync = 0.0
            if connection is not None and time.monotonic() >= next_sync:
                connection.client.sync_screen_clock(datetime.datetime.now().replace(microsecond=0))
                next_sync = time.monotonic() + args.interval
        except (OSError, DeviceTimeout, RuntimeError):
            if connection is not None:
                connection.close()
            connection = None
        time.sleep(3)


def cmd_dpi_follow(args, tr):
    from .dpi_follow import DpiFollower
    connection = _connect(tr)
    follower = DpiFollower(lambda: connection.client, speed=args.speed, brightness=args.brightness)
    print(tr('cli.dpi_follow_started'), flush=True)
    try:
        follower.start()
        started = time.monotonic()
        shown = None
        while args.seconds == 0 or time.monotonic() - started < args.seconds:
            stage = follower.poll()
            if stage is not None and stage != shown:
                shown = stage
                print(tr('cli.dpi_stage', stage=stage + 1, count=follower.stage_count), flush=True)
            time.sleep(0.15)
    finally:
        try:
            follower.stop()
        finally:
            connection.close()


def cmd_gui(args, tr):
    from .app import run
    run(tr)


def cmd_tray(args, tr):
    """Start hidden in the notification area (open the window from the icon)."""
    from .app import run
    run(tr, start_hidden=True)


def build_parser(tr):
    parser = argparse.ArgumentParser(prog='dexp_dock', description=tr('app.title'))
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('gui').set_defaults(func=cmd_gui)
    sub.add_parser('tray').set_defaults(func=cmd_tray)
    sub.add_parser('list').set_defaults(func=cmd_list)
    sub.add_parser('check').set_defaults(func=cmd_check)
    sub.add_parser('sync-time').set_defaults(func=cmd_sync_time)
    probe = sub.add_parser('screen-probe')
    probe.add_argument('--pause', type=int, default=5)
    probe.set_defaults(func=cmd_screen_probe)
    sub.add_parser('read').set_defaults(func=cmd_read)
    light = sub.add_parser('light')
    light.add_argument('--mode', type=int, choices=range(0, 7))
    light.add_argument('--color')
    light.add_argument('--brightness', type=int, choices=range(1, 11))
    light.add_argument('--speed', type=int, choices=range(1, 11))
    light.set_defaults(func=cmd_light)
    indicator = sub.add_parser('indicator')
    indicator.add_argument('slots', type=int, nargs=3)
    indicator.set_defaults(func=cmd_indicator)
    daemon = sub.add_parser('daemon')
    daemon.add_argument('--interval', type=int, default=60)
    daemon.set_defaults(func=cmd_daemon)
    follow = sub.add_parser('dpi-follow')
    follow.add_argument('--seconds', type=float, default=0, help='0 = until Ctrl+C')
    follow.add_argument('--brightness', type=int, choices=range(1, 11), default=10)
    follow.add_argument('--speed', type=int, choices=range(1, 11), default=5)
    follow.set_defaults(func=cmd_dpi_follow)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args_log_path[0] = log.setup_logging()
    tr = system_translator()
    args = build_parser(tr).parse_args(argv)
    func = getattr(args, 'func', cmd_gui)
    logger.info('dexp_dock %s, python %s, args %s', __version__, sys.version.split()[0], sys.argv[1:])
    try:
        func(args, tr)
    except DeviceTimeout:
        print(tr('error.timeout'), file=sys.stderr)
        sys.exit(3)
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception('unhandled error')
        raise
    finally:
        log.shutdown()


if __name__ == '__main__':
    main()
