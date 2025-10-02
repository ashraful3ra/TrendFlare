import sqlite3, os, time

DB_FILE = os.path.join('data', 'app.db')
SCHEMA_VERSION = 12 # সর্বশেষ স্কিমা ভার্সন

def now(): return int(time.time())

def connect():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con

def to_dict(row):
    if not row: return None
    return dict(row)

def init_db():
    if not os.path.exists('data'):
        os.makedirs('data')
    
    con = connect()
    cur = con.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);")
    cur.execute("SELECT version FROM schema_version;")
    r = cur.fetchone()

    if r is None:
        cur.execute("INSERT INTO schema_version (version) VALUES (0);")
        con.commit()
        current_version = 0
    else:
        current_version = r['version']

    if current_version < 1:
        cur.execute("""CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, exchange TEXT NOT NULL,
            api_key_enc TEXT NOT NULL, api_secret_enc TEXT NOT NULL, testnet INTEGER DEFAULT 1, active INTEGER DEFAULT 1,
            futures_balance REAL, created_at INTEGER, updated_at INTEGER );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS bots (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, account_id INTEGER NOT NULL,
            symbol TEXT NOT NULL, long_enabled INTEGER, long_amount REAL, long_leverage INTEGER,
            short_enabled INTEGER, short_amount REAL, short_leverage INTEGER, r_points_json TEXT,
            cond_sl_close INTEGER, cond_trailing INTEGER, cond_close_last INTEGER, start_time INTEGER,
            long_entry_price REAL, short_entry_price REAL, long_status TEXT, short_status TEXT,
            long_sl_point REAL, short_sl_point REAL, testnet INTEGER, margin_type TEXT DEFAULT 'ISOLATED',
            long_final_roi REAL DEFAULT 0.0, short_final_roi REAL DEFAULT 0.0 );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS templates (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, symbol TEXT, long_enabled INTEGER,
            long_amount REAL, long_leverage INTEGER, short_enabled INTEGER, short_amount REAL, short_leverage INTEGER,
            r_points_json TEXT, cond_sl_close INTEGER, cond_trailing INTEGER, cond_close_last INTEGER, created_at INTEGER );""")

    if current_version < 5:
        try: cur.execute("ALTER TABLE templates ADD COLUMN margin_type TEXT DEFAULT 'ISOLATED'")
        except: pass
    
    if current_version < 6:
        new_columns = [ "time_frame TEXT DEFAULT '1m'", "trade_mode TEXT DEFAULT 'Follow'", "run_mode TEXT DEFAULT 'Ongoing'",
            "recovery_margin REAL DEFAULT 5", "max_trades INTEGER DEFAULT 0", "open_on_new_candle INTEGER DEFAULT 1",
            "close_on_candle_end INTEGER DEFAULT 0" ]
        for col in new_columns:
            try: cur.execute(f"ALTER TABLE bots ADD COLUMN {col}")
            except: pass
            try: cur.execute(f"ALTER TABLE templates ADD COLUMN {col}")
            except: pass

    if current_version < 7:
        try: cur.execute("ALTER TABLE bots ADD COLUMN trade_amount_mode TEXT DEFAULT 'Normal'")
        except: pass
        try: cur.execute("ALTER TABLE templates ADD COLUMN trade_amount_mode TEXT DEFAULT 'Normal'")
        except: pass
        
    if current_version < 8:
        stat_columns = [
            "total_trades INTEGER DEFAULT 0", "winning_trades INTEGER DEFAULT 0", "losing_trades INTEGER DEFAULT 0",
            "breakeven_trades INTEGER DEFAULT 0", "total_pnl REAL DEFAULT 0.0" ]
        for col in stat_columns:
            try: cur.execute(f"ALTER TABLE bots ADD COLUMN {col}")
            except: pass
            
    if current_version < 9:
        try: cur.execute("ALTER TABLE bots ADD COLUMN recovery_max_amount REAL DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE templates ADD COLUMN recovery_max_amount REAL DEFAULT 0")
        except: pass
        
    if current_version < 10:
        try: cur.execute("ALTER TABLE bots ADD COLUMN current_trade_amount REAL DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE templates ADD COLUMN current_trade_amount REAL DEFAULT 0")
        except: pass
        
    if current_version < 11:
        stat_columns_v11 = ["total_profit REAL DEFAULT 0.0", "total_loss REAL DEFAULT 0.0"]
        for col in stat_columns_v11:
            try: cur.execute(f"ALTER TABLE bots ADD COLUMN {col}")
            except: pass
            
    if current_version < 12:
        try: cur.execute("ALTER TABLE bots ADD COLUMN paused INTEGER DEFAULT 0")
        except: pass

    if current_version < SCHEMA_VERSION:
        cur.execute("UPDATE schema_version SET version=?;", (SCHEMA_VERSION,))

    con.commit()
    con.close()
    print(f"DB init OK. Schema version is now {SCHEMA_VERSION}.")