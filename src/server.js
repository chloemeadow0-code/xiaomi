const express = require('express');
const { createClient } = require('@supabase/supabase-js');

const app = express();
app.use(express.json());

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_ANON_KEY
);

app.get('/', (req, res) => {
  res.send('health webhook running!');
});

app.post('/webhook', async (req, res) => {
  console.log('收到完整数据：', JSON.stringify(req.body));
  const rows = [];

  if (req.body.steps) {
    for (const s of req.body.steps) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'steps',
        value: s.count,
        recorded_at: s.start_time
      });
    }
  }

  if (req.body.sleep) {
    for (const s of req.body.sleep) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'sleep',
        value: s.duration_seconds,
        recorded_at: s.session_end_time
      });
    }
  }

  if (req.body.heart_rate) {
    for (const h of req.body.heart_rate) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'heart_rate',
        value: h.bpm || h.value || h.rate || h.heart_rate,
        recorded_at: h.start_time || h.timestamp || h.time
      });
    }
  }

  if (req.body.blood_oxygen || req.body.spo2 || req.body.oxygen_saturation) {
    const spo2 = req.body.blood_oxygen || req.body.spo2 || req.body.oxygen_saturation;
    for (const s of spo2) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'blood_oxygen',
        value: s.percentage || s.value || s.spo2,
        recorded_at: s.start_time || s.timestamp || s.time
      });
    }
  }

  if (req.body.weight) {
    for (const w of req.body.weight) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'weight',
        value: w.weight || w.value || w.kg,
        recorded_at: w.start_time || w.timestamp || w.time
      });
    }
  }

  if (req.body.blood_pressure) {
    for (const b of req.body.blood_pressure) {
      rows.push({
        user_id: 'xiaoju',
        data_type: 'blood_pressure',
        value: JSON.stringify({ systolic: b.systolic, diastolic: b.diastolic }),
        recorded_at: b.start_time || b.timestamp || b.time
      });
    }
  }

  const knownKeys = ['timestamp', 'app_version', 'steps', 'sleep', 'heart_rate', 'blood_oxygen', 'spo2', 'oxygen_saturation', 'weight', 'blood_pressure'];
  for (const key of Object.keys(req.body)) {
    if (!knownKeys.includes(key) && Array.isArray(req.body[key]) && req.body[key].length > 0) {
      console.log('发现未知数据类型：', key, JSON.stringify(req.body[key][0]));
      for (const item of req.body[key]) {
        rows.push({
          user_id: 'xiaoju',
          data_type: key,
          value: item.value || item.count || item.bpm || item.rate || item.percentage || JSON.stringify(item),
          recorded_at: item.start_time || item.timestamp || item.time || new Date().toISOString()
        });
      }
    }
  }

  if (rows.length === 0) {
    return res.json({ success: true, message: 'no data' });
  }

  // 去重：查出已有数据，跳过重复的
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

  const newRows = rows.filter(r => {
    const key = `${r.data_type}_${r.value}_${r.recorded_at}`;
    return !existingSet.has(key);
  });

  if (newRows.length === 0) {
    console.log('全部重复，跳过写入');
    return res.json({ success: true, message: 'all duplicates skipped', count: 0 });
  }

  const { error } = await supabase
    .from('health_data')
    .insert(newRows);

  if (error) {
    console.log('写入失败：', error);
    return res.status(500).json({ error });
  }

  console.log('写入成功！新增', newRows.length, '条，跳过重复', rows.length - newRows.length, '条');
  res.json({ success: true, count: newRows.length });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('running on ' + PORT));
