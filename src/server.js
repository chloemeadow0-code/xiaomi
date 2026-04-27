const express = require('express');
const { createClient } = require('@supabase/supabase-js');

const app = express();
app.use(express.json());

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_ANON_KEY
);

app.post('/webhook', async (req, res) => {
  const { data_type, value, recorded_at } = req.body;
  
  const { error } = await supabase
    .from('health_data')
    .insert({
      user_id: 'xiaoju',
      data_type,
      value,
      recorded_at: recorded_at || new Date().toISOString()
    });

  if (error) return res.status(500).json({ error });
  res.json({ success: true });
});

app.get('/', (req, res) => {
  res.send('health webhook running!');
});

app.listen(3000, () => console.log('running on 3000'));
