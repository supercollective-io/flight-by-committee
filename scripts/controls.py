"""Transport-independent equal-weight control aggregation and freshness."""
import math
import re
import secrets
import threading
import time

AXES = ('roll', 'pitch', 'rudder', 'brake', 'throttle')


def generation_valid(value):
    return type(value) in (int, float) and math.isfinite(value) and value == int(value) and 0 <= value < 2**31


def bounded_controls(values):
    if not isinstance(values, dict) or set(values) != set(AXES):
        raise ValueError('A complete fixed control frame is required')
    for axis, value in values.items():
        if axis == 'throttle' and value is None:
            continue
        low = -1 if axis in ('roll', 'pitch', 'rudder') else 0
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= 1:
            raise ValueError('Invalid control range')


class State:
    def __init__(self, config, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.lock = threading.Lock()
        self.sessions = {}
        self.brake_release = 0
        self.release_owner = None
        self.release_counter = 0
        self.revision = 0
        self.ready = False
        self.connected = False
        self.generation = None
        self.throttle = 0
        self.applied = dict(roll=0, pitch=0, rudder=0, brake=0)
        self.join_url = None
        self.qr_svg = None

    def invalidate(self):
        self.brake_release = 0
        self.sessions.clear()
        self.release_owner = None

    def participants(self):
        now = self.clock()
        for session, participant in list(self.sessions.items()):
            if now - max(participant['last_input'], participant['issued']) >= self.config['expiry_s']:
                del self.sessions[session]
        active = [p for p in self.sessions.values()
                  if self.ready and now - p['last_input'] < self.config['expiry_s']]
        if self.release_owner is not None and self.sessions.get(self.release_owner) not in active:
            self.brake_release = 0
            self.release_owner = None
        return active

    def fresh(self):
        return bool(self.participants())

    @property
    def values(self):
        participants = self.participants()
        if not participants:
            return dict(roll=0, pitch=0, rudder=0, brake=0, throttle=None)
        return {axis: sum(p['values'][axis] for p in participants) / len(participants)
                for axis in AXES}

    def status(self):
        participants = self.participants()
        return dict(simulator=self.connected, ready=self.ready, active=bool(participants),
                    count=len(participants), throttle=self.throttle, accepted=self.applied,
                    collective=self.values,
                    inputs=[{axis: p['values'][axis] for axis in ('roll', 'pitch')}
                            for p in participants])

    def exchange(self, data):
        if not isinstance(data, dict) or set(data) - {'session', 'challenge', 'controls', 'release_brakes'}:
            raise ValueError('Invalid input message')
        if type(data.get('release_brakes', False)) is not bool:
            raise ValueError('Invalid brake release action')
        session = data.get('session')
        if not isinstance(session, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', session):
            raise ValueError('Invalid session')
        now = self.clock()
        self.participants()  # Prune abandoned handshakes and expired sessions.
        participant = self.sessions.get(session)
        if participant is not None and now - participant['last_input'] >= self.config['expiry_s'] and participant['last_input'] != -math.inf:
            del self.sessions[session]
            participant = None
        if participant is None:
            throttle = self.values['throttle']
            participant = dict(last_input=-math.inf, challenge=None, issued=now,
                               values=dict(roll=0, pitch=0, rudder=0, brake=0,
                                           throttle=self.throttle if throttle is None else throttle))
            self.sessions[session] = participant
        controls = data.get('controls')
        valid = (self.ready and participant['challenge'] is not None
                 and data.get('challenge') == participant['challenge']
                 and now - participant['issued'] < 0.5)
        participant['challenge'] = None  # Single use, even for invalid frames.
        if controls is not None and valid:
            bounded_controls(controls)
            pending_throttle = participant['values']['throttle']
            participant['values'] = controls.copy()
            if participant['values']['throttle'] is None:
                participant['values']['throttle'] = pending_throttle
            if data.get('release_brakes'):
                self.release_counter += 1
                self.brake_release = self.release_counter
                self.release_owner = session
                participant['values']['brake'] = 0
            participant['last_input'] = now
            self.revision += 1
        participant['challenge'] = secrets.token_hex(16)
        participant['issued'] = now
        return dict(self.status(), challenge=participant['challenge'], resync=not valid,
                    personal_throttle=participant['values']['throttle'])
