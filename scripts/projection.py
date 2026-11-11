# /// script
# requires-python = ">=3.11"
# dependencies = ["obsws-python>=1.8,<2"]
# ///
"""Compose an existing OBS FlightGear capture with the read-only browser overlay."""
import argparse
import os
import subprocess
import sys
import shlex
from urllib.parse import urlsplit

SCENE = 'Flight by committee'
OVERLAY = 'Collective overlay'


def open_projection(url):
    """Open the audience tools without taking ownership of the user's OBS process."""
    if sys.platform == 'darwin':
        for label, command in [('OBS', ['open', '-a', 'OBS']),
                               ('overlay preview', ['open', url])]:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                if result.returncode:
                    print(f'Could not open {label}: {result.stderr.strip()}', file=sys.stderr, flush=True)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f'Could not open {label}: {exc}', file=sys.stderr, flush=True)
    else:
        print('Open OBS and the overlay URL in your browser.', flush=True)
    print('OBS composition requires the one-time capture/WebSocket setup in docs/projection.md.\n'
          'Then run in another terminal:\n  uv run scripts/projection.py --url ' + shlex.quote(url), flush=True)
    print('Overlay preview works only while this flight launcher is running. '
          'Use this run’s URL on this computer.', flush=True)


def configure(client, url, capture, monitor=None):
    """Reuse named sources and scene items, so rerunning refreshes the run's URL."""
    sources = {item['inputName'] for item in client.get_input_list().inputs}
    if capture not in sources:
        raise ValueError(f'Create an OBS macOS Screen Capture source named {capture!r} first.')
    video = client.get_video_settings()
    width, height = video.base_width, video.base_height
    scenes = {item['sceneName'] for item in client.get_scene_list().scenes}
    if SCENE not in scenes:
        client.create_scene(SCENE)
    settings = dict(url=url, width=width, height=height, fps=30,
                    shutdown=False, restart_when_active=False)
    if OVERLAY not in sources:
        client.create_input(SCENE, OVERLAY, 'browser_source', settings, True)
    else:
        client.set_input_settings(OVERLAY, settings, True)
    items = {item['sourceName']: item['sceneItemId']
             for item in client.get_scene_item_list(SCENE).scene_items}
    for name in (capture, OVERLAY):
        if name not in items:
            items[name] = client.create_scene_item(SCENE, name, True).scene_item_id
        client.set_scene_item_enabled(SCENE, items[name], True)
        client.set_scene_item_transform(SCENE, items[name], {
            'positionX': 0, 'positionY': 0, 'rotation': 0,
            'boundsType': 'OBS_BOUNDS_SCALE_INNER', 'boundsWidth': width,
            'boundsHeight': height, 'boundsAlignment': 0,
            'alignment': 5, 'cropLeft': 0, 'cropRight': 0, 'cropTop': 0, 'cropBottom': 0,
        })
    client.set_scene_item_index(SCENE, items[OVERLAY],
                                len(client.get_scene_item_list(SCENE).scene_items) - 1)
    client.set_current_program_scene(SCENE)
    if monitor is not None:
        monitors = client.get_monitor_list().monitors
        if monitor not in {m['monitorIndex'] for m in monitors}:
            raise ValueError(f'Unknown monitor {monitor}; use --list-monitors.')
        client.open_video_mix_projector('OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM', monitor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Overlay URL printed by fly; changes each flight')
    parser.add_argument('--capture', default='FlightGear', help='Existing OBS capture source')
    parser.add_argument('--port', type=int, default=4455)
    parser.add_argument('--monitor', type=int, help='OBS monitor index for fullscreen projection')
    parser.add_argument('--list-monitors', action='store_true')
    args = parser.parse_args()
    if not args.list_monitors:
        parsed = urlsplit(args.url or '')
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/projection':
            parser.error('--url must be the local overlay URL printed by fly')
    import obsws_python
    client = obsws_python.ReqClient(host='127.0.0.1', port=args.port,
                                    password=os.environ.get('OBS_WEBSOCKET_PASSWORD', ''), timeout=5)
    try:
        if args.list_monitors:
            for monitor in client.get_monitor_list().monitors:
                print(monitor)
        else:
            configure(client, args.url, args.capture, args.monitor)
            print('Projection scene ready. No recording or streaming started.')
    finally:
        client.disconnect()


if __name__ == '__main__':
    main()
