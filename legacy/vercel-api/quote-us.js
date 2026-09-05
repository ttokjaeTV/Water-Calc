// api/quote-us.js
// Yahoo Finance 프록시 — 미국 주식/ETF 현재가, 52주 고/저, 종목명 조회
// v2: 429 차단 방지용 헤더 강화 + 재시도 로직

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') return res.status(200).end();
  
  const { ticker } = req.query;
  if (!ticker) return res.status(400).json({ error: 'ticker parameter required' });
  
  const symbol = String(ticker).toUpperCase().trim();
  
  try {
    const data = await fetchYahooChart(symbol);
    const result = data?.chart?.result?.[0];
    
    if (!result) {
      return res.status(404).json({ error: 'No data for this ticker' });
    }
    
    const meta = result.meta || {};
    const closes = (result.indicators?.quote?.[0]?.close || []).filter(v => v != null);
    
    if (closes.length < 15) {
      return res.status(400).json({ error: 'Insufficient data to calculate RSI' });
    }
    
    const rsi = calculateRSI(closes, 14);
    const high52w = meta.fiftyTwoWeekHigh ?? Math.max(...closes);
    const low52w = meta.fiftyTwoWeekLow ?? Math.min(...closes);
    const price = meta.regularMarketPrice ?? closes[closes.length - 1];
    
    res.setHeader('Cache-Control', 'public, s-maxage=300, stale-while-revalidate=600');
    
    return res.status(200).json({
      ticker: symbol,
      name: meta.longName || meta.shortName || symbol,
      price: Number(price.toFixed(2)),
      currency: meta.currency || 'USD',
      rsi: Number(rsi.toFixed(2)),
      high52w: Number(high52w.toFixed(2)),
      low52w: Number(low52w.toFixed(2)),
      changeFromLow: Number(((price - low52w) / low52w * 100).toFixed(2)),
      changeFromHigh: Number(((price - high52w) / high52w * 100).toFixed(2)),
      exchange: meta.exchangeName || '',
      timestamp: new Date().toISOString(),
    });
    
  } catch (err) {
    // 429 에러는 구체적 메시지로
    if (err.message?.includes('429')) {
      return res.status(429).json({ 
        error: 'Yahoo Finance 일시 차단 (너무 많은 요청). 10~15분 후 다시 시도하세요.',
        status: 429 
      });
    }
    return res.status(500).json({ 
      error: err.message || 'Server error',
      status: 500
    });
  }
}

// Yahoo Chart API 호출 (재시도 + 더 사람 같은 헤더)
async function fetchYahooChart(symbol, retry = 0) {
  // 여러 Yahoo 호스트 중 하나를 랜덤 선택 (부하 분산)
  const hosts = ['query1.finance.yahoo.com', 'query2.finance.yahoo.com'];
  const host = hosts[Math.floor(Math.random() * hosts.length)];
  
  const url = `https://${host}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=1y&includePrePost=false`;
  
  // 브라우저와 거의 동일한 헤더 세트
  const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://finance.yahoo.com/',
    'Origin': 'https://finance.yahoo.com',
    'Cache-Control': 'no-cache',
    'Sec-Ch-Ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
  };
  
  const response = await fetch(url, { headers });
  
  if (response.status === 429) {
    // 차단된 경우, 최대 2번 재시도 (지수 백오프)
    if (retry < 2) {
      const delay = 1000 * Math.pow(2, retry); // 1초, 2초
      await new Promise(r => setTimeout(r, delay));
      return fetchYahooChart(symbol, retry + 1);
    }
    throw new Error('Yahoo 429 - too many requests');
  }
  
  if (!response.ok) {
    throw new Error(`Yahoo ${response.status} - ${response.statusText}`);
  }
  
  return response.json();
}

// Wilder's smoothed RSI (14일 표준)
function calculateRSI(closes, period = 14) {
  if (closes.length < period + 1) return 50;
  
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = closes[i] - closes[i - 1];
    if (change > 0) gains += change;
    else losses -= change;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  
  for (let i = period + 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
  }
  
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - (100 / (1 + rs));
}