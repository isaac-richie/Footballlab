// Shared club kit colours and broadcast codes (colours only: no club badges or marks).
(function(root){
// Club kit colours (primary, secondary). Colours only: no club badges or marks.
const KITS = [
  ['arsenal', '#ef0107', '#ffffff'], ['aston villa', '#670e36', '#95bfe5'], ['bournemouth', '#da291c', '#000000'], ['brentford', '#e30613', '#ffffff'],
  ['brighton', '#0057b8', '#ffffff'], ['chelsea', '#034694', '#ffffff'], ['crystal palace', '#1b458f', '#c4122e'], ['everton', '#003399', '#ffffff'],
  ['fulham', '#ffffff', '#000000'], ['liverpool', '#c8102e', '#ffffff'], ['manchester city', '#6cabdd', '#1c2c5b'], ['manchester united', '#da291c', '#fbe122'],
  ['newcastle', '#241f20', '#ffffff'], ['nottingham', '#dd0000', '#ffffff'], ['tottenham', '#ffffff', '#132257'], ['west ham', '#7a263a', '#1bb1e7'],
  ['wolverhampton', '#fdb913', '#231f20'], ['leeds', '#ffffff', '#1d428a'], ['sunderland', '#eb172b', '#ffffff'], ['burnley', '#6c1d45', '#99d6ea'],
  ['coventry', '#87ceeb', '#ffffff'], ['ipswich', '#0033a0', '#ffffff'], ['hull', '#f5a12d', '#000000'], ['leicester', '#003090', '#fdbe11'],
  ['real madrid', '#ffffff', '#febe10'], ['barcelona', '#a50044', '#004d98'], ['atletico', '#cb3524', '#272e61'], ['sevilla', '#ffffff', '#d81920'],
  ['real betis', '#0bb363', '#ffffff'], ['valencia', '#ffffff', '#ee3524'], ['villarreal', '#ffe667', '#005187'], ['athletic', '#ee2523', '#ffffff'],
  ['real sociedad', '#0067b1', '#ffffff'], ['bayern', '#dc052d', '#ffffff'], ['dortmund', '#fde100', '#000000'], ['leverkusen', '#e32221', '#000000'],
  ['leipzig', '#ffffff', '#dd0741'], ['stuttgart', '#ffffff', '#e32219'], ['frankfurt', '#000000', '#e1000f'], ['internazionale', '#0068a8', '#000000'],
  ['ac milan', '#fb090b', '#000000'], ['juventus', '#ffffff', '#000000'], ['napoli', '#12a0d7', '#ffffff'], ['roma', '#8e1f2f', '#f0bc42'],
  ['lazio', '#87d8f7', '#ffffff'], ['atalanta', '#1e71b8', '#000000'], ['fiorentina', '#482e92', '#ffffff'], ['paris saint-germain', '#004170', '#da291c'],
  ['marseille', '#ffffff', '#2faee0'], ['monaco', '#e51b22', '#ffffff'], ['lyonnais', '#ffffff', '#da0812'], ['lille', '#e01e13', '#20325f'], ['lens', '#ffd700', '#e30613'],
];
function kit(name){
  const n = name.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  const hit = KITS.find(([k]) => n.includes(k));
  if(hit) return {primary: hit[1], secondary: hit[2]};
  let h = 0; for(const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return {primary: `hsl(${h} 62% 46%)`, secondary: '#ffffff'};
}
const inkOn = c => /^#(f|e|d)[0-9a-f]{5}$/i.test(c) || c === '#ffffff' || /^#(fd|fe|ff|f5)/i.test(c) ? '#0b0f14' : '#ffffff';
// Broadcast codes where the first three letters would be ambiguous or odd.
const CODES = {'manchester city': 'MCI', 'manchester united': 'MUN', 'nottingham': 'NFO', 'crystal palace': 'CRY', 'west ham': 'WHU', 'aston villa': 'AVL',
  'tottenham': 'TOT', 'brighton': 'BHA', 'wolverhampton': 'WOL', 'newcastle': 'NEW', 'leeds': 'LEE', 'real madrid': 'RMA', 'real betis': 'BET',
  'real sociedad': 'RSO', 'atletico': 'ATM', 'athletic': 'ATH', 'ac milan': 'MIL', 'internazionale': 'INT', 'paris saint-germain': 'PSG',
  'bayern': 'BAY', 'borussia dortmund': 'BVB', 'monchengladbach': 'BMG', 'leverkusen': 'B04', 'rb leipzig': 'RBL', 'olympique lyonnais': 'OL',
  'marseille': 'OM', 'as roma': 'ROM', 'sporting': 'SCP'};
const abbr0 = name => { const w = name.replace(/\b(FC|CF|AFC|SC|AC|SSC|AS|RC|OGC|VfB|VfL|TSG|1\.|de|Club)\b/g, '').trim().split(/\s+/).filter(Boolean); return (w.length > 1 ? w[0].slice(0, 3) : (w[0] || name).slice(0, 3)).toUpperCase() };
const abbr = name => { const n = name.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, ''); const k = Object.keys(CODES).find(c => n.includes(c)); return k ? CODES[k] : abbr0(name) };

  root.Kits = {kit, inkOn, abbr};
})(typeof globalThis !== 'undefined' ? globalThis : this);
