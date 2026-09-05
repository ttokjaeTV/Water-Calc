// api/macros.js v3
// VIX, CNN 공포탐욕지수, VKOSPI 자동 조회
// v3: VKOSPI를 CNBC API로 변경 (안정적, Vercel에서도 작동!)

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') return res.status(200).end();
  
  const results = {
    vix: null,
    cnnFearGreed: null,
    vkospi: null,
    errors: [],
    timestamp: new Date().toISOString(),
  };
  
  const promises = [
    fetchVIX().then(v => results.vix = v).catch(e => results.errors.push({ source: 'VIX', error: e.message })),
    fetchCNNFearGreed().then(v => results.cnnFearGreed = v).catch(e => results.errors.push({ source: 'CNN', error: e.message })),
    fetchVKOSPI().then(v => results.vkospi = v).catch(e => results.errors.push({ source: 'VKOSPI', error: e.message })),
  ];
  
  await Promise.allSettled(promises);
  
  res.setHeader('Cache-Control', 'public, s-maxage=900, stale-while-revalidate=1800');
  return res.status(200).json(results);
}

// VIX from Yahoo Finance
async function fetchVIX() {
  const url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d';
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!r.ok) throw new Error('Yahoo VIX fetch failed');
  const d = await r.json();
  const meta = d?.chart?.result?.[0]?.meta;
  return {
    value: Number((meta?.regularMarketPrice || 0).toFixed(2)),
    previousClose: Number((meta?.chartPreviousClose || 0).toFixed(2)),
  };
}

// CNN Fear & Greed
async function fetchCNNFearGreed() {
  const url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata';
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Referer': 'https://www.cnn.com/',
    },
  });
  if (!r.ok) throw new Error(`CNN F&G fetch failed: ${r.status}`);
  const d = await r.json();
  const score = d?.fear_and_greed?.score;
  if (score == null) throw new Error('No F&G score');
  return {
    value: Math.round(score),
    rating: d?.fear_and_greed?.rating || '',
    previousClose: Math.round(d?.fear_and_greed?.previous_close || 0),
  };
}

// VKOSPI - CNBC API (v3: 완전 안정화)
async function fetchVKOSPI() {
  // CNBC 공식 API - .KSVKOSPI 심볼 사용
  const url = 'https://quote.cnbc.com/quote-html-webservice/quote.htm?partnerId=2&requestMethod=quick&exthrs=1&noform=1&fund=1&output=json&symbols=.KSVKOSPI';
  
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Referer': 'https://www.cnbc.com/',
    },
  });
  
  if (!r.ok) throw new Error(`CNBC status ${r.status}`);
  
  const data = await r.json();
  const quote = data?.QuickQuoteResult?.QuickQuote;
  // quote는 배열일 수도, 객체일 수도 있음
  const q = Array.isArray(quote) ? quote[0] : quote;
  
  if (!q) throw new Error('VKOSPI 데이터 없음');
  
  const value = parseFloat(q.last);
  const prevClose = parseFloat(q.previous_day_closing);
  
  if (isNaN(value) || value <= 5 || value >= 200) {
    throw new Error(`VKOSPI 값 이상: ${q.last}`);
  }
  
  return {
    value: Number(value.toFixed(2)),
    previousClose: isNaN(prevClose) ? null : Number(prevClose.toFixed(2)),
    source: 'cnbc',
    high52w: parseFloat(q.FundamentalData?.yrhiprice) || null,
    low52w: parseFloat(q.FundamentalData?.yrloprice) || null,
  };
}
