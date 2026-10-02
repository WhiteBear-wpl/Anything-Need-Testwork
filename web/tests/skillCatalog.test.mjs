import test from 'node:test';
import assert from 'node:assert/strict';

import {
  mapSpecialists,
  mergeStoredSpecialists,
} from '../src/pages/generate/constants.js';


test('catalog drives specialist order without fixed fallback', () => {
  assert.deepEqual(
    mapSpecialists({
      specialist: [
        {
          name: 'api_test',
          title: '接口测试',
          description: '接口专项',
          execution_order: 20,
        },
        {
          name: 'performance',
          title: '性能测试',
          description: '容量专项',
          execution_order: 15,
        },
      ],
    }),
    [
      {
        key: 'performance',
        label: '性能测试',
        desc: '容量专项',
        executionOrder: 15,
      },
      {
        key: 'api_test',
        label: '接口测试',
        desc: '接口专项',
        executionOrder: 20,
      },
    ],
  );
  assert.deepEqual(mapSpecialists(null), []);
  assert.deepEqual(mapSpecialists({ specialist: [] }), []);
});


test('stored unknown specialist stays visible and disabled', () => {
  const options = [
    {
      key: 'security',
      label: '安全测试',
      desc: '权限专项',
      executionOrder: 10,
    },
  ];
  const merged = mergeStoredSpecialists(options, ['retired_skill', 'security']);

  assert.equal(merged.length, 2);
  assert.equal(merged[0].key, 'security');
  assert.equal(merged[0].unavailable, undefined);
  assert.equal(merged[1].key, 'retired_skill');
  assert.equal(merged[1].unavailable, true);
  assert.match(merged[1].label, /当前不可用/);
  assert.deepEqual(options.map(item => item.key), ['security']);
});
