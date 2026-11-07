"""Metric runway geometry and provisional simulator landing acceptance checks."""
import math

# Nightly apt.dat.ws3 EDSB physical ends and displaced thresholds.
RUNWAY_START = (48.76784332, 8.06972798)
RUNWAY_END = (48.79084241, 8.09125803)
THRESHOLD_OFFSET_M = 264
RUNWAY_WIDTH_M = 45
EARTH_RADIUS_M = 6371000


def distance_m(latitude_a, longitude_a, latitude_b, longitude_b):
    a, b = math.radians(latitude_a), math.radians(latitude_b)
    dlon = math.radians(longitude_b - longitude_a)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, h)))


def runway_position(latitude_deg, longitude_deg):
    lat, lon = map(math.radians, RUNWAY_START)
    end_lat, end_lon = map(math.radians, RUNWAY_END)
    heading = math.atan2(math.sin(end_lon - lon) * math.cos(end_lat),
                         math.cos(lat) * math.sin(end_lat) - math.sin(lat) * math.cos(end_lat) * math.cos(end_lon - lon))
    north = math.radians(latitude_deg - RUNWAY_START[0]) * EARTH_RADIUS_M
    east = math.radians(longitude_deg - RUNWAY_START[1]) * EARTH_RADIUS_M * math.cos(lat)
    return (north * math.cos(heading) + east * math.sin(heading) - THRESHOLD_OFFSET_M,
            east * math.cos(heading) - north * math.sin(heading))


def assess(touchdown, final):
    """These prototype thresholds are not aircraft operating limits."""
    if touchdown is None:
        return {'passed': False, 'reason': 'No main-gear touchdown observed'}
    along, across = runway_position(touchdown['latitude_deg'], touchdown['longitude_deg'])
    stop_along, stop_across = runway_position(final['latitude_deg'], final['longitude_deg'])
    checks = {
        'touchdown_on_runway': 0 <= along <= 2740 and abs(across) <= RUNWAY_WIDTH_M / 2,
        'touchdown_sink_rate': abs(touchdown['vertical_speed_m_s']) <= 3,
        'touchdown_bank': abs(touchdown['roll_deg']) <= 5,
        'stopped_on_runway': 0 <= stop_along <= 2740 and abs(stop_across) <= RUNWAY_WIDTH_M / 2,
        'stopped_on_main_gear': final['main_gear_wow'] == 1 and final['groundspeed_m_s'] < 1,
        'no_modelled_wing_failure': touchdown['wings_broken'] == 0 and final['wings_broken'] == 0,
    }
    return {'passed': all(checks.values()), 'checks': checks,
            'touchdown_along_m': along, 'touchdown_cross_m': across,
            'stop_along_m': stop_along, 'stop_cross_m': stop_across}
