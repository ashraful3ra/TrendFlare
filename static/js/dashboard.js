let R_points=[]; let symbolsCache=[]; let sio=null; let currentPage = 1;

function el(tag,attrs={},children=[]){const e=document.createElement(tag);Object.entries(attrs).forEach(([k,v])=>{if(k==='class')e.className=v;else if(k==='html')e.innerHTML=v;else e.setAttribute(k,v);});children.forEach(c=>e.appendChild(c));return e;}
function renderR(){const root=document.getElementById('r_list');root.innerHTML='';R_points.forEach((v,i)=>{const val=(v===null||isNaN(v))?'':v;const inp=el('input',{class:'input',type:'number',step:'0.1',value:val,placeholder:`R${i+1}`});inp.addEventListener('input',ev=>{R_points[i]=parseFloat(ev.target.value);if(isNaN(R_points[i]))R_points[i]=null});root.appendChild(inp);});}
function renderTemplates(items){const root=document.getElementById('tpl_list');root.innerHTML='';if(!items.length){root.innerHTML='<div class="small">No templates</div>';return}for(const t of items){const d=el('div',{class:'list-item'});d.innerHTML=`<div><div class="name">${t.name}</div><div class="small">${new Date(t.created_at*1000).toLocaleString()}</div></div><div class="row"><button class="btn" data-id="${t.id}" data-act="load"><i class="fas fa-edit"></i></button><button class="btn btn-danger" data-id="${t.id}" data-act="del"><i class="fas fa-trash-alt"></i></button></div>`;root.appendChild(d)}root.querySelectorAll('button').forEach(b=>b.addEventListener('click',async ev=>{const btn=ev.target.closest('button');const id=btn.getAttribute('data-id');const act=btn.getAttribute('data-act');if(act==='del'){if(!confirm('Delete template?'))return;await fetch('/templates/delete/'+id,{method:'POST'});loadTemplates()}else{const r=await fetch('/templates/get/'+id);const t=await r.json();loadTemplateIntoForm(t)}}));}
function toggleRecoveryFields(){const mode=document.getElementById('trade_amount_mode').value;const fields=document.getElementById('recovery_fields');fields.style.display=mode==='Recovery'?'flex':'none';}
function loadTemplateIntoForm(t){bot_name.value=t.name||'';bot_symbol.value=t.symbol||'';document.getElementById('time_frame').value=t.time_frame||'1m';document.getElementById('margin_mode').value=t.margin_type||'ISOLATED';document.getElementById('leverage').value=t.long_leverage||'';document.getElementById('trade_amount').value=t.long_amount||'';document.getElementById('trade_mode').value=t.trade_mode||'Follow';document.getElementById('trade_amount_mode').value=t.trade_amount_mode||'Normal';document.getElementById('recovery_margin').value=t.recovery_margin||'0';document.getElementById('recovery_max_amount').value=t.recovery_max_amount||'0';document.getElementById('run_mode').value=t.run_mode||'Ongoing';document.getElementById('max_trades').value=t.max_trades||'0';R_points=(t.r_points_json?t.r_points_json:[]).filter(p=>p!==null);if(R_points.length<5){R_points.push(...new Array(5-R_points.length).fill(null))}renderR();document.getElementById('cond_open_new_candle').checked=!!t.open_on_new_candle;document.getElementById('cond_sl_close').checked=!!t.cond_sl_close;document.getElementById('cond_close_candle_end').checked=!!t.close_on_candle_end;document.getElementById('cond_trailing').checked=!!t.cond_trailing;document.getElementById('cond_close_last').checked=!!t.cond_close_last;toggleRecoveryFields();}
async function safeJson(r){const txt=await r.text();try{return JSON.parse(txt)}catch(e){return{__raw:txt,error:`HTTP ${r.status}`}}}
async function fetchSymbols(){const r=await fetch('/api/futures/symbols');const d=await safeJson(r);if(d.symbols){return d.symbols}alert('Symbol list error: '+(d.error||d.__raw||'unknown'));return[]}
async function initSymbolSuggest(){symbolsCache=await fetchSymbols();const input=document.getElementById('bot_symbol');const list=document.getElementById('symbol_suggest');input.addEventListener('input',e=>{const q=(e.target.value||'').toUpperCase();if(!q){list.innerHTML='';list.style.display='none';return}const matches=symbolsCache.filter(s=>s.startsWith(q)).slice(0,10);list.innerHTML='';if(matches.length){list.style.display='block'}else{list.style.display='none'}matches.forEach(m=>{const li=el('div',{class:'list-item'});li.innerHTML=`<div class="name">${m.replace(new RegExp(`(${q})`,'i'),'<font color="#f08d25"><b>$1</b></font>')}</div>`;li.addEventListener('click',()=>{input.value=m;list.innerHTML='';list.style.display='none'});list.appendChild(li)});});document.addEventListener('click',e=>{if(!input.contains(e.target)){list.style.display='none'}});}

function calculateSlRoi(entry, sl, lev, side) {
    if (!entry || !sl || !lev) return 0;
    if (side === 'Long') return (((sl - entry) / entry) * lev * 100);
    if (side === 'Short') return (((entry - sl) / entry) * lev * 100);
    return 0;
}

function renderBots(bots) {
    const root = document.getElementById('bot-display-area');
    root.innerHTML = '';
    if (!bots || !bots.length) {
        root.innerHTML = '<div class="small mt">No bots yet.</div>';
        return;
    }
    bots.forEach(b => {
        const roi = b.current_roi || 0;
        const pnl = b.total_pnl || 0;
        const total_profit = b.total_profit || 0;
        const total_loss = b.total_loss || 0;
        const status = b.long_status === 'Running' || b.short_status === 'Running' ? 'Running' : b.long_status;
        const runningTrade = b.long_status === 'Running' ? 'Long' : (b.short_status === 'Running' ? 'Short' : 'None');
        const isCompleted = status === 'Completed';
        const isPaused = b.paused;
        
        let slText = '-';
        if(runningTrade !== 'None') {
            const slPrice = runningTrade === 'Long' ? b.long_sl_point : b.short_sl_point;
            const entryPrice = runningTrade === 'Long' ? b.long_entry_price : b.short_entry_price;
            if(slPrice && entryPrice) {
                const slRoi = calculateSlRoi(entryPrice, slPrice, b.long_leverage, runningTrade);
                slText = `${runningTrade.charAt(0)}: ${slRoi.toFixed(2)}%`;
            }
        }
        
        let statusText = status;
        let statusColorClass = 'status-warn';
        if(isPaused) {
            statusText = "Paused";
            statusColorClass = 'status-warn';
        } else if (status === 'Running') {
            statusColorClass = 'roi-pos';
        } else if (status === 'Completed') {
            statusColorClass = 'status-off';
        }
        
        let runningTradeColorClass = 'trade-none';
        if (runningTrade === 'Long') runningTradeColorClass = 'trade-long';
        else if (runningTrade === 'Short') runningTradeColorClass = 'trade-short';

        let actionsHTML = isCompleted ? `<div class="btn btn-closed">Closed</div>` : `
            <button class="btn ${isPaused ? 'btn-success' : 'btn-warning'}" id="btn-pause-${b.id}" onclick="toggleBotPause(${b.id})">${isPaused ? 'Resume' : 'Pause'}</button>
            <button class="btn btn-danger" id="btn-close-${b.id}" onclick="closeBotTrade(${b.id})">Close</button>`;

        const card = el('div', { class: 'bot-container', id: `bot-card-${b.id}` });
        card.innerHTML = `
            <div class="bot-header-grid">
                <div><div class="bot-name">${b.name}</div><div>Coin: <span class="value">${b.symbol}</span></div></div>
                <div style="text-align: right; font-size: 12px; color: var(--muted);"><div>Start at: <span class="value">${new Date(b.start_time * 1000).toLocaleString()}</span></div><div>Account: <span class="value">${b.account_name}</span></div></div>
            </div>
            <div class="bot-live-info-grid">
                <div>
                    <div>Status: <b id="bot-status-${b.id}" class="${statusColorClass}">${statusText}</b></div>
                    <div>Running Trade: <b id="bot-running-trade-${b.id}" class="${runningTradeColorClass}">${runningTrade}</b></div>
                    <div>Entry Price: <b id="bot-entry-price-${b.id}">${b.long_entry_price ? b.long_entry_price.toFixed(5) : (b.short_entry_price ? b.short_entry_price.toFixed(5) : '-')}</b></div>
                </div>
                <div style="text-align: right;">
                    <div>ROI: <b id="bot-roi-${b.id}" class="${roi >= 0 ? 'roi-pos' : 'roi-neg'}">${roi.toFixed(2)}%</b></div>
                    <div>Current SL: <b id="bot-sl-${b.id}" class="roi-neg">${slText}</b></div>
                    <div>Market Price: <b id="bot-market-price-${b.id}">-</b></div>
                </div>
            </div>
            <div class="bot-stats-grid">
                <div><div><span class="small">Total Trade:</span> <b id="bot-total-trades-${b.id}">${b.total_trades || 0}</b></div><div><span class="small">Total Breakeven:</span> <b id="bot-breakeven-trades-${b.id}">${b.breakeven_trades || 0}</b></div></div>
                <div style="text-align: right;"><div><span class="small">Total Losing:</span> <b id="bot-losing-trades-${b.id}">${b.losing_trades || 0}</b></div><div><span class="small">Total Winning:</span> <b id="bot-winning-trades-${b.id}">${b.winning_trades || 0}</b></div></div>
            </div>
            <div class="bot-pnl-section">
                <div><div class="small">Total Profit: <span class="roi-pos" id="bot-total-profit-${b.id}">$${total_profit.toFixed(2)}</span></div><div class="small">Total Loss: <span class="roi-neg" id="bot-total-loss-${b.id}">$${total_loss.toFixed(2)}</span></div></div>
                <div><div class="small" style="text-align: right;">PnL</div><div id="bot-pnl-${b.id}" class="pnl-value ${pnl >= 0 ? 'roi-pos' : 'roi-neg'}">$${pnl.toFixed(2)}</div></div>
            </div>
            <div class="bot-actions">${actionsHTML}</div>
        `;
        root.appendChild(card);
    });
}

async function toggleBotPause(botId) {
    await fetch('/bots/toggle_pause/' + botId, { method: 'POST' });
}

async function closeBotTrade(botId){if(!confirm('Are you sure you want to close this trade?'))return;await fetch('/bots/close/'+botId,{method:'POST'});}
async function refreshBots(page=currentPage){ document.getElementById('page_info').textContent=`${page}`; try{ const r=await fetch(`/bots/list?page=${page}`); const d=await r.json(); renderBots(d.items||[]); const totalPages = Math.ceil((d.total || 0) / 5); document.getElementById('btn_next').disabled = (page >= totalPages); document.getElementById('btn_prev').disabled = (page <= 1); }catch(e){console.error("Failed to refresh bots:",e)} }
document.getElementById('r_add').addEventListener('click',()=>{R_points.push(null);renderR()});
function getFormPayload(){return{name:bot_name.value.trim(),account_id:parseInt(bot_account.value||0),symbol:bot_symbol.value.trim().toUpperCase(),time_frame:document.getElementById('time_frame').value,margin_mode:document.getElementById('margin_mode').value,leverage:parseInt(document.getElementById('leverage').value||50),trade_amount:parseFloat(document.getElementById('trade_amount').value||0),trade_mode:document.getElementById('trade_mode').value,trade_amount_mode:document.getElementById('trade_amount_mode').value,recovery_margin:parseFloat(document.getElementById('recovery_margin').value||0),recovery_max_amount:parseFloat(document.getElementById('recovery_max_amount').value||0),run_mode:document.getElementById('run_mode').value,max_trades:parseInt(document.getElementById('max_trades').value||0),r_points:R_points.filter(p=>p!==null&&!isNaN(p)),open_on_new_candle:document.getElementById('cond_open_new_candle').checked?1:0,cond_sl_close:document.getElementById('cond_sl_close').checked?1:0,close_on_candle_end:document.getElementById('cond_close_candle_end').checked?1:0,cond_trailing:document.getElementById('cond_trailing').checked?1:0,cond_close_last:document.getElementById('cond_close_last').checked?1:0};}
document.getElementById('btn_save_tpl').addEventListener('click',async()=>{ const body=getFormPayload(); if(!body.name){alert('Template name required');return} const r = await fetch('/templates/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const d = await safeJson(r); if (d.error || !d.ok) { alert('Failed to save template: ' + (d.error || d.__raw || 'Unknown error')); return; } await loadTemplates(); alert('Template saved'); });
document.getElementById('btn_submit').addEventListener('click',async()=>{const body=getFormPayload();if(!body.name||!body.account_id||!body.symbol){alert('Name, account and symbol required');return}if(body.trade_amount<=0){alert('Trade amount must be greater than 0');return}const r=await fetch('/bots/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await safeJson(r);if(d.error||!d.ok){alert('Submit failed: '+(d.error||d.__raw||'unknown'));return}await refreshBots();alert('Bot submitted')});
document.getElementById('btn_next').addEventListener('click',()=>{currentPage++;refreshBots(currentPage)});
document.getElementById('btn_prev').addEventListener('click',()=>{if(currentPage>1){currentPage--;refreshBots(currentPage)}});

function initSocket(){
    sio=io();
    sio.on('bot_update', p => {
        if(!p || !p.bot_id) return;
        const botCard = document.getElementById(`bot-card-${p.bot_id}`);
        if (!botCard) return;
        
        // Update pause status
        if (p.hasOwnProperty('paused')) {
            const statusEl = botCard.querySelector(`#bot-status-${p.bot_id}`);
            const pauseBtn = botCard.querySelector(`#btn-pause-${p.bot_id}`);
            if (p.paused) {
                statusEl.textContent = 'Paused';
                statusEl.className = 'status-warn';
                if(pauseBtn) {
                    pauseBtn.textContent = 'Resume';
                    pauseBtn.className = 'btn btn-success';
                }
            } else {
                // If unpausing, let the regular status update handle the text
                if(pauseBtn) {
                    pauseBtn.textContent = 'Pause';
                    pauseBtn.className = 'btn btn-warning';
                }
            }
        }

        const statusEl = botCard.querySelector(`#bot-status-${p.bot_id}`);
        if(statusEl && !p.hasOwnProperty('paused')) {
            statusEl.textContent = p.status || 'Idle';
            let statusColorClass = 'status-warn';
            if (p.status === 'Running') statusColorClass = 'roi-pos';
            else if (p.status === 'Completed') statusColorClass = 'status-off';
            statusEl.className = statusColorClass;
        }
        
        const runningTradeEl = botCard.querySelector(`#bot-running-trade-${p.bot_id}`);
        if (runningTradeEl) {
            runningTradeEl.textContent = p.running_trade || 'None';
            let runningTradeColorClass = 'trade-none';
            if (p.running_trade === 'Long') runningTradeColorClass = 'trade-long';
            else if (p.running_trade === 'Short') runningTradeColorClass = 'trade-short';
            runningTradeEl.className = runningTradeColorClass;
        }
        
        const entryPriceEl = botCard.querySelector(`#bot-entry-price-${p.bot_id}`);
        if (entryPriceEl) entryPriceEl.textContent = p.entry_price ? p.entry_price.toFixed(5) : '-';
        
        const slEl = botCard.querySelector(`#bot-sl-${p.bot_id}`);
        if(slEl) {
            let slText = '-';
            if(p.running_trade !== 'None' && p.current_sl_price && p.entry_price && p.leverage) {
                const slRoi = calculateSlRoi(p.entry_price, p.current_sl_price, p.leverage, p.running_trade);
                slText = `${p.running_trade.charAt(0)}: ${slRoi.toFixed(2)}%`;
            }
            slEl.textContent = slText;
        }

        const roiEl = botCard.querySelector(`#bot-roi-${p.bot_id}`);
        if(roiEl) { const roi = p.roi || 0; roiEl.textContent = `${roi.toFixed(2)}%`; roiEl.className = roi >= 0 ? 'roi-pos' : 'roi-neg'; }
        
        const marketPriceEl = botCard.querySelector(`#bot-market-price-${p.bot_id}`);
        if (marketPriceEl) marketPriceEl.textContent = p.price ? p.price.toFixed(5) : '-';
        
        const actionsDiv = botCard.querySelector('.bot-actions');
        if (actionsDiv) {
            const isCompleted = p.status === 'Completed';
            if (isCompleted && !actionsDiv.querySelector('.btn-closed')) {
                actionsDiv.innerHTML = `<div class="btn btn-closed">Closed</div>`;
            }
        }

        if (p.stats) {
            botCard.querySelector(`#bot-total-trades-${p.bot_id}`).textContent = p.stats.total_trades || 0;
            botCard.querySelector(`#bot-winning-trades-${p.bot_id}`).textContent = p.stats.winning_trades || 0;
            botCard.querySelector(`#bot-losing-trades-${p.bot_id}`).textContent = p.stats.losing_trades || 0;
            botCard.querySelector(`#bot-breakeven-trades-${p.bot_id}`).textContent = p.stats.breakeven_trades || 0;
            botCard.querySelector(`#bot-total-profit-${p.bot_id}`).textContent = `$${(p.stats.total_profit || 0).toFixed(2)}`;
            botCard.querySelector(`#bot-total-loss-${p.bot_id}`).textContent = `$${(p.stats.total_loss || 0).toFixed(2)}`;
            const pnlEl = botCard.querySelector(`#bot-pnl-${p.bot_id}`);
            const pnl = p.stats.total_pnl || 0;
            pnlEl.textContent = `$${pnl.toFixed(2)}`;
            pnlEl.className = `pnl-value ${pnl >= 0 ? 'roi-pos' : 'roi-neg'}`;
        }
    });
}

async function loadTemplates(){ try { const r=await fetch('/templates/list'); const d=await r.json(); renderTemplates(d.items||[]); } catch(e) { console.error("Failed to load templates:", e); } }
async function hydrateDashboard(){ try { R_points=[null,null,null,null,null]; renderR(); document.getElementById('trade_amount_mode').addEventListener('change',toggleRecoveryFields); toggleRecoveryFields(); await initSymbolSuggest(); await loadTemplates(); await refreshBots(); initSocket(); } catch (error) { console.error("Failed to hydrate dashboard:", error); alert("There was an error loading the dashboard. Please check the console (F12) for details."); } }