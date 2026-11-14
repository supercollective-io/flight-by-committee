"""Strict display-only feedback from the authenticated hybrid bridge."""
import math
from scripts.controls import AXES, bounded_controls


def validate_feedback(frame):
    fields = {'epoch', 'sequence', 'valid_for', 'mode', 'count', 'collective', 'inputs',
              'sources', 'axis_counts', 'camera_available', 'phone_available'}
    if not isinstance(frame, dict) or set(frame) != fields or frame['mode'] != 'hybrid':
        raise ValueError('Invalid hybrid feedback')
    if frame['epoch'] is not None and (not isinstance(frame['epoch'], str) or len(frame['epoch']) != 32):
        raise ValueError('Invalid feedback epoch')
    if type(frame['sequence']) is not int or not 0 <= frame['sequence'] < 2**53:
        raise ValueError('Invalid feedback sequence')
    age = frame['valid_for']
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= .5:
        raise ValueError('Invalid feedback lifetime')
    bounded_controls(frame['collective'])
    sources, counts, inputs = frame['sources'], frame['axis_counts'], frame['inputs']
    if not isinstance(sources, dict) or set(sources) != {'phone', 'camera'}:
        raise ValueError('Invalid source counts')
    for source, limit in (('phone', 400), ('camera', 100)):
        if type(sources[source]) is not int or not 0 <= sources[source] <= limit:
            raise ValueError('Invalid source count')
    if type(frame['count']) is not int or frame['count'] != sum(sources.values()):
        raise ValueError('Invalid contribution count')
    if not isinstance(inputs, list) or len(inputs) != frame['count']:
        raise ValueError('Invalid contribution display')
    if not isinstance(counts, dict) or set(counts) != set(AXES):
        raise ValueError('Invalid axis counts')
    actual_sources = dict(phone=0, camera=0)
    actual_counts = dict.fromkeys(AXES, 0)
    for vote in inputs:
        if not isinstance(vote, dict) or set(vote) != {'source', 'roll', 'pitch'} or vote['source'] not in actual_sources:
            raise ValueError('Invalid contribution display')
        actual_sources[vote['source']] += 1
        if vote['roll'] is None and vote['pitch'] is None:
            raise ValueError('Empty contribution')
        for axis in ('roll', 'pitch'):
            value = vote[axis]
            if value is None and vote['source'] == 'camera':
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError('Invalid contribution axis')
            actual_counts[axis] += 1
    for axis in ('rudder', 'brake', 'throttle'):
        actual_counts[axis] = sources['phone']
    if actual_sources != sources or any(type(counts[k]) is not int or counts[k] != v for k, v in actual_counts.items()):
        raise ValueError('Inconsistent feedback counts')
    if any(type(frame[k]) is not bool for k in ('camera_available', 'phone_available')):
        raise ValueError('Invalid source availability')
