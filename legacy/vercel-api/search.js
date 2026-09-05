// api/search.js
// 통합 티커 검색 - 미국+한국 한 번에, 종목명/코드 모두 지원
// Usage: /api/search?q=삼성 또는 /api/search?q=VOO 또는 /api/search?q=360750

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') return res.status(200).end();
  
  const { q } = req.query;
  if (!q || q.length < 1) return res.status(200).json({ results: [] });
  
  const query = String(q).trim();
  
  // 쿼리 분석: 한글/숫자/영문 여부 판단
  const isKorean = /[가-힣]/.test(query);
  const isPureNumber = /^\d+$/.test(query);
  const isMixedCode = /^[0-9A-Za-z]{5,6}$/.test(query) && /\d/.test(query) && /[A-Za-z]/.test(query);
  
  try {
    // 한글/숫자면 국내 우선, 그 외는 병렬 검색
    const results = [];
    
    if (isKorean || isPureNumber || isMixedCode) {
      // 국내 검색 먼저
      const krResults = await searchKR(query).catch(() => []);
      results.push(...krResults.map(r => ({ ...r, _priority: 1 })));
      
      // 미국 검색 (쿼리가 영문/숫자 혼합이거나 짧은 숫자인 경우)
      if (!isKorean) {
        const usResults = await searchUS(query).catch(() => []);
        results.push(...usResults.map(r => ({ ...r, _priority: 2 })));
      }
    } else {
      // 영문 쿼리: 둘 다 병렬 검색
      const [usResults, krResults] = await Promise.all([
        searchUS(query).catch(() => []),
        searchKR(query).catch(() => []),
      ]);
      results.push(...usResults.map(r => ({ ...r, _priority: 1 })));
      results.push(...krResults.map(r => ({ ...r, _priority: 2 })));
    }
    
    // 중복 제거 + 우선순위 정렬
    const seen = new Set();
    const unique = results.filter(r => {
      const key = `${r.market}_${r.ticker}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    unique.sort((a, b) => a._priority - b._priority);
    
    // _priority 필드 제거
    const cleanResults = unique.slice(0, 12).map(({ _priority, ...r }) => r);
    
    return res.status(200).json({ results: cleanResults });
  } catch (err) {
    return res.status(500).json({ error: err.message, results: [] });
  }
}

// Yahoo Finance 검색 (미국)
async function searchUS(query) {
  const url = `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(query)}&quotesCount=8&newsCount=0`;
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Referer': 'https://finance.yahoo.com/',
    },
  });
  if (!r.ok) return [];
  const data = await r.json();
  return (data.quotes || [])
    .filter(q => q.quoteType === 'EQUITY' || q.quoteType === 'ETF')
    .filter(q => {
      // 한국 거래소는 국내 검색으로 따로 처리하므로 제외
      const ex = String(q.exchange || '').toUpperCase();
      return !['KSC', 'KOE', 'KOSDAQ', 'KRX'].includes(ex);
    })
    .slice(0, 8)
    .map(q => ({
      ticker: q.symbol,
      name: q.longname || q.shortname || q.symbol,
      exchange: q.exchDisp || q.exchange || '',
      type: q.quoteType,
      market: 'us',
    }));
}

// 네이버 증권 검색 (국내)
async function searchKR(query) {
  const url = `https://ac.stock.naver.com/ac?q=${encodeURIComponent(query)}&target=stock,index,marketindicator`;
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0',
      'Referer': 'https://finance.naver.com/',
    },
  });
  if (!r.ok) return [];
  const data = await r.json();
  return (data.items || [])
    // 종목코드: 6자리 숫자 or 영문+숫자 혼합
    .filter(item => item.code && /^[0-9A-Z]{6}$/i.test(item.code))
    .slice(0, 10)
    .map(item => ({
      ticker: item.code,
      name: item.name || item.code,
      exchange: item.typeName || 'KRX',
      type: item.typeName || '',
      market: 'kr',
    }));
}
