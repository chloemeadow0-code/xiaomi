const express = require('express');
const { createClient } = require('@supabase/supabase-js');

const app = express();
app.use(express.text({ type: 'application/json', limit: '1mb' }));

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_ANON_KEY
);

function toArray(val) {
  if (val === undefined || val === null || val === '') return [];
  return Array.isArray(val) ? val : [val];
}

function sanitizeJson(raw) {
  return raw
    .replace(/:[ \t]*,/g, ': null,')
    .replace(/:[ \t]*}/g, ': null}')
    .replace(/:[ \t]*]/g, ': null]');
}

app.get('/', (req, res) => {
  res.send('health webhook running!');
});

app.post('/webhook', async (req, res) => {
  let body;
  try {
    const cleaned = sanitizeJson(req.body);
    body = JSON.parse(cleaned);
    console.log('收到完整数据：', JSON.stringify(body));
  } catch (e) {
    console.log('JSON 解析失败：', e.message);
    console.log('原始 body：', req.body);
    return res.status(400).json({ error: 'invalid json', detail: e.message });
  }

  const rows = [];

  // 步数
  for (const s of toArray(body.steps)) {
    if (s === null) continue;
    rows.push({
      user_id: 'xiaoju',
      data_type: 'steps',
      value: s.count ?? s.value,
      recorded_at: s.start_time ?? s.timestamp ?? s.time ?? body.timestamp ?? new Date().toISOString()
    });
  }

  // 睡眠
  for (const s of toArray(body.sleep)) {
    if (s === null) continue;
    rows.push({
      user_id: 'xiaoju',
      data_type: 'sleep',
      value: s.duration_seconds ?? s.value,
      recorded_at: s.session_end_time ?? s.timestamp ?? s.time ?? body.timestamp ?? new Date().toISOString()
    });
  }

  // 心率
  for (const h of toArray(body.heart_rate)) {
    if (h === null || h === '') continue;

    const raw = typeof h === 'number' || typeof h === 'string'
      ? h
      : (h.bpm ?? h.value ?? h.rate ?? h.heart_rate);

    const value = parseFloat(raw);
    if (isNaN(value)) continue;

    const recorded_at = typeof h === 'number' || typeof h === 'string'
      ? (body.timestamp ?? new Date().toISOString())
      : (h.start_time ?? h.timestamp ?? h.time ?? body.timestamp ?? new Date().toISOString());

    rows.push({ user_id: 'xiaoju', data_type: 'heart_rate', value, recorded_at });
  }

  // 血氧
  const spo2Raw = body.blood_oxygen ?? body.spo2 ?? body.oxygen_saturation;
  for (const s of toArray(spo2Raw)) {
    if (s === null || s === '') continue;

    const raw = typeof s === 'number' || typeof s === 'string'
      ? s
      : (s.percentage ?? s.value ?? s.spo2);

    const value = parseFloat(raw);
    if (isNaN(value)) continue;

    const recorded_at = typeof s === 'number' || typeof s === 'string'
      ? (body.timestamp ?? new Date().toISOString())
      : (s.start_time ?? s.timestamp ?? s.time ?? body.timestamp ?? new Date().toISOString());

    rows.push({ user_id: 'xiaoju', data_type: 'blood_oxygen', value, recorded_at });
  }

  // 体重
  for (const w of toArray(body.weight)) {
    if (w === null) continue;
    const value = parseFloat(w.weight ?? w.value ?? w.kg);
    if (isNaN(value)) continue;
    rows.push({
      user_id: 'xiaoju',
      data_type: 'weight',
      value,
      recorded_at: w.start_time ?? w.timestamp ?? w.time ?? body.timestamp ?? new Date().toISOString()
    });
  }

  // 血压
  for (const b of toArray(body.blood_pressure)) {
    if (b === null) continue;
    rows.push({
      user_id: 'xiaoju',
      data_type: 'blood_pressure',
      value: JSON.stringify({ systolic: b.systolic, diastolic: b.diastolic }),
      recorded_at: b.start_time ?? b.timestamp ?? b.time ?? body.timestamp ?? new Date().toISOString()
    });
  }

  // 未知字段兜底
  const knownKeys = ['timestamp', 'app_version', 'steps', 'sleep', 'heart_rate',
    'blood_oxygen', 'spo2', 'oxygen_saturation', 'weight', 'blood_pressure'];
  for (const key of Object.keys(body)) {
    if (!knownKeys.includes(key) && Array.isArray(body[key]) && body[key].length > 0) {
      console.log('发现未知数据类型：', key, JSON.stringify(body[key][0]));
      for (const item of body[key]) {
        if (item === null) continue;
        rows.push({
          user_id: 'xiaoju',
          data_type: key,
          value: item.value ?? item.count ?? item.bpm ?? item.rate ?? item.percentage ?? JSON.stringify(item),
          recorded_at: item.start_time ?? item.timestamp ?? item.time ?? new Date().toISOString()
        });
      }
    }
  }

  if (rows.length === 0) {
    console.log('无有效数据');
    return res.json({ success: true, message: 'no data' });
  }

  // 去重
  const types = [...new Set(rows.map(r => r.data_type))];
  const { data: existing } = await supabase
    .from('health_data')
    .select('data_type, value, recorded_at')
    .in('data_type', types);

  const existingSet = new Set();
  if (existing) {
    for (const e of existing) {
      existingSet.add(`${e.data_type}_${e.value}_${e.recorded_at}`);
    }
  }

  const newRows = rows.filter(r => !existingSet.has(`${r.data_type}_${r.value}_${r.recorded_at}`));

  if (newRows.length === 0) {
    console.log('全部重复，跳过写入');
    return res.json({ success: true, message: 'all duplicates skipped', count: 0 });
  }

  const { error } = await supabase.from('health_data').insert(newRows);

  if (error) {
    console.log('写入失败：', error);
    return res.status(500).json({ error });
  }

  console.log('写入成功！新增', newRows.length, '条，跳过重复', rows.length - newRows.length, '条');
  res.json({ success: true, count: newRows.length });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('running on ' + PORT));
