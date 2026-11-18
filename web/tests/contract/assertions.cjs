const assert = require('node:assert/strict');

const kinds = {
  null: value => value === null,
  object: value => value !== null && typeof value === 'object' && !Array.isArray(value),
  number: Number.isFinite,
  string: value => typeof value === 'string',
  boolean: value => typeof value === 'boolean',
};

const errorShape = { error: { code: 'string', message: 'string', details: 'object' } };

function shape(value, schema, models, label = '响应') {
  if (typeof schema === 'string') {
    if (schema.startsWith('?')) {
      if (value !== null) shape(value, schema.slice(1), models, label);
    } else if (schema.startsWith('@')) {
      assert.ok(Object.hasOwn(models, schema.slice(1)), `${label} 使用了未知模型 ${schema}`);
      shape(value, models[schema.slice(1)], models, label);
    } else {
      assert.ok(schema.split('|').some(kind => {
        assert.ok(Object.hasOwn(kinds, kind), `${label} 使用了未知类型 ${kind}`);
        return kinds[kind](value);
      }), `${label} 应为 ${schema}`);
    }
    return;
  }
  if (Array.isArray(schema)) {
    assert.ok(Array.isArray(value), `${label} 应为数组`);
    if (schema.length === 1) {
      value.forEach((item, index) => shape(item, schema[0], models, `${label}[${index}]`));
    } else {
      assert.equal(value.length, schema.length, `${label} 的元组长度不符`);
      schema.forEach((item, index) => shape(value[index], item, models, `${label}[${index}]`));
    }
    return;
  }
  assert.ok(kinds.object(value), `${label} 应为对象`);
  for (const [key, field] of Object.entries(schema)) {
    assert.ok(Object.hasOwn(value, key), `缺少必需字段 ${label}.${key}`);
    shape(value[key], field, models, `${label}.${key}`);
  }
}

function verify(response, contract, models) {
  if (contract.error) {
    assert.equal(response.status, contract.status, '错误状态码不符');
    shape(response.body, errorShape, models);
    assert.equal(response.body.error.code, contract.error, '错误码不符');
    assert.ok(response.body.error.message.trim(), '错误消息为空');
  } else {
    assert.ok(response.status >= 200 && response.status < 300, `预期 2xx，收到 ${response.status}`);
    shape(response.body, contract.response, models);
  }
}

module.exports = { shape, verify };
