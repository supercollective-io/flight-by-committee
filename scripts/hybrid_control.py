"""Combine independent camera and phone contributions behind one simulator writer."""
from contextlib import contextmanager
import os
import time

from scripts import body_control, phone_control, relay_bridge
from scripts.controls import AXES, State, weighted_controls


class HybridState(State):
    def __init__(self, config, clock=time.monotonic, *, hosted=False):
        self.phone = (relay_bridge.RemoteState if hosted else State)(config, clock)
        super().__init__(config, clock)
        self.camera = body_control.BodyState(config, clock)
        self.phone.lock = self.camera.lock = self.lock
        self.sessions = self.phone.sessions
        self.hosted = hosted

    @property
    def brake_release(self):
        return self.phone.brake_release

    @brake_release.setter
    def brake_release(self, value):
        self.phone.brake_release = value

    def invalidate(self):
        self.phone.invalidate()
        self.camera.invalidate()

    def sync(self):
        for source in (self.phone, self.camera):
            source.ready, source.connected = self.ready, self.connected
            source.generation, source.throttle = self.generation, self.throttle

    def snapshot(self):
        """Capture contributors, expiry and withdrawal token from the same sample."""
        self.sync()
        phones = self.phone.participants()
        camera = self.camera.participants()
        m = len(phones)
        if not phones:
            self.phone.brake_release = 0
        if self.hosted:
            phone_values = self.phone.frame['controls'] if phones else {}
            phone_inputs = phones
            phone_token = (self.phone.epoch, self.phone.sequence)
            deadlines = [self.phone.frame_deadline] if phones else []
        else:
            phone_values = {axis: sum(p['values'][axis] for p in phones) / m
                            for axis in AXES} if phones else {}
            phone_inputs = [{axis: p['values'][axis] for axis in ('roll', 'pitch')}
                            for p in phones]
            phone_token = tuple(sorted(id(p) for p in phones))
            deadlines = [p['last_input'] + self.config['expiry_s'] for p in phones]
        counts = {axis: sum(v[axis] is not None for v in camera)
                  if axis in ('roll', 'pitch') else 0 for axis in AXES}
        values = weighted_controls((phone_values, dict.fromkeys(AXES, m)),
                                   (self.camera.command, counts))
        inputs = [dict(v, source='phone') for v in phone_inputs]
        inputs += [dict(v, source='camera') for v in camera]
        if camera:
            deadlines.append(self.camera.frame_deadline)
        status = dict(simulator=self.connected, ready=self.ready, mode='hybrid',
                      active=bool(inputs), count=len(inputs), throttle=self.throttle,
                      collective=values, accepted=self.applied, inputs=inputs,
                      sources=dict(phone=m, camera=len(camera)),
                      axis_counts={axis: m + counts[axis] for axis in AXES},
                      camera_available=self.camera.available and self.clock() < self.camera.frame_deadline,
                      phone_available=(self.phone.relay_connected and self.clock() < self.phone.frame_deadline)
                                      if self.hosted else self.connected)
        token = self.camera.invalidated, tuple(status['axis_counts'].values()), phone_token
        return status, min(deadlines, default=self.clock()), token

    def participants(self):
        return self.status()['inputs']

    def fresh(self):
        return self.status()['active']

    @property
    def values(self):
        return self.status()['collective']

    @property
    def frame_deadline(self):
        return self.snapshot()[1]

    def command_token(self):
        return self.snapshot()[2]

    def bridge_snapshot(self):
        status, deadline, token = self.snapshot()
        return status['active'], status['collective'], self.brake_release, deadline, token

    def status(self):
        return self.snapshot()[0]

    def exchange(self, data):
        self.sync()
        response = self.phone.exchange(data)
        return response | self.status()

    def feedback(self):
        status, deadline, _token = self.snapshot()
        return dict(epoch=self.phone.epoch, sequence=self.phone.sequence,
                    valid_for=max(0, min(.5, deadline - self.clock())) if status['active'] else .5,
                    **{key: status[key] for key in ('mode', 'count', 'collective', 'inputs',
                        'sources', 'axis_counts', 'camera_available', 'phone_available')})


@contextmanager
def running(config, simulator_port):
    hosted = bool(os.environ.get('FLIGHT_RELAY_URL'))
    state = HybridState(config, hosted=hosted)
    with body_control.camera_running(config, state.camera):
        controller = relay_bridge if hosted else phone_control
        with controller.running(config, simulator_port, state=state):
            print('Hybrid controls: choose body or phone, one method at a time. '
                  'Lower arms or stop phone controls to withdraw.', flush=True)
            yield state
