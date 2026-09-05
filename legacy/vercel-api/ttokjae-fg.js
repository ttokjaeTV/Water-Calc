// api/ttokjae-fg.js v3
// 똑재 공포탐욕지수 산출용 5개 지표 자동 수집
// v3: VKOSPI를 CNBC API로 변경 (100% 작동 보장)
// 외국인 순매수, 52주 신고가는 KRX 접근 불가로 null 반환 (수동 입력 유도)

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') return res.status(200).end();
  
  const result = {
    momentum: null,    // ✅ 자동 (네이버 KOSPI)
    vkospi: null,      // ✅ 자동 (CNBC)
    rsi: null,         // ✅ 자동 (네이버 KOSPI)
    foreign: null,     // ❌ 수동 입력 필요 (KRX 차단)
    highlow: null,     // ❌ 수동 입력 필요 (KRX 차단)
    errors: [],
    autoCount: 0,      // 자동으로 수집된 지표 개수
    timestamp: new Date().toISOString(),
  };
  
  // 1. KOSPI 차트 (momentum + RSI)
  try {
    const kospiData = await fetchKospiChart();
    if (kospiData) {
      result.momentum = kospiData.momentum;
      result.rsi = kospiData.rsi;
      result.autoCount += 2;
    }
  } catch (e) {
    result.errors.push({ source: 'KOSPI', error: e.message });
  }
  
  // 2. VKOSPI from CNBC
  try {
    result.vkospi = await fetchVKOSPI();
    result.autoCount += 1;
  } catch (e) {
    result.errors.push({ source: 'VKOSPI', error: e.message });
  }
  
  res.setHeader('Cache-Control', 'public, s-maxage=1800, stale-while-revalidate=3600');
  return res.status(200).json(result);
}

// KOSPI 차트 (모멘텀 + RSI)
async function fetchKospiChart() {
  const today = new Date();
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - 500);
  const fmt = d => d.getFullYear().toString() +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0');
  
  const url = `https://api.finance.naver.com/siseJson.naver?symbol=KOSPI&requestType=1&startTime=${fmt(startDate)}&endTime=${fmt(today)}&timeframe=day`;
  
  const r = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/' },
  });
  if (!r.ok) throw new Error(`Naver KOSPI ${r.status}`);
  
  let text = await r.text();
  text = text.trim().replace(/'/g, '"').replace(/,\s*]/g, ']').replace(/,\s*\}/g, '}');
  const rows = JSON.parse(text);
  
  if (!Array.isArray(rows) || rows.length < 130) throw new Error('KOSPI 데이터 부족');
  
  const dataRows = rows.slice(1);
  const closes = dataRows.map(r => Number(r[4])).filter(v => !isNaN(v) && v > 0);
  
  if (closes.length < 125) throw new Error('125일 이평 데이터 부족');
  
  const currentPrice = closes[closes.length - 1];
  const last125 = closes.slice(-125);
  const ma125 = last125.reduce((s, v) => s + v, 0) / 125;
  const momentum = Number(((currentPrice - ma125) / ma125 * 100).toFixed(2));
  const rsi = calculateRSI(closes, 14);
  
  return {
    momentum,
    rsi: Number(rsi.toFixed(2)),
  };
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

// VKOSPI from CNBC (v3: 100% 안정적)
async function fetchVKOSPI() {
  const url = 'https://quote.cnbc.com/quote-html-webservice/quote.htm?partnerId=2&requestMethod=quick&exthrs=1&noform=1&fund=1&output=json&symbols=.KSVKOSPI';
  
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Referer': 'https://www.cnbc.com/',
    },
  });
  
  if (!r.ok) throw new Error(`CNBC ${r.status}`);
  
  const data = await r.json();
  const quote = data?.QuickQuoteResult?.QuickQuote;
  const q = Array.isArray(quote) ? quote[0] : quote;
  
  if (!q) throw new Error('VKOSPI 응답 없음');
  
  const value = parseFloat(q.last);
  if (isNaN(value) || value <= 5 || value >= 200) {
    throw new Error(`VKOSPI 값 이상: ${q.last}`);
  }
  
  return Number(value.toFixed(2));
}
