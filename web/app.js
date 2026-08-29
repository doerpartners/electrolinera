'use strict';
const API = '';
const METRO_CENTER = {
  Monterrey: [25.67, -100.31], Guadalajara: [20.67, -103.39], CDMX: [19.43, -99.13],
  "Mérida": [20.97, -89.62], Morelia: [19.70, -101.19], "San Miguel de Allende": [20.914, -100.745],
};
const COLOR = {EXCELENTE:'#37e0a6', BUENA:'#8fd14f', MODERADA:'#f4c04d', BAJA:'#f4795b'};
const CTRL_TABS = new Set(['explorar','candidatos']); // pestañas que usan el mapa/controles

let map, chargerLayer, candLayer, evalLayer, nseLayer, obsLayer;
let lastQuery = null;
let showChargers = true, showNse = false, nseData = null;
const loaded = {insights:false, ajustes:false, ayuda:false, agregar:false};
let pinMode = false, zoneSeq = 0;

function nseColor(idx){
  if(idx >= 0.8) return '#37e0a6';
  if(idx >= 0.6) return '#8fd14f';
  if(idx >= 0.45) return '#f4c04d';
  if(idx >= 0.3) return '#f0955b';
  return '#f4795b';
}
const $ = s => document.querySelector(s);
const money = n => '$'+Math.round(n/1000)+'k';

function init(){
  map = L.map('map', {zoomControl:true}).setView(METRO_CENTER.Monterrey, 12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {maxZoom:19, attribution:'© OpenStreetMap'}).addTo(map);
  nseLayer = L.layerGroup().addTo(map);
  chargerLayer = L.layerGroup().addTo(map);
  obsLayer = L.layerGroup().addTo(map);
  candLayer = L.layerGroup().addTo(map);
  evalLayer = L.layerGroup().addTo(map);
  map.on('click', e => {
    if(pinMode){ setPin(e.latlng.lat, e.latlng.lng); return; }
    switchTab('explorar'); evaluate(e.latlng.lat, e.latlng.lng);
  });

  $('#metro').addEventListener('change', onMetro);
  $('#radius').addEventListener('input', e=>{ $('#radiusVal').textContent = e.target.value; });
  $('#btnCand').addEventListener('click', loadCandidates);
  $('#btnChargers').addEventListener('click', toggleChargers);
  $('#btnNse').addEventListener('click', toggleNse);
  $('#coordGo').addEventListener('click', goToCoords);
  $('#coordInput').addEventListener('keydown', e=>{ if(e.key==='Enter') goToCoords(); });
  document.querySelectorAll('#tabs button').forEach(b=>
    b.addEventListener('click', ()=>switchTab(b.dataset.tab)));

  loadMeta(); loadNse(); loadObsLayer(); loadChargers('Monterrey');
}

async function loadObsLayer(){
  obsLayer.clearLayers();
  try{
    const d = await (await fetch(API+'/api/observations')).json();
    d.observations.forEach(o=>{
      const oper=o.zones.reduce((s,z)=>s+z.chargers.filter(c=>c.status==='operational').reduce((a,c)=>a+c.count,0),0);
      const plan=o.zones.reduce((s,z)=>s+z.chargers.filter(c=>c.status==='planned').reduce((a,c)=>a+c.count,0),0);
      const oos=o.zones.reduce((s,z)=>s+z.chargers.filter(c=>c.status==='out_of_service').reduce((a,c)=>a+c.count,0),0);
      // morado lleno si hay carga operativa; anillo si no
      const col = oper>0 ? '#b06ff2' : '#f4795b';
      let pop=`<b>${o.name}</b> <span style="opacity:.7">(campo)</span><br>`+
        `${oper} operativos`+(oos?` · ${oos} fuera de servicio`:'')+(plan?` · ${plan} planeados`:'');
      if(o.parking_spaces) pop+=`<br>~${o.parking_spaces.toLocaleString()} cajones`;
      if(o.ev_observed!=null) pop+=`<br>${o.ev_observed} EV observados`;
      L.circleMarker([o.lat,o.lon],{radius:7,color:'#fff',weight:2,fillColor:col,
        fillOpacity: oper>0?0.95:0.55}).bindPopup(pop).addTo(obsLayer);
    });
  }catch(e){}
}

function switchTab(name){
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('active', b.dataset.tab===name));
  document.querySelectorAll('.tabpanel').forEach(p=>p.classList.toggle('active', p.id==='tab-'+name));
  $('#mapControls').classList.toggle('hide', !CTRL_TABS.has(name));
  setTimeout(()=>map.invalidateSize(), 50);
  if(name==='insights' && !loaded.insights) loadInsights();
  if(name==='ajustes' && !loaded.ajustes) loadAjustes();
  if(name==='agregar' && !loaded.agregar) loadAgregar();
  if(name==='ayuda' && !loaded.ayuda) loadAyuda();
}

function onMetro(){
  const m = $('#metro').value;
  map.setView(METRO_CENTER[m], 12);
  loadChargers(m); candLayer.clearLayers();
}

async function loadMeta(){
  try{
    const m = await (await fetch(API+'/api/meta')).json();
    $('#metaFoot').innerHTML =
      `Base: <b>${m.chargers_total}</b> cargadores (${m.public} púb · ${m.residential} resid · `+
      `${m.tesla_sites} Tesla · ${m.fast} rápidos) · ${m.states_with_demand} estados con adopción.<br>`+
      `Fuentes: PlugShare · INEGI RAIAVL · ICCT 2025 · AMIA 2026.`;
  }catch(e){}
}

/* ---------- capa NSE ---------- */
async function loadNse(){
  try{ nseData = await (await fetch(API+'/api/nse')).json(); drawNse(); }catch(e){}
}
function drawNse(){
  nseLayer.clearLayers();
  if(!showNse || !nseData) return;
  nseData.features.forEach(f=>{
    const p = f.properties, g = f.geometry;
    const polys = g.type==='MultiPolygon' ? g.coordinates : [g.coordinates];
    const col = nseColor(p.ses_index);
    let all = [];
    polys.forEach(poly=>{
      const ring = poly[0].map(c=>[c[1], c[0]]);
      all = all.concat(ring);
      L.polygon(ring, {color:col, weight:1.5, fillColor:col, fillOpacity:.20, interactive:false}).addTo(nseLayer);
    });
    if(all.length){
      const clat=(Math.min(...all.map(r=>r[0]))+Math.max(...all.map(r=>r[0])))/2;
      const clon=(Math.min(...all.map(r=>r[1]))+Math.max(...all.map(r=>r[1])))/2;
      L.tooltip({permanent:true, direction:'center', className:'nse-lbl', opacity:.9})
        .setContent(p.nse).setLatLng([clat,clon]).addTo(nseLayer);
    }
  });
}
function toggleNse(){
  showNse=!showNse; $('#nseToggle').textContent=showNse?'ON':'OFF'; drawNse();
}

/* ---------- cargadores ---------- */
async function loadChargers(metro){
  chargerLayer.clearLayers();
  if(!showChargers) return;
  const d = await (await fetch(API+`/api/chargers?metro=${encodeURIComponent(metro)}`)).json();
  d.chargers.forEach(c=>{
    const color = c.tesla?'#e05a4e':(c.class==='residential'?'#7a8aa0':(c.fast?'#4ea1ff':'#37e0a6'));
    L.circleMarker([c.lat,c.lon],{radius:4,color,weight:1,fillColor:color,fillOpacity:.75})
      .bindPopup(`<b>${c.name||'Cargador'}</b><br>${c.class}${c.tesla?' · Tesla':''}${c.fast?' · rápido':''}<br>${(c.connectors||[]).join(', ')}`)
      .addTo(chargerLayer);
  });
}
function toggleChargers(){
  showChargers=!showChargers; $('#chToggle').textContent=showChargers?'ON':'OFF';
  loadChargers($('#metro').value);
}

/* ---------- evaluación de punto ---------- */
function goToCoords(){
  const raw = ($('#coordInput')?.value||'').trim();
  // acepta "lat, lon", "lat lon", "(lat, lon)"
  const nums = raw.replace(/[()]/g,'').split(/[,;\s]+/).map(parseFloat).filter(v=>!isNaN(v));
  if(nums.length < 2){
    $('#analysis').innerHTML='<div class="empty">Formato inválido. Usa: lat, lon (ej. 19.3958, -99.1553)</div>';
    return;
  }
  const [lat, lon] = nums;
  if(!(lat>=-90 && lat<=90 && lon>=-180 && lon<=180)){
    $('#analysis').innerHTML='<div class="empty">Coordenadas fuera de rango.</div>';
    return;
  }
  switchTab('explorar');
  map.setView([lat, lon], 15);
  evaluate(lat, lon);
}

async function evaluate(lat, lon){
  const radius = parseFloat($('#radius').value);
  const cp = ($('#cp')?.value||'').trim();
  lastQuery = {lat, lon, radius, cp};
  evalLayer.clearLayers();
  L.circle([lat,lon],{radius:radius*1000,color:'#4ea1ff',weight:1.5,fillOpacity:.06}).addTo(evalLayer);
  L.marker([lat,lon]).addTo(evalLayer);
  $('#analysis').innerHTML='<div class="empty">Analizando…</div>';
  try{
    const a = await (await fetch(API+`/api/analyze?lat=${lat}&lon=${lon}&radius=${radius}`+(cp?`&cp=${encodeURIComponent(cp)}`:''))).json();
    renderAnalysis(a);
  }catch(e){ $('#analysis').innerHTML='<div class="empty">Error: '+e+'</div>'; }
}

function bar(lbl, v){
  return `<div class="bar"><span class="lbl">${lbl}</span><span class="track"><span class="fill" style="width:${v}%"></span></span><span class="val">${Math.round(v)}</span></div>`;
}
function stat(n,k){ return `<div class="stat"><div class="n">${n}</div><div class="k">${k}</div></div>`; }
const usd = n => '$'+(n>=1e6 ? (n/1e6).toFixed(2)+'M' : Math.round(n).toLocaleString());
const OPEX_LBL={electricidad:'Electricidad',mantenimiento_plataforma_pasarela:'Mantenimiento + plataforma + pasarela'};
function costRows(bd, labels, total){
  return Object.entries(bd).sort((a,b)=>b[1]-a[1]).map(([k,v])=>
    `<div class="hbar"><div class="top"><span>${labels[k]||k}</span><span>${usd(v)}</span></div>
     <div class="track"><div class="fill" style="width:${Math.max(2,100*v/total)}%"></div></div></div>`).join('');
}
function yearBars(years){
  const maxAbs = Math.max(...years.map(y=>Math.abs(y.cumulative_investor_profit)), 1);
  return years.map(y=>{
    const neg = y.cumulative_investor_profit < 0;
    const w = Math.max(2, 100*Math.abs(y.cumulative_investor_profit)/maxAbs);
    return `<div class="hbar"><div class="top"><span>Año ${y.year}</span><span>${usd(y.cumulative_investor_profit)}</span></div>
     <div class="track"><div class="fill" style="width:${w}%;background:${neg?'var(--low)':'var(--acc)'}"></div></div></div>`;
  }).join('');
}
function businessHtml(b){
  if(!b) return '';
  const be = b.break_even_months!=null ? b.break_even_months+' meses' : 'no rentable';
  const beCol = b.break_even_months==null ? 'var(--low)'
    : b.break_even_months<=36 ? 'var(--exc)' : b.break_even_months<=72 ? 'var(--mod)' : 'var(--low)';
  const pay = b.payback_years!=null ? b.payback_years+' años' : 'n/d';
  const roiPct = b.roi!=null ? (b.roi*100).toFixed(0)+'%' : 'n/d';
  const lf=b.local_factors, y9=b.year9, com=b.commissions;
  return `<div class="section-t">💰 Business case · 1 set de ${b.chargers} cargadores (${b.chargers} autos simultáneos)</div>
    <div class="bekpi" style="border-color:${beCol}">
      <div class="bev" style="color:${beCol}">${be}</div>
      <div class="bel">Punto de equilibrio<br><span>recuperar CapEx de ${usd(b.capex_total)}</span></div>
    </div>
    <div class="disc" style="margin-top:2px">Margen de contribución ${b.contribution_margin_per_kwh} USD/kWh
      (servicio ${b.service_cost_per_kwh}/kWh) · reparto utilidad: 16% local / 84% inversionista.</div>
    <div class="grid2">
      ${stat(usd(b.capex_total),'CapEx (inversión)')}
      ${stat(pay,'Payback')}
      ${stat(usd(b.revenue_annual)+'/a','Ingreso año 1')}
      ${stat(usd(y9.revenue)+'/a','Ingreso año 9 (meseta)')}
      ${stat(usd(b.gross_profit_annual)+'/a','Utilidad año 1')}
      ${stat(roiPct,'ROI '+b.roi_horizon_years+' años')}
    </div>
    <div class="disc">Electricidad punta ${lf.electricity_peak_usd_kwh} USD/kWh · valle ${lf.electricity_offpeak_usd_kwh} USD/kWh ·
      precio al usuario ${lf.price_per_kwh_user} USD/kWh · utilización efectiva ${(lf.utilization*100).toFixed(0)}%</div>
    <details class="costs"><summary>Desglose OpEx (año 1)</summary>${costRows(b.opex_breakdown,OPEX_LBL,b.opex_annual)}</details>
    <details class="costs"><summary>Utilidad acumulada del inversionista (9 años)</summary>${yearBars(b.years)}</details>
    <details class="costs"><summary>🤝 Esquema de comisiones (pago único, informativo)</summary>
      <div class="disc">VIP ${usd(com.vip_usd)} (5% del CapEx) · Vendedor ${usd(com.vendedor_usd)} · Arquitecto ${usd(com.arquitecto_usd)}.
      Se pagan al implementar el sitio; no se restan del ROI del inversionista mostrado arriba.<br>${com.recurring_note}</div></details>
    <details class="costs" id="sensWrap"><summary>📊 Sensibilidad: equilibrio × precio × costo de servicio</summary>
      <div id="sensBox"><div class="empty">Abriendo…</div></div></details>`;
}

function beColorMonths(m){
  if(m==null) return 'rgba(244,121,91,.60)';
  if(m<=36)  return 'rgba(55,224,166,.60)';
  if(m<=48)  return 'rgba(143,209,79,.55)';
  if(m<=60)  return 'rgba(214,224,79,.50)';
  if(m<=84)  return 'rgba(244,192,77,.55)';
  if(m<=120) return 'rgba(240,149,91,.55)';
  return 'rgba(244,121,91,.60)';
}
function nearestIdx(arr, v){
  let bi=0, bd=Infinity;
  arr.forEach((x,i)=>{ const d=Math.abs(x-v); if(d<bd){bd=d;bi=i;} });
  return bi;
}
async function loadSensitivity(){
  if(!lastQuery){ $('#sensBox').innerHTML='<div class="empty">Evalúa un punto primero.</div>'; return; }
  $('#sensBox').innerHTML='<div class="empty">Calculando matriz…</div>';
  const {lat,lon,radius,cp}=lastQuery;
  try{
    const d=await (await fetch(API+`/api/sensitivity?lat=${lat}&lon=${lon}&radius=${radius}`+(cp?`&cp=${encodeURIComponent(cp)}`:''))).json();
    const pi=nearestIdx(d.prices,d.current.price), sj=nearestIdx(d.services,d.current.service);
    const head=`<tr><th>P&nbsp;\\&nbsp;S</th>${d.services.map(s=>`<th>${(s*100).toFixed(0)}%</th>`).join('')}</tr>`;
    const rows=d.prices.map((p,i)=>`<tr><th>${p}</th>${d.grid[i].map((v,j)=>{
      const cur=(i===pi&&j===sj)?' cur':'';
      const label=v==null?'∞':Math.round(v);
      return `<td class="heatc${cur}" style="background:${beColorMonths(v)}" title="precio ${p} · servicio ${(d.services[j]*100).toFixed(0)}%: ${label} meses">${label}</td>`;
    }).join('')}</tr>`).join('');
    $('#sensBox').innerHTML=`
      <div class="disc" style="margin:2px 0 6px">Meses para recuperar CapEx (1 set de 6 cargadores). Filas = <b>precio de carga</b> (USD/kWh), columnas = <b>costo de servicio</b> (% de facturación). Electricidad punta ${d.site.electricity} USD/kWh. Borde blanco = punto actual (precio ${d.current.price}, servicio ${(d.current.service*100).toFixed(0)}%).</div>
      <div style="overflow-x:auto"><table class="heat">${head}${rows}</table></div>
      <div class="heatleg">
        <span><i style="background:${beColorMonths(24)}"></i>≤36m</span>
        <span><i style="background:${beColorMonths(54)}"></i>≤60m</span>
        <span><i style="background:${beColorMonths(72)}"></i>≤84m</span>
        <span><i style="background:${beColorMonths(100)}"></i>≤120m</span>
        <span><i style="background:${beColorMonths(999)}"></i>&gt;120m / ∞</span>
      </div>`;
  }catch(e){ $('#sensBox').innerHTML='<div class="empty">Error: '+e+'</div>'; }
}

function renderAnalysis(a){
  const col=COLOR[a.verdict]||'#888', s=a.subscores, est=a.estimation, ch=a.chargers, nse=a.nse;
  const conn=a.connector_types.slice(0,6).map(([k,v])=>`<span class="chip">${k} <b>${v}</b></span>`).join('');
  const veh=a.vehicles_seen.slice(0,6).map(([k,v])=>`<span class="chip">${k} <b>${v}</b></span>`).join('')||'<span class="chip">sin datos de reviews</span>';
  const ins=a.insights.map(t=>`<div class="ins">${t}</div>`).join('');
  const nseBadge = nse.source==='polygon'
    ? `<span class="chip" style="border-color:${nseColor(nse.index)}">NSE <b>${nse.nse}</b> · ${nse.zone}</span>`
    : `<span class="chip">NSE proxy · índice ${nse.index}</span>`;
  const f = a.field_observations;
  let fieldHtml='';
  if(f && f.count){
    const zrows=f.detail.map(z=>`<tr><td><b>${z.site}</b></td>
      <td>${z.operational}</td><td>${z.out_of_service||'—'}</td><td>${z.planned||'—'}</td>
      <td>${z.parking_spaces?z.parking_spaces.toLocaleString():'—'}</td></tr>`).join('');
    const extra=[];
    if(f.parking_spaces) extra.push(stat('~'+f.parking_spaces.toLocaleString(),'cajones (real)'));
    if(f.ev_observed!=null) extra.push(stat(f.ev_observed,'EV observados (real)'));
    fieldHtml=`<div class="section-t">📍 Levantamiento de campo · ${f.sites.join(', ')}</div>
      <div class="grid2">${stat(f.units_operational,'operativos')}${stat(f.units_out_of_service,'fuera de servicio')}
        ${stat(f.units_planned,'planeados')}${extra.join('')}</div>
      <table class="mini"><tr><th>Sitio</th><th>Op.</th><th>F.S.</th><th>Plan.</th><th>Cajones</th></tr>${zrows}</table>`;
  }
  $('#analysis').innerHTML=`
    <div class="scorecard">
      <div class="scorehead">
        <div class="dial" style="background:conic-gradient(${col} ${a.score*3.6}deg,#0f1a25 0)">
          <div style="background:var(--card);width:56px;height:56px;border-radius:50%;display:grid;place-items:center;color:${col}">${a.score}</div>
        </div>
        <div class="meta"><div class="verdict" style="color:${col}">${a.verdict}<small>${a.verdict_msg}</small></div></div>
      </div>
      <div class="stations">Instalar <b>1 set de ${a.business_case.chargers} cargadores</b> <small>(${a.business_case.chargers} autos simultáneos)</small></div>
      <div class="bars">
        ${bar('Demanda',s.demand)}${bar('Brecha',s.gap)}${bar('NSE',s.ses)}
        ${bar('Ancla retail',s.retail_anchor)}${bar('Oport. Tesla',s.tesla_opportunity)}
      </div>
    </div>
    <div class="section-t">Nivel socioeconómico</div>
    <div class="chips">${nseBadge}</div>
    <div class="section-t">En ${a.query.radius_km} km a la redonda${a.query.metro?' · '+a.query.metro:''}</div>
    <div class="grid2">
      ${stat('~'+est.cars_est.toLocaleString(),'autos (est.)')}
      ${stat('~'+est.ev_est.toLocaleString(),'eléctricos (est.)')}
      ${stat(ch.public,'cargadores públicos')}
      ${stat(ch.fast,'carga rápida')}
      ${stat(ch.tesla,'sitios Tesla')}
      ${stat('~'+est.home_chargers_est.toLocaleString(),'carga en casa (est.)')}
    </div>
    ${fieldHtml}
    ${businessHtml(a.business_case)}
    <div class="section-t">Tipos de conector</div><div class="chips">${conn||'<span class="chip">ninguno</span>'}</div>
    <div class="section-t">Vehículos vistos en la zona</div><div class="chips">${veh}</div>
    <div class="section-t">Insights</div>${ins}
    <div class="disc">${a.disclaimer}</div>`;
  const sw=$('#sensWrap');
  if(sw) sw.addEventListener('toggle',()=>{ if(sw.open && !sw.dataset.loaded){ sw.dataset.loaded='1'; loadSensitivity(); } });
}

/* ---------- candidatos ---------- */
async function loadCandidates(){
  const metro=$('#metro').value;
  $('#candlist').innerHTML='<div class="empty">Generando candidatos para '+metro+'…</div>';
  candLayer.clearLayers();
  try{
    const d=await (await fetch(API+`/api/candidates?metro=${encodeURIComponent(metro)}&top=15`)).json();
    const rows=d.candidates.map((c,i)=>{
      const col=COLOR[c.verdict]||'#888';
      const icon=L.divIcon({html:`<div class="marker-num" style="background:${col}">${i+1}</div>`,className:'',iconSize:[26,26],iconAnchor:[13,13]});
      L.marker([c.lat,c.lon],{icon}).addTo(candLayer)
        .bindPopup(`<b>#${i+1} ${c.label}</b><br>Score ${c.score} · ${c.verdict}<br>Instalar 1 set de ${c.chargers} cargadores<br><i>${c.reason}</i>`);
      return `<div class="candrow" data-lat="${c.lat}" data-lon="${c.lon}">
        <div class="rank" style="background:${col}">${i+1}</div>
        <div class="cinfo"><div class="cname">${c.label}</div>
        <div class="csub"><span class="kind">${c.kind}</span> · 1 set de ${c.chargers} cargadores · ${usd(c.capex)} · equilibrio ${c.break_even_months!=null?c.break_even_months+'m':'n/d'}</div></div>
        <div class="cscore" style="color:${col}">${c.score}</div></div>`;
    }).join('');
    $('#candlist').innerHTML=`<div class="section-t">Top candidatos · ${metro}</div>${rows}
      <div class="disc">Clic en un renglón para volar al punto y evaluarlo.</div>`;
    document.querySelectorAll('.candrow').forEach(r=>r.addEventListener('click',()=>{
      const la=parseFloat(r.dataset.lat),lo=parseFloat(r.dataset.lon);
      map.setView([la,lo],14); switchTab('explorar'); evaluate(la,lo);
    }));
    if(d.candidates.length) map.fitBounds(L.latLngBounds(d.candidates.map(c=>[c.lat,c.lon])).pad(0.2));
  }catch(e){ $('#candlist').innerHTML='<div class="empty">Error: '+e+'</div>'; }
}

/* ---------- INSIGHTS dashboard ---------- */
function hbar(label, val, max, right){
  const w=Math.max(2, 100*val/max);
  return `<div class="hbar"><div class="top"><span>${label}</span><span>${right}</span></div>
    <div class="track"><div class="fill" style="width:${w}%"></div></div></div>`;
}
async function loadInsights(){
  loaded.insights=true;
  const el=$('#insights');
  try{
    const [ins, demand, an] = await Promise.all([
      (await fetch(API+'/api/insights')).json(),
      (await fetch(API+'/api/demand')).json(),
      (await fetch(API+'/api/armadora-nse')).json(),
    ]);
    const mk=ins.market_2025;
    // adopción por estado (top 10)
    const states=Object.entries(demand).map(([k,v])=>({k,...v}))
      .sort((a,b)=>b.ev_units_period-a.ev_units_period).slice(0,10);
    const maxU=states[0].ev_units_period;
    const adoption=states.map(s=>hbar(s.entidad, s.ev_units_period, maxU,
      `${s.ev_units_period.toLocaleString()} · ${(s.share_national*100).toFixed(1)}%`)).join('');
    // precios
    const pr=ins.avg_price_mxn, maxP=Math.max(...Object.values(pr));
    const prices=Object.entries(pr).map(([k,v])=>hbar(k, v, maxP, money(v))).join('');
    // armadora x NSE
    const tierCls={3:'t3',2:'t2',1:'t1'};
    const brows=an.brands.map(b=>`<tr>
      <td><b>${b.brand}</b></td><td>${b.segment}</td>
      <td><span class="tier-pill ${tierCls[b.ses_tier]}">${b.ses_label}</span></td>
      <td>${b.market_share_bev!=null?(b.market_share_bev*100).toFixed(0)+'%':'—'}</td>
      <td>${(b.home_charging_prop*100).toFixed(0)}%</td></tr>`).join('');
    // carga en casa por NSE
    const hc=ins.home_charging_propensity;
    const home=Object.entries(hc).map(([t,v])=>hbar('NSE tier '+t+({1:' (medio)',2:' (medio-alto)',3:' (alto)'}[t]||''), v, 1, (v*100)+'%')).join('');

    el.innerHTML=`
      <div class="section-t">Mercado LDV México 2025 (ICCT)</div>
      <div class="kpis">
        <div class="kpi"><div class="n">${(mk.ev_share*100).toFixed(1)}%</div><div class="k">EV del mercado</div></div>
        <div class="kpi"><div class="n">+${(mk.ev_growth_yoy*100).toFixed(0)}%</div><div class="k">crecim. EV YoY</div></div>
        <div class="kpi"><div class="n">${(mk.ldv_total_units/1e6).toFixed(2)}M</div><div class="k">unidades LDV</div></div>
        <div class="kpi"><div class="n">+${(mk.phev_growth_yoy*100).toFixed(0)}%</div><div class="k">crecim. PHEV</div></div>
      </div>

      <div class="section-t">Precio promedio por tecnología (MXN)</div>${prices}
      <div class="disc">EVs son premium → adopción ligada a NSE alto.</div>

      <div class="section-t">Adopción EV+PHEV por estado (RAIAVL)</div>${adoption}

      <div class="section-t">Armadora × NSE (derivado)</div>
      <table class="mini"><tr><th>Marca</th><th>Seg</th><th>NSE</th><th>Sh.BEV</th><th>Casa</th></tr>${brows}</table>
      <div class="disc">Sh.BEV = participación BEV 2025 · Casa = propensión a carga en casa.</div>

      <div class="section-t">Carga en casa por NSE</div>${home}
      <div class="note">${an.notes.map(n=>'▸ '+n).join('<br>')}</div>`;
  }catch(e){ el.innerHTML='<div class="empty">Error: '+e+'</div>'; }
}

/* ---------- AJUSTES ---------- */
const WLABEL={demand:'Demanda',gap:'Brecha oferta/demanda',ses:'NSE',retail_anchor:'Ancla retail',tesla_opportunity:'Oportunidad Tesla'};
async function loadAjustes(){
  loaded.ajustes=true;
  const cfg=await (await fetch(API+'/api/config')).json();
  const nse=await (await fetch(API+'/api/nse')).json();
  const w=cfg.weights;
  const sliders=Object.keys(WLABEL).map(k=>`
    <div class="wrow"><div class="top"><span>${WLABEL[k]}</span><b id="wv-${k}">${(w[k]*100).toFixed(0)}</b></div>
    <input type="range" min="0" max="100" value="${w[k]*100}" data-w="${k}"></div>`).join('');
  const zones=nse.features.map(f=>f.properties)
    .sort((a,b)=>b.ses_index-a.ses_index)
    .map(p=>`<tr><td><b>${p.name}</b></td><td>${p.metro||'—'}</td><td><span class="tier-pill ${p.ses_index>=0.6?'t3':p.ses_index>=0.45?'t2':'t1'}">${p.nse}</span></td><td>${p.ses_index}</td></tr>`).join('');
  $('#ajustes').innerHTML=`
    <div class="section-t">Pesos del scoring (se normalizan a 100%)</div>
    ${sliders}
    <div class="btns"><button id="wApply" class="primary">Aplicar pesos</button>
      <button id="wReset" class="ghost">Restablecer</button></div>
    <div id="wMsg" class="disc"></div>

    <h3 class="s">Capa NSE — ${nse.features.length} zonas cargadas</h3>
    <table class="mini"><tr><th>Zona</th><th>Metro</th><th>NSE</th><th>Índice</th></tr>${zones}</table>
    <div class="note">
      <b>Cargar datos NSE oficiales (INEGI/AMAI):</b><br>
      1. Exporta a GeoJSON (desde shapefile: <code>ogr2ogr -f GeoJSON out.geojson in.shp</code> o mapshaper.org).<br>
      2. <code>python3 etl/load_nse.py out.geojson</code> &nbsp;(usa <code>--append</code> para sumar).<br>
      3. Pulsa <button id="nseReload" class="ghost" style="padding:2px 8px;font-size:11px">Recargar NSE</button> para reflejarlo sin reiniciar.<br>
      El cargador mapea campos comunes (NOMGEO, ESTRATO, NSE…) y deriva <code>ses_index</code>.
    </div>`;
  document.querySelectorAll('#ajustes input[data-w]').forEach(inp=>
    inp.addEventListener('input',()=>{ $('#wv-'+inp.dataset.w).textContent=inp.value; }));
  $('#wApply').addEventListener('click', applyWeights);
  $('#wReset').addEventListener('click', ()=>{ loaded.ajustes=false; loadAjustes(); });
  $('#nseReload').addEventListener('click', reloadNse);

  // --- business case ---
  const bc=await (await fetch(API+'/api/business-config')).json();
  const bizDiv=document.createElement('div');
  bizDiv.innerHTML=`
    <h3 class="s">💰 Business case (supuestos, 1 set de ${bc.chargers_per_site} cargadores)</h3>
    <div class="form">
      <label style="font-size:11px;color:var(--mut)">CapEx del set (USD, ${bc.chargers_per_site} cargadores)
        <input id="b-capex" type="number" value="${bc.site_capex_usd}"></label>
      <label style="font-size:11px;color:var(--mut)">Precio de carga al usuario (USD/kWh)
        <input id="b-price" type="number" step="0.01" value="${bc.price_per_kwh_user}"></label>
      <label style="font-size:11px;color:var(--mut)">Costo electricidad punta (USD/kWh)
        <input id="b-elecpeak" type="number" step="0.01" value="${bc.electricity_cost_peak_per_kwh}"></label>
      <label style="font-size:11px;color:var(--mut)">Costo electricidad valle (USD/kWh)
        <input id="b-elecoffpeak" type="number" step="0.01" value="${bc.electricity_cost_offpeak_per_kwh}"></label>
      <label style="font-size:11px;color:var(--mut)">% de ganancia para el dueño del local
        <input id="b-landlord" type="number" step="1" value="${(bc.landlord_profit_share*100).toFixed(0)}"></label>
    </div>
    <button id="bApply" class="primary block">Aplicar supuestos</button>
    <div id="bMsg" class="disc"></div>
    <div class="note">Modelo fijo: 1 set de 6 cargadores (360kW, 6 autos simultáneos), 9 años — no se
      proponen sets adicionales. CapEx de partida <b>USD $250k</b>. Utilización esperada 23%→40%
      (año 7 en adelante). Mantenimiento (10%) y plataforma (13%) escalan con la facturación.
      Edita el detalle en <code>app/config.py</code>.</div>`;
  $('#ajustes').appendChild(bizDiv);
  $('#bApply').addEventListener('click', applyBusiness);
}
async function applyBusiness(){
  const body={site_capex_usd:parseFloat($('#b-capex').value),
    price_per_kwh_user:parseFloat($('#b-price').value),
    electricity_cost_peak_per_kwh:parseFloat($('#b-elecpeak').value),
    electricity_cost_offpeak_per_kwh:parseFloat($('#b-elecoffpeak').value),
    landlord_profit_share:parseFloat($('#b-landlord').value)/100};
  await fetch(API+'/api/business',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('#bMsg').style.color='var(--acc)';
  $('#bMsg').innerHTML='Supuestos aplicados. Vuelve a Explorar y evalúa un punto.';
}
async function applyWeights(){
  const weights={};
  document.querySelectorAll('#ajustes input[data-w]').forEach(inp=>weights[inp.dataset.w]=parseFloat(inp.value));
  const r=await (await fetch(API+'/api/weights',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({weights})})).json();
  $('#wMsg').innerHTML='Pesos aplicados: '+Object.entries(r.weights).map(([k,v])=>`${k} ${(v*100).toFixed(0)}%`).join(' · ')+
    '. Vuelve a Explorar y evalúa un punto.';
}
async function reloadNse(){
  const r=await (await fetch(API+'/api/nse/reload')).json();
  await loadNse();
  loaded.ajustes=false; loadAjustes();
  alert('Capa NSE recargada: '+r.reloaded+' zonas.');
}

/* ---------- AGREGAR observación de campo ---------- */
function zoneCard(z){
  const id = ++zoneSeq;
  z = z || {};
  const div = document.createElement('div');
  div.className = 'zonecard'; div.dataset.zid = id;
  div.innerHTML = `
    <div class="zhead"><b>Zona</b><button class="zdel" title="Quitar">✕</button></div>
    <input class="z-zone" placeholder="Nombre de zona (ej. Sótano 1 - Corporativo)" value="${z.zone||''}">
    <div class="frow">
      <select class="z-section">
        <option value="">— sección —</option>
        <option ${z.section==='corporativo'?'selected':''}>corporativo</option>
        <option ${z.section==='comercial'?'selected':''}>comercial</option>
      </select>
      <input class="z-level" placeholder="Nivel (Sótano 1)" value="${z.level||''}">
    </div>
    <div class="frow">
      <input class="z-count" type="number" min="0" placeholder="# cargadores" value="${z.count!=null?z.count:''}">
      <select class="z-status">
        <option value="operational" ${z.status==='operational'?'selected':''}>operativo</option>
        <option value="planned" ${z.status==='planned'?'selected':''}>planeado</option>
        <option value="out_of_service" ${z.status==='out_of_service'?'selected':''}>fuera de servicio</option>
      </select>
    </div>
    <input class="z-brands" placeholder="Marcas (coma: Siemens, BYD, ClipperCreek)" value="${(z.brands||[]).join(', ')}">
    <input class="z-vehicles" placeholder="Vehículos cargando (coma: BYD camioneta, Tesla)" value="${(z.vehicles||[]).join(', ')}">`;
  div.querySelector('.zdel').addEventListener('click',()=>div.remove());
  return div;
}
function setPin(lat, lon){
  pinMode = false;
  const b=$('#pinBtn'); if(b){b.textContent='📍 Fijar con clic en el mapa'; b.classList.remove('primary');}
  if($('#f-lat')){ $('#f-lat').value=lat.toFixed(5); $('#f-lon').value=lon.toFixed(5); }
  evalLayer.clearLayers();
  L.marker([lat,lon]).addTo(evalLayer);
}
function loadAgregar(){
  loaded.agregar = true;
  const c = map.getCenter();
  $('#agregar').innerHTML = `
    <div class="section-t">Nueva observación de campo</div>
    <div class="form">
      <input id="f-name" placeholder="Nombre del sitio (ej. Samara)">
      <div class="frow">
        <input id="f-lat" placeholder="lat" value="${c.lat.toFixed(5)}">
        <input id="f-lon" placeholder="lon" value="${c.lng.toFixed(5)}">
      </div>
      <button id="pinBtn" class="ghost block">📍 Fijar con clic en el mapa</button>
      <input id="f-address" placeholder="Dirección (opcional)">
      <div class="frow">
        <select id="f-type">
          <option value="mixed">mixto</option><option value="mall">centro comercial</option>
          <option value="corporate">corporativo</option><option value="other">otro</option>
        </select>
        <input id="f-observer" placeholder="Observador">
      </div>
      <div class="frow">
        <input id="f-parking" type="number" min="0" placeholder="Cajones totales (opcional)">
        <input id="f-evobs" type="number" min="0" placeholder="EV observados (opcional)">
      </div>
      <input id="f-date" placeholder="Fecha (YYYY-MM-DD)">
    </div>
    <div class="section-t">Zonas</div>
    <div id="zones"></div>
    <button id="addZone" class="ghost block">+ Agregar zona</button>
    <div class="btns">
      <button id="obsSubmit" class="primary">Guardar observación</button>
      <button id="obsSample" class="ghost">Ejemplo Samara</button>
    </div>
    <div id="obsMsg" class="disc"></div>
    <div class="section-t">Observaciones cargadas</div>
    <div id="obsList"></div>`;
  $('#zones').appendChild(zoneCard());
  $('#addZone').addEventListener('click',()=>$('#zones').appendChild(zoneCard()));
  $('#pinBtn').addEventListener('click',()=>{
    pinMode=!pinMode; const b=$('#pinBtn');
    b.textContent = pinMode ? '🖱️ Haz clic en el mapa…' : '📍 Fijar con clic en el mapa';
    b.classList.toggle('primary', pinMode);
  });
  $('#obsSubmit').addEventListener('click', submitObservation);
  $('#obsSample').addEventListener('click', fillSamara);
  refreshObsList();
}
function fillSamara(){
  $('#f-name').value='Samara'; $('#f-lat').value='19.35920'; $('#f-lon').value='-99.25850';
  $('#f-address').value='Santa Fe, CDMX (aprox — ajústala)'; $('#f-type').value='mixed';
  $('#f-observer').value='fmondragon'; $('#f-date').value='2026-08-13';
  $('#zones').innerHTML='';
  [{zone:'Sótano 1 - Corporativo',section:'corporativo',level:'Sótano 1',count:5,status:'operational',brands:['Siemens','BYD','ClipperCreek'],vehicles:['BYD camioneta']},
   {zone:'Sótano 1 - Comercial',section:'comercial',level:'Sótano 1',count:2,status:'operational',brands:['ChargeNow','ClipperCreek'],vehicles:['Tesla camioneta','Toyota']},
   {zone:'Sótano 1 - Comercial (al fondo)',section:'comercial',level:'Sótano 1',count:8,status:'planned',brands:[],vehicles:[]},
   {zone:'Sótano 2 - Comercial',section:'comercial',level:'Sótano 2',count:2,status:'operational',brands:[],vehicles:[]}
  ].forEach(z=>$('#zones').appendChild(zoneCard(z)));
  setPin(19.3592,-99.2585); map.setView([19.3592,-99.2585],14);
}
function splitList(s){ return (s||'').split(',').map(x=>x.trim()).filter(Boolean); }
async function submitObservation(){
  const zones=[...document.querySelectorAll('#zones .zonecard')].map(z=>({
    zone: z.querySelector('.z-zone').value.trim(),
    section: z.querySelector('.z-section').value || null,
    level: z.querySelector('.z-level').value.trim() || null,
    chargers: [{count: parseInt(z.querySelector('.z-count').value||'0',10),
      brands: splitList(z.querySelector('.z-brands').value),
      status: z.querySelector('.z-status').value}],
    vehicles_charging: splitList(z.querySelector('.z-vehicles').value).map(v=>({make:v,type:null})),
  }));
  const pInt = v => { v=parseInt(v,10); return isNaN(v)?null:v; };
  const body={name:$('#f-name').value.trim(), lat:parseFloat($('#f-lat').value),
    lon:parseFloat($('#f-lon').value), address:$('#f-address').value.trim(),
    site_type:$('#f-type').value, observer:$('#f-observer').value.trim(),
    parking_spaces:pInt($('#f-parking').value), ev_observed:pInt($('#f-evobs').value),
    observed_at:$('#f-date').value.trim(), zones};
  const res=await fetch(API+'/api/observations',{method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d=await res.json();
  const msg=$('#obsMsg');
  if(!d.ok){ msg.style.color='var(--low)'; msg.innerHTML='✗ '+ (d.errors||['error']).join(' · '); return; }
  msg.style.color='var(--acc)';
  msg.innerHTML=`✓ Guardada "${d.observation.name}" (${d.observation.zones.length} zonas). Total puntos de campo: ${d.field_points}.`;
  await loadObsLayer();
  refreshObsList();
}
async function refreshObsList(){
  const d=await (await fetch(API+'/api/observations')).json();
  $('#obsList').innerHTML = d.observations.length
    ? d.observations.map(o=>{
        const oper=o.zones.reduce((s,z)=>s+z.chargers.filter(c=>c.status==='operational').reduce((a,c)=>a+c.count,0),0);
        const plan=o.zones.reduce((s,z)=>s+z.chargers.filter(c=>c.status==='planned').reduce((a,c)=>a+c.count,0),0);
        return `<div class="candrow" data-lat="${o.lat}" data-lon="${o.lon}">
          <div class="cinfo"><div class="cname">${o.name}</div>
          <div class="csub">${o.zones.length} zonas · ${oper} operativos · ${plan} planeados</div></div></div>`;
      }).join('')
    : '<div class="empty">Sin observaciones aún.</div>';
  document.querySelectorAll('#obsList .candrow').forEach(r=>r.addEventListener('click',()=>{
    const la=parseFloat(r.dataset.lat),lo=parseFloat(r.dataset.lon);
    map.setView([la,lo],15); switchTab('explorar'); evaluate(la,lo);
  }));
}

/* ---------- AYUDA ---------- */
function loadAyuda(){
  loaded.ayuda=true;
  $('#ayuda').innerHTML=`
    <div class="ayuda">
    <h3 class="s">¿Qué hace este sistema?</h3>
    <p>Sugiere <b>dónde instalar un set de 6 cargadores</b> (6 autos simultáneos) EV y responde,
    para cualquier punto, <b>“¿aquí es buena ubicación?”</b> con datos locales y a la redonda.</p>

    <h3 class="s">Cómo usar la UI</h3>
    <ol>
      <li><b>Explorar</b>: elige metrópoli y radio, haz <b>clic en el mapa</b> para evaluar un punto.
      Enciende <b>Cargadores</b> y <b>Capa NSE</b> para ver la infraestructura y el nivel socioeconómico.</li>
      <li><b>Candidatos</b>: genera el <b>top 15</b> de ubicaciones sugeridas (sitios Tesla, malls sin carga, huecos de demanda). Clic en un renglón para evaluarlo.</li>
      <li><b>Insights</b>: dashboard del mercado (ICCT/AMIA/INEGI): adopción por estado, precios, y el cruce <b>armadora × NSE</b>.</li>
      <li><b>Agregar</b>: registra un <b>levantamiento de campo</b> (sitio + zonas: sótanos, corporativo/comercial, marcas, vehículos vistos, cargadores planeados). Usa <b>Ejemplo Samara</b> para ver el formato. Los datos entran al motor de inmediato.</li>
      <li><b>Ajustes</b>: mueve los <b>pesos del scoring</b> y aplícalos; administra y <b>recarga la capa NSE</b> con datos oficiales.</li>
    </ol>

    <h3 class="s">Cómo consumir la API (app móvil)</h3>
    <p>Todo corre sobre estos endpoints (CORS abierto):</p>
    <div class="note">
      <code>GET /api/analyze?lat=..&amp;lon=..&amp;radius=5</code> → ¿buena ubicación?<br>
      <code>GET /api/candidates?metro=Monterrey</code> → sugerencias<br>
      <code>GET /api/armadora-nse</code> · <code>/api/insights</code> · <code>/api/nse</code> · <code>/api/demand</code><br>
      <code>POST /api/weights</code> {weights} · <code>GET /api/nse/reload</code>
    </div>

    <h3 class="s">Afinar el sistema</h3>
    <p>Los parámetros viven en <code>app/config.py</code> (pesos, umbrales, malls, modelo vehicular)
    e <code>data/nse_polygons.geojson</code> (NSE). Reconstruye datos con
    <code>python3 etl/build_dataset.py</code>. Ver <b>README.md</b> para el roadmap completo.</p>
    </div>`;
}

window.addEventListener('DOMContentLoaded', init);
