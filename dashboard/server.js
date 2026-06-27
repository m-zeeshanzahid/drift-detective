require('dotenv').config();
const express = require('express');
const axios   = require('axios');
const cors    = require('cors');
const path    = require('path');

const app  = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'dist')));

const SUPERPLANE_API_URL  = process.env.SUPERPLANE_API_URL || 'https://api.superplane.com';
const SUPERPLANE_API_KEY  = process.env.SUPERPLANE_API_KEY;
const SUPERPLANE_APP_NAME = process.env.SUPERPLANE_APP_NAME || 'drift-detective';
const SUPERPLANE_ORG      = process.env.SUPERPLANE_ORG;

const headers = {
  'Authorization': `Bearer ${SUPERPLANE_API_KEY}`,
  'Content-Type': 'application/json'
};

app.get('/api/runs', async (req, res) => {
  try {
    const url  = `${SUPERPLANE_API_URL}/v1/organizations/${SUPERPLANE_ORG}/apps/${SUPERPLANE_APP_NAME}/runs`;
    const resp = await axios.get(url, { headers });
    res.json(resp.data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/runs/:id', async (req, res) => {
  try {
    const url  = `${SUPERPLANE_API_URL}/v1/organizations/${SUPERPLANE_ORG}/apps/${SUPERPLANE_APP_NAME}/runs/${req.params.id}`;
    const resp = await axios.get(url, { headers });
    res.json(resp.data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/trigger', async (req, res) => {
  try {
    const url  = `${SUPERPLANE_API_URL}/v1/organizations/${SUPERPLANE_ORG}/apps/${SUPERPLANE_APP_NAME}/triggers`;
    const resp = await axios.post(url, {
      type: 'manual',
      inputs: { triggered_by: 'dashboard' }
    }, { headers });
    res.json(resp.data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/health', (req, res) => res.json({ status: 'ok', ts: new Date().toISOString() }));

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Drift Detective dashboard on port ${PORT}`));
