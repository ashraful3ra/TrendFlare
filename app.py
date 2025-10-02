import os, json, time, threading, ssl
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from functools import wraps
from flask_socketio import SocketIO
from dotenv import load_dotenv
from utils.db import init_db, connect, now, to_dict
from utils.crypto import enc_str, dec_str
from utils.binance import BinanceUM
from cryptography.fernet import InvalidToken
import websocket

load_dotenv(); init_db()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

#<editor-fold desc="Auth & Helpers">
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == os.environ.get('APP_PASSWORD'):
            session['logged_in'] = True; session.permanent = True
            return redirect(url_for('dashboard'))
        else: flash('Invalid password!', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None); flash('You have been logged out.', 'success'); return redirect(url_for('login'))

def get_bot(bot_id):
    with connect() as con: r = con.cursor().execute('SELECT * FROM bots WHERE id=?', (bot_id,)).fetchone(); return to_dict(r) if r else None
def get_account(acc_id):
    with connect() as con: r=con.cursor().execute('SELECT * FROM accounts WHERE id=?',(acc_id,)).fetchone(); return to_dict(r)
def safe_get_client(acc):
    try: api_key=dec_str(acc['api_key_enc']); api_secret=dec_str(acc['api_secret_enc']); return BinanceUM(api_key, api_secret, bool(acc['testnet']))
    except InvalidToken: raise RuntimeError("Encryption key mismatch")
def list_accounts():
    with connect() as con: return [to_dict(r) for r in con.cursor().execute('SELECT * FROM accounts ORDER BY id DESC').fetchall()]
def list_templates():
    with connect() as con:
        out=[]
        for r in con.cursor().execute('SELECT * FROM templates ORDER BY id DESC').fetchall():
            d=to_dict(r); d['r_points_json']=json.loads(d['r_points_json'] or '[]'); out.append(d)
        return out
def list_bots(limit=5, offset=0):
    with connect() as con:
        items = [to_dict(r) for r in con.cursor().execute('SELECT b.*, a.name as account_name FROM bots b LEFT JOIN accounts a ON a.id=b.account_id ORDER BY b.id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()]
        total = con.cursor().execute('SELECT COUNT(*) FROM bots').fetchone()[0]
        return {'items': items, 'total': total}
def update_account_balances():
    for acc in list_accounts():
        if not acc['active']: continue
        try:
            bn = safe_get_client(acc); balance = bn.futures_balance()
            with connect() as con: con.cursor().execute('UPDATE accounts SET futures_balance=?, updated_at=? WHERE id=?', (balance, now(), acc['id'])); con.commit()
        except Exception as e: print(f"Could not update balance for {acc['name']}: {e}")
#</editor-fold>

#<editor-fold desc="UI Routes">
@app.route('/')
@login_required
def home(): return redirect(url_for('dashboard'))

@app.route('/account')
@login_required
def account(): update_account_balances(); return render_template('account.html', accounts_json=json.dumps(list_accounts()))

@app.route('/dashboard')
@login_required
def dashboard(): return render_template('dashboard.html', accounts=list_accounts())
#</editor-fold>

#<editor-fold desc="API Routes">
@app.route('/accounts/add', methods=['POST'])
def accounts_add():
    data=request.get_json(force=True); name=data.get('name','').strip(); api_key=data.get('api_key','').strip(); api_secret=data.get('api_secret','').strip(); testnet=1 if data.get('testnet') else 0
    if not name or not api_key or not api_secret: return jsonify({'error':'Missing fields'}),400
    try: bn=BinanceUM(api_key, api_secret, bool(testnet)); balance = bn.futures_balance(); bn.set_hedge_mode(True)
    except Exception as e: return jsonify({'error':str(e)}),400
    with connect() as con: con.cursor().execute('INSERT INTO accounts (name,exchange,api_key_enc,api_secret_enc,testnet,active,futures_balance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)', (name,'BINANCE_UM',enc_str(api_key),enc_str(api_secret),testnet,1,balance,now(),now())); con.commit()
    return jsonify({'ok':True,'accounts':list_accounts()})

@app.route('/accounts/toggle/<int:acc_id>', methods=['POST'])
def accounts_toggle(acc_id):
    with connect() as con:
        con.cursor().execute('UPDATE accounts SET active = 1 - active, updated_at=? WHERE id=?',(now(),acc_id))
        con.commit()
    return jsonify({'ok':True})
@app.route('/accounts/delete/<int:acc_id>', methods=['POST'])
def accounts_delete(acc_id):
    with connect() as con:
        con.cursor().execute('DELETE FROM accounts WHERE id=?',(acc_id,))
        con.commit()
    return jsonify({'ok':True,'accounts':list_accounts()})
@app.route('/api/futures/symbols')
def futures_symbols():
    bn=BinanceUM('', '', False)
    try:
        info=bn.exchange_info()
        symbols=[s['symbol'] for s in info.get('symbols',[]) if s.get('quoteAsset')=='USDT' and s.get('status')=='TRADING']
        return jsonify({'symbols':symbols})
    except Exception as e:
        return jsonify({'symbols':[],'error':str(e)}),500

@app.route('/templates/save', methods=['POST'])
def tpl_save():
    data = request.get_json(force=True)
    name = data.get('name', '').strip()
    if not name: return jsonify({'error': 'Name required'}), 400
    with connect() as con:
        con.cursor().execute("""INSERT INTO templates (
                name, symbol, margin_type, time_frame, trade_mode, run_mode, long_amount, long_leverage, 
                recovery_margin, max_trades, r_points_json, open_on_new_candle, cond_sl_close, 
                close_on_candle_end, cond_trailing, cond_close_last, created_at, trade_amount_mode, recovery_max_amount
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            name, data.get('symbol','').upper(), data.get('margin_mode'), data.get('time_frame'), data.get('trade_mode'), data.get('run_mode'), 
            data.get('trade_amount'), data.get('leverage'), data.get('recovery_margin'), data.get('max_trades'), 
            json.dumps(data.get('r_points') or []), data.get('open_on_new_candle'), data.get('cond_sl_close'), 
            data.get('close_on_candle_end'), data.get('cond_trailing'), data.get('cond_close_last'), now(), 
            data.get('trade_amount_mode'), data.get('recovery_max_amount')
        ))
        con.commit()
    return jsonify({'ok': True})

@app.route('/templates/get/<int:tpl_id>')
def tpl_get(tpl_id):
    with connect() as con:
        r=con.cursor().execute('SELECT * FROM templates WHERE id=?',(tpl_id,)).fetchone()
        d=to_dict(r)
        d['r_points_json']=json.loads(d['r_points_json'] or '[]')
        return jsonify(d)
@app.route('/templates/delete/<int:tpl_id>', methods=['POST'])
def tpl_delete(tpl_id):
    with connect() as con:
        con.cursor().execute('DELETE FROM templates WHERE id=?',(tpl_id,))
        con.commit()
    return jsonify({'ok':True})

@app.route('/templates/list')
def templates_list():
    return jsonify({'items': list_templates()})

@app.route('/bots/list')
def bots_list():
    page = int(request.args.get('page', 1))
    limit = 5
    offset = (page - 1) * limit
    return jsonify(list_bots(limit=limit, offset=offset))

@app.route('/bots/submit', methods=['POST'])
def bots_submit():
    data = request.get_json(force=True)
    if not all(k in data for k in ['name', 'symbol', 'account_id', 'trade_amount']): return jsonify({'error': 'Missing fields'}), 400
    acc = get_account(data['account_id'])
    if not acc or not acc['active']: return jsonify({'error': 'Account not active'}), 400
    try:
        bn = safe_get_client(acc)
        bn.set_margin_type(data['symbol'], data['margin_mode'])
        bn.set_leverage(data['symbol'], data['leverage'])
        
        with connect() as con:
            cur = con.cursor()
            cur.execute("""INSERT INTO bots (
                    name, account_id, symbol, long_amount, long_leverage, r_points_json, start_time, testnet, 
                    margin_type, time_frame, trade_mode, run_mode, recovery_margin, max_trades, open_on_new_candle, 
                    cond_sl_close, close_on_candle_end, cond_trailing, cond_close_last, long_status, short_status, 
                    trade_amount_mode, recovery_max_amount, current_trade_amount
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                data['name'], data['account_id'], data['symbol'], data['trade_amount'], data['leverage'], 
                json.dumps(data.get('r_points') or []), now(), acc['testnet'], data['margin_mode'], data['time_frame'], 
                data['trade_mode'], data['run_mode'], data.get('recovery_margin'), data.get('max_trades'), 
                data.get('open_on_new_candle'), data.get('cond_sl_close'), data.get('close_on_candle_end'), 
                data.get('cond_trailing'), data.get('cond_close_last'), 'Idle', 'Idle', data.get('trade_amount_mode'), 
                data.get('recovery_max_amount'), data['trade_amount']
            ))
            bot_id = cur.lastrowid
            con.commit()
        start_trade_worker(bot_id)
        return jsonify({'ok': True, 'bot_id': bot_id})

    except Exception as e:
        return jsonify({'error': f'Failed to set margin/leverage: {e}'}), 400

@app.route('/bots/close/<int:bot_id>', methods=['POST'])
def bots_close_route(bot_id):
    bot = get_bot(bot_id)
    acc = get_account(bot['account_id'])
    bn = safe_get_client(acc)
    close_position(bot, bn, manual_close=True)
    return jsonify({'ok': True})

@app.route('/bots/toggle_pause/<int:bot_id>', methods=['POST'])
def bots_toggle_pause(bot_id):
    bot = get_bot(bot_id)
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    
    new_paused_state = 1 - (bot.get('paused', 0) or 0)
    db_update_bot(bot_id, {'paused': new_paused_state})
    
    # Send an immediate UI update
    socketio.emit('bot_update', {'bot_id': bot_id, 'paused': bool(new_paused_state)})
    
    return jsonify({'ok': True, 'paused': bool(new_paused_state)})

#</editor-fold>

#<editor-fold desc="Trading Logic & Websocket">
TRADE_THREADS = {}
TRADE_LOCK = threading.Lock()
def db_update_bot(bot_id, updates):
    fields = ', '.join([f"{k}=?" for k in updates.keys()])
    values = list(updates.values()) + [bot_id]
    with connect() as con:
        con.cursor().execute(f"UPDATE bots SET {fields} WHERE id=?", values)
        con.commit()

def compute_roi(entry, mark, lev, side):
    if not entry or entry <= 0: return 0.0
    return (((mark - entry) / entry) * lev * 100.0) if side == 'LONG' else (((entry - mark) / entry) * lev * 100.0)

def open_position(bot, bn_client, side):
    symbol = bot['symbol']
    amount = bot.get('current_trade_amount') or bot['long_amount']
    r_points = sorted(json.loads(bot.get('r_points_json', '[]')))
    
    try:
        price = float(bn_client.price(symbol)['price'])
        qty = bn_client.round_lot_size(symbol, amount / price)
        bn_client.order_market(symbol, 'BUY' if side == 'LONG' else 'SELL', qty, position_side=side)
        time.sleep(0.5)
        entry_price = float(bn_client.get_user_trades(symbol, limit=1)[0].get('price', price))
        
        updates = {
            ('long_status' if side == 'LONG' else 'short_status'): 'Running',
            ('long_entry_price' if side == 'LONG' else 'short_entry_price'): entry_price,
            'short_status' if side == 'LONG' else 'long_status': 'Idle'
        }
        
        if bot.get('cond_sl_close') and r_points:
            sl_roi = -abs(r_points[0]) 
            sl_price = entry_price * (1 + (sl_roi / (100 * bot['long_leverage']))) if side == 'LONG' else entry_price * (1 - (sl_roi / (100 * bot['long_leverage'])))
            updates[('long_sl_point' if side == 'LONG' else 'short_sl_point')] = sl_price
        
        db_update_bot(bot['id'], updates)
        print(f"SUCCESS: Opened {side} for bot {bot['id']} with amount {amount}")
        return True
    except Exception as e:
        print(f"FAIL: Could not open {side} for bot {bot['id']}. Reason: {e}")
        return False

def close_position(bot, bn_client, manual_close=False):
    symbol = bot['symbol']
    pnl = 0.0
    bot_id = bot['id']
    try:
        pos_to_close = None
        for p in bn_client.position_risk(symbol):
            amt = float(p.get('positionAmt', 0))
            if amt != 0:
                pos_to_close = p
                break
        
        if pos_to_close:
            side = 'LONG' if float(pos_to_close['positionAmt']) > 0 else 'SHORT'
            bn_client.order_market(symbol, 'SELL' if side == 'LONG' else 'BUY', abs(float(pos_to_close['positionAmt'])), position_side=side)
            time.sleep(1)
            last_trade = bn_client.get_user_trades(symbol, limit=1)[0]
            pnl = float(last_trade.get('realizedPnl', 0))
            print(f"SUCCESS: Closed {side} for bot {bot_id} with PnL: {pnl}")
    except Exception as e:
        print(f"FAIL: Could not close for bot {bot_id}. Reason: {e}")
    
    current_pnl = bot.get('total_pnl', 0.0) or 0.0
    current_profit = bot.get('total_profit', 0.0) or 0.0
    current_loss = bot.get('total_loss', 0.0) or 0.0
    
    updates = {
        'total_trades': (bot.get('total_trades', 0) or 0) + 1,
        'total_pnl': current_pnl + pnl
    }
    if pnl > 0:
        updates['winning_trades'] = (bot.get('winning_trades', 0) or 0) + 1
        updates['total_profit'] = current_profit + pnl
    elif pnl < 0:
        updates['losing_trades'] = (bot.get('losing_trades', 0) or 0) + 1
        updates['total_loss'] = current_loss + abs(pnl)
    else:
        updates['breakeven_trades'] = (bot.get('breakeven_trades', 0) or 0) + 1

    if bot.get('trade_amount_mode') == 'Recovery' and not manual_close:
        base_amount = bot['long_amount']
        current_amount = bot.get('current_trade_amount') or base_amount
        recovery_add_amount = bot.get('recovery_margin', 0)
        max_amount = bot.get('recovery_max_amount', 0)

        if pnl < 0:
            new_amount = current_amount + recovery_add_amount
            if max_amount > 0 and new_amount > max_amount:
                new_amount = max_amount
            updates['current_trade_amount'] = new_amount
            print(f"Bot {bot_id} Recovery: Loss detected. New trade amount: {new_amount}")
        elif pnl > 0:
            if current_amount != base_amount:
                updates['current_trade_amount'] = base_amount
                print(f"Bot {bot_id} Recovery: Profit detected. Trade amount reset to base: {base_amount}")

    status_update = 'Idle'
    if manual_close:
        status_update = 'Completed'
    elif bot.get('run_mode') == 'Limit':
        if (updates['total_trades']) >= (bot.get('max_trades', 0) or 0):
            status_update = 'Completed'
            print(f"Bot {bot_id}: Max trades limit ({bot.get('max_trades')}) reached. Stopping bot.")

    updates.update({
        'long_status': status_update, 'short_status': status_update,
        'long_entry_price': None, 'short_entry_price': None,
        'long_sl_point': None, 'short_sl_point': None
    })
    db_update_bot(bot_id, updates)

    final_bot_state = get_bot(bot_id)
    socketio.emit('bot_update', {
        'bot_id': bot_id, 'price': None, 'roi': 0, 'status': final_bot_state['long_status'], 
        'entry_price': None, 'running_trade': 'None', 'current_sl_price': None,
        'leverage': final_bot_state['long_leverage'], 'paused': False,
        'stats': {
            'total_trades': final_bot_state['total_trades'], 'winning_trades': final_bot_state['winning_trades'], 
            'losing_trades': final_bot_state['losing_trades'], 'breakeven_trades': final_bot_state['breakeven_trades'], 
            'total_pnl': final_bot_state['total_pnl'], 'total_profit': final_bot_state.get('total_profit'), 'total_loss': final_bot_state.get('total_loss')
        }
    })


def start_trade_worker(bot_id):
    bot = get_bot(bot_id)
    acc = get_account(bot['account_id'])
    bn = safe_get_client(acc)
    ws_url = f"{bn.ws_base}/{bot['symbol'].lower()}@kline_{bot['time_frame']}"
    
    def on_message(ws, message):
        nonlocal bot
        bot = get_bot(bot_id)
        if not bot or 'Completed' in bot['long_status']:
            ws.close(); return
        
        # --- Pause Check ---
        if bot.get('paused'):
            return # Do nothing if bot is paused

        data = json.loads(message)
        kline = data.get('k')
        is_candle_closed = kline.get('x', False)
        open_price, close_price = float(kline.get('o')), float(kline.get('c'))
        is_in_long, is_in_short = bot['long_status'] == 'Running', bot['short_status'] == 'Running'
        is_in_trade = is_in_long or is_in_short
        
        # R-Points গুলোকে ছোট থেকে বড় ক্রমে সাজিয়ে নেওয়া হয়েছে
        r_points = sorted(json.loads(bot.get('r_points_json', '[]')))

        if is_in_trade:
            side = 'LONG' if is_in_long else 'SHORT'
            entry_price_from_db = bot.get('long_entry_price') if is_in_long else bot.get('short_entry_price')
            
            # --- Stop-loss price retrieval and type conversion ---
            sl_price_from_db = bot.get('long_sl_point') if is_in_long else bot.get('short_sl_point')
            sl_price = float(sl_price_from_db) if sl_price_from_db is not None else None

            # Ensure entry_price is also a float for ROI calculation
            if not entry_price_from_db:
                # If for some reason entry price is missing, we can't proceed with checks
                return 
            entry_price = float(entry_price_from_db)

            current_roi = compute_roi(entry_price, close_price, bot['long_leverage'], side)

            # Condition 4: যদি ট্রেডের ROI শেষ R Point স্পর্শ করে বা অতিক্রম করে, তাহলে ট্রেড বন্ধ হবে (Take-Profit)
            if bot.get('cond_close_last') and r_points and current_roi >= r_points[-1]:
                print(f"Bot {bot_id}: Last R point (TP) reached. ROI: {current_roi}%. Closing trade.")
                close_position(bot, bn); return

            # Condition 1: Stoploss লজিক
            if bot.get('cond_sl_close') and sl_price is not None:
                # Stoploss হিট করলে ট্রেড বন্ধ হবে
                if (side == 'LONG' and close_price <= sl_price) or (side == 'SHORT' and close_price >= sl_price):
                    sl_roi = compute_roi(entry_price, sl_price, bot['long_leverage'], side)
                    print(f"Bot {bot_id}: SL hit at ROI {sl_roi:.2f}%. Price: {close_price}, SL: {sl_price}. Closing trade.")
                    close_position(bot, bn); return
            
            # Trailing Stoploss লজিক
            if bot.get('cond_trailing') and r_points and sl_price is not None:
                new_sl_roi = None
                # R-Point গুলোকে বিপরীত ক্রমে (বড় থেকে ছোট) চেক করা হচ্ছে
                for i in range(len(r_points) - 1, 0, -1): # R1 বাদ দিয়ে R2 থেকে চেক করা শুরু হবে
                    if current_roi >= r_points[i]:
                        new_sl_roi = r_points[i-1] # Stoploss তার আগের R-point এ সেট হবে
                        break
                
                if new_sl_roi is not None:
                    # নতুন SL Price ক্যালকুলেট করা
                    new_sl_price = entry_price * (1 + (new_sl_roi / (100 * bot['long_leverage']))) if side == 'LONG' else entry_price * (1 - (new_sl_roi / (100 * bot['long_leverage'])))
                    
                    # যদি নতুন SL আগের SL থেকে ভালো হয়, তাহলেই শুধু আপডেট হবে
                    if (side == 'LONG' and new_sl_price > sl_price) or (side == 'SHORT' and new_sl_price < sl_price):
                        print(f"Bot {bot_id}: Trailing SL updated. ROI reached {current_roi:.2f}%, New SL set at ROI {new_sl_roi}%. New SL Price: {new_sl_price}")
                        db_update_bot(bot_id, {('long_sl_point' if side == 'LONG' else 'short_sl_point'): new_sl_price})

        # --- Candle Close Logic (Unchanged) ---
        if is_candle_closed:
            bot = get_bot(bot_id)
            is_in_long, is_in_short = bot['long_status'] == 'Running', bot['short_status'] == 'Running'
            is_in_trade = is_in_long or is_in_short
            
            if is_in_trade and bot.get('close_on_candle_end'):
                print(f"Bot {bot['id']}: Candle closed, closing trade.")
                close_position(bot, bn); return
            
            if not is_in_trade and bot.get('open_on_new_candle'):
                if 'Completed' in bot['long_status']: ws.close(); return

                print(f"Bot {bot['id']}: New candle, determining trade direction.")
                trade_direction = 'LONG' if close_price > open_price else 'SHORT'
                if bot.get('trade_mode') == 'Unfollow':
                    trade_direction = 'SHORT' if trade_direction == 'LONG' else 'LONG'
                
                print(f"Bot {bot['id']}: Opening {trade_direction} trade.")
                open_position(bot, bn, trade_direction)

        # --- UI Update Logic (Unchanged) ---
        bot = get_bot(bot_id)
        roi, status, entry, running_trade, sl_price_for_ui = 0.0, bot['long_status'], None, 'None', None
        
        if bot.get('long_status') == 'Running':
            entry = bot['long_entry_price']
            roi=compute_roi(entry, close_price, bot['long_leverage'], 'LONG')
            status, running_trade, sl_price_for_ui = 'Running', 'Long', bot.get('long_sl_point')
        elif bot.get('short_status') == 'Running':
            entry = bot['short_entry_price']
            roi=compute_roi(entry, close_price, bot['long_leverage'], 'SHORT')
            status, running_trade, sl_price_for_ui = 'Running', 'Short', bot.get('short_sl_point')
        
        socketio.emit('bot_update', {
            'bot_id': bot_id, 'price': close_price, 'roi': roi, 'status': status, 
            'entry_price': entry, 'running_trade': running_trade, 'current_sl_price': sl_price_for_ui,
            'leverage': bot['long_leverage'], 'paused': bot.get('paused'),
            'stats': {
                'total_trades': bot['total_trades'], 'winning_trades': bot['winning_trades'], 
                'losing_trades': bot['losing_trades'], 'breakeven_trades': bot['breakeven_trades'], 
                'total_pnl': bot['total_pnl'], 'total_profit': bot.get('total_profit'), 'total_loss': bot.get('total_loss')
            }
        })

    def on_error(ws, err): print(f"WS Error for bot {bot['id']}: {err}")
    def on_close(ws, status_code, msg): print(f"WS Closed for bot {bot['id']}.")
    
    def run():
        while True:
            bot_status = get_bot(bot_id)
            if not bot_status or 'Completed' in bot_status['long_status']:
                print(f"Bot {bot_id} is completed. Worker thread stopping."); break
            try:
                # On restart, reset paused state to resume trading
                if bot_status.get('paused'):
                    db_update_bot(bot_id, {'paused': 0})
                    
                ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_error=on_error, on_close=on_close)
                ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception as e: print(f"Websocket failed for bot {bot_id}: {e}")
            
            if get_bot(bot_id) and 'Completed' in get_bot(bot_id)['long_status']: break 
            print(f"Websocket for bot {bot_id} disconnected. Reconnecting in 10s...")
            time.sleep(10)
    
    th = threading.Thread(target=run, daemon=True)
    th.start()
    TRADE_THREADS[bot_id] = th

def start_all_bot_workers():
    print("Starting workers for all active bots...")
    with connect() as con:
        query = "SELECT id FROM bots WHERE long_status NOT LIKE 'Completed%'"
        for r in con.cursor().execute(query).fetchall():
            if r['id'] not in TRADE_THREADS:
                print(f"Starting worker for bot ID: {r['id']}")
                start_trade_worker(r['id'])

if __name__ == '__main__':
    start_all_bot_workers()
    host=os.environ.get('HOST','0.0.0.0')
    port=int(os.environ.get('PORT','5000'))
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
#</editor-fold>