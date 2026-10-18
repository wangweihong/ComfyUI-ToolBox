import sys
import unittest
from pathlib import Path
import numpy as np
import importlib.util
core_path = Path(__file__).resolve().parents[1] / 'nodes/skin_color_pipeline/core.py'
spec = importlib.util.spec_from_file_location('skin_color_test_core', core_path)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class SkinPipelineTests(unittest.TestCase):
    def test_lab_known_anchors_and_roundtrip(self):
        colors=np.array([[0,0,0],[1,1,1],[1,0,0],[.86,.77,.78]],dtype=np.float32)
        lab=core.rgb_to_lab(colors)
        np.testing.assert_allclose(lab[0],[0,0,0],atol=.001)
        np.testing.assert_allclose(lab[1],[100,0,0],atol=.001)
        np.testing.assert_allclose(lab[2],[53.2408,80.0925,67.2032],atol=.002)
        np.testing.assert_allclose(core.lab_to_rgb(lab),colors,atol=2e-5)

    def sample(self,color):
        image=np.ones((1,40,40,3),dtype=np.float32)
        image[0,8:32,8:32]=color
        mask=np.zeros((40,40),dtype=np.float32);mask[8:32,8:32]=1
        packet={'frames':[{'shape':[40,40],'tiles':[{'box':[0,0,40,40],'label':'body',
                'body':mask,'face':np.zeros_like(mask)}]}]}
        return image,core.make_sample(image,packet)

    def test_automatic_correction_improves_and_preserves_outside(self):
        _,reference=self.sample([.86,.77,.78]);image,target=self.sample([.66,.52,.48])
        result,mask,report=core.correct_skin(image,reference,target,feather=2)
        self.assertTrue(report['improved']);self.assertTrue(report['correction_triggered'])
        self.assertEqual(report['max_rgb_change_outside_skin'],0)
        np.testing.assert_array_equal(result[mask==0],image[mask==0])
        self.assertEqual(report['after']['sampling'],'exactly the same indices as before')

    def test_disabled_or_below_threshold_is_exact_passthrough(self):
        image,sample=self.sample([.86,.77,.78])
        for enabled in [True,False]:
            result,mask,report=core.correct_skin(image,sample,sample,enabled=enabled)
            np.testing.assert_array_equal(result,image)
            self.assertFalse(report['correction_triggered'])
            self.assertFalse(np.any(mask))

    def test_white_purple_gold_and_dark_hair_are_not_skin(self):
        candidates=np.array([[1,1,1],[.6,.4,.8],[.86,.72,.3],[.1,.08,.08],[.86,.77,.78]],dtype=np.float32)
        np.testing.assert_array_equal(core.color_guard(candidates),[False,False,False,False,True])

    def test_prompt_comparison_ignores_unmatched_regions(self):
        def record(label,error):return {'frame':0,'label':label,'kind':'body','delta_E76':error}
        baseline=[record('a',10),record('b',10),record('c',10),record('old_only',0)]
        before=[record('a',9),record('b',9),record('c',9),record('new_only',100)]
        after=[record('a',2),record('b',2),record('c',2),record('new_only',90)]
        result=core.matched_baseline_comparison(baseline,before,after)
        self.assertEqual(result['common_regions'],3)
        self.assertTrue(result['improved'])
        self.assertEqual(result['delta_E_reduction'],1)
        self.assertEqual(result['calibrated_median_delta_E76'],2)


if __name__=='__main__':unittest.main()
