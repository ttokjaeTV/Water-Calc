// api/quote-kr.js
// 네이버 증권 프록시 v3 - 영문 혼합 종목코드 지원 + 종목명 조회 안정화
// Usage: /api/quote-kr?ticker=360750 / 0144L0 / 005930

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') return res.status(200).end();
  
  const { ticker } = req.query;
  if (!ticker) return res.status(400).json({ error: 'ticker parameter required' });
  
  const code = String(ticker).trim().toUpperCase().padStart(6, '0');
  if (!/^[0-9A-Z]{6}$/.test(code)) {
    return res.status(400).json({ error: '국내 종목코드는 6자리(숫자 또는 영문+숫자)여야 합니다' });
  }
  
  try {
    const today = new Date();
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - 500);
    
    const formatDate = d => d.getFullYear().toString() +
      String(d.getMonth() + 1).padStart(2, '0') +
      String(d.getDate()).padStart(2, '0');
    
    const chartUrl = `https://api.finance.naver.com/siseJson.naver?symbol=${code}&requestType=1&startTime=${formatDate(startDate)}&endTime=${formatDate(today)}&timeframe=day`;
    
    const chartRes = await fetch(chartUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://finance.naver.com/',
      },
    });
    
    if (!chartRes.ok) {
      return res.status(404).json({ error: '네이버 증권에서 데이터를 가져올 수 없습니다' });
    }
    
    let chartText = await chartRes.text();
    chartText = chartText.trim()
      .replace(/'/g, '"')
      .replace(/,\s*]/g, ']')
      .replace(/,\s*\}/g, '}');
    
    let rows;
    try {
      rows = JSON.parse(chartText);
    } catch (e) {
      return res.status(500).json({ error: '차트 데이터 파싱 실패', raw: chartText.substring(0, 200) });
    }
    
    if (!Array.isArray(rows) || rows.length < 2) {
      return res.status(404).json({ error: '데이터 없음 (종목코드 확인 필요)' });
    }
    
    const dataRows = rows.slice(1);
    const closes = dataRows.map(r => Number(r[4])).filter(v => !isNaN(v) && v > 0);
    const highs = dataRows.map(r => Number(r[2])).filter(v => !isNaN(v) && v > 0);
    const lows = dataRows.map(r => Number(r[3])).filter(v => !isNaN(v) && v > 0);
    
    if (closes.length < 15) {
      return res.status(400).json({ error: 'RSI 계산을 위한 데이터 부족 (신규 상장 종목일 수 있음)' });
    }
    
    const recent252 = {
      highs: highs.slice(-252),
      lows: lows.slice(-252),
    };
    const high52w = Math.max(...recent252.highs);
    const low52w = Math.min(...recent252.lows);
    
    const price = closes[closes.length - 1];
    const rsi = calculateRSI(closes, 14);
    
    // 종목명 조회 (여러 소스 시도)
    const name = await fetchKoreanStockName(code);
    
    res.setHeader('Cache-Control', 'public, s-maxage=300, stale-while-revalidate=600');
    
    return res.status(200).json({
      ticker: code,
      name,
      price: Math.round(price),
      currency: 'KRW',
      rsi: Number(rsi.toFixed(2)),
      high52w: Math.round(high52w),
      low52w: Math.round(low52w),
      changeFromLow: Number(((price - low52w) / low52w * 100).toFixed(2)),
      changeFromHigh: Number(((price - high52w) / high52w * 100).toFixed(2)),
      exchange: 'KRX',
      timestamp: new Date().toISOString(),
    });
    
  } catch (err) {
    return res.status(500).json({ 
      error: 'Server error',
      message: err.message 
    });
  }
}

// 종목명 조회 - 여러 소스를 순차 시도하는 견고한 방식
async function fetchKoreanStockName(code) {
  // 방법 1: 네이버 검색 자동완성 API (가장 안정적)
  try {
    const url = `https://ac.stock.naver.com/ac?q=${code}&target=stock,index,marketindicator`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/' },
    });
    if (r.ok) {
      const data = await r.json();
      const match = (data.items || []).find(it => it.code === code);
      if (match && match.name && match.name !== code) {
        return match.name;
      }
    }
  } catch (e) {}
  
  // 방법 2: 네이버 종목 메인 페이지 스크래핑
  try {
    const url = `https://finance.naver.com/item/main.naver?code=${code}`;
    const r = await fetch(url, {
      headers: { 
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
      },
    });
    if (r.ok) {
      const html = await r.text();
      let m = html.match(/<title>([^:<]+):\s*\d+/);
      if (m && m[1]) return m[1].trim();
      m = html.match(/class="wrap_company"[^>]*>\s*<h2[^>]*>\s*<a[^>]*>([^<]+)</);
      if (m && m[1]) return m[1].trim();
    }
  } catch (e) {}
  
  // 방법 3: polling API (마지막 수단)
  try {
    const url = `https://polling.finance.naver.com/api/realtime/domestic/stock/${code}`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/' },
    });
    if (r.ok) {
      const j = await r.json();
      const n = j?.datas?.[0]?.nm;
      if (n && n !== code) return n;
    }
  } catch (e) {}
  
  return code;
}

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
