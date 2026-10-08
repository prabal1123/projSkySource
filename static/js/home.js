(function(){
var $=function(s,r){return(r||document).querySelector(s)};
var reduce=matchMedia("(prefers-reduced-motion:reduce)").matches,io='IntersectionObserver' in window;
/* Lite / Pro switch */
var radios=[].slice.call(document.querySelectorAll('[role=radio]')),pill=$('[aria-hidden=true].absolute'),priceEl=$('p.tabular-nums'),blurb=priceEl.nextElementSibling,cta=blurb.nextElementSibling,rows=[].slice.call(document.querySelectorAll('.frows li'));
var P={lite:{price:799,blurb:'For small and growing teams. Free for 30 days, no card needed.',cta:'Start free with Lite',href:'#lite-signup'},pro:{price:999,blurb:'The full HR lifecycle, from first day to last. Shown to you in a demo.',cta:'Book a Pro demo',href:'#book-demo'}};
var cur=799,timer;
function plan(p){var d=P[p],pro=p==='pro';
radios.forEach(function(b,x){var on=(x===1)===pro;b.setAttribute('aria-checked',on);b.tabIndex=on?0:-1;b.classList.toggle('text-background',on);b.classList.toggle('text-foreground',!on)});
pill.style.transform=pro?'translateX(100%)':'none';
blurb.textContent=d.blurb;cta.textContent=d.cta;cta.setAttribute('href',d.href);
rows.forEach(function(li,x){var ok=li.getAttribute(pro?'data-pro':'data-lite')==='1';setTimeout(function(){li.classList.toggle('no',!ok);li.firstChild.textContent=ok?'\u2713':'\u00d7'},reduce?0:x*25)});
clearInterval(timer);var to=d.price;
if(reduce){cur=to;priceEl.firstChild.textContent='\u20b9'+to;return}
timer=setInterval(function(){cur+=cur<to?10:-10;if(Math.abs(to-cur)<10)cur=to;priceEl.firstChild.textContent='\u20b9'+cur;if(cur===to)clearInterval(timer)},14)}
radios.forEach(function(b,x){b.onclick=function(){plan(x?'pro':'lite')}});
radios.forEach(function(b,x){b.onkeydown=function(e){if(e.key==='ArrowRight'||e.key==='ArrowLeft'){plan(x?'lite':'pro');radios[x?0:1].focus()}}});
plan('lite');
/* 30-day trial dots */
var grid=$('[aria-label^="Day "]'),dots=[].slice.call(grid.children),lab=grid.nextElementSibling.lastElementChild,fin=$('p.opacity-30');
function fill(d){dots.forEach(function(x,k){x.setAttribute('data-fill',k<d)});grid.setAttribute('aria-label','Day '+d+' of 30');lab.textContent='Day '+Math.max(d,1);if(d>=30)fin.style.opacity=1}
if(io&&!reduce){new IntersectionObserver(function(e,o){if(!e[0].isIntersecting)return;o.disconnect();var d=0,t=setInterval(function(){fill(++d);if(d>=30)clearInterval(t)},70)},{threshold:.5}).observe(grid)}else fill(30);
})();
(function(){
var open=function(){return document.querySelectorAll('.login-dd[open]')};
document.addEventListener('click',function(e){open().forEach(function(d){if(!d.contains(e.target))d.removeAttribute('open')})});
document.addEventListener('keydown',function(e){if(e.key==='Escape')open().forEach(function(d){d.removeAttribute('open')})});
})();