/* Single-purchase marginal rewards. Personal balances never enter the public dataset. */
var DecisionGuide=(function(){
 'use strict';
 const DEFAULT={version:1,fx:{USD:7.8,CNY:1.08,MOP:0.97},aviosHkd:0.10,rhrCategory:'',buckets:{},hangsengMulti:false,atmosForeign:false,guru:'',feeUs:0,feeHk:0,sub:{card:'',target:0,spent:0,currency:'USD',deadline:'',bonusHkd:0},history:[]};
 const clone=x=>JSON.parse(JSON.stringify(x));
 function valid(raw){let p=clone(DEFAULT);if(!raw||raw.version!==1)return p;
  for(const k of ['USD','CNY','MOP'])if(Number.isFinite(+raw.fx?.[k])&&+raw.fx[k]>0&&+raw.fx[k]<100)p.fx[k]=+raw.fx[k];
  if(Number.isFinite(+raw.aviosHkd)&&+raw.aviosHkd>=0&&+raw.aviosHkd<=2)p.aviosHkd=+raw.aviosHkd;
  if(['','world','dining','home','shopping','enjoy'].includes(raw.rhrCategory))p.rhrCategory=raw.rhrCategory;
  for(const [k,v] of Object.entries(raw.buckets||{}))if(/^[a-z0-9-]+(?::\d{4}-\d{2})?$/.test(k)&&(v===null||Number.isFinite(+v)&&+v>=0&&+v<1e9))p.buckets[k]=v===null?null:+v;
  p.hangsengMulti=raw.hangsengMulti===true;p.atmosForeign=raw.atmosForeign===true;
  if(['','GO','GING','GURU'].includes(raw.guru))p.guru=raw.guru;
  for(const k of ['feeUs','feeHk'])if(Number.isFinite(+raw[k])&&+raw[k]>=0&&+raw[k]<=30)p[k]=+raw[k];
  const s=raw.sub||{};if(typeof s.card==='string'&&s.card.length<100)p.sub.card=s.card;
  for(const k of ['target','spent','bonusHkd'])if(Number.isFinite(+s[k])&&+s[k]>=0&&+s[k]<1e8)p.sub[k]=+s[k];
  if(['USD','HKD','CNY'].includes(s.currency))p.sub.currency=s.currency;
  if(/^\d{4}-\d{2}-\d{2}$/.test(s.deadline||''))p.sub.deadline=s.deadline;
  if(Array.isArray(raw.history))p.history=raw.history.slice(-30).filter(x=>x&&typeof x==='object'&&typeof x.card==='string'&&typeof x.date==='string').map(x=>({card:x.card,date:x.date,changes:Object.fromEntries(Object.entries(x.changes||{}).filter(([k,v])=>/^[a-z0-9-]+(?::\d{4}-\d{2})?$/.test(k)&&Number.isFinite(+v)&&+v>=0).map(([k,v])=>[k,+v])),sub:Math.max(0,Number(x.sub)||0)}));
  return p;
 }
 function hkAmount(tx,p){return tx.amount*(tx.currency==='HKD'?1:p.fx[tx.currency]);}
 function cnyValue(hkd,p){return hkd/p.fx.CNY;}
 function bucket(rules,id,date){return rules.buckets.find(x=>x.id===id&&date>=x.start&&date<=x.end);}
 function progressKey(rules,id,date){let b=bucket(rules,id,date);return b?.cycle==='month'?`${id}:${date.slice(0,7)}`:id;}
 function used(p,id){return Object.hasOwn(p.buckets,id)&&Number.isFinite(p.buckets[id])?p.buckets[id]:null;}
 function room(rules,p,id,date){let b=bucket(rules,id,date),u=used(p,progressKey(rules,id,date));return b&&u!==null?Math.max(0,b.limit-u):null;}
 function classify(tx){let q=tx.purpose.toLowerCase();if(/12306|高铁|火车票|火車票|rail/i.test(q))return 'rail';if(/电费|水费|燃气|煤气|物业|充值|缴费/.test(q))return 'bills';if(/starbucks|星巴克|麦当劳|mcdonald|美团外卖|餐厅|餐館/.test(q))return 'dining';if(/山姆|sam.s club|costco|盒马|超市/.test(q))return 'grocery';let m=CardGuide.classify(q);return m.scene||'generic';}
 function rhrMatch(p,scene,tx){if(!p.rhrCategory||scene==='bills')return false;if(p.rhrCategory==='world')return tx.region!=='hk';if(p.rhrCategory==='dining')return scene==='dining'&&tx.region==='hk';return false;}
 function evaluate(data,hk,rules,tx,p,values){const amount=hkAmount(tx,p),scene=classify(tx),known=[],possible=[],missing=[];
  if(!Number.isFinite(amount)||amount<=0)return {error:'请填写有效金额及汇率'};
  const travel=scene==='thirdparty',bills=scene==='bills',usContext={location:tx.region==='us'?'us':tx.region==='cn'?'cn':'foreign',channel:tx.channel==='wallet'||tx.channel==='qr'?'wallet':'direct',fee:p.feeUs,foreignEligible:p.atmosForeign,bofaBonus:false,ibpCapReached:false,travelCategoryConfirmed:false};
  // Existing US category engine stays responsible for its own eligibility and point values.
  const usQuery=({rail:'普通消费',bills:'电费',dining:'餐饮',grocery:'超市',generic:'普通消费',thirdparty:'Trip.com',travel:'旅行',transit:'打车'})[scene]||tx.purpose;
  const out=CardGuide.recommend(data,usQuery,usContext,values);
  if(tx.channel!=='qr')for(const x of out.results){const pct=x.low,hi=x.high;known.push({id:x.card.id,name:x.card.name,bank:x.card.bank,group:'美国',value:amount*pct/100,upper:amount*hi/100,pct,highPct:hi,reason:`${x.rawRate}X ${x.card.currency} · ${x.reason}`,note:travel?'第三方旅行平台先按普通消费；商户类别需账单确认。':x.note||'',source:data.sources.find(s=>s.id===x.card.sources[0])?.url,consumed:{},certainty:x.conditional?'账户条件待确认':'估值'});}
  const qrCards=new Set(['hsbc-pulse']);
  const add=(id,rate,reason,note,source,consumed={},opts={})=>{let c=hk.cards.find(x=>x.id===id),reward=typeof opts.reward==='number'?opts.reward:amount*rate/100,fee=amount*p.feeHk/100,value=reward*(opts.rewardFactor??1)-fee;
   if(tx.channel==='qr'&&!qrCards.has(id))return;
   known.push({id,name:c.name,bank:c.bank,group:'香港',value,upper:value,pct:value/amount*100,highPct:value/amount*100,reason,note,source:source||c.url,consumed,certainty:tx.channel==='qr'?'渠道资格待确认':'已按所填额度'});
  };
  const rcFactor=Math.max(1,15*p.aviosHkd);
  const rcNote=`$1 奖赏钱 = 15 BA Avios；按每 Avios HK$${p.aviosHkd.toFixed(2)} 估值（也可当 HK$1 用），不是现金回赠倍数。`;
  if(!bills){
   for(const id of ['icbc-horoscope-up','icbc-horoscope-visa','icbc-gba-up'])add(id,1.5,'合资格消费 1.5% 现金回赠','人民币签账、钱包传递及排除项目仍须核对。');
   for(const id of ['hsbc-premier','hsbc-pulse','hsbc-visa-signature','hsbc-red']){
    if(tx.channel==='qr'&&!qrCards.has(id))continue;
    let c=hk.cards.find(x=>x.id===id),rc=amount*.004,parts=['基本 0.4% 奖赏钱'],consumed={},unresolved=[];
    if(id!=='hsbc-red'&&rhrMatch(p,scene,tx)){let n=room(rules,p,'hsbc-rhr-2026',tx.date);if(n===null&&bucket(rules,'hsbc-rhr-2026',tx.date))unresolved.push('最红自主共享年度已用额');else if(n>0){let take=Math.min(amount,n);rc+=take*.02;consumed['hsbc-rhr-2026']=take;parts.push(`最红额外 2%（本笔 HK$${take.toFixed(0)} 计入）`);}}
    else if(id!=='hsbc-red'&&!p.rhrCategory)unresolved.push('最红自主登记类别');
    if(id==='hsbc-pulse'&&['cn','mo'].includes(tx.region)&&['CNY','MOP'].includes(tx.currency)&&tx.channel==='qr'){
     let bid=tx.date<'2026-07-01'?'hsbc-pulse-h1-2026':'hsbc-pulse-h2-2026',n=room(rules,p,bid,tx.date);
     if(n===null&&bucket(rules,bid,tx.date))unresolved.push('Pulse 半年度已用额');else if(n>0){let take=Math.min(amount,n);rc+=take*.02;consumed[bid]=take;parts.push(`Pulse 额外 2%（本笔 HK$${take.toFixed(0)} 计入）`);}
    }
    if(id==='hsbc-visa-signature'&&p.rhrCategory&&rhrMatch(p,scene,tx)){
     let n=room(rules,p,'hsbc-vs-2026',tx.date);if(n===null&&bucket(rules,'hsbc-vs-2026',tx.date))unresolved.push('Visa Signature 专属年度已用额');else if(n>0){let take=Math.min(amount,n);rc+=take*.012;consumed['hsbc-vs-2026']=take;parts.push(`VS 额外 1.2%（本笔 HK$${take.toFixed(0)} 计入）`);}
    }
    if(id==='hsbc-red'&&tx.channel==='online'){
     let n=room(rules,p,'hsbc-red-month',tx.date);if(n===null&&bucket(rules,'hsbc-red-month',tx.date))unresolved.push('Red 网上签账本月已用额');else if(n>0){let take=Math.min(amount,n);rc+=take*.036;consumed[progressKey(rules,'hsbc-red-month',tx.date)]=take;parts.push(`Red 网上额外 3.6%（本笔 HK$${take.toFixed(0)} 计入）`);}
    }
    if(id==='hsbc-premier'&&p.guru&&['other','us','mo','cn'].includes(tx.region)&&tx.currency!=='HKD')unresolved.push('Travel Guru 会籍与当期门槛／上限，尚未计入');
    let value=rc*rcFactor-amount*p.feeHk/100;
    known.push({id,name:c.name,bank:c.bank,group:'香港',value,upper:value,pct:value/amount*100,highPct:value/amount*100,reason:parts.join(' + '),note:rcNote+(unresolved.length?' 未计：'+unresolved.join('、')+'。':''),source:c.url,consumed,certainty:unresolved.length?'仍有待确认加成':'已按所填额度',rc,miles:rc*15});
    if(unresolved.length)possible.push({name:c.name,note:unresolved.join('、'),source:id==='hsbc-pulse'?rules.sources.hsbcPulse:rules.sources.hsbcRhr});
   }
  }
  if(scene==='rail'&&tx.region==='cn'&&tx.channel==='online'&&tx.date>='2026-10-01'&&tx.date<='2026-12-31'){
   let n=room(rules,p,'hangseng-rail-h2-2026',tx.date);
   if(!p.hangsengMulti||n===null)possible.push({name:'恒生多货币 Mastercard 扣账卡 · 12306 15%',note:!p.hangsengMulti?'先确认卡种':'填本阶段已获回赠额',source:rules.sources.hangsengRail});
   else if(n>0){let r=Math.min(amount*.15,n);add('hangseng-debit',0,'12306 官方网站／App 15% 回赠，阶段最高 HK$120','指定网站或 App 才适用；已计入本阶段剩余额。',rules.sources.hangsengRail,{'hangseng-rail-h2-2026':r},{reward:r});}
  }
  if(tx.channel!=='qr'&&(scene==='dining'||scene==='generic'||scene==='thirdparty'))possible.push({name:'信银 Motion / 东亚 World / 建行 eye+ 等',note:'月门槛、登记、产品级别或类别尚未录入个人进度，不作为确定最高回赠。',source:rules.sources.cncbiMotion});
  if(tx.channel==='qr')possible.push({name:'工银亚洲银联卡',note:'银联扫码的基础回赠及临时活动是否合资格，待核对支付入口和银行入账。',source:hk.cards.find(c=>c.id==='icbc-horoscope-up')?.url});
  if(p.rhrCategory&&['home','shopping','enjoy'].includes(p.rhrCategory))possible.push({name:'汇丰最红自主指定商户',note:'此类别需逐个核对参加商户；仅凭“购物／家居”字眼不加到确定收益。',source:rules.sources.hsbcRhr});
  if(tx.channel!=='qr'&&tx.region==='hk'&&scene!=='bills'&&!rhrMatch(p,scene,tx))possible.push({name:'汇丰 Visa Signature 专属额外 1.2%',note:'适用最红类别的具体商户可能有奖励，尚未核实该商户及专属上限。',source:rules.sources.hsbcVisa});
  known.sort((a,b)=>b.value-a.value||a.name.localeCompare(b.name));
  if(tx.currency!=='HKD')missing.push('跨币结算汇率是本机规划值；发卡行实际换汇价、境外／跨境收费及平台手续费需核对。');
  if(bills)missing.push('账单缴费是否按合资格零售交易入账尚未确认；以下美国卡普通消费估值不保证获点。');
  if(travel)missing.push('Trip.com 等第三方不自动当航空直购、酒店直订或银行旅行门户。');
  if(tx.channel==='qr')missing.push('银联二维码仅比较已确认的银联卡；如实际走支付宝／微信绑卡，请改选钱包付款，并核对商户分类。');
  else if(tx.region==='cn'&&tx.channel==='wallet')missing.push('内地钱包能否绑定并使用美国卡、商户分类能否传递，需要以该付款入口及入账结果为准。');
  return {amount,scene,known,possible,missing};
 }
 return {DEFAULT,valid,hkAmount,cnyValue,bucket,room,progressKey,classify,rhrMatch,evaluate};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=DecisionGuide;
if(typeof document!=='undefined') (function(){
 const rules=JSON.parse(document.getElementById('decision-data').textContent);let p;
 try{p=DecisionGuide.valid(JSON.parse(localStorage.getItem('cards-magic-decision-v1')||'null'))}catch(e){p=DecisionGuide.valid(null)}
 const amt=n=>`HK$${Number(n).toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2})}`;
 const rmb=n=>`¥${DecisionGuide.cnyValue(n,p).toLocaleString('zh-CN',{maximumFractionDigits:2,minimumFractionDigits:2})}`;
 const todayHK=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const save=()=>{try{localStorage.setItem('cards-magic-decision-v1',JSON.stringify(p));return true}catch(e){toast('此浏览器无法保存，请导出配置');return false}};
 $('d-date').value=todayHK();
 function config(){let options=[...DATA.cards.map(c=>({id:c.id,name:'美国 · '+c.name})),...HK.cards.map(c=>({id:c.id,name:'香港 · '+c.bank+' '+c.name}))];
  let currentDate=$('d-date').value||todayHK();
  $('d-config-body').innerHTML=`<div class="d-settings"><h3>估值与账户条件</h3><label>汇丰最红 5X 集中分配类别（分拆待核对）<select id="dc-rhr"><option value="">未确认</option><option value="world">赏世界（境外／内地／澳门）</option><option value="dining">赏滋味（香港餐饮）</option><option value="home">赏家居</option><option value="shopping">赏购物</option><option value="enjoy">赏享受</option></select></label><label>BA Avios 每里估值（港币）<input id="dc-avios" type="number" min="0" max="2" step="0.01" value="${p.aviosHkd}"></label><label>Travel Guru 等级<select id="dc-guru"><option value="">未确认／未登记</option><option value="GO">GO（待核对门槛）</option><option value="GING">GING（待核对门槛）</option><option value="GURU">GURU（待核对门槛）</option></select></label><label>1 美元约合港币<input id="dc-usd" type="number" min="0.01" max="100" step="0.001" value="${p.fx.USD}"></label><label>1 人民币约合港币<input id="dc-cny" type="number" min="0.01" max="100" step="0.001" value="${p.fx.CNY}"></label><label>1 澳门元约合港币<input id="dc-mop" type="number" min="0.01" max="100" step="0.001" value="${p.fx.MOP}"></label><label>美国卡额外通道费 %<input id="dc-fee-us" type="number" min="0" max="30" step="0.1" value="${p.feeUs}"></label><label>香港卡额外通道费 %<input id="dc-fee-hk" type="number" min="0" max="30" step="0.1" value="${p.feeHk}"></label><label>恒生扣账卡版本<select id="dc-hangseng"><option value="">未确认</option><option value="yes">已确认多货币 Mastercard</option></select></label><label>Atmos 内地合资格境外 3X<select id="dc-atmos"><option value="">尚未确认</option><option value="yes">账单确认合资格</option></select></label><h3>本期已使用额（空白表示未知；填 0 表示确认尚未使用）</h3>${rules.buckets.filter(b=>b.start<=currentDate&&b.end>=currentDate).map(b=>{let key=DecisionGuide.progressKey(rules,b.id,currentDate)||b.id;return `<label class="d-bucket-row">${esc(b.label)}${b.cycle==='month'?' · '+esc(currentDate.slice(0,7)):''}<input type="number" min="0" step="0.01" data-bucket="${key}" placeholder="未知" value="${p.buckets[key]??''}"><small>上限 ${b.limit.toLocaleString('en-US')} ${esc(b.currency)} · ${esc(b.end)}</small></label>`}).join('')}<h3>新卡开卡任务（个人信息仅本机）</h3><label>要冲任务的卡<select id="dc-sub-card"><option value="">目前没有</option>${options.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><label>任务币种<select id="dc-sub-currency"><option>USD</option><option>HKD</option><option>CNY</option></select></label><label>目标金额<input id="dc-sub-target" type="number" min="0" step="0.01" value="${p.sub.target||''}"></label><label>已计入任务<input id="dc-sub-spent" type="number" min="0" step="0.01" value="${p.sub.spent||''}"></label><label>截止日期<input id="dc-sub-deadline" type="date" value="${p.sub.deadline}"></label><label>任务奖励个人估值（HKD，可空）<input id="dc-sub-bonus" type="number" min="0" step="1" value="${p.sub.bonusHkd||''}"></label></div>`;
  $('dc-rhr').value=p.rhrCategory;$('dc-guru').value=p.guru;$('dc-hangseng').value=p.hangsengMulti?'yes':'';$('dc-atmos').value=p.atmosForeign?'yes':'';$('dc-sub-card').value=p.sub.card;$('dc-sub-currency').value=p.sub.currency;
 }
 function readConfig(){let next=DecisionGuide.valid(p);next.rhrCategory=$('dc-rhr').value;next.guru=$('dc-guru').value;next.hangsengMulti=$('dc-hangseng').value==='yes';next.atmosForeign=$('dc-atmos').value==='yes';
  next.aviosHkd=Number($('dc-avios').value);next.fx={USD:Number($('dc-usd').value),CNY:Number($('dc-cny').value),MOP:Number($('dc-mop').value)};next.feeUs=Number($('dc-fee-us').value);next.feeHk=Number($('dc-fee-hk').value);
  if(!Object.values(next.fx).every(x=>x>0&&x<100)||next.aviosHkd<0||next.aviosHkd>2||[next.feeUs,next.feeHk].some(x=>x<0||x>30||!Number.isFinite(x)))throw Error('请核对汇率、点值及费用');
  document.querySelectorAll('[data-bucket]').forEach(el=>{if(el.value==='')delete next.buckets[el.dataset.bucket];else{let v=Number(el.value);if(!Number.isFinite(v)||v<0)throw Error('已用额度不能为负数');next.buckets[el.dataset.bucket]=v}});
  next.sub={card:$('dc-sub-card').value,currency:$('dc-sub-currency').value,target:Number($('dc-sub-target').value)||0,spent:Number($('dc-sub-spent').value)||0,deadline:$('dc-sub-deadline').value,bonusHkd:Number($('dc-sub-bonus').value)||0};return next;
 }
 function link(url,label){return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`:''}
 let last=null,lastTx=null;
 function render(){let amount=Number($('d-amount').value),purpose=$('d-purpose').value.trim(),tx={amount,currency:$('d-currency').value,region:$('d-region').value,channel:$('d-channel').value,date:$('d-date').value,purpose};lastTx=tx;
  if(!purpose||!Number.isFinite(amount)||amount<=0){$('d-results').innerHTML='<div class="d-intro">填写消费金额和用途即可比较。商户代码、登记状态、额度不明时会提示核对，不把最高宣传回赠当确定收益。</div>';return}
  let out=DecisionGuide.evaluate(DATA,HK,rules,tx,p,pointValues);if(out.error){$('d-results').textContent=out.error;return}last=out;
  let top=out.known[0],n=out.known.length,missing=out.missing.map(x=>`<div class="d-warning">${esc(x)}</div>`).join('');
  const sub=p.sub,remaining=Math.max(0,sub.target-sub.spent),days=sub.deadline?Math.ceil((new Date(sub.deadline+'T12:00:00Z')-new Date(tx.date+'T12:00:00Z'))/86400000):null;
  let subHtml=sub.card&&remaining>0&&days!==null&&days>=0?`<div class="d-sub"><strong>新卡任务优先检查：</strong>${esc([...DATA.cards,...HK.cards].find(c=>c.id===sub.card)?.name||sub.card)}，尚差 ${remaining.toLocaleString()} ${sub.currency}，距截止约 ${days} 天。${sub.bonusHkd?'完成后的个人奖励估值 '+amt(sub.bonusHkd)+'；':''}这笔能否计入任务须核对条款。任务未完成时，可优先考虑这张卡；不把任务奖励按每笔消费摊作保证回报。</div>`:'';
  const show=c=>`<article class="d-result-card ${c===top?'first':''}"><div class="d-result-top"><div><span class="d-chip">${esc(c.group)} · ${esc(c.bank)}</span><h3>${esc(c.name)}</h3><div class="d-status">${esc(c.certainty)}</div></div><div class="d-result-value"><span class="d-reward-label">可返利益 · 本笔估值</span><span class="d-reward-rate">${c.highPct-c.pct>.01?`${c.pct.toFixed(2)}–${c.highPct.toFixed(2)}%`:`约 ${c.pct.toFixed(2)}%`}</span><strong>${rmb(c.value)} 人民币</strong></div></div><div class="d-result-details"><div class="d-reason">${esc(c.reason)}</div>${c.rc!==undefined?`<p>约 $${c.rc.toFixed(2)} 奖赏钱 → ${c.miles.toFixed(0)} BA Avios；按本机估值折算。</p>`:''}<p>${esc(c.note)}</p></div><div class="d-foot">${link(c.source,'官方依据')} ${c===top?`<button class="small" id="d-record" data-card="${esc(c.id)}">这笔已刷，记入本机进度</button>`:''}</div></article>`;
  const alternatives=out.known.slice(1);
  $('d-results').innerHTML=`${subHtml}${missing}${out.possible.length?`<div class="d-warning"><strong>先核对，可能改变首选：</strong>${out.possible.slice(0,5).map(x=>`${esc(x.name)}（${esc(x.note)}） ${link(x.source,'规则')}`).join('；')}</div>`:''}<div class="advisor-heading"><h2>当前已录入、可估算条件下的首选</h2><span class="tiny muted">${esc(tx.date)} · ${amt(out.amount)} 规划基数</span></div>${top?show(top):'<div class="d-warning">这笔尚无可靠候选，请核对商户与付款方式。</div>'}<div class="advisor-heading"><h2>其他选择</h2><span class="tiny muted">按保守估值排序，共 ${n} 张可估算</span></div><div class="d-result-grid">${alternatives.map(show).join('')}</div><p class="tiny muted">美国卡积分采用本页可调整的点值下限；香港里数按你设定的 BA Avios 价值。数值是规划估值，不是保证现金入账。独立报销与未知商户分类不计入本次排序。</p>`;
  $('d-coverage').innerHTML=`当前比较：美国 11 张与已编码的香港现金／汇丰叠加／12306 等规则。其余香港卡保留在“香港卡”资料页，未核实产品版本、登记或进度时不参加确定收益排名。${link(rules.sources.hsbcGuru,'Travel Guru 规则')} ${link(rules.sources.icbcSupermarketExpired,'工银超市活动（已于 9 月结束）')}`;
 }
 function record(cardId){if(!last||!lastTx)return;let c=last.known.find(x=>x.id===cardId);if(!c)return;let changes={};for(const [key,v]of Object.entries(c.consumed)){let id=key.split(':')[0],current=DecisionGuide.room(rules,p,id,lastTx.date);if(current!==null&&v>0){p.buckets[key]=(p.buckets[key]||0)+v;changes[key]=v}}
  let sub=0;if(p.sub.card===cardId&&p.sub.target>p.sub.spent){sub=Math.min(p.sub.target-p.sub.spent,last.amount/(p.sub.currency==='HKD'?1:p.fx[p.sub.currency]));p.sub.spent+=sub;}
  if(!Object.keys(changes).length&&!sub){toast('这张卡没有可自动记入的已确认额度；请在账户配置中手动更新实际入账。');return}
  p.history.push({date:lastTx.date,card:cardId,changes,sub});p.history=p.history.slice(-30);save();config();render();toast('已记录到当前浏览器，可在下方撤销最近一笔');
 }
 $('d-run').onclick=render;for(const id of ['d-amount','d-purpose'])$(id).addEventListener('keydown',e=>{if(e.key==='Enter')render()});
 $('d-date').addEventListener('change',()=>{if($('d-config').open)config();render()});
 document.querySelectorAll('[data-d-query]').forEach(b=>b.onclick=()=>{$('d-purpose').value=b.dataset.dQuery;render()});
 $('d-results').addEventListener('click',e=>{let b=e.target.closest('[data-card]');if(b)record(b.dataset.card)});
 $('d-save').onclick=()=>{try{p=readConfig();save();config();render();toast('配置已保存在当前浏览器')}catch(e){toast(e.message)}};
 $('d-export').onclick=()=>{try{p=readConfig();save()}catch(e){toast(e.message);return}let blob=new Blob([JSON.stringify(p,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Cards-Magic-本机配置.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
 $('d-import').onclick=()=>$('d-file').click();$('d-file').onchange=async e=>{let f=e.target.files[0];if(!f)return;try{if(f.size>150000)throw Error('配置文件过大');let raw=JSON.parse(await f.text());if(raw.version!==1)throw Error('配置版本不符');p=DecisionGuide.valid(raw);save();config();render();toast('已导入本机配置')}catch(x){toast(x.message||'导入失败')}e.target.value=''};
 config();$('d-results').insertAdjacentHTML('afterend','<div class="d-actions"><button class="small" id="d-undo">撤销最近一笔本机进度</button></div>');$('d-undo').onclick=()=>{let h=p.history.pop();if(!h){toast('没有可撤销的记录');return}for(const [id,v]of Object.entries(h.changes))p.buckets[id]=Math.max(0,(p.buckets[id]||0)-v);p.sub.spent=Math.max(0,p.sub.spent-(h.sub||0));save();config();render();toast('已撤销最近一笔')};
 switchTab('decide');
})();
