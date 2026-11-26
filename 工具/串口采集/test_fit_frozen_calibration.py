import unittest
from fit_frozen_calibration import compare_windows,fit_coefficient,add_mass_results


def window(tag,mass,t,raw,role='标定',session='test'):
    return dict(tag=tag,mass_g=mass,time_center_s=t,raw_mean=raw,raw_sd=2.,
                role=role,session_id=session,average_temperature_c=20.)


class FrozenCalibrationTests(unittest.TestCase):
    def test_baseline_drift_removed_in_count_domain(self):
        windows=[window('a',0,0,100),window('b',200,10,20110),window('c',0,20,120),
                 window('d',500,30,50130),window('e',0,40,140)]
        rows=compare_windows(windows);k,_=fit_coefficient(rows)
        self.assertAlmostEqual(k,100.)
        self.assertEqual([r['mass_fitted_k_g'] for r in add_mass_results(rows,k)],[200.,500.])

    def test_validation_never_changes_coefficient(self):
        windows=[window('a',0,0,0),window('b',200,10,20000),window('c',0,20,0),
                 window('d',500,30,50000),window('e',0,40,0),
                 window('f',100,50,12345,role='独立核验'),window('g',0,60,0)]
        rows=compare_windows(windows);k,_=fit_coefficient(rows)
        self.assertEqual(k,100.)
        self.assertAlmostEqual(add_mass_results(rows,k)[-1]['error_fitted_k_g'],23.45)

    def test_no_interpolation_between_sessions(self):
        with self.assertRaises(ValueError):
            compare_windows([window('a',0,0,0),window('b',200,10,20000),window('c',0,20,0,session='other')])

    def test_incomplete_load_not_used_and_two_masses_required(self):
        rows=compare_windows([window('a',0,0,0),window('b',200,10,20000)])
        self.assertEqual(rows,[])
        with self.assertRaises(ValueError):fit_coefficient(rows)


if __name__=='__main__':unittest.main()
