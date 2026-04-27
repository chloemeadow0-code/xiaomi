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
  console.log('收到数据：', JSON.stringify(req.body));
  
  const { data_type, value, recorded_at } = req.body;
  
  const { error } = await supabase
    .from('health_data')
    .insert({
      user_id: 'xiaoju',
      data_type,
      value,
      recorded_at: recorded_at || new Date().toISOString()
    });

  if (error) {
    console.log('写入失败：', error);
    return res.status(500).json({ error });
  }
  
  console.log('写入成功！');
  res.json({ success: true });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('running on ' + PORT));
