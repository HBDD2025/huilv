/* Calculation rules are separate from UI so utilities and fees can be verified. */
var CardGuide = (function () {
  'use strict';
  const aliases = [
    ['utilities', '生活缴费', ['电费','水费','燃气','煤气','物业','水电','生活缴费','国家电网','utility','utilities']],
    ['telecom','通信 / 网络',['手机话费','电话费','宽带','通信','网络费','电信','联通','移动话费','telecom']],
    ['marriott','万豪酒店',['万豪','丽思','瑞吉','marriott','ritz']],
    ['hilton','希尔顿酒店',['希尔顿','hilton']],['hyatt','凯悦酒店',['凯悦','hyatt']],['ihg','IHG 酒店',['洲际','智选','皇冠假日','ihg']],
    ['onlinegrocery','网购超市',['网购超市','线上超市','online grocery']],
    ['dining','餐饮',['餐饮','餐厅','吃饭','外卖','咖啡','饭店','餐费','dining','restaurant']],
    ['airfare','机票直购',['机票','飞机票','航空','airfare','flight']],
    ['hotel','酒店直订',['酒店','住宿','宾馆','hotel']],
    ['gas','加油 / 充电',['加油','充电','油费','gas']],['grocery','超市',['超市','买菜','生鲜','grocery','groceries']],
    ['transit','打车 / 通勤',['打车','出租车','滴滴','地铁','公交','通勤','停车','过路','transit']],
    ['fitness','健身',['健身','gym','fitness']],['entertainment','娱乐',['电影','娱乐','演唱会','球赛','entertainment']],
    ['streaming','流媒体',['流媒体','netflix','spotify','youtube','订阅']],['shipping','运输',['快递','运输','邮费','shipping']],
    ['ads','网络广告',['广告','advertising']],['foreign','境外日常',['境外','海外','外币','foreign']],
    ['generic','普通消费',['网购','购物','日常','普通','京东','淘宝','拼多多','百货','generic']]
  ];
  function classify(input) {
    const text=String(input||'').trim().toLowerCase();
    const hit=aliases.find(x=>x[2].some(k=>text.includes(k)));
    return {scene:hit?.[0]||null,label:hit?.[1]||'',wallet:/支付宝|微信|alipay|wechat/.test(text)};
  }
  function resolve(card,scene,context) {
    let scenes=[scene];
    if(['marriott','hilton','ihg','hyatt'].includes(scene))scenes.push('hotel','travel');
    if(scene==='hotel')scenes.push('travel');
    const allowed=card.rates.filter(r=>r.scenes.some(s=>scenes.includes(s)) && (r.region==='all'||r.region===(context.location==='us'?'us':'foreign')));
    let rate={value:card.base,label:'普通合资格消费',note:'没有已核验的该类专项加倍'};
    if(allowed.length)rate=allowed.reduce((a,b)=>a.value>b.value?a:b);
    if(card.id==='ibp'&&context.ibpCapReached)rate={value:card.base,label:'年度类别上限已用完',note:'按普通 1X 计算'};
    if(card.id==='atmos'&&context.location!=='us'&&context.foreignEligible&&rate.value<3)rate={value:3,label:'已确认合资格境外交易',note:'需银行实际认定'};
    const wallet=context.channel==='wallet';
    // Do not promise that a wallet preserves dining, hotel or travel category data.
    const possible=rate;
    if(wallet&&rate.value>card.base&&!(card.id==='atmos'&&context.foreignEligible&&context.location!=='us'))rate={value:card.base,label:'钱包渠道按普通积分先估',note:'加倍是否传递取决于实际入账；上限情形单列'};
    const factor=card.id==='atmos'&&context.bofaBonus?1.1:1;
    return {rate:rate.value*factor,rawRate:rate.value,reason:rate.label,note:rate.note,possibleRate:possible.value*factor,conditional:wallet||card.status==='account',special:rate.value>card.base,potentialForeign:card.id==='atmos'&&context.location!=='us'&&!context.foreignEligible&&rate.value<3};
  }
  function calculate(rate,pointValue,fee) {
    const low=rate*pointValue[0]-fee,high=rate*pointValue[1]-fee;
    return {low,high};
  }
  function recommend(data,input,context,values) {
    const match=classify(input);if(!match.scene)return {match,results:[]};
    const results=data.cards.map(card=>{
      const earning=resolve(card,match.scene,context);
      const pointValue=card.currency==='cash'?[1,1]:values[card.currency];
      const range=calculate(earning.rate,pointValue,context.fee);
      const benefits=card.benefits.filter(b=>
        (match.scene==='dining'&&['brilliant-dining'].includes(b.id))||
        (match.scene==='airfare'&&['aspire-flight','ihg-air'].includes(b.id))||
        (match.scene==='hilton'&&b.id==='aspire-resort')||
        (['hotel','marriott','hilton','ihg','hyatt'].includes(match.scene)&&['citi-hotel','csp-hotel','vx-credit'].includes(b.id))
      );
      return {card,...earning,...range,benefits};
    }).sort((a,b)=>Number(a.conditional)-Number(b.conditional)||b.low-a.low||Number(b.card.currency==='cash')-Number(a.card.currency==='cash')||b.high-a.high);
    return {match,results};
  }
  return {classify,resolve,calculate,recommend};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=CardGuide;
