import unittest
from analyze_temperature_zones import zones


def row(t,seconds,mass,label):
    return dict(paired_temp_c_mean=t,center_s=seconds,net_mass_g_mean=mass,
                start=str(seconds),source_csv_row=label)


class TemperatureZoneTests(unittest.TestCase):
    def test_first_window_depends_on_time_not_weight(self):
        original=[row(22.31,120,100,1),row(22.32,60,-100,2),row(22.65,180,1,3)]
        selected=[b['first']['source_csv_row'] for b in zones(original,.25)]
        for r in original:r['net_mass_g_mean']=-r['net_mass_g_mean']*100
        self.assertEqual(selected,[b['first']['source_csv_row'] for b in zones(original,.25)])
        self.assertEqual(selected,[2,3])

    def test_left_closed_right_open_and_zero_anchor(self):
        result=zones([row(22.2499,0,0,1),row(22.25,60,0,2),row(22.50,120,0,3)],.25)
        self.assertEqual([b['bin_low_c'] for b in result],[22.,22.25,22.5])

    def test_large_zero_difference_remains_in_bin_range(self):
        result=zones([row(22.31,0,-2,1),row(22.32,60,0,2)],.25)[0]
        self.assertEqual(result['minutes'],2)
        self.assertEqual(result['empty_mean_g'],-1)
        self.assertEqual(result['minute_mean_range_g'],2)
        self.assertEqual(len(result['members']),2)

    def test_every_minute_accounted_for_exactly_once(self):
        original=[row(22+i*.08,i*60,float(i),i+2) for i in range(12)]
        result=zones(original,.25)
        represented=[r['source_csv_row'] for b in result for r in b['members']]
        self.assertEqual(sorted(represented),list(range(2,14)))
        self.assertEqual(len(result)+sum(len(b['members'])-1 for b in result),len(original))


if __name__=='__main__':unittest.main()
