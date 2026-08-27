import assert from 'assert';

import { resolveLabelCapability } from '../detection/taxonomy';
import { BAIKIEM_V9_CLASSES, BAIKIEM_V9_PROFILE, loadBaikiemV9Profile } from '../training/yardTrainingProfile';

const profile = loadBaikiemV9Profile();
assert.equal(profile.profile, BAIKIEM_V9_PROFILE);
assert.deepEqual(profile.classes.map((item) => item.baseClass), BAIKIEM_V9_CLASSES);
assert.equal(profile.acceptance.minimumEndToEndFps, 8.0);

const renamedCar = resolveLabelCapability(
  { vietnameseName: 'Ô tô nội bộ', baseClass: 'car' },
  {
    versionKey: 'baikiem-v9',
    runtimeMode: 'UNIFIED',
    labelMap: Object.fromEntries(BAIKIEM_V9_CLASSES.map((baseClass) => [baseClass, baseClass])),
  },
);
assert.equal(renamedCar.canonicalClass, 'car');
assert.equal(renamedCar.isDetectable, true);

console.log('BAI-KIEM V9 training profile: PASS');
