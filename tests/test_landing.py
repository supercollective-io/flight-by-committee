import unittest
from scripts import landing


class LandingTests(unittest.TestCase):
    def state(self, **changes):
        state = dict(latitude_deg=48.775, longitude_deg=8.07643,
                     vertical_speed_m_s=-1.5, roll_deg=1, main_gear_wow=1,
                     groundspeed_m_s=0.5, wings_broken=0)
        return dict(state, **changes)

    def test_landing_and_stop_on_runway(self):
        self.assertTrue(landing.assess(self.state(), self.state())['passed'])

    def test_no_touchdown_cannot_pass(self):
        self.assertFalse(landing.assess(None, self.state())['passed'])

    def test_hard_landing_overrun_and_moving_finish_fail(self):
        for touchdown, final in [
            (self.state(vertical_speed_m_s=-5), self.state()),
            (self.state(), self.state(latitude_deg=48.81)),
            (self.state(), self.state(groundspeed_m_s=20)),
            (self.state(longitude_deg=8.09), self.state()),
        ]:
            with self.subTest(touchdown=touchdown, final=final):
                self.assertFalse(landing.assess(touchdown, final)['passed'])

    def test_profile_starts_twelve_kilometres_before_threshold(self):
        from scripts.flightgear import resolve
        location = resolve('karlsruhe-747-landing')['location']
        along, across = landing.runway_position(location['latitude_deg'], location['longitude_deg'])
        self.assertAlmostEqual(along, -12000, delta=20)
        self.assertAlmostEqual(across, 0, delta=20)
