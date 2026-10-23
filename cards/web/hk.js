'use strict';
(function(){
 const data=JSON.parse(document.getElementById('hk-data').textContent), cards=data.cards;
 const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const banks=[...new Set(cards.map(x=>x.bank))];$('hk-bank').insertAdjacentHTML('beforeend',banks.map(b=>`<option value="${esc(b)}">${esc(b)}</option>`).join(''));
 $('hk-count-tab').textContent=cards.length;
 const categoryAliases={餐饮:/餐|食|饭|外卖|food|dining|restaurant/i,网购:/网购|网上|在线|online|amazon|淘宝|京东/i,旅行:/旅行|旅游|trip|携程|booking|expedia|机票|酒店|airline|hotel/i,外币:/外币|境外|海外|美元|日元|foreign|overseas/i,内地:/内地|中国|大陆|人民币|rmb|cny/i,钱包:/微信|支付宝|云闪付|apple pay|wallet|paywave|钱包/i,购物:/购物|消费|超市|百货|shopping/i,扣账:/扣账|debit|提款/i,电费:/电费|电力|港灯|中电/i,水费:/水费|水务/i};
 function canonical(q){return Object.entries(categoryAliases).find(([_,rx])=>rx.test(q))?.[0]||''}
 function render(){const q=$('hk-search').value.trim().toLowerCase(),bank=$('hk-bank').value,type=$('hk-type').value,tag=canonical(q);
 let found=cards.filter(c=>(!bank||c.bank===bank)&&(!type||c.type===type)&&(!q||[c.bank,c.name,c.type,c.offer,c.note,...c.categories].join(' ').toLowerCase().includes(q)||tag&&c.categories.includes(tag)));
 // Explicit product names also work when a category alias is present in the query.
 const thirdParty=/trip\.com|携程|booking|expedia/i.test(q),bills=/电费|水费|煤气|管理费|学费|保险/i.test(q);
 $('hk-result').textContent=`显示 ${found.length} / ${cards.length} 张 · ${new Set(found.map(c=>c.bank)).size} 家银行 · 含 6 张扣账卡`;
 $('hk-advice').textContent=thirdParty?'第三方平台可归入旅行用途，但银行是否认定为旅行／指定网上商户，要按实际商户代码及账单核实；不套用航空公司直订或门户加成。':bills?'当前没有核实适用于该账单类别的香港卡专项回赠；银行账单缴费、自动转账和商户直接刷卡的奖励规则可能不同。':q?'以下按用途与卡名模糊匹配；“最高”回赠须先检查门槛、登记和月度上限。':'先输入用途或商户；所有香港持卡默认全部列出，无需逐张展开。';
 let groups=[...new Set(found.map(c=>c.bank))];$('hk-list').innerHTML=found.length?groups.map(b=>`<section class="hk-group"><h3>${esc(b)} <small>${found.filter(c=>c.bank===b).length} 张</small></h3><div class="hk-cards">${found.filter(c=>c.bank===b).map(c=>`<article class="hk-card"><div class="hk-card-heading"><div><span class="hk-type">${esc(c.type)}</span><h4>${esc(c.name)}</h4></div><span class="hk-status ${c.status==='常规回赠'?'solid':c.status==='卡种待确认'?'uncertain':''}">${esc(c.status)}</span></div><div class="hk-offer">${esc(c.offer)}</div><p>${esc(c.note)}</p><div class="hk-card-foot"><span>${c.categories.map(t=>`<span class="hk-chip">${esc(t)}</span>`).join('')}</span><span class="hk-source-links"><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">官方产品 ↗</a>${c.termsUrl?` <a href="${esc(c.termsUrl)}" target="_blank" rel="noopener noreferrer">活动条款 ↗</a>`:''}</span></div></article>`).join('')}</div></section>`).join(''):'<div class="hk-empty">没有匹配的香港卡，或尚未核实这一类别的专项回赠。换个词试试，或清空筛选查看全部。</div>';
 }
 $('hk-search').addEventListener('input',render);$('hk-bank').addEventListener('change',render);$('hk-type').addEventListener('change',render);
 document.querySelectorAll('[data-hk-query]').forEach(b=>b.onclick=()=>{$('hk-search').value=b.dataset.hkQuery;render();$('hk-search').focus()});
 $('hk-clear').onclick=()=>{$('hk-search').value='';$('hk-bank').value='';$('hk-type').value='';render();$('hk-search').focus()};render();
})();
