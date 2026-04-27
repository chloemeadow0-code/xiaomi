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
  console.log('收到数据：', JSON.stringify(req.body).substring(0, 200));
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

  if (rows.length === 0) {
    return res.json({ success: true, message: 'no data' });
  }

  const { error } = await supabase
    .from('health_data')
    .insert(rows);

  if (error) {
    console.log('写入失败：', error);
    return res.status(500).json({ error });
  }

  console.log('写入成功！共', rows.length, '条');
  res.json({ success: true, count: rows.length });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('running on ' + PORT));
